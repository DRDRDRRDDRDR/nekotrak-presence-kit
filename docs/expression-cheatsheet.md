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

三条结论：

1. `cmd` 模式下 `%VAR%` 会被展开，PowerShell 表达式一律报错。
2. `powershell` 模式下 PowerShell 表达式可用，但 `%VAR%` 会变成纯文本，不再展开。
3. `whoami`、`cmd /c` 这类外部命令在两个模式下都能跑，是唯一的公共子集。

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

不想改语义只想换 shell，就把整段包回 cmd：

```
${cmd /c "echo %RANDOM%"}
```

这样两个模式下都能跑，代价是每次多起一个 cmd 进程。

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

截至 2026-10-14，这台机器的全局与用户级 `config.json` 都是 `steamCommandShell: "cmd"`。

已有的 350 条短语里只用到两个命令替换表达式：

```
${echo %RANDOM%}       出现 325 次
${echo %TIME:~0,5%}    出现 4 次
```

也就是说，如果要把 Shell 换成 `powershell` 去用 maozi 的速查表，迁移量是两条：

```
${echo %RANDOM%}      ->  ${Get-Random -Max 32768}
${echo %TIME:~0,5%}   ->  ${(Get-Date).ToString('HH:mm')}
```

改完稳妥起见重启一次主程序。`steamCommandShell` 是启动期读取还是每次执行时读取，本机没有实测，不要赌。
