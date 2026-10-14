# 表达式与 Shell 模式

这一页解决一个很容易踩的坑：社区速查表里的表达式为什么粘进去没反应。

## 一、机制

自定义文本支持 `${...}` 命令替换。`${}` 里的内容会交给一个 shell 执行，stdout 被内联进短语，末尾换行会被去掉。`${}` 之外的文字原样保留。

用哪个 shell 由配置项 `steamCommandShell` 决定。它只有两个合法取值：

| 取值 | 含义 |
| --- | --- |
| `cmd` | 交给 cmd.exe 执行 |
| `powershell` | 交给 PowerShell 执行 |

这两个取值来自主程序 exe 里的枚举字面量 `cmdpowershell`，位于偏移 44713246，紧邻 `[State] Database connection initialized` 与 `src\utils\dir.rs`。

## 二、两种模式的实测差异

同一段表达式在两个模式下结果完全不同。下面全部是本机实测，不是推测。

| 表达式 | `cmd` 模式 | `powershell` 模式 |
| --- | --- | --- |
| `echo %RANDOM%` | 25710 | 原样输出 `%RANDOM%` |
| `echo %COMPUTERNAME%` | DESKTOP-47S7OU6 | 原样输出 `%COMPUTERNAME%` |
| `echo %TIME%` | 16:17:21.33 | 原样输出 `%TIME%` |
| `whoami` | desktop-47s7ou6\dr | desktop-47s7ou6\dr |
| `(Get-Date).ToString('HH:mm')` | 报错 `.ToString('HH:mm') was unexpected at this time.` | 18:35 |
| `Get-Random -Max 32768` | 报错 | 31564 |
| `& "powershell.exe" -Command "..."` | 报错 `& was unexpected at this time.` | 正常 |
| `cmd /c "echo %RANDOM%"` | 26024 | 26024 |

上表最后一行只在「裸表达式」语境成立。真正装进 `${}` 后，程序会给整段再加一层引号，结果就变了，见第七节。

三条结论：

1. `cmd` 模式下 `%VAR%` 会被展开，PowerShell 表达式一律报错。
2. `powershell` 模式下 PowerShell 表达式可用，但 `%VAR%` 会变成纯文本，不再展开。
3. `whoami` 这类不依赖 shell 变量的外部命令在两个模式下都能跑，是公共子集。

## 三、前导 & 不是跨 shell 惯用法

网上常见一个说法，认为 `${& "powershell.exe" ...}` 里的前导 `&` 在 cmd 下会被当成命令分隔符从而照常执行。实测不成立：

```
cmd /c "& echo HELLO"        ->  & was unexpected at this time.
cmd /c "echo A & echo B"     ->  A 换行 B        && 分隔符只在两个命令之间有效
```

所以在 `cmd` 模式下，`${& "powershell.exe" ...}` 一律失败。它只在 `powershell` 模式下成立，此处 `&` 是调用运算符。

## 四、迁移对照表

打算把 Shell 从 `cmd` 换成 `powershell` 的话，按下表替换即可。反过来迁移则手工改写。

| cmd 写法 | PowerShell 等价写法 |
| --- | --- |
| `%RANDOM%` | `Get-Random -Max 32768` |
| `%TIME%` | `(Get-Date).ToString('HH:mm:ss')` |
| `%TIME:~0,5%` | `(Get-Date).ToString('HH:mm')` |
| `%DATE%` | `(Get-Date).ToString('yyyy-MM-dd')` |
| `%COMPUTERNAME%` | `$env:COMPUTERNAME` |
| `%USERNAME%` | `$env:USERNAME` |
| `%USERDOMAIN%` | `$env:USERDOMAIN` |
| `%TEMP%` | `$env:TEMP` |
| `%USERPROFILE%` | `$env:USERPROFILE` |
| `%CD%` | `(Get-Location).Path` |
| `%NUMBER_OF_PROCESSORS%` | `$env:NUMBER_OF_PROCESSORS` |
| `%OS%` | `(Get-CimInstance Win32_OperatingSystem).Caption` |

