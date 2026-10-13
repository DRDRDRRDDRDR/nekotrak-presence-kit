# 操作手册：从零复刻一遍

按顺序做。每步都有验证方法，别跳。

前置：NekoTrak 正在运行；PowerShell 5.1+；Python 3（读浏览器历史、以及硬写入要用）；管理员权限不是必须的，但读注册表 HKLM 时最好有。

**要硬写入的话还需要一个 DLL**：任意导出 `sqlite3_key` 的 sqlite3 构建（本机用的是 `C:\Program Files\i4Tools9\sqlcipher.dll`）。找不到就整个第 4 步退回 UI 通道，其他步骤不受影响。

---

## 第 0 步：备份

**先做这个。** 后面所有操作都不可逆（没有撤销功能）。

```powershell
$src = "$env:APPDATA\NekoTrak\users\<steamid>\data"
$dst = "$env:TEMP\nekotrak-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "$src\NekoTrak.db*" $dst
Copy-Item "$src\manifest.json" $dst
"backed up to $dst"
```

`<steamid>` 从 `%APPDATA%\NekoTrak\local.json` 里的 `steam_id` 拿。

要全部推倒重来时，把这三个文件拷回去即可。

---

## 第 1 步：确认语法

在 UI 里手动做一次，别信任何文档。

1. 打开 NekoTrak → 设置 → **行为** Tab → 找「丰富状态」分组。
2. 看「自定义文本项」输入框的 **placeholder 原文**。应该是：
   `添加自定义文本项，可通过 ${...} 语法调用终端命令`
3. 往里填 `${echo hello}`，看右边「Steam 状态预览」有没有变成 `hello`。
4. 再填 `%RANDOM%`，看它是不是**原样显示** `%RANDOM%`。

第 3、4 步的结果就是你的语法判据：

- `${}` 求值 + `%VAR%` 不求值 ⇒ 用本仓库的写法，继续
- 两个都求值 ⇒ 这个版本可能换实现（本仓库基于 1.1.6），`tools/` 的写入逻辑照用，短语包的写法要改
- 两个都不求值 ⇒ 找那个输入框旁边的其他提示，别猜

---

## 第 2 步：读搜索历史（写短语的素材）

**只看搜索词，别看具体网址。** 搜索框是人最不设防的地方。

```python
# save as read_history.py，先改 BROWSER 路径
import sqlite3, io, os

HISTORY = r'C:\Users\<user>\AppData\Roaming\Opera Software\Opera GX Stable\Default\History'
OUT = r'searches.txt'

uri = 'file:' + HISTORY.replace('\\', '/') + '?mode=ro'   # 只读，别锁住浏览器
con = sqlite3.connect(uri, uri=True)

lines = []
for term, in con.execute(
        'SELECT DISTINCT term FROM keyword_search_terms ORDER BY term'):
    lines.append(term)

with io.open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('wrote %d search terms -> %s' % (len(lines), OUT))
```

**浏览器历史库路径**（`UserChoice` 注册表键告诉你默认浏览器是谁）：

| 浏览器 | 路径 |
|---|---|
| Opera GX | `%APPDATA%\Opera Software\Opera GX Stable\Default\History` |
| Chrome | `%LOCALAPPDATA%\Google\Chrome\User Data\Default\History` |
| Edge | `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History` |
| Firefox | `%APPDATA%\Mozilla\Firefox\Profiles\<xxx>.default\places.sqlite`（表名不同） |

查默认浏览器：

```powershell
(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice').ProgId
```

**坑**：Windows 控制台是 GBK，Python 打中文会 `UnicodeEncodeError`。**一律写文件再读**，或者设 `$env:PYTHONIOENCODING='utf-8'`。

**用的时候挑什么**：重复出现的、看起来有点丢人的、有具体数字的。比如「hotmail找回」「学信网」「385泰铢」这类。**别用涉及他人隐私的搜索词。**

---

## 第 3 步：生成短语

把第 2 步的收获和软件清单丢给 AI，或者自己写。规则：

- **具体** — 指向真实用过的东西，越具体越好笑
- **自嘲** — 开自己玩笑，不开别人
- **随机** — 用 `${echo %RANDOM%}` 让数字每次刷新都变
- **不泄漏** — 别用 `%COMPUTERNAME%` / `%USERNAME%` / `whoami`，需要指代自己就写死代号
- **短** — 60 字符以内

写成一行一条的 UTF-8 txt。多个风格包就多个文件。

**自查花括号配对**（`${` 和 `}` 数量必须相等，这个错误会让整条短语显示成残缺）：

