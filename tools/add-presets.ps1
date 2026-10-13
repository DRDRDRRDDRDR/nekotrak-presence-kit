#Requires -Version 5.1
<#
.SYNOPSIS
    把 txt 里的短语批量灌进 NekoTrak 的「自定义文本预设」库。

.DESCRIPTION
    走 UI Automation：设置 -> 行为 Tab -> 打开预设列表 -> 逐条 填框 + 点「添加预设」。
    预设存在 NekoTrak 自己的 SQLCipher 库里，外部脚本写不进去，必须走界面。

.PARAMETER File
    UTF-8 文本文件，一行一条短语。空行会被跳过。支持一次给多个文件。

.PARAMETER Clear
    先清空已有预设（逐条点「删除预设」直到按钮消失）。不写就等于追加。

.PARAMETER Delay
    每条之间的等待毫秒数，默认 700。机器慢就加大。

.PARAMETER Limit
    只灌前 N 条，用来先试水。

.PARAMETER Dump
    干完之后把整棵 UI 树 dump 到这个路径，便于核对。

.EXAMPLE
    .\add-presets.ps1 -File ..\phrases\packs\00-core.txt
    .\add-presets.ps1 -File ..\phrases\packs\*.txt -Clear -Delay 800
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string[]]$File,
    [switch]$Clear,
    [int]$Delay = 700,
    [int]$Limit = 0,
    [string]$Dump = ''
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'NekoTrakUIA.psm1') -Force

$main = Get-NekoTrakMainWindow
if (-not $main) { throw 'NekoTrak 主窗口没找到，先把它打开。' }
"pid=$((Get-Process NekoTrak | Select-Object -First 1).Id)"

if (-not (Enter-NekoTrakSettings $main -Tab '行为')) { throw '进不去「行为」Tab。' }

# --- 打开预设列表
# 注意：判断浮层是否已打开必须只看可见节点，否则上一次的 offscreen 残留会误判成「已经开着」。
if (-not (Get-NekoTrakNode $main -Name '自定义文本预设' -VisibleOnly)) {
    $btn = Get-NekoTrakNode $main -Name '打开预设列表' -ControlType ([System.Windows.Automation.ControlType]::Button)
    if (-not $btn) { throw '找不到「打开预设列表」按钮。' }
    Invoke-NekoTrakNode $btn | Out-Null
    Start-Sleep -Seconds 2
    Initialize-NekoTrakTree $main | Out-Null
    'opened preset dialog'
}

# --- 收集待写入内容
$values = @()
foreach ($f in $File) {
    $resolved = (Resolve-Path -LiteralPath $f).Path
    $part = Read-Utf8Lines $resolved
    "loaded $($part.Count) line(s) from $resolved"
    $values += $part
}
$values = @($values | Select-Object -Unique)
if ($Limit -gt 0) { $values = @($values | Select-Object -First $Limit) }
"total candidates = $($values.Count)"

# --- 可选：清空
if ($Clear) {
    $n = 0
    while ($true) {
        $d = Get-NekoTrakNode $main -Name '删除预设' -ControlType ([System.Windows.Automation.ControlType]::Button)
        if (-not $d) { break }
        Invoke-NekoTrakNode $d | Out-Null
        $n++
        Start-Sleep -Milliseconds 450
        if ($n -gt 2000) { break }
    }
    "cleared $n preset(s)"
    Start-Sleep -Milliseconds 600
}

# --- 逐条写入
$EditType = [System.Windows.Automation.ControlType]::Edit
$BtType   = [System.Windows.Automation.ControlType]::Button
$ok = 0; $bad = 0
foreach ($v in $values) {
    $ed = Get-NekoTrakNode $main -Like '新预设文本' -ControlType $EditType
    if (-not $ed) { "  input box gone - abort"; break }
    try { Set-NekoTrakEditValue $ed $v } catch { "  FAIL set '$v' : $($_.Exception.Message)"; $bad++; continue }
    Start-Sleep -Milliseconds 220

    $btn = Get-NekoTrakNode $main -Name '添加预设' -ControlType $BtType
    if (-not $btn) { "  add button gone - abort"; break }
    Invoke-NekoTrakNode $btn | Out-Null
    $ok++
    Start-Sleep -Milliseconds $Delay
}
"added ok=$ok bad=$bad"

# --- 复核：对话框里现在是几条
Initialize-NekoTrakTree $main | Out-Null
$count = 0
foreach ($e in (Get-NekoTrakNodes $main)) {
    try {
        $c = $e.Current
        if ($c.ControlType -eq [System.Windows.Automation.ControlType]::Group -and
            $c.ClassName -like '*truncate text-sm*') { $count++ }
    } catch { }
}
"dialog now holds $count preset(s)"

if ($Dump -ne '') {
    "dumped $((Export-NekoTrakTree $main $Dump)) node(s) -> $Dump"
}
