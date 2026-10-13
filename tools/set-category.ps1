#Requires -Version 5.1
<#
.SYNOPSIS
    批量把 NekoTrak 应用库里的应用归入分类（应用 -> 卡片上的「分类: X」-> 菜单项）。

.DESCRIPTION
    卡片上的「分类: X」按钮只有 ExpandCollapsePattern（没有 InvokePattern），
    Expand 之后会弹出 8 个 MenuItem：
        未分类 / 游戏 / 媒体 / 社交 / 工作 / 创作 / 参考 / 工具
    点 MenuItem 走 InvokePattern。

    为了让脚本不依赖滚动，输入的 TSV 里带一列「搜索词」：
    脚本会把它填进应用页的搜索框（ClassName 含 'pl-9' 的 Edit），把列表筛到那张卡。

    输入 TSV 三列：搜索词 <TAB> 分类名 <TAB> 卡片上显示的完整路径

.PARAMETER File
    UTF-8 TSV，三列。

.PARAMETER Delay
    每条之间的等待毫秒数，默认 2600（改分类后列表会重排，别太急）。

.EXAMPLE
    .\set-category.ps1 -File .\setcat.tsv
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$File,
    [int]$Delay = 2600
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'NekoTrakUIA.psm1') -Force

$CT = [System.Windows.Automation.ControlType]

$rows = @()
foreach ($line in [System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $File).Path,
                                                 [System.Text.Encoding]::UTF8)) {
    if ($line.Trim() -eq '') { continue }
    $p = $line -split "`t"
    if ($p.Count -lt 3) { continue }
    $rows += [pscustomobject]@{ Query = $p[0].Trim(); Cat = $p[1].Trim(); Path = $p[2].Trim() }
}
"items = $($rows.Count)"

$main = Get-NekoTrakMainWindow
if (-not $main) { throw 'NekoTrak 主窗口没找到。' }
if (-not (Enter-NekoTrakPage $main -Page '应用')) { throw '进不去「应用」页。' }

# 搜索框：ClassName 含 pl-9 的 Edit
function Get-SearchBox($m) {
    foreach ($e in (Get-NekoTrakNodes $m)) {
        try {
            if ($e.Current.ControlType -eq $CT::Edit -and $e.Current.ClassName -like '*pl-9*') { return $e }
        } catch { }
    }
    return $null
}

$ok = 0; $bad = 0; $skip = 0
foreach ($row in $rows) {
    $box = Get-SearchBox $main
    if (-not $box) { "  no search box - abort"; break }
    Set-NekoTrakEditValue $box $row.Query
    Start-Sleep -Milliseconds 1400
    Initialize-NekoTrakTree $main | Out-Null

    # 定位卡片：先找路径 Text，再在其后的节点里找「分类:」按钮
    $nodes = Get-NekoTrakNodes $main
    $pathIdx = -1
    for ($i = 0; $i -lt $nodes.Count; $i++) {
        try { if ($nodes[$i].Current.Name -eq $row.Path) { $pathIdx = $i; break } } catch { }
    }
    if ($pathIdx -lt 0) { "  [$($row.Path)] card not found"; $bad++; continue }

    $catBtn = $null
    for ($j = $pathIdx; $j -lt [Math]::Min($pathIdx + 8, $nodes.Count); $j++) {
        try {
            $c = $nodes[$j].Current
            if ($c.ControlType -eq $CT::Button -and $c.Name -like '分类:*') { $catBtn = $nodes[$j]; break }
        } catch { }
    }
    if (-not $catBtn) { "  [$($row.Path)] no 分类 button"; $bad++; continue }

    if ($catBtn.Current.Name -eq "分类: $($row.Cat)") {
        "  SKIP [$($row.Query)] already=$($row.Cat)"; $skip++; continue
    }

    Invoke-NekoTrakNode $catBtn | Out-Null   # Expand
    Start-Sleep -Milliseconds 900
    Initialize-NekoTrakTree $main | Out-Null

    $mi = Get-NekoTrakNode $main -Name $row.Cat -ControlType $CT::MenuItem
    if (-not $mi) { "  [$($row.Query)] menu item '$($row.Cat)' not found"; $bad++; continue }
    $how = Invoke-NekoTrakNode $mi
    "  OK   [$($row.Query)] -> $($row.Cat) (menu=$how)"
    $ok++
    Start-Sleep -Milliseconds $Delay
}
"done ok=$ok skip=$skip bad=$bad"