```python
import io
bad = 0
for i, line in enumerate(io.open('phrases.txt', encoding='utf-8'), 1):
    if line.count('${') != line.count('}'):
        print('line %d unbalanced: %s' % (i, line.strip()))
        bad += 1
print('unbalanced %d' % bad)
```

**注意 `%` 结尾**：`${echo %RANDOM%}%` 想输出「数字后跟一个百分号」是合法的，但写成 `${echo %RANDOM%%` 就少了个右括号。这种错最先出现在概率类的短语里。

---

## 第 4 步：灌进预设库

**先试硬写入。** 不用点界面，0.13 秒灌 300 条：

```bash
python tools/nk-hardwrite.py key                       # 取出密钥（软件要先跑一次）
python tools/nk-hardwrite.py presets phrases.txt       # 追加
python tools/nk-hardwrite.py presets phrases.txt --replace   # 清空重来
python tools/nk-hardwrite.py dump                      # 核对
```

写完**不用重启软件**，切到预设对话框就能看见（这一点做过专项验证：插入探针行后界面计数当场 +1）。

如果硬写入不通（找不到导出 `sqlite3_key` 的 DLL、或者以后版本换了加密方式），退回 UI 通道：

```powershell
cd tools

# 先试 3 条
.\add-presets.ps1 -File ..\phrases\packs\00-core.txt -Limit 3 -Dump ..\dump-test.txt

# 核对：dump 里应该能看到那 3 条，逐字一致
Select-String -Path ..\dump-test.txt -Pattern '正在假装很忙'

# 全量（清空重来）
.\add-presets.ps1 -File ..\phrases\packs\00-core.txt -Clear -Delay 800

# 多个包一起
.\add-presets.ps1 -File ..\phrases\packs\*.txt -Clear -Delay 800
```

**成功判据**：输出里有 `added ok=N bad=0`，且 `dialog now holds N preset(s)` 的 N 和写入数一致。

**如果 `added ok=0`**：看有没有 `input box gone`。那是「打开预设列表」没点开 —— 检查脚本是否成功进了「行为」Tab（第 4 步的前置导航）。

**如果个别条目写入失败**：多半是超长。软件对单条文本有长度上限（错误码 `custom_text_preset_too_long`，具体数值没测出来）。把长的那条拆短或删掉。

---

## 第 5 步：导入应用

```powershell
cd tools

# 扫描：注册表 + 运行中进程 + 开始菜单
.\scan-installed-apps.ps1 -Out ..\apps.tsv

# 看一眼结果，有没有明显的垃圾条目
Get-Content ..\apps.tsv | Select-Object -First 30

# 先试一条
.\add-apps.ps1 -File ..\apps.tsv -Test

# 全量
.\add-apps.ps1 -File ..\apps.tsv -Delay 700
```

**成功判据**：`done ok=N bad=0`。

**已知失败**：路径里用了正斜杠 → 报 `保存应用失败`。改成反斜杠重跑那一条。

