#Requires -Version 5.1
<#
.SYNOPSIS
    把本机安装的应用批量导入 NekoTrak「应用库」（应用 -> 新建应用）。

.DESCRIPTION
    输入一个 UTF-8 的 TSV：应用名 <TAB> 完整 exe 路径。
    UI 里的两个输入框（「应用名称」「可执行文件 / 路径」）都没有 AccessibleName，
    所以定位方式是「标签 Text 之后第一个 Edit」。

    路径必须用反斜杠：正斜杠会被应用拒绝（保存应用失败）。

.PARAMETER File
    UTF-8 TSV，一行一条：名称<TAB>路径。

.PARAMETER Delay
    每条之间的等待毫秒数，默认 700。

.PARAMETER Limit
    只导入前 N 条。

.PARAMETER Test
    只导入第一条，用来确认通道可用。

.EXAMPLE
    .\add-apps.ps1 -File .\apps.tsv -Test
    .\add-apps.ps1 -File .\apps.tsv -Delay 700
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$File,
    [int]$Delay = 700,
    [int]$Limit = 0,
    [switch]$Test
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'NekoTrakUIA.psm1') -Force

$CT = [System.Windows.Automation.ControlType]

# --- 读 TSV
$rows = @()
foreach ($line in [System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $File).Path,
                                                 [System.Text.Encoding]::UTF8)) {
    if ($line.Trim() -eq '') { continue }
    $parts = $line -split "`t"
    if ($parts.Count -lt 2) { continue }
    $rows += [pscustomobject]@{ Name = $parts[0].Trim(); Path = $parts[1].Trim() }
}
if ($Limit -gt 0) { $rows = @($rows | Select-Object -First $Limit) }
if ($Test) { $rows = @($rows | Select-Object -First 1) }
"items = $($rows.Count)"

$main = Get-NekoTrakMainWindow
if (-not $main) { throw 'NekoTrak 主窗口没找到。' }
if (-not (Enter-NekoTrakPage $main -Page '应用')) { throw '进不去「应用」页。' }

$ok = 0; $bad = 0
foreach ($row in $rows) {
    $nameEd = Find-NekoTrakEditAfterLabel $main -Label '应用名称'
    $pathEd = Find-NekoTrakEditAfterLabel $main -Label '可执行文件 / 路径'
    if (-not $nameEd -or -not $pathEd) {
        # 对话框没开（或已关闭）：点「新建应用」再试
        $nb = Get-NekoTrakNode $main -Name '新建应用' -ControlType $CT::Button
        if (-not $nb) { "  no 新建应用 button - abort"; break }
        Invoke-NekoTrakNode $nb | Out-Null
        Start-Sleep -Milliseconds 900
        Initialize-NekoTrakTree $main | Out-Null
        $nameEd = Find-NekoTrakEditAfterLabel $main -Label '应用名称'
        $pathEd = Find-NekoTrakEditAfterLabel $main -Label '可执行文件 / 路径'
        if (-not $nameEd -or -not $pathEd) { "  dialog did not open - abort"; break }
    }

    try {
        Set-NekoTrakEditValue $nameEd $row.Name
        Start-Sleep -Milliseconds 150
        Set-NekoTrakEditValue $pathEd $row.Path
        Start-Sleep -Milliseconds 250
    } catch {
        "  [$($row.Name)] set failed: $($_.Exception.Message)"; $bad++; continue
    }

    $create = Get-NekoTrakNode $main -Name '创建应用' -ControlType $CT::Button
    if (-not $create) { "  no 创建应用 button - abort"; break }
    Invoke-NekoTrakNode $create | Out-Null
    Start-Sleep -Milliseconds $Delay
    Initialize-NekoTrakTree $main | Out-Null

    # 按钮还在 = 没关掉，说明失败；抓提示文字
    $still = Get-NekoTrakNode $main -Name '创建应用' -ControlType $CT::Button
    if ($still) {
        $msg = ''
        foreach ($e in (Get-NekoTrakNodes $main)) {
            try {
                $n = $e.Current.Name
                if ($n -match '已存在|失败|无效|必填|不能为空|必须|格式') { $msg = $n; break }
            } catch { }
        }
        "  FAIL [$($row.Name)] err='$msg'"
        $bad++
        $cancel = Get-NekoTrakNode $main -Name '取消' -ControlType $CT::Button
        if ($cancel) { Invoke-NekoTrakNode $cancel | Out-Null; Start-Sleep -Milliseconds 500 }
    } else {
        "  OK   [$($row.Name)]"
        $ok++
    }
}
"done ok=$ok bad=$bad"
