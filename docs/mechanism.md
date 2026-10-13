# 机制取证：怎么证明 `${}` 才执行

这份文档记录的是**实验**，不是文档摘抄。NekoTrak 网上没有可用的机制说明，所有结论都是从这台机器上跑出来的。

被取证的版本：NekoTrak 1.1.6（Steam appid 5249210，前身 FlowTrak）。

---

## 一、错误起点：`%RANDOM%`

第一版短语全是用 `%RANDOM%` 写的。依据来自两条看起来很像回事的线索：

1. 在 exe 里搜到了 `cmd.exe /e:ON /v:OFF /d /c "` 这个字面量。`/v:OFF` 关掉了延迟展开，意味着 `!VAR!` 语法无效、只剩 `%VAR%`。
2. 商店页写「支持自定义状态文本，**可嵌入命令行表达式**」。

于是推断：「命令替换 = 写 cmd 变量」。

**错了。** 而且错得很自然 —— 这两个线索都是真的，但推出的结论不是。

---

## 二、纠正：placeholder 才是权威

在「设置 → 行为 → 丰富状态」找到自定义文本输入框，读它的 **placeholder 原文**：

```
添加自定义文本项，可通过 ${...} 语法调用终端命令
```

`${...}`。不是 `%...%`。

这是应用自己写在界面上的话，比任何逆向猜测都硬。

---

## 三、对照实验

往输入框写值，然后读「Steam 状态预览」（预览 = 真实渲染结果，不是模拟）。

| # | 写入的值 | 预览显示 | 结论 |
|---|---|---|---|
| 1 | `${echo hi}` | `hi` | `${}` 被执行了 |
| 2 | `%RANDOM%` | `%RANDOM%` | **裸变量原样输出，不求值** |
| 3 | `R%RANDOM%S ${echo T1}${echo T2}` | `R%RANDOM%S T1T2` | 裸变量死；`${}` 活；**多个 `${}` 可相邻拼接** |
| 4 | `TEST-A ${echo hi} TEST-B` | `TEST-A TEST-B` | 空格被保留，替换是纯文本内联 |

**实验 3 是决定性的。** 同一行里两种语法并列，一种死了、一种活着，排除了「整个字符串都没被处理」和「全都处理了」两种解释。

### 一个差点误导的观察

往输入框写 `TEST-A ${echo hi} TEST-B`，列表里显示成 `TEST-A TEST-B`（`${echo hi}` 直接没了）。

第一反应是「已经被求值成空字符串了」。**其实不是** —— PowerShell 在把参数交给脚本之前就把 `${echo hi}` 当变量吞掉了，根本没传到应用里。

教训：**做这种实验时，值必须从文件读，不能从命令行传。** 用文件读（绕开 shell）写入的 5 条测试值全部**逐字原样**存进了库：

```
A${echo hi}B
C%RANDOM%D
E${echo %RANDOM%}F
G${whoami}H
I${echo test}J
```

⇒ **预设列表只做原样存储，求值发生在渲染时。**

---

## 四、证明它真的执行命令（副作用实验）

「预览里出现了 `hi`」还不能完全排除「应用自己实现了个 echo 解析器」这种可能。要证明执行，得有**只有真执行才会发生**的副作用。

写入：

```
P${echo NKEVALOK> %TEMP%\nekoprobe\nkeval.txt}Q
```

点保存后 1 秒内，`nkeval.txt` **出现了**，内容 `NKEVALOK`。

同时预览显示 `... | PQ` —— 因为 stdout 被重定向进了文件，所以替换结果为空，只剩两边的 `P` 和 `Q`。

⇒ **`${}` 里的内容是真正的命令行执行**，不是模板替换。

### 副作用警告

这不是沙箱。`${}` 里能干的事和你在 cmd 里能干的事一样多：

- 写文件、删文件
- 起进程、拉网络
- 改配置

别把来路不明的字符串贴进自定义文本项。别人发给你一条「好玩的状态」，里面塞了个 `> C:\Windows\...`，那就是另一个故事了。

---

## 五、执行环境