```powershell
# 单条补录
@"
Cinema 4D 2023`tC:\Program Files\Maxon Cinema 4D 2023\Cinema 4D.exe
"@ | Set-Content -Encoding UTF8 one.tsv
.\add-apps.ps1 -File one.tsv -Delay 1200
```

**别导入的东西**：卸载器、安装包、系统进程（`svchost` 之类）。扫描脚本默认过滤了一部分，但不是全部 —— `apps.tsv` 生成后人工扫一遍再导入。

---

## 第 6 步：批量分类

准备三列 TSV：`搜索词 <TAB> 分类名 <TAB> 卡片上显示的完整路径`。

分类名只能是这 8 个：`未分类 游戏 媒体 社交 工作 创作 参考 工具`。

**搜索词**要够独特，能把列表筛到你想要的那一张卡（exe 名通常够用）。

```powershell
cd tools
.\set-category.ps1 -File .\setcat.example.tsv -Delay 2600
```

**成功判据**：`done ok=N skip=M bad=0`。

**核对**：跑完之后到「分类」页看各分类的条目数，「未分类」应该大幅下降。

**如果 `card not found`**：搜索词没筛出那一张卡 —— 换更独特的词，或者直接用完整路径。

**如果 `menu item not found`**：`Expand()` 没生效。加大 `-Delay`。

---

## 第 7 步：让它跟着 App 变 —— 原生通道（首选）

**先做这个，别急着上脚本。** NekoTrak 自带分类级的「状态显示格式」：

`分类` 页 → 选中一个分类 → `编辑` → 「状态显示格式」输入框。

```powershell
cd tools
.\set-category-format.ps1 -Category 游戏 -Format '{app} 已启动 | 这局我很认真'
.\set-category-format.ps1 -MapFile formats.tsv      # 每行「分类名<TAB>格式串」
.\set-category-format.ps1 -Read                     # 回显 8 个分类的当前格式
```

或者直接用硬写入，一次设完 7 个分类：

```bash
python tools/nk-hardwrite.py formats phrases/category-formats/00-personal.tsv
```

模板变量实测只有两个（扫全 exe，`{app}` @45385128 与 `{title}` @45385133 相邻，是唯一一组）：

- `{app}` —— 替换成当前应用名，**约 400 ms 内跟上切换**
- `{title}` —— 窗口标题，实测常为空/原样输出
- 其他 `{xxx}` —— 原样输出，不报错。别写 `{song}`/`{time}` 这类幻觉变量

**`未分类` 是内置分类**，它的编辑对话框只有颜色标签，没有这个字段。脚本会如实报 `FAIL`，那是软件行为不是 bug。

格式里可以混 `${...}`，但命令段退回 5 秒节拍。想快就纯用 `{app}`。

**怎么验它真的切了**：找两个不同分类的程序，来回切前台，读「Steam 状态预览」。注意预览面板每 ~15 秒才重绘一次（见下），所以别用短间隔采样下结论。

---

## 第 8 步：让它跟着 App 变 —— 脚本通道（可选，更细但更慢）

只有当你需要的变体比「8 个分类」更细时才用这一步。改 `tools/fg-phrase.ps1` 里的 `$Rules` 表，加上你自己的程序名。

然后把它整串放进「自定义文本项」：

```
${powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\完整路径\tools\fg-phrase.ps1}
```

**先测速**：

```powershell
$t = Measure-Command { & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\fg-phrase.ps1 }
"单次 $($t.TotalMilliseconds) ms"
```

实测约 1400 ms。**软件对命令有 2000 ms 硬超时**，超时就丢掉这次输出，日志里会出现：

```
[STEAM] command execution timed out (2000 ms) [cmd]: powershell -NoProfile ...
```

1.4 秒贴着实测上限，实际会频繁被判超时（本机日志里累计 46 次）。两条出路：改用第 7 步的原生通道，或者把脚本编译成原生 exe（用 Rust 重写后单次 11 ms，告警归零）。

**如果输出是乱码**：脚本里 `[Console]::OutputEncoding` 那段没生效，或者被编辑工具改坏了编码。重新补 BOM。

---

## 关于速度：两个必须分清的节拍

想优化「短语跟不上切换」，先知道自己在跟什么较劲：

| 现象 | 真实值 | 怎么测出来的 |
|---|---|---|
| `${...}` 命令多久跑一次 | **固定 5.00 秒**（不可配） | 让命令自己记账：`${echo %TIME%>>hit.txt & ...}`，等 150 秒数行数 → 42 次，间隔恒定 5.00 s |
| UI「Steam 状态预览」多久重绘 | **约 15 秒** | 轮询预览文本，间隔 15034/14977/14850/15088 ms |
| `{app}` 替换延迟 | **约 400 ms** | 切前台后 250 ms 级采样，401 ms 时 `{app}` 已变 |

**最容易踩的坑**：拿 UI 预览去测命令频率，会测出 15 秒，然后误判成「命令 15 秒才跑一次」。**测「命令多久跑一次」必须让命令自己记账。**

`presenceIntervalMs` / `commandTimeoutMs` 之类的配置项在 exe 里搜不到（22 个候选字段名全部 0 命中）—— 5 秒节拍和 2000 ms 超时都是硬编码，改不了。

---

## 收尾检查表

- [ ] 备份文件在，知道怎么回滚
- [ ] 语法判据用 UI 亲自验证过（不是抄文档）
- [ ] 短语里没有 `%COMPUTERNAME%` / `%USERNAME%` / `whoami`
- [ ] 花括号配对校验通过，`unbalanced 0`
- [ ] 预设库条数和写入数一致（硬写入的话：写完在界面上数一遍，**确认软件不用重启**）
- [ ] 硬写入的字符串绑了 `SQLITE_TRANSIENT`（用 `SQLITE_STATIC` 会写进乱码）
- [ ] `apps.tsv` 人工扫过一遍，没有卸载器和安装包
- [ ] 分类后「未分类」接近 0
- [ ] 分类「状态显示格式」写对了（`未分类` 报了 FAIL 是正常的）
- [ ] 用过 `edit` 工具改过的 .ps1 都补回了 BOM
- [ ] 所有 .ps1 都能直接跑通（不是只跑过一部分）
- [ ] 脚本里没有把「毫秒」写成「秒」的 `Start-Sleep -Seconds $Delay`（`-Delay 1800` 会变成睡 30 分钟，看起来像卡死）
