#Requires -Version 5.1
<#
  NekoTrakUIA.psm1 —— 用 UI Automation 驱动 NekoTrak（Tauri + WebView2）的公共底座。

  为什么需要它：
    NekoTrak 的前端打包在 exe 里，WebView2 的调试端口被 wry 的
    AdditionalBrowserArguments 硬编码占死（环境变量与注册表策略都无效），
    唯一可用的自动化通道就是 Windows UI Automation。

  三条硬规则（踩过的坑，别绕）：
    1) WebView2 的无障碍树是惰性构建的：先 FindAll 碰一次，再 sleep >= 2s，
       否则只能看到 18 个 Chrome 内部视图节点，看不到任何 DOM。
    2) 绝对不要用屏幕坐标点击：窗口中心是 TAURI_DRAG_RESIZE_BORDERS 拖拽区，
       点一下窗口就被拖走。一律用 InvokePattern / SelectionItemPattern / ValuePattern。
    3) 本模块文件必须存成 UTF-8 with BOM，否则 PowerShell 5.1 按 GBK 解析中文会炸。
#>

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$script:CT  = [System.Windows.Automation.ControlType]
$script:AE  = [System.Windows.Automation.AutomationElement]
$script:TW  = [System.Windows.Automation.TreeWalker]

function Get-NekoTrakMainWindow {
    <# 找到 NekoTrak 主窗口（ClassName='Tauri Window'，Name='NekoTrak'）。#>
    param([int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Tauri Window')

    while ((Get-Date) -lt $deadline) {
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)) {
            try { if ($w.Current.Name -eq 'NekoTrak') { return $w } } catch { }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Initialize-NekoTrakTree {
    <# 触发 WebView2 的无障碍树构建，然后等它长出来。#>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [int]$SettleSeconds = 2
    )
    $null = $MainWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                                [System.Windows.Automation.Condition]::TrueCondition)
    Start-Sleep -Seconds $SettleSeconds
}

function Get-NekoTrakNode {
    <#
      在整棵树里找第一个匹配的控件。 -Name 精确匹配，-Like 子串匹配。

      ★ 默认包含 offscreen 节点，这是刻意的。
        NekoTrak 的设置页很长，滚动区外的控件 IsOffscreen 会是 True，
        但它们照样能被 InvokePattern / ValuePattern 操作。
        旧版脚本不过滤才跑得通；加了过滤反而全部找不到。
        真要「只找看得见的」时才传 -VisibleOnly（典型用途：判断某个浮层是否还开着）。
    #>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [string]$Name,
        [string]$Like,
        $ControlType,
        [switch]$VisibleOnly
    )
    $all = $MainWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                               [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        try {
            $c = $e.Current
            if ($VisibleOnly -and $c.IsOffscreen) { continue }
            if ($PSBoundParameters.ContainsKey('Name') -and $c.Name -ne $Name) { continue }
            if ($PSBoundParameters.ContainsKey('Like') -and $c.Name -notlike "*$Like*") { continue }
            if ($ControlType -and $c.ControlType -ne $ControlType) { continue }
            return $e
        } catch { }
    }
    return $null
}

function Get-NekoTrakNodes {
    <# 返回整棵树的快照（数组），比每找一个控件就 FindAll 一次快得多。#>
    param([Parameter(Mandatory)] $MainWindow)
    return @($MainWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                                 [System.Windows.Automation.Condition]::TrueCondition))
}

function Invoke-NekoTrakNode {
    <# 依次尝试 Invoke / SelectionItem / Toggle / ExpandCollapse，返回实际用的模式名。#>
    param([Parameter(Mandatory)] $Element)

    $plans = @(
        @{ P = [System.Windows.Automation.InvokePattern]::Pattern;           K = 'Invoke' },
        @{ P = [System.Windows.Automation.SelectionItemPattern]::Pattern;    K = 'Select' },
        @{ P = [System.Windows.Automation.TogglePattern]::Pattern;           K = 'Toggle' },
        @{ P = [System.Windows.Automation.ExpandCollapsePattern]::Pattern;   K = 'Expand' }
    )
    foreach ($plan in $plans) {
        try {
            $o = $Element.GetCurrentPattern($plan.P)
            if ($null -eq $o) { continue }
            switch ($plan.K) {
                'Invoke' { $o.Invoke() }
                'Select' { $o.Select() }
                'Toggle' { $o.Toggle() }
                'Expand' { $o.Expand() }
            }
            return $plan.K
        } catch { }
    }
    return 'NONE'
}

function Set-NekoTrakEditValue {
    <# 用 ValuePattern 写输入框（比 SendKeys 可靠，且不受输入法/焦点影响）。#>
    param(
        [Parameter(Mandatory)] $Element,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Value
    )
    $vp = [System.Windows.Automation.ValuePattern]$Element.GetCurrentPattern(
            [System.Windows.Automation.ValuePattern]::Pattern)
    $vp.SetValue($Value)
}

function Get-NekoTrakEditValue {
    param([Parameter(Mandatory)] $Element)
    $vp = [System.Windows.Automation.ValuePattern]$Element.GetCurrentPattern(
            [System.Windows.Automation.ValuePattern]::Pattern)
    return $vp.Current.Value
}