- **执行器**：设置里的「终端程序」（本机 = `命令提示符（cmd）`）。另可选 PowerShell。
- **调用形式**：`cmd.exe /e:ON /v:OFF /d /c "<你的${}内容>"`
- `/v:OFF` ⇒ 延迟展开关闭，`!VAR!` 不可用；但因为在 `${}` 内部，直接写 `%VAR%` 是可以的（实验 3 已证）。

cmd 里可用的变量（短语包用到的那几个）：

| 表达式 | 本机实测值 |
|---|---|
| `%RANDOM%` | `11477`（1..32767，每次刷新都变） |
| `%TIME%` | `18:56:41.23` |
| `%TIME:~0,5%` | `18:56` |
| `%DATE%` | `2026/10/13 周一` |
| `%COMPUTERNAME%` | 真实机器名 —— **短语里不用** |
| `%USERNAME%` | 真实账户名 —— **短语里不用** |

需要多行或复杂逻辑时，用 `for /f`：

```
${for /f "tokens=*" %i in ('whoami') do @echo %i 正在上网}
```

### `%VAR%` 能用，但不建议用会泄露身份的

`%COMPUTERNAME%` 和 `%USERNAME%` 技术上可用（它们会把真实机器名/账户名送到 Steam 状态栏上，任何好友都能看到）。宁可写死一个代号：

```
这台电脑属于 DRRD，但 DRRD 现在不属于这台电脑
```

### 命令是固定 5 秒跑一次，不是按需触发

这是 `%VAR%` 方案最大的隐性代价。自记账实测（把值临时设成 `${echo %TIME%>>hit.txt & echo DRRD 正在假装忙}`，150 秒后数行数）：

```
42 次调用，间隔恒为 5.00 s
20:21:59.42 / :04.41 / :09.41 / :14.39 / :19.41 …
```

换成编译好的 exe 复测（27 次）间隔一样是 5.00 s ⇒ **跟命令本身快慢无关，是软件节奏**。

`presenceIntervalMs` / `presence_interval_ms` / `commandIntervalMs` / `commandTimeoutMs` / `syncIntervalMs` 等 22 个候选配置字段名在 exe 里**全部 0 命中** ⇒ 不可配。

### 命令有 2000 ms 硬超时

超时就丢掉这次输出，日志里记为：

```
[STEAM] command execution timed out (2000 ms) [cmd]: powershell -NoProfile ...
```

本机用 PowerShell 脚本时累计 46 次（单次 ~1.4 s，贴着上限）。改用 Rust 编译的 exe（单次 11 ms）后告警归零。⇒ **给 `${}` 用的程序必须是毫秒级的，别用冷启动几百毫秒的解释器。**

### 命令模板的其他硬限制（exe 日志串，未文档化）

- `[STEAM] command too long in custom template, max: , actual: ` —— 有长度上限
- `[STEAM] nested expression is not supported: ` —— **不支持嵌套 `${}`**
- `[STEAM] custom template has too many expressions, max: ` —— 有表达式条数上限
- `[STEAM] command stdout truncated to  bytes` —— stdout 会截断

---

## 五之二、分类级的「状态显示格式」（原生模板，比 `${}` 快得多）

除了全局的「自定义文本项」，每个分类还能有自己的显示格式。UI 路径：`分类` → 选中分类 → `编辑` → 「状态显示格式」。

它存在加密库的 `categories` 表里：

```sql
presence_format TEXT NULL,
```

DAO 走 `upsert_category`（`INSERT INTO categories (id, parent_id, name, color, icon, hidden, focus_score, presence_format, auto_classification_enabled) VALUES (?,…) ON CONFLICT(id) DO UPDATE SET … presence_format = excluded.presence_format …`）。exe 里 `presence_format` 共 6 处命中，全是字段名或 SQL，**没有独立的 Tauri 命令**。

### 模板变量：实测只有 `{app}` 和 `{title}`

