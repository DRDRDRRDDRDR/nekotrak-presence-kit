# nekotrak-presence-kit

把 [NekoTrak](https://store.steampowered.com/app/5249210/NekoTrak/) 的 Steam / Discord 在线状态，做成一个能自己长东西的玩意儿。

三样东西：

1. **`PROMPT.md`** —— 一份可以直接丢给 AI Agent 的提示词。它会带着 AI 从零摸清 NekoTrak 的状态文本机制、把你的浏览器历史和应用清单读出来、生成只属于你的搞怪短语、再通过 Windows UI Automation 直接灌进软件里。
2. **`phrases/`** —— 426 条现成的中文搞怪短语，按 19 个风格包分好，用软件支持的命令替换语法写成，可以一条一条挑，也可以整包灌。
3. **`tools/`** —— 6 个 PowerShell 脚本，干活的。批量灌短语、扫描导入本机应用、批量改分类、按前台程序吐词。

---

## 先说机制：不然写了也白写

NekoTrak 的「自定义文本」有个命令替换语法 —— 输入框的 placeholder 原文是：

> 添加自定义文本项，可通过 `${...}` 语法调用终端命令

**只有 `${...}` 里的东西会被执行**（交给「终端程序」设置项，本机默认是 `cmd`），stdout 会被内联进最终状态。花括号外面的内容原样输出。

实测（把值写进去，读「Steam 状态预览」）：

| 写入 | 预览显示 | 结论 |
|---|---|---|
| `${echo hi}` | `hi` | 执行了 |
| `%RANDOM%` | `%RANDOM%` | **没执行**，原样吐出 |
| `R%RANDOM%S ${echo T1}${echo T2}` | `R%RANDOM%S T1T2` | 裸变量死，`${}` 活，且可相邻拼接 |

所以网上那些教你写 `%RANDOM%` 的 NekoTrak 教程是错的。正确的写法是：

```
正在找回 hotmail，第 ${echo %RANDOM%} 次
```

`${}` 里跑的是 cmd，所以 cmd 那套变量能直接用：`%RANDOM%`、`%TIME%`、`%TIME:~0,5%`、`%DATE%`、`%COMPUTERNAME%`、`%USERNAME%`。

**副作用警告**：`${}` 里是真正的命令行执行，不是沙箱。`${echo hi > C:\x.txt}` 是真会写文件的。别把来路不明的字符串贴进去。

**预设存在哪**：不在 `config.json`，在一个 SQLCipher 加密的 SQLite 库里（表 `custom_text_presets`），密钥由 SteamID 派生。外部脚本写不进去 —— 只能走界面。这就是 `tools/` 存在的理由。

---

## 用法

### 一、直接拿现成短语

`phrases/packs/` 下 19 个文件，共 **426 条**，分成两组：

**A 组 · 个人包（300 条）** —— 从真实浏览历史和软件清单里长出来的，带具体名字、具体数字。分成 14 个：

| 文件 | 条数 | 内容 |
|---|---|---|
| `00-core.txt` | 47 | 核心包：身份 / 搜索史 / 游戏 / 音频 / 破解 / 猫 / 荒诞 |
| `01-identity-search.txt` | 27 | 身份延伸 + 搜索史 + API 薅羊毛 |
| `07-games.txt` | 21 | 塔科夫 / 法环 / PAYDAY / 独立游戏 / Mod |
| `08-audio-music.txt` | 17 | 音频路由 / 变声 / 编曲 / 修音 |
| `09-hacking-tools.txt` | 12 | 越狱解锁 / Steam 工具 / 修改器 / 加速器 |
| `10-cat.txt` | 10 | NekoTrak 猫梗 |
| `11-absurd.txt` | 10 | 纯荒诞 |
| `16-productivity.txt` | 24 | 摸鱼生产力 / 进程 / 浏览器 |
| `17-media-live.txt` | 12 | 直播 / 剪辑 / 渲染 |
| `18-dev.txt` | 30 | 开发 / AI 写码 / 终端 / 服务器 |
| `19-network.txt` | 18 | 代理组网 / 下载 / 解压 |
| `20-office.txt` | 14 | 办公 / 会议 / 翻译 |
| `21-system.txt` | 18 | 备份分区 / 硬件 / 显卡 / 蓝屏 |
| `22-security.txt` | 40 | 安全 / 破解汉化 / 报错重装 / 自动化 / 注册表 |

**B 组 · 体裁包（126 条）** —— 不限个人经历，纯玩文体，谁都能用：

| 文件 | 条数 | 内容 |
|---|---|---|
| `02-cyber-ritual.txt` | 26 | 赛博祭祀：机魂、开机仪式、向风扇祈祷 |
| `03-military.txt` | 26 | 军事战报腔：阵地、弹药、战损 |
| `04-support-ticket.txt` | 24 | 客服工单腔：排队、转接、已关闭 |
| `05-classical.txt` | 24 | 文言古风：夜半三更、问君能有几多愁 |
| `06-logfile.txt` | 26 | 系统日志腔：INFO/WARN/FATAL、异常堆栈 |

两个合并文件：`phrases/all-300.txt`、`phrases/all-genre-126.txt`。

**个人包更好笑，但只对我好笑。** 体裁包你拿去就能用。

批量灌进去（NekoTrak 开着）：

```powershell
cd tools
.\add-presets.ps1 -File ..\phrases\packs\00-core.txt
```

想清空重来加 `-Clear`，想整包一起上给多个文件：

```powershell
.\add-presets.ps1 -File ..\phrases\packs\*.txt -Clear -Delay 800
```

### 二、把你自己的应用导进去

NekoTrak 自带扫描，但它只收「开启后跑过一遍」的应用。要一次收全：

```powershell
cd tools
.\scan-installed-apps.ps1 -Out ..\apps.tsv     # 扫注册表 + 运行中进程 + 开始菜单
.\add-apps.ps1 -File ..\apps.tsv -Test         # 先试一条，确认通道通
.\add-apps.ps1 -File ..\apps.tsv -Delay 700    # 全量
```

然后再批量分类：

```powershell
# setcat.tsv 三列：搜索词 <TAB> 分类名 <TAB> 卡片上显示的完整路径
.\set-category.ps1 -File .\setcat.tsv
```

分类名只能是这 8 个：`未分类 游戏 媒体 社交 工作 创作 参考 工具`。

### 三、让短语跟着你在用的 App 变

NekoTrak 的「应用活动」段本来就会随前台 App 变（显示应用名和图标），但**你选中的那条自定义文本是死的**。想让短语也跟着变，把这条整串丢进「自定义文本项」：

```
${powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\path\to\tools\fg-phrase.ps1}
```

改 `tools/fg-phrase.ps1` 里的 `$Rules` 表就能加规则。

**代价**：每次状态刷新都要起一次 PowerShell，实测单次约 1.4 秒。状态会比平时慢半拍，能接受再开。

---

## 工具清单

| 脚本 | 干什么 |
|---|---|
| `NekoTrakUIA.psm1` | 公共底座：找主窗口、触发 WebView2 无障碍树、找控件、点控件、写输入框 |
| `add-presets.ps1` | 批量灌短语到预设库 |
| `add-apps.ps1` | 批量导入应用（应用 → 新建应用） |
| `set-category.ps1` | 批量改应用分类 |
| `scan-installed-apps.ps1` | 扫描本机应用，产出 TSV |
| `fg-phrase.ps1` | 按前台程序吐词（给 `${}` 调用的） |

**全部要求 PowerShell 5.1+，全部存成 UTF-8 with BOM。** 这不是洁癖 —— 无 BOM 的 UTF-8 中文 .ps1 会被 PS 5.1 按 GBK 解析，报一堆莫名其妙的 `Missing closing ')'`。改完脚本记得补回 BOM：

```powershell
$f = 'tools\add-presets.ps1'
[System.IO.File]::WriteAllText($f, [System.IO.File]::ReadAllText($f, [Text.Encoding]::UTF8), (New-Object System.Text.UTF8Encoding($true)))
```

---

## 为什么是 UI Automation（而不是 DevTools）

想自动化一个 Tauri + WebView2 应用，正常人第一反应是开远程调试端口，用 CDP 直接操作 DOM。这条路在 NekoTrak 上**走不通**，而且是代码级的死：

- Tauri 的 wry 层硬编码了 `AdditionalBrowserArguments`。按 WebView2 规则，**宿主一旦显式设置这个属性，`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 环境变量一律被忽略**。实测用 Python 显式构造子进程环境塞 `--remote-debugging-port=9444`，WebView2 命令行里连个影子都没有。
- 注册表企业策略（`Policies\Microsoft\Edge`）在 WebView2 运行时目录里搜不到挂载点。
- exe 里 `devtoolsEnabled` / `open_devtools` / `RemoteDebuggingAllowed` 全部 0 命中，没有配置开关。
- F12 热键：这个应用的 DevTools 没开，按了没反应。

剩下的路只有 UI Automation。它有一个大坑：

> **WebView2 的无障碍树是惰性构建的。** 第一次 `FindAll(Descendants, TrueCondition)` 只能拿到 18 个 Chrome 内部视图节点（`WRY_WEBVIEW`、`BrowserRootView`、`NonClientView` …），看起来像根本没有 DOM。**碰一次，sleep ≥ 2 秒，再查就有 162 个节点**，`Document name='NekoTrak'` 底下是完整的 React DOM，按钮带名字、输入框能写值。

知道了这个，一切就通了：

- 按钮 → `InvokePattern.Invoke()`
- Tab → `SelectionItemPattern.Select()`
- 输入框 → `ValuePattern.SetValue()`
- 「分类: X」按钮 → 它**只有 `ExpandCollapsePattern`**，`Expand()` 之后弹出 8 个 `MenuItem`，再 Invoke 选中的
- 用 Text 渲染的可点元素（侧栏分类名、Tab 标题）→ 沿 `ControlViewWalker` 向上找第一个带可执行模式的祖先
- **绝对不要用屏幕坐标点击** —— 窗口中心是 `TAURI_DRAG_RESIZE_BORDERS` 拖拽区，点一下窗口就被拖走了（这是真踩过的）

---

## 目录

```
nekotrak-presence-kit/
├── PROMPT.md                 # 丢给 AI 的提示词
├── README.md
├── phrases/
│   ├── packs/                # 19 个风格包，426 条
│   ├── all-300.txt           # 个人包合并版
│   └── all-genre-126.txt     # 体裁包合并版
├── tools/                    # 6 个 PowerShell 脚本
└── docs/
    ├── mechanism.md          # 机制取证全过程：怎么证明 ${} 才执行
    ├── uia-notes.md          # UIA 通道细节与全部踩坑
    └── recipe.md             # 从零复刻一遍的完整操作序列
```

---

## 许可

短语和文档随便用。脚本按 MIT。

**但请先读一遍 `docs/mechanism.md` 的副作用一节** —— `${}` 是真执行命令，不是模板替换。
