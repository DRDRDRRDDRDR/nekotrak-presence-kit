# nekotrak-presence-kit

把 [NekoTrak](https://store.steampowered.com/app/5249210/NekoTrak/) 的 Steam / Discord 在线状态，做成一个能自己长东西的玩意儿。

三样东西：

1. **`PROMPT.md`** —— 一份可以直接丢给 AI Agent 的提示词。它会带着 AI 从零摸清 NekoTrak 的状态文本机制、把你的浏览器历史和应用清单读出来、生成只属于你的搞怪短语、再通过 Windows UI Automation 或者直接写数据库，把它们灌进软件里。
2. **`phrases/`** —— 426 条现成的中文搞怪短语，按 19 个风格包分好，外加 6 套分类状态格式模板。可以一条一条挑，也可以整包灌。
3. **`tools/`** —— 8 个工具：7 个 PowerShell 脚本走界面，1 个 Python 工具直接写数据库（300 条 0.13 秒）。批量灌短语、扫描导入本机应用、批量改分类、按分类设状态模板、按前台程序吐词。

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

`${}` 里跑的是 cmd，所以 cmd 那套变量能直接用：`%RANDOM%`、`%TIME%`、`%TIME:~0,5%`、`%DATE%`。

（`%COMPUTERNAME%` 和 `%USERNAME%` 也能用，但它们会把你的机器名和账户名广播到 Steam 状态栏上。这套短语包刻意不用它们 —— 需要露面就写死一个代号。）

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

### 三、让短语跟着你在用的 App 变（原生通道，推荐）

**这条是软件自带的，不用跑任何脚本。** 每个分类可以有自己的「状态显示格式」。当前台应用属于某个分类时，就用那个分类的模板渲染状态。

路径：`分类` → 选中分类 → `编辑` → 「状态显示格式」输入框。

模板变量实测只有两个：

| 变量 | 行为 |
|---|---|
| `{app}` | 替换成当前应用名，**约 400 ms 内跟上切换** |
| `{title}` | 窗口标题，实测常为空/原样输出，别依赖 |
| 其他 `{xxx}` | 一律原样输出，不报错 —— 所以别写 `{song}`/`{time}` 这类幻觉变量 |

批量设置：

```powershell
cd tools
.\set-category-format.ps1 -Category 游戏 -Format '{app} 已启动 | 这局我很认真'
.\set-category-format.ps1 -MapFile ..\phrases\category-formats\03-military.tsv
.\set-category-format.ps1 -Read                   # 回显各分类当前格式（未分类会报 FAIL，正常）
```

`phrases/category-formats/` 里有 6 套现成模板（同样是 `{app}` 的七行表格）：

| 文件 | 风格 |
|---|---|
| `00-personal.tsv` | 个人包（本机在用的那套） |
| `02-cyber-ritual.tsv` | 赛博祭祀 · 机魂 |
| `03-military.tsv` | 军事战报 |
| `04-support-ticket.tsv` | 客服工单 |
| `05-classical.tsv` | 文言古风 |
| `06-logfile.tsv` | 系统日志 |

**`未分类` 是内置分类，它的编辑对话框只有颜色标签，没有「状态显示格式」字段。** 这是软件行为，不是脚本问题 —— 脚本会如实报 `FAIL`。

格式里可以混 `${...}` 命令段，但那样就退回 5 秒节拍了。想「跟得上切换」就纯用 `{app}`。

### 四、让短语跟着你在用的 App 变（脚本通道）

上一节是软件原生的。如果你要的变体比「8 个分类」更细 —— 比如同一个分类里不同程序说不同话 —— 就得自己算。把这条整串丢进「自定义文本项」：

```
${powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\path\to\tools\fg-phrase.ps1}
```

改 `tools/fg-phrase.ps1` 里的 `$Rules` 表就能加规则。

**代价**：每次状态刷新都要起一次 PowerShell，实测单次约 1.4 秒。软件对命令有 **2000 ms 硬超时**，超时就丢掉这次输出（日志里能看到 `[STEAM] command execution timed out (2000 ms)`）。1.4 秒离上限太近，实际经常被判超时。要么改用原生的分类格式，要么把脚本换成编译好的 exe（本机用 Rust 重写后降到 11 ms，超时告警归零）。

---

### 五、跳过 UI：直接硬写入数据库（最快，也最该先读这段话）

上面所有方法都是「模拟人点界面」。软件内部用 SQLCipher 加密自己的数据库，密钥就摆在 `NekoTrak.exe` 的进程内存里 —— 找出来之后，写数据不用再跟界面较劲：

```bash
python tools/nk-hardwrite.py key                  # 从进程内存里取出密钥
python tools/nk-hardwrite.py presets presets.txt  # 一次性灌进全部短语
python tools/nk-hardwrite.py formats map.tsv      # 批量设分类格式
python tools/nk-hardwrite.py dump                 # 看看库里有什么
```

**实测：清空 300 条预设 + 重新写入 300 条 = 0.129 秒。** 走界面点一遍是几个小时。软件**不需要重启** —— 表格是实时读的，写完切到预设对话框就能看见（这是实测确认的，304 条计数当场就对上了）。

密钥长这样：

```
x'9b53c55d…<64 位十六进制密钥>… 8bff5504cd9a5a97ebd837a6ec8486b5'
  └── 32 字节 AES 密钥 ─────────┘ └── 16 字节 salt ─────────────────┘
```

后半段 salt 与 `.db` 文件**开头的 16 个字节逐字节相同** —— 这就是为什么能在满内存的十六进制串里认出真密钥：拿文件头去比对，对上的那个就是。

几个注意点：

- **每次写之前自动备份**（`.db` + `-wal` + `-shm` 一起拷进 `dbbackup-<时间戳>/`）。
- 需要一个**导出 `sqlite3_key` 的 sqlite3 DLL**。套件不附带（发行版杂、体积大），用本机已有的即可，比如 `C:\Program Files\i4Tools9\sqlcipher.dll`。找不到就设环境变量 `NK_SQLCIPHER_DLL` 指过去。
- 写入时 Python 必须用 `SQLITE_TRANSIENT` 绑参数。用 `SQLITE_STATIC` 的话 Python 的 bytes 对象一返回就被回收，表里会留下乱码 —— 这个坑踩过，工具里已经改对了。
- **全局库（`data\NekoTrak.db`）用同一把钥匙打不开**，它有自己的 salt。预设、分类、应用都在用户库里，全局库一般不用动。

---

## 一个必须知道的限制：命令是固定 5 秒跑一次

`${...}` 命令**不是按需触发，是固定每 5.00 秒跑一次**（自记账实测：150 秒 42 次，间隔 5.00 s 雷打不动）。所以命令段永远慢半拍 —— 这是软件节奏，改不了，`presenceIntervalMs` 之类的配置项在 exe 里搜不到（22 个候选字段名全 0 命中）。

`{app}` 不走这条路，所以快得多。

另外，UI 上那个「Steam 状态预览」**每约 15 秒才重绘一次**。别拿它测速度 —— 拿它测只会测出面板的刷新率，测不到状态的真实更新率（这是真踩过的坑，一度以为命令 15 秒才跑一次）。

---

## 工具清单

| 脚本 | 干什么 |
|---|---|
| `NekoTrakUIA.psm1` | 公共底座：找主窗口、触发 WebView2 无障碍树、找控件、点控件、写输入框 |
| `add-presets.ps1` | 批量灌短语到预设库 |
| `add-apps.ps1` | 批量导入应用（应用 → 新建应用） |
| `set-category.ps1` | 批量改应用分类 |
| `scan-installed-apps.ps1` | 扫描本机应用，产出 TSV |
| `set-category-format.ps1` | 给分类设「状态显示格式」——**原生通道，比 `${}` 命令快得多** |
| `fg-phrase.ps1` | 按前台程序吐词（给 `${}` 调用的） |
| `nk-hardwrite.py` | **硬写入**：直连加密数据库读写预设/分类格式，不走界面。300 条约 0.13 秒 |

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
│   ├── category-formats/     # 6 套分类状态格式模板（.tsv）
│   ├── all-300.txt           # 个人包合并版
│   └── all-genre-126.txt     # 体裁包合并版
├── tools/                    # 7 个 PowerShell 脚本 + 1 个 Python 硬写入工具
└── docs/
    ├── mechanism.md          # 机制取证全过程：怎么证明 ${} 才执行
    ├── uia-notes.md          # UIA 通道细节与全部踩坑
    └── recipe.md             # 从零复刻一遍的完整操作序列
```

---

## 许可

短语和文档随便用。脚本按 MIT。

**但请先读一遍 `docs/mechanism.md` 的副作用一节** —— `${}` 是真执行命令，不是模板替换。
