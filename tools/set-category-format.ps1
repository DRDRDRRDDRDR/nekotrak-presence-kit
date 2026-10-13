<#
  set-category-format.ps1 —— 给 NekoTrak 的分类批量设置「状态显示格式」。

  这是 NekoTrak 的**原生**状态模板通道：每个分类可以有自己的显示格式，
  当前台应用属于该分类时，就用该分类的格式渲染 Steam 状态。

  ★ 为什么这个比 ${...} 命令更快（实测）
    分类格式里的 {app} 替换在 ~400 ms 内完成；
    而 ${...} 里的命令受软件固定的 5.00 秒节拍驱动。
    UI 上看到的「Steam 状态预览」是每 ~15 秒才重绘一次的，别拿它测速度。

  ★ 模板变量（实测：exe 里只存在这两个）
    {app}    当前应用名（如 网易UU远程）—— 会被替换
    {title}  窗口标题 —— 常为空/原样输出，别依赖它
    其他 {xxx} 一律原样输出，不报错。所以别写 {song}/{time} 这类幻觉变量。

  ★ 与 ${...} 混用
    可以。`{app} 正在玩 | 第 ${echo %RANDOM%} 次` 会先替换 {app}，
    再走 5 秒节拍执行命令段。追求「跟得上切换」就别放 ${...}。

  用法：
    .\set-category-format.ps1 -Category 游戏 -Format '{app} 已启动 | 这局我很认真'
    .\set-category-format.ps1 -MapFile formats.tsv      # 每行「分类名<TAB>格式串」
    .\set-category-format.ps1 -Read                     # 只读回显所有分类的当前格式

  ★「未分类」是内置分类，它的编辑对话框只有颜色标签，没有状态显示格式字段。
    这是软件行为，不是脚本的问题。
#>
[CmdletBinding(DefaultParameterSetName = 'Single')]
param(
    [Parameter(ParameterSetName = 'Single', Mandatory)]
    [string]$Category,

    [Parameter(ParameterSetName = 'Single', Mandatory)]
    [string]$Format,

    [Parameter(ParameterSetName = 'Map')]
    [string]$MapFile,

    [Parameter(ParameterSetName = 'Read')]
    [switch]$Read,

    [int]$Delay = 1800,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'NekoTrakUIA.psm1') -Force

$CT = [System.Windows.Automation.ControlType]

function Write-Line($msg) { if (-not $Quiet) { Write-Host $msg } }

# 分类编辑对话框里的「状态显示格式」输入框，唯一的可靠锚点是它的 placeholder
# （含「例如」二字）。用「状态显示格式」标签往后找会撞上条目详情区的只读 Text。
function Get-FormatEdit($main) {
    foreach ($e in (Get-NekoTrakNodes $main)) {
        try {
            $c = $e.Current
            if ($c.ControlType -eq $CT::Edit -and $c.Name -like '*例如*') { return $e }
        } catch { }
    }
    return $null
}

function Select-CategoryRow($main, $name) {
    $nodes = @(Get-NekoTrakNodes $main)
    for ($i = 0; $i -lt $nodes.Count; $i++) {
        try {
            $c = $nodes[$i].Current
            if ($c.ControlType -eq $CT::Text -and $c.Name -eq $name -and -not $c.IsOffscreen) {
                return (Invoke-NekoTrakAncestor $nodes[$i] 5)
            }
        } catch { }
    }
    return 'not-found'
}

function Enter-CategoriesPage($main) {
    $e = Get-NekoTrakNode $main -Name '分类' -ControlType $CT::Button -VisibleOnly
    if ($e) { Invoke-NekoTrakNode $e | Out-Null; Start-Sleep -Seconds 3 }
    $e = Get-NekoTrakNode $main -Name '条目' -ControlType $CT::TabItem -VisibleOnly
    if ($e) { Invoke-NekoTrakNode $e | Out-Null; Start-Sleep -Seconds 3 }
}

function Set-OneCategoryFormat($main, $cat, $fmt) {
    # 先关掉可能残留的对话框
    $e = Get-NekoTrakNode $main -Name '取消' -ControlType $CT::Button -VisibleOnly
    if ($e) { Invoke-NekoTrakNode $e | Out-Null; Start-Sleep -Seconds 2 }

    $rc = Select-CategoryRow $main $cat
    Start-Sleep -Milliseconds $Delay
    Initialize-NekoTrakTree -MainWindow $main -SettleSeconds 1

    $re = Get-NekoTrakNode $main -Name '编辑' -ControlType $CT::Button -VisibleOnly
    $rr = if ($re) { Invoke-NekoTrakNode $re } else { 'no-edit-button' }
    Start-Sleep -Milliseconds $Delay
    Initialize-NekoTrakTree -MainWindow $main -SettleSeconds 2

    $fe = Get-FormatEdit $main
    if (-not $fe) {
        Write-Line "  FAIL  $cat : 没有「状态显示格式」字段（选分类=$rc 点编辑=$rr）"
        return $false
    }

    $before = Get-NekoTrakEditValue $fe
    if ($null -eq $fmt) {
        Write-Line "  $cat : '$before'"
        $e = Get-NekoTrakNode $main -Name '取消' -ControlType $CT::Button -VisibleOnly
        if ($e) { Invoke-NekoTrakNode $e | Out-Null; Start-Sleep -Seconds 2 }
        return $true
    }

    Set-NekoTrakEditValue -Element $fe -Value $fmt | Out-Null
    Start-Sleep -Milliseconds 600
    $after = Get-NekoTrakEditValue $fe

    $e = Get-NekoTrakNode $main -Name '保存更改' -ControlType $CT::Button -VisibleOnly
    $rs = if ($e) { Invoke-NekoTrakNode $e } else { 'no-save-button' }
    Start-Sleep -Seconds 3

    if ($after -eq $fmt) {
        Write-Line "  OK    $cat : '$before' -> '$after'  (save=$rs)"
        return $true
    }
    Write-Line "  BAD   $cat : 写入后回读不一致  want='$fmt' got='$after'"
    return $false
}

# ---- 主流程 ----

$main = Get-NekoTrakMainWindow
if (-not $main) { throw '找不到 NekoTrak 主窗口。请确认软件正在运行。' }
Initialize-NekoTrakTree -MainWindow $main
Enter-CategoriesPage $main
Initialize-NekoTrakTree -MainWindow $main -SettleSeconds 2

$pairs = @()
if ($PSCmdlet.ParameterSetName -eq 'Single') {
    $pairs += , @($Category, $Format)
} elseif ($PSCmdlet.ParameterSetName -eq 'Map') {
    foreach ($line in (Read-Utf8Lines -Path $MapFile)) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $i = $line.IndexOf("`t")
        if ($i -lt 1) { $i = $line.IndexOf('=') }
        if ($i -lt 1) { continue }
        $pairs += , @($line.Substring(0, $i).Trim(), $line.Substring($i + 1).Trim())
    }
} else {
    $pairs += , @($null, $null)
}

if ($Read -or $PSCmdlet.ParameterSetName -eq 'Read') {
    $cats = @('游戏', '媒体', '社交', '工作', '创作', '参考', '工具', '未分类')
    Write-Line '当前各分类的状态显示格式：'
    foreach ($c in $cats) { Set-OneCategoryFormat $main $c $null | Out-Null }
    return
}

$ok = 0; $bad = 0
foreach ($p in $pairs) {
    if (Set-OneCategoryFormat $main $p[0] $p[1]) { $ok++ } else { $bad++ }
}
Write-Line ""
Write-Line "done  ok=$ok  bad=$bad"
