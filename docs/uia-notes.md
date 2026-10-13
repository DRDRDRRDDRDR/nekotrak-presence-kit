# UIA 通道：全部细节与踩坑

给 NekoTrak 这类 Tauri + WebView2 应用做自动化，UI Automation 是最后一条活路。这份文档把走通的路径和撞过的墙都写下来。

---

## 一、为什么不用 CDP（远程调试）

想操作 WebView2 里的 DOM，标准做法是开远程调试端口，用 CDP 协议。**这条路在 NekoTrak 上是代码级死的。**

### 死因

Tauri 的 wry 层**硬编码**了 `AdditionalBrowserArguments`。按 WebView2 的官方规则：

> **宿主一旦显式设置了 `AdditionalBrowserArguments` 属性，`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 环境变量一律被忽略。**

在 NekoTrak.exe 里能直接找到那个字符串（1.1.6，偏移 45431984）：

```
--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required --proxy-server=http:// --proxy-server=socks5://
```

紧挨着后面是 UTF-16 的 `WRY_WEBVIEW`。这就是 WebView2 子进程实际收到的全部参数 —— 没有给环境变量留位置。

### 实测（两次，都失败）

**实验 1**：PowerShell 里 `$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=9444'`，然后 `Start-Process` 启动。
结果：子进程命令行里没有 marker，`9444` 不监听。