不想改语义只想换 shell，请用第七节的可移植写法。下面这种是**错的**：

```
${cmd /c "echo %RANDOM%"}
```

裸表达式语境下它两个模式都能跑，但装进 `${}` 之后程序会给整段再加一层引号，
cmd 模式下会多吐一个游离的双引号出来。第七节有实测。

## 五、社区速查表 maozi.io

`https://ytoqtr5xf-nekotrak-3b0036y.maozi.io` 是一个第三方「表达式速查表」，作者做了三件事：把常用表达式按分类列出来、做了个拼接构建器、附带一个天气脚本 `Get-Weather.ps1`。

它的表达式全部是 PowerShell 写法，例如：

```
${(Get-Date).ToString('HH:mm')}
${(Get-CimInstance Win32_Processor).Name}
${[math]::Round((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1MB)}GB
${(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits).Trim()}%
${[Environment]::MachineName}
${(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples | Measure-Object CookedValue -Sum | Select-Object -ExpandProperty Sum}
```

**因此这个速查表默认你的 Shell 是 `powershell`。** 如果你的 `steamCommandShell` 是 `cmd`，把上面任何一条粘进去都不会有输出，只会静默失败。页面本身没有把这一点写在显眼处，这是它最大的坑。

站点提供的天气调用是：

```
${& "powershell.exe" -ExecutionPolicy Bypass -File "D:\TTplayer\Get-Weather.ps1" -City "北京"}
```

按第三节的实测，这条同样只在 `powershell` 模式下成立。

### 天气脚本值得借鉴的一点

`Get-Weather.ps1` 不走 `Write-Output`，而是直接往标准输出写 UTF-8 字节：

```powershell
$bytes = [System.Text.Encoding]::UTF8.GetBytes($Text + [Environment]::NewLine)
$stdout = [System.Console]::OpenStandardOutput()
$stdout.Write($bytes, 0, $bytes.Length)
```

这样绕开了 PowerShell 默认编码，中文城市名和天气图标不会乱码。任何要输出中文的表达式都可以照这个思路做。

### 抄它的表达式之前先确认

1. 确认 Shell 模式，`cmd` 模式下一条都用不了。
2. 确认依赖存在。NVIDIA 那几条要求 `nvidia-smi` 在 PATH 里，A 卡的几条用性能计数器，不需要额外工具。
3. 每条会起一个进程，`Get-CimInstance` 尤其慢。别把七八条堆在一条短语里，5 秒的执行节拍会撑不住。执行超时是 2000 毫秒。

## 六、本机当前状态

截至 2026-10-14，这台机器的全局与用户级 `config.json` 都是 `steamCommandShell: "powershell"`。
早先两个都是 `cmd`，为了用 maozi 那套速查表切了过来，切换过程见第七节。

数据库里的 350 条短语已经全部改成第七节的跨 shell 形态，不再依赖当前 shell 取值：

```
${cmd.exe /c echo %RANDOM%}        301 行
${cmd.exe /c echo %TIME:~0,5%}     4 行
```

改完重启了一次主程序。`steamCommandShell` 在**运行期生效** —— 切换后日志里的 shell 标签当场从 `[cmd]` 变成 `[powershell]`，不必重启，但重启一次没有坏处。

**单条受控复测，2026-10-14 23:32**：把 `steamSyncItems` 换成唯一一条
`Q1~${cmd.exe /c echo %RANDOM% %TIME:~0,5%>> hits.txt}~Q1`，130 秒后标记文件累计 26 行，
间隔正是 5.00 秒节拍，值每次都变，且这段时间内 `timed out` 增量为 0。
⇒ 跨 shell 形态既被执行，也没被 2000 毫秒超时丢掉。

