#Requires -Version 5.1
<#
.SYNOPSIS
    按当前前台程序吐出一句搞怪短语 —— 让状态栏随你正在用的 App 自动变。

.DESCRIPTION
    把这条命令整串丢进 NekoTrak 的「自定义文本项」输入框：

        ${powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\path\to\fg-phrase.ps1}

    NekoTrak 每次刷新状态都会重新执行它，于是短语跟着前台程序走。

    代价：每次刷新都要起一个 PowerShell 进程，实测单次约 1.4 秒。
    所以「应用活动」那一段会比平时慢半拍，能接受再开。

    想加规则就往 switch 里加行，或者直接改 $Rules 表（正则 -> 模板）。
    $name 在这张表里能直接用；$r 是 1..998 的随机数。

.PARAMETER Plain
    不要随机数，永远输出模板原文（调试用）。

.EXAMPLE
    .\fg-phrase.ps1
    .\fg-phrase.ps1 -Plain
#>
[CmdletBinding()]
param([switch]$Plain)

# --- 中文输出必须显式走 UTF-8，否则 NekoTrak 收到的是乱码
$enc = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $enc } catch { }
try { $OutputEncoding = $enc } catch { }

function Get-ForegroundProcessName {
    $sig = @'
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
'@
    $t = Add-Type -MemberDefinition $sig -Name 'NkFg' -Namespace 'NekoTrakKit' -PassThru -ErrorAction SilentlyContinue
    if (-not $t) { $t = [NekoTrakKit.NkFg] }
    $h = $t::GetForegroundWindow()
    $pid_ = 0
    [void]$t::GetWindowThreadProcessId($h, [ref]$pid_)
    try { return (Get-Process -Id $pid_ -ErrorAction Stop).ProcessName } catch { return '未知程序' }
}

# 正则 -> 模板。顺序有意义，先匹配到的先用。
# 占位符：{n} = 进程名，{r} = 随机数
$Rules = [ordered]@{
    '^(Code|devenv|Qoder|WorkBuddy|WindowsTerminal|powershell|pwsh|cmd|conhost)$' = '正在写代码，第 {r} 个 bug'
    '^(opera|msedge|chrome|firefox|Waterfox|brave)$'                             = '正在浏览，第 {r} 个标签页'
    '^(steam|steamwebhelper)$'                                                    = '正在挑游戏，购物车 {r} 个'
    '^(EscapeFromTarkov|EscapeFromTarkov_BE)$'                                    = '正在被大树守卫教育，第 {r} 次'
    '^(NekoTrak)$'                                                                = '正在被一只猫监督，第 {r} 圈'
    '^(mstsc)$'                                                                   = '正在远程别人的电脑，延迟 {r} ms'
    '^(QQ|WeChat|Weixin|Discord|TeamSpeak|Telegram|Oopz|KOOK)$'                   = '正在假装社交，第 {r} 次已读不回'
    '^(PotPlayerMini64|vlc|mpv|Cider)$'                                           = '正在看片，看到第 {r} 分钟'
    '^(FL64|FL|FLStudio|Studio One|Melodyne|Serato DJ Pro)$'                      = '正在编曲，第 {r} 小节还没编出来'
    '^(OBS64|obs64|bilibili直播姬|StartLive|直播伴侣)$'                            = '正在直播，第 {r} 个观众是我自己'
    '^(Photoshop|Illustrator|Resolve|Cinema 4D|CapCut|JianyingPro|万兴喵影)$'     = '正在做图，第 {r} 版还是第一版好看'
    '^(explorer)$'                                                                = '正在翻文件夹，第 {r} 层目录'
    '^(clash-verge|Clash Verge|Clash|verge)$'                                     = '正在科学上网，第 {r} 个节点都不通'
    '^(UU|uu|ZeroTier|zerotier|easyTier|easytier-gui)$'                           = '正在加速，延迟从 {r} ms 变成 {r} ms'
    '^(wps|WINWORD|EXCEL|POWERPNT|et|wpp)$'                                       = '正在假装办公，第 {r} 页排版又乱了'
    '^(Taskmgr|procexp64)$'                                                       = '正在看第 {r} 个进程是谁开的'
}

$name = Get-ForegroundProcessName
$r = Get-Random -Minimum 1 -Maximum 999

foreach ($pattern in $Rules.Keys) {
    if ($name -match $pattern) {
        $tpl = $Rules[$pattern]
        $out = $tpl.Replace('{n}', $name)
        if ($Plain) { $out = $out.Replace('{r}', 'N') } else { $out = $out.Replace('{r}', [string]$r) }
        return $out
    }
}

if ($Plain) { return '正在用 {n}，第 N 次' }
return "正在用 $name，第 $r 次"