**实验 2**（更严格）：用 Python 显式构造子进程环境字典，`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 启动：

```python
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9444 --nk-marker-xyz"
```

结果：WebView2 命令行里 `marker=False port9444=False`，只有 wry 的那串默认参数。

### 其他通道也一并排除

| 通道 | 结果 |
|---|---|
| 注册表企业策略 `Policies\Microsoft\Edge` | 在 WebView2 运行时目录全文件搜索 **0 命中**，没有挂载点 |
| exe 里的配置开关 | `devtoolsEnabled` / `debugMode` / `open_devtools` / `enable_devtools` / `RemoteDebuggingAllowed` **全部 0 命中** |
| F12 热键 | 焦点成功夺取（`AttachThreadInput` 强制前台），`keybd_event(0x7B)` 原生 F12 连按三次，**窗口树零变化**；截图确认就是正常仪表盘，没有 DevTools。这个应用没编 DevTools |

另一个陷阱：**端口 9222 被 Opera GX 占了**。`/json`、`/json/version` 全部返回 **HTTP 404**。

> **教训**：404 而不是「连接被拒绝」= 端口被别的 HTTP 服务占了。查 `Get-NetTCPConnection -LocalPort 9222 | Select OwningProcess` 再动手，别浪费时间改参数。

---

## 二、UIA 的坑：无障碍树是惰性的

**这是整件事最关键的一条。**

第一次调用 `FindAll(Descendants, TrueCondition)`，只能拿到十几个节点，而且全是 Chrome 内部视图：

```
TAURI_DRAG_RESIZE_BORDERS
WRY_WEBVIEW
Chrome_WidgetWin_1
Intermediate D3D Window
BrowserRootView
NonClientView
EmbeddedBrowserFrameView
BrowserView
TopContainerView
SidebarContentsSplitView
MultiContentsView
...
```

**看起来就像 WebView2 根本不暴露 DOM** —— 我一开始就是这么误判的，写下了「UIA 路线不可用」的结论。

实际是**惰性构建**。实测三次采样同一窗口：

| 采样时机 | 节点数 | 内容 |
|---|---|---|
| T+0s | 18 | 只有 Chrome 内部视图 |
| T+3s | **162** | 出现 `Document name='NekoTrak'`，底下是完整 React DOM |
| T+9s | 162 | 稳定 |

**正确姿势**：

```powershell
# 1. 先碰一次，触发树构建
$null = $MainWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                            [System.Windows.Automation.Condition]::TrueCondition)
# 2. 等它长出来
Start-Sleep -Seconds 2
# 3. 现在 DOM 完整可读可操作
```

触发之后，DOM 就全在了 —— `Document` 节点 `name='NekoTrak'`，里面 Button 带 `name`、Edit 能写值、TabItem 能选中。

---

## 三、操作模式对照表

| 目标 | 用的模式 | 备注 |
|---|---|---|
| Button | `InvokePattern.Invoke()` | 包括 React 渲染的按钮，实测有效 |
| TabItem | `SelectionItemPattern.Select()` | 设置页六个 Tab |
| ToggleButton | `TogglePattern.Toggle()` | 开关 |
| Edit | `ValuePattern.SetValue()` | 比 SendKeys 可靠，不受输入法和焦点影响 |
| ComboBox | `ExpandCollapsePattern.Expand()` | **但展开后的选项在 WebView2 popup 里，不在主窗口树内，读不到选项清单** |
| 卡片上的「分类: X」 | `ExpandCollapsePattern.Expand()` → MenuItem `Invoke()` | **它没有 InvokePattern**，直接 Invoke 会失败 |
| 用 Text 渲染的可点元素 | 沿 `ControlViewWalker` 向上找可执行祖先 | 见下 |

### 没有 AccessibleName 的控件怎么找

NekoTrak 的表单输入框**都没有无障碍名**。定位方式是「标签 Text 之后的第一个 Edit」：

```powershell
# 在名为「应用名称」的 Text 节点之后 6 个节点内找 Edit
$ed = Find-NekoTrakEditAfterLabel $main -Label '应用名称' -Lookahead 6
```

已确认可用：

| 标签 | 输入框 |
|---|---|
| `应用名称` | 新建应用对话框的名称框 |
| `可执行文件 / 路径` | 新建应用对话框的路径框 |
| `新预设文本...` | 预设对话框的添加框（用 `-Like` 子串匹配） |

### 用 Text 渲染的可点元素

分类页侧栏的分类名、Tab 标题这类，节点本身是 `Text`，不带任何模式。可点的祖先在**上面 1~3 层**：

```powershell
$node = $TextElement
for ($k = 0; $k -lt 5; $k++) {
    $node = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($node)
    if (-not $node) { break }
    $r = Invoke-NekoTrakNode $node     # 依次试 Invoke/Select/Toggle/Expand
    if ($r -ne 'NONE') { break }
}
```

### 搜索框

应用页的搜索框 ClassName 含 `pl-9`：

```powershell
if ($e.Current.ControlType -eq $Edit -and $e.Current.ClassName -like '*pl-9*') { ... }
```

用它把列表筛到单张卡，比滚动遍历可靠得多。

---

## 四、血流下来的教训

### 1. 绝对不要用屏幕坐标点击

`ClickCenter` 点窗口中心 → 落进了 `TAURI_DRAG_RESIZE_BORDERS` 拖拽区 → **窗口被拖走了**。

证据：两次截图 `GetWindowRect` 返回的 origin 不同（250,220 → 2495,268），窗口跑到了另一个显示器的坐标上。

一律用 UIA 模式，别碰坐标。

### 2. 主窗口类名是 `Tauri Window`

不是 `Chrome_WidgetWin_1`。按后者匹配的枚举脚本会返回 `hwnd = 0x0`，静默失败。

```powershell
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Tauri Window')
# 再按 Name -eq 'NekoTrak' 确认
```

### 3. 对话框不是独立窗口

「新建应用」「自定义文本预设」都是 **WebView2 内的 React 浮层**，节点直接存在于主窗口的无障碍树里。按顶层窗口枚举是找不到的。

判定对话框是否打开时，**必须排除 offscreen 节点**：

```powershell
if ($e.Current.Name -eq '自定义文本预设' -and -not $e.Current.IsOffscreen) { ... }
```

否则上一次的残留节点会让你以为对话框还开着。

### 4. 前置导航必须内置

应用可能停在任意页面。任何多步脚本都该先做：

```
侧栏「设置」→ 「行为」TabItem  → 再找目标控件
```

没有这段前置导航的脚本，在仪表盘页会静默 `exit 1`，报 `cannot open preset dialog ('打开预设列表' not found)`。

### 5. 别指望从 ComboBox 读选项

`Expand()` 之后，选项渲染在 WebView2 的 popup 里，**不在主窗口的 UIA 树内**。只能读到当前选中值，读不到选项清单。要确认可选值，得从 exe 字符串或界面文案反推。

---

## 五、踩过的 PowerShell 坑（不是 UIA 的锅，但会一起炸）
### 中文 .ps1 必须带 UTF-8 BOM

无 BOM 的 UTF-8 中文脚本，PS 5.1 按 GBK 解析，报出来的错完全看不出病因：

```
Missing closing ')' in expression.
The string is missing the terminator: ".
```

而且报错行显示的**中文是乱码**（`'鏂伴璁炬枃鏈?`）—— 这就是信号。