function Find-NekoTrakEditAfterLabel {
    <#
      在某个标签文本之后的若干节点内找 Edit。
      NekoTrak 的表单输入框都没有 AccessibleName，只能按「标签 -> 紧随其后的 Edit」定位。
    #>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [Parameter(Mandatory)] [string]$Label,
        [int]$Lookahead = 6
    )
    $nodes = Get-NekoTrakNodes $MainWindow
    for ($i = 0; $i -lt $nodes.Count; $i++) {
        try {
            $c = $nodes[$i].Current
            if ($c.ControlType -ne $script:CT::Text -or $c.Name -ne $Label) { continue }
            for ($j = $i + 1; $j -lt [Math]::Min($i + 1 + $Lookahead, $nodes.Count); $j++) {
                if ($nodes[$j].Current.ControlType -eq $script:CT::Edit) { return $nodes[$j] }
            }
        } catch { }
    }
    return $null
}

function Invoke-NekoTrakAncestor {
    <#
      点一个用 Text 渲染的元素：沿 ControlViewWalker 向上找第一个带可执行模式的祖先。
      分类侧栏、Tab 标题这类节点自己不可点，可点的祖先通常在上面 1~3 层。
    #>
    param(
        [Parameter(Mandatory)] $Element,
        [int]$MaxDepth = 5
    )
    $node = $Element
    for ($k = 0; $k -lt $MaxDepth; $k++) {
        $node = $script:TW::ControlViewWalker.GetParent($node)
        if (-not $node) { break }
        $r = Invoke-NekoTrakNode $node
        if ($r -ne 'NONE') { return $r }
    }
    return 'NONE'
}

function Enter-NekoTrakSettings {
    <# 侧栏 -> 设置 -> 指定 Tab（默认「行为」）。所有多步脚本都该先跑这段。#>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [string]$Tab = '行为'
    )
    Initialize-NekoTrakTree $MainWindow | Out-Null

    if (-not (Get-NekoTrakNode $MainWindow -Name $Tab)) {
        $s = Get-NekoTrakNode $MainWindow -Name '设置' -ControlType $script:CT::Button
        if ($s) {
            Invoke-NekoTrakNode $s | Out-Null
            Start-Sleep -Seconds 3
            Initialize-NekoTrakTree $MainWindow | Out-Null
        }
    }
    $t = Get-NekoTrakNode $MainWindow -Name $Tab
    if ($t) {
        Invoke-NekoTrakNode $t | Out-Null
        Start-Sleep -Seconds 3
        Initialize-NekoTrakTree $MainWindow | Out-Null
        return $true
    }
    return $false
}

function Enter-NekoTrakPage {
    <# 点侧栏一级导航：仪表盘 / 待办 / 分类 / 应用 / 网站 / 统计 / 联机 / 宠物 / 设置。#>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [Parameter(Mandatory)] [string]$Page
    )
    Initialize-NekoTrakTree $MainWindow | Out-Null
    $p = Get-NekoTrakNode $MainWindow -Name $Page -ControlType $script:CT::Button
    if (-not $p) { return $false }
    Invoke-NekoTrakNode $p | Out-Null
    Start-Sleep -Seconds 3
    Initialize-NekoTrakTree $MainWindow | Out-Null
    return $true
}

function Export-NekoTrakTree {
    <# dump 整棵树，用于侦察 UI 结构。#>
    param(
        [Parameter(Mandatory)] $MainWindow,
        [Parameter(Mandatory)] [string]$Path
    )
    $out = New-Object System.Collections.Generic.List[string]
    $i = 0
    foreach ($e in (Get-NekoTrakNodes $MainWindow)) {
        try {
            $c = $e.Current
            $ct = $c.ControlType.ProgrammaticName.Replace('ControlType.', '')
            if ($ct -eq 'Image') { continue }
            $n = $c.Name
            if ($n -eq '' -and $ct -eq 'Pane') { continue }
            if ($n.Length -gt 100) { $n = $n.Substring(0, 100) + '...' }
            $cls = $c.ClassName
            if ($cls.Length -gt 60) { $cls = $cls.Substring(0, 60) + '...' }
            $out.Add(("[{0,4}] {1} | {2} | {3} | id='{4}' | off={5} en={6}" -f `
                      $i, $ct, $cls, $n, $c.AutomationId, $c.IsOffscreen, $c.IsEnabled))
            $i++
        } catch { }
    }
    [System.IO.File]::WriteAllLines($Path, $out, (New-Object System.Text.UTF8Encoding($false)))
    return $out.Count
}

function Read-Utf8Lines {
    <# 读 UTF-8 行文件，跳过空行。#>
    param([Parameter(Mandatory)] [string]$Path)
    $vals = @()
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        if ($line.Trim() -ne '') { $vals += $line }
    }
    return $vals
}

Export-ModuleMember -Function @(
    'Get-NekoTrakMainWindow', 'Initialize-NekoTrakTree', 'Get-NekoTrakNode', 'Get-NekoTrakNodes',
    'Invoke-NekoTrakNode', 'Set-NekoTrakEditValue', 'Get-NekoTrakEditValue',
    'Find-NekoTrakEditAfterLabel', 'Invoke-NekoTrakAncestor',
    'Enter-NekoTrakSettings', 'Enter-NekoTrakPage', 'Export-NekoTrakTree', 'Read-Utf8Lines'
)
