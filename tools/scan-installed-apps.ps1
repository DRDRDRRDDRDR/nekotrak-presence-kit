#Requires -Version 5.1
<#
.SYNOPSIS
    扫描本机已安装的应用，产出一份可以直接喂给 add-apps.ps1 的 TSV。

.DESCRIPTION
    三个来源合并去重：
      1) 注册表 Uninstall 三处（HKLM 64 位 / HKLM 32 位 / HKCU），取 DisplayIcon
      2) 当前正在运行、且拿得到 Path 的进程
      3) 开始菜单（用户 + 全局）里的 .lnk 快捷方式

    默认会过滤掉一堆噪声：.NET / VC++ 运行库、SDK、驱动、安装器、卸载器、
    以及 NekoTrak 库本身已经有的条目（可选）。

.PARAMETER Out
    输出的 TSV 路径，默认 .\apps.tsv

.PARAMETER IncludeNoisy
    不过滤运行库/驱动/安装器之类的噪声条目。

.PARAMETER Existing
    已有的 TSV（例如上一次导出的），用来跳过路径重复的条目。

.EXAMPLE
    .\scan-installed-apps.ps1 -Out .\apps.tsv
#>
[CmdletBinding()]
param(
    [string]$Out = '.\apps.tsv',
    [switch]$IncludeNoisy,
    [string]$Existing = ''
)

$ErrorActionPreference = 'Stop'

$rows = New-Object System.Collections.Generic.List[object]
$seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

function Add-App {
    param([string]$Name, [string]$Path)
    if (-not $Name -or -not $Path) { return }
    $Path = $Path.Trim('"').Trim()
    if ($Path -notmatch '\.exe$') { return }
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if (-not $seen.Add($Path)) { return }
    $rows.Add([pscustomobject]@{ Name = $Name.Trim(); Path = $Path })
}

# --- 1) 注册表
$uninstallKeys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($k in $uninstallKeys) {
    foreach ($item in (Get-ItemProperty $k -ErrorAction SilentlyContinue)) {
        if (-not $item.DisplayName) { continue }
        if (-not $IncludeNoisy -and $item.SystemComponent -eq 1) { continue }
        if (-not $IncludeNoisy -and $item.ParentKeyName) { continue }
        $icon = $item.DisplayIcon
        if (-not $icon) { continue }
        # DisplayIcon 可能是 "path,0" 或 "path" 或带引号
        $p = ($icon -split ',')[0].Trim().Trim('"')
        if ($p -match '\.exe$') { Add-App $item.DisplayName $p }
    }
}

# --- 2) 运行中的进程
foreach ($proc in (Get-Process -ErrorAction SilentlyContinue)) {
    $p = $null
    try { $p = $proc.Path } catch { }
    if ($p) { Add-App $proc.ProcessName $p }
}

# --- 3) 开始菜单快捷方式
$wsh = New-Object -ComObject WScript.Shell
$lnkRoots = @(
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
)
foreach ($rootDir in $lnkRoots) {
    if (-not (Test-Path $rootDir)) { continue }
    foreach ($lnk in (Get-ChildItem $rootDir -Filter *.lnk -Recurse -ErrorAction SilentlyContinue)) {
        try {
            $target = $wsh.CreateShortcut($lnk.FullName).TargetPath
            if ($target -match '\.exe$') { Add-App ($lnk.BaseName) $target }
        } catch { }
    }
}

# --- 噪声过滤
if (-not $IncludeNoisy) {
    # 1) 按显示名过滤运行库 / SDK / 更新包之类
    $noisy = 'Microsoft \.NET|\.NET (Runtime|Framework|Host|SDK)|Visual C\+\+|VC\+\+ \d|Redistributable|' +
             'Windows (Software Development Kit|Driver Kit|SDK)|Runtime|Runtime Library|' +
             'Update for|Hotfix|Security Update|Installer|Uninstall|卸载|辅助|Update Helper|' +
             'Package Cache|MSI (After )?Reboot|Diagnostics|Crash|Telemetry|Language Pack|' +
             'Microsoft Visual Studio Installer|Bonjour|Windows App Runtime|Host Package|' +
             'App Installer|Client Update|Service Pack|Microsoft Edge Update'
    $n0 = $rows.Count
    $rows = [System.Collections.Generic.List[object]]@($rows | Where-Object { $_.Name -notmatch $noisy })
    $n1 = $rows.Count

    # 2) 按 exe 文件名过滤卸载器 / 安装器 / 更新器
    $badExe = '(?i)\\(unins[^\\]*|uninstall[^\\]*|uninst[^\\]*|setup|installer|install|update|' +
              'updater|upgrade|patch|repair|msiexec|vcredist[^\\]*)\.exe$'
    $rows = [System.Collections.Generic.List[object]]@($rows | Where-Object { $_.Path -notmatch $badExe })
    $n2 = $rows.Count

    # 3) 过滤掉纯系统宿主（控制面板项、各类系统设置入口）
    $sysJunk = '(?i)^C:\\Windows\\(System32|SysWOW64)\\(control|rundll32|msiexec|dllhost|' +
               'taskmgr|regedit|mmc|wscript|cscript|mshta|colorcpl|SystemSettings)\.exe$'
    $rows = [System.Collections.Generic.List[object]]@($rows | Where-Object { $_.Path -notmatch $sysJunk })
    $n3 = $rows.Count

    "filtered by name: $($n0 - $n1)"
    "filtered by exe : $($n1 - $n2)"
    "filtered syshost: $($n2 - $n3)"
}

# --- 跳过已有
# -Existing 接受两种格式：本脚本产出的 TSV（名称<TAB>路径），或纯路径清单（一行一个路径）。
if ($Existing -ne '' -and (Test-Path $Existing)) {
    $have = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($line in [System.IO.File]::ReadAllLines((Resolve-Path $Existing).Path, [System.Text.Encoding]::UTF8)) {
        if ($line.Trim() -eq '') { continue }
        $p = $line -split "`t"
        $candidate = if ($p.Count -ge 2) { $p[1].Trim() } else { $line.Trim() }
        if ($candidate -match '\.exe$') { $null = $have.Add($candidate) }
    }
    $before = $rows.Count
    $rows = [System.Collections.Generic.List[object]]@($rows | Where-Object { -not $have.Contains($_.Path) })
    "skipped $($before - $rows.Count) already-known path(s) (from $($have.Count) known)"
}

# 注意：$sorted 为空时 ForEach-Object 返回 $null，WriteAllLines 会抛 ArgumentNullException。
# 外面套 @(...) 强制成数组就没这个问题。
$sorted = @($rows | Sort-Object Name)
$lines = @($sorted | ForEach-Object { "$($_.Name)`t$($_.Path)" })
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) $Out), $lines,
                                (New-Object System.Text.UTF8Encoding($false)))

"wrote $($sorted.Count) app(s) -> $Out"
$sorted | Select-Object -First 20 | ForEach-Object { "  $($_.Name)  <-  $($_.Path)" }
if ($sorted.Count -gt 20) { "  ... and $($sorted.Count - 20) more" }