> 早期测出的「跨 shell 形态会被超时丢掉」是并发假象。当时把多个候选同时塞进 `steamSyncItems`，
> 每个候选各起一个 shell 进程，预算互相挤爆。**判定任何 `${}` 写法都必须一次只装一条。**

## 七、跨 shell 的可移植写法

套件要发给别人，而别人的 `steamCommandShell` 可能是 `cmd` 也可能是 `powershell`。
能不能找到一种两个模式下都成立的写法？可以，但**只有一种**，而且它跟裸表达式的结论完全相反。

这一节全部是单条对照实测。**必须一条一条单独测** —— 把多个候选同时塞进 `steamSyncItems`，
在 `powershell` 模式下会一起撞上 2000 毫秒硬超时而集体报错，分不清是形式不对还是预算被挤爆。

### 候选与结果

装进「自定义文本项」，以 `~` 包夹便于辨认，重启后在预览里读：

| 候选 | 写法 | `cmd` 模式 | `powershell` 模式 |
| --- | --- | --- | --- |
| 裸变量 | `${echo %RANDOM%}` | 干净求值 | 原样输出文本 |
| 短包装 | `${cmd /c echo %RANDOM%}` | **漏一个游离双引号** | 干净求值 |
| 加引号包装 | `${cmd /c "echo %RANDOM%"}` | 不执行 | 干净求值 |
| 全路径包装 | `${C:\Windows\System32\cmd.exe /c echo %RANDOM%}` | 干净求值 | 干净求值 |
| PATH 包装 | `${cmd.exe /c echo %RANDOM%}` | 干净求值 | 干净求值 |
| 环境变量包装 | `${%ComSpec% /c echo %RANDOM%}` | 干净求值 | **不执行** |
| 原生 PowerShell | `${$(Get-Random -Max 32768)}` | 不执行 | 干净求值 |

### 为什么短包装会漏引号

`cmd` 模式下程序拼出的命令行大致是：

```
cmd.exe /e:ON /v:OFF /d /c "cmd /c echo %RANDOM%"
```

外层 `cmd` 剥掉引号后交给内层，内层解析时把行尾当成了未闭合的引号，于是输出里带出一个 `"`。
换成 `cmd.exe` 全名或带路径时，外层的解析路径不同，反而干净。

`%ComSpec%` 那条死因不同：`powershell` 模式下 `%ComSpec%` 不会被展开，
整段变成字面文本交给 PowerShell，于是什么都没发生。

### 定案

**跨 shell 可移植形态 = `${cmd.exe /c echo %RANDOM%}` 与 `${cmd.exe /c echo %TIME:~0,5%}`。**

用全路径 `${C:\Windows\System32\cmd.exe /c ...}` 同样成立，但字符数约是前者的 1.4 倍，
而 Steam 状态栏有长度上限，长短语会顶到边。除非系统装在非 `C:\Windows`，否则用短的那个。

代价与性能，各 5 次平均，含进程冷启动：

| 形态 | `cmd` 模式 | `powershell` 模式 |
| --- | --- | --- |
| `${cmd.exe /c echo %RANDOM%}` | 约 62 ms | 约 876 ms |
| `${$(Get-Random -Max 32768)}` | 不执行 | 约 1058 ms |

可移植形态**不但没有代价，反而更快**，因为 `powershell` 模式下它起的进程比原生表达式更轻。
2000 毫秒硬超时下 876 ms 是安全的，但余量并不宽裕：机器变慢或有杀毒软件扫描进程启动时会被吃掉。
若你确定自己的模式且追求极限，原生形态更快；要发给别人，就用可移植形态。

### 反过来不成立

**不要**指望「把表达式包进 `cmd /c` 就一定可移植」。第三节那个 `cmd /c "echo %RANDOM%"`
的表格是裸表达式语境的结论，装进 `${}` 后引号层级会变。只有上面定案的两种形态经过实测。

