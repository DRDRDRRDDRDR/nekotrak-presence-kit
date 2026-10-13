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