扫全 exe（55 MB）正则 `\{([a-z][a-z0-9_]{0,19})\}` 得 37 个候选，绝大多数是误报（`{cat}`/`{other}`/`{winner}`/`{rounds}` 属宠物叙事系统，`{m}`/`{n}`/`{z}` 是压缩字典常量）。真正相邻的只有这一组，位于偏移 45385128：

```
{app}{title}
details_present=, details_chars=, state_present=, state_chars=, text_chars=, display_mode=
```

**验证实验**：把「游戏」分类格式设为

```
A={app} B={title} C={song} D={artist} E={todo} F={time} G={date} H={category} I={n} J={count}
```

读预览得到：

```
A=网易UU远程 B={title} C={song} D={artist} E={todo} F={time} G={date} H={category} I={n} J={count}
```

⇒ **只有 `{app}` 被替换；未定义的变量不报错、按字面输出**（所以别写幻觉变量，它们会原样挂在那里很难看）。

### 速度对比（这就是它的价值）

| 通道 | 生效延迟 | 测法 |
|---|---|---|
| `{app}` 替换 | **约 400 ms** | 切前台后 250 ms 采样，401 ms 时已变 |
| `${...}` 命令段 | **5.00 s 节拍** | 自记账 |

所以「短语跟不上程序切换」的正确解法是**用分类格式的 `{app}`，而不是 `${}` 命令**。

### ★ 别用 UI 预览测速度

「Steam 状态预览」面板**每约 15 秒才重绘一次**。轮询它测出的间隔是 15034 / 14977 / 14850 / 15088 / 14806 / 15176 ms —— 那是面板刷新率，不是状态更新率。

一度据此误判成「命令 15 秒才跑一次」，后来用自记账法才测出真正的 5.00 s。**测「多久跑一次」必须让被测量的东西自己记账。**

### `未分类` 改不了

它是内置分类，编辑对话框里只有颜色标签（`Edit ph='#000000'`），**没有「状态显示格式」字段**。这是软件行为。

---

## 六、预设存在哪

**不在 `config.json`。**

`config.json` 里确实有两个看起来很对的键：

```json
"steamCustomTextPresets": [],
"overlayClockCustomTextPresets": []
```

它们永远是空数组，写进去也没用。exe 里配套的日志字符串是：

```
[State] Failed to clear migrated custom text preset config fields:
[Setup] Failed to migrate legacy custom text presets:
```

⇒ 这是**旧版的遗留字段，已经废弃**，只作为一次性迁移的读取源存在。

真正的位置是加密 SQLite 库：

```sql
CREATE TABLE IF NOT EXISTS custom_text_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    normalized_text TEXT NOT NULL,
    sort_order INTEGER NOT NULL UNIQUE CHECK(sort_order >= 0)
)
```

数据库文件 `%APPDATA%\NekoTrak\users\<steamid>\data\NekoTrak.db` —— **不是明文 SQLite**。文件头前 48 字节是随机密文，`sqlite3.connect` 会报 `file is not a database`。是 SQLCipher，密钥由 SteamID + 盐派生：

```
FlowTrak_Secure_Database_Salt_2026
```

**结论：外部脚本写不进去，必须走 UI。** 这就是 `tools/` 存在的全部理由。

（`config.json` 里的 `steamDisplayMode` 只有两个值：`merge`（界面显示「自动」）和 `carousel`（轮播）。`steamMergeSeparator` 默认 `" | "`，决定多段状态怎么拼。）

---

## 七、网络取证记录

商店页（`store.steampowered.com/app/5249210/NekoTrak/`，HTTP 200）的原话：

> 支持自定义状态文本，**可嵌入命令行表达式**
> 支持**合并展示、轮播展示与自动切换**
> 可选择显示应用名称、**窗口标题**、音乐标题与播放进度
> 通过**状态规则与表情**自定义展示方式

「可嵌入命令行表达式」这句是对的，只是没告诉你语法长什么样。

**其余网络检索基本无收获**：中文教程类查询返回 0 结果，Bing 引擎直接空手，自动回落到 exa。第三方报道只有一篇改名的新闻稿。⇒ **这类小众软件的机制只能靠本地取证。**