写完脚本补 BOM：

```powershell
$f = 'C:\path\to\script.ps1'
[System.IO.File]::WriteAllText($f,
    [System.IO.File]::ReadAllText($f, [Text.Encoding]::UTF8),
    (New-Object System.Text.UTF8Encoding($true)))
```

校验：`[System.IO.File]::ReadAllBytes($f)[0..2]` 应该是 `239,187,191`。

> 用 `edit` 工具改过的 .ps1 会**丢掉 BOM**，改完记得补。

### 变量名大小写不敏感

```powershell
$P = 'C:\dir'
foreach ($f in $files) { $p = Join-Path $P $f }   # $p 和 $P 是同一个变量！
```

结果拼出 `...\probe2.ps1\ui.ps1` 这种怪路径。**别同时用大小写只差一个字母的变量名。**

### `*>` 重定向写出的是 UTF-16

```powershell
.\script.ps1 *> log.txt      # log.txt 是 UTF-16
```

读它：

```powershell
$fs = [System.IO.File]::Open($p, 'Open', 'Read', 'ReadWrite')   # 进程可能还持有句柄
$sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::Unicode)
```

不加 `ReadWrite` 共享，读运行中任务的日志会 `IOException: 文件正由另一进程使用`。

### 没有 heredoc

`python - <<'PY' ... PY` 在 PS 5.1 里不存在，报 `缺少表达式` / `缺少文件规范`。写成 `.py` 文件再跑。

### 函数名撞内置别名

```powershell
function Echo { ... }     # 被内置别名 Echo (Write-Output) 吞掉，输出丢失
```

改个名（比如 `Snap`）就好。

### `Start-Sleep -Seconds $Delay` 会把毫秒当秒用

写脚本时很容易把手感的「毫秒延迟」参数直接喂给秒版 cmdlet：

```powershell
param([int]$Delay = 1800)          # 1800 毫秒，人之常情
...
Start-Sleep -Seconds $Delay        # 变成睡 1800 秒 = 30 分钟
```

表现是**脚本看起来彻底卡死**（跑到 600 秒超时都不返回），而逻辑其实完全正确。本项目就踩过：`set-category-format.ps1` 的 `-Read` 模式一次跑 8 个分类，每类睡两次 30 分钟，实际永远跑不完。

**判据**：脚本「卡死」但逐步手工复现能 25 秒跑完 → 先全局搜一遍 `Start-Sleep -Seconds $`。

### 编辑工具会吃掉 UTF-8 BOM

任何编辑工具改写已有 `.ps1` 后，BOM 通常就没了。改完必须补：

```powershell
$f = 'tools\add-presets.ps1'
[System.IO.File]::WriteAllText($f, [System.IO.File]::ReadAllText($f, [Text.Encoding]::UTF8), (New-Object System.Text.UTF8Encoding($true)))
$b = [System.IO.File]::ReadAllBytes($f); "$($b[0]),$($b[1]),$($b[2])"   # 应该是 239,187,191
```
