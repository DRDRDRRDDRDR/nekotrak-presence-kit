# -*- coding: utf-8 -*-
"""发布前本地自检。编码 / BOM / 条数 / 去重 / 花括号配对 / 文档一致性。

用法：python tools/selfcheck-kit.py
仓库根目录由脚本自身的路径推出，所以克隆到任何位置都能跑。
"""
import io, os, re, sys, glob

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
warns = []


def ok(m):
    print('  OK   ' + m)


def bad(m):
    print('  FAIL ' + m)
    fails.append(m)


def warn(m):
    print('  WARN ' + m)
    warns.append(m)


print('KIT = %s' % KIT)
print()
print('=== 1. PowerShell 脚本必须带 UTF-8 BOM ===')
for path in sorted(glob.glob(os.path.join(KIT, 'tools', '*.ps1')) +
                   glob.glob(os.path.join(KIT, 'tools', '*.psm1'))):
    with open(path, 'rb') as f:
        head = f.read(3)
    name = os.path.basename(path)
    if head == b'\xef\xbb\xbf':
        ok('%s  BOM present' % name)
    else:
        bad('%s  MISSING BOM  head=%r' % (name, head))

print()
print('=== 2. 文本文件必须是无 BOM 的合法 UTF-8 ===')
texts = (glob.glob(os.path.join(KIT, '**', '*.txt'), recursive=True) +
         glob.glob(os.path.join(KIT, '**', '*.md'), recursive=True) +
         glob.glob(os.path.join(KIT, '**', '*.tsv'), recursive=True))
for path in sorted(texts):
    with open(path, 'rb') as f:
        raw = f.read()
    name = os.path.relpath(path, KIT)
    if raw[:3] == b'\xef\xbb\xbf':
        bad('%s  has BOM, should be plain UTF-8' % name)
        continue
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError as e:
        bad('%s  not valid UTF-8: %s' % (name, e))
        continue
    ok('%s  utf-8 clean  %d bytes' % (name, len(raw)))

print()
print('=== 3. 短语包：条数 / 去重 / 花括号配对 / 长度 ===')
PACK_RE = re.compile(r'^\d{2}-[A-Za-z0-9_-]+\.txt$')
# 体裁包是另立风格用的，不并入个人包
GENRE = {'02-cyber-ritual.txt', '03-military.txt', '04-support-ticket.txt',
         '05-classical.txt', '06-logfile.txt'}

seen = {}
unbalanced = []
toolong = []
personal_lines = []
genre_lines = []
for p in sorted(glob.glob(os.path.join(KIT, 'phrases', 'packs', '*.txt'))):
    base = os.path.basename(p)
    lines = [l.rstrip('\n') for l in io.open(p, encoding='utf-8') if l.strip()]
    if not PACK_RE.match(base):
        bad('pack name does not match NN-slug.txt: %s' % base)
    if base in GENRE:
        genre_lines += lines
    else:
        personal_lines += lines
    for i, l in enumerate(lines, 1):
        if l.count('${') != l.count('}'):
            unbalanced.append('%s:%d %s' % (base, i, l))
        if len(l) > 70:
            toolong.append('%s:%d  %d chars' % (base, i, len(l)))
        if l in seen:
            bad('duplicate phrase: "%s" in %s and %s' % (l, seen[l], base))
        seen[l] = base
    ok('%-24s %3d lines' % (base, len(lines)))

print('  ---')
print('  personal = %d, genre = %d, unique total = %d'
      % (len(personal_lines), len(genre_lines), len(seen)))
if unbalanced:
    for u in unbalanced:
        bad('unbalanced braces: ' + u)
else:
    ok('all braces balanced')
for t in toolong:
    warn('long phrase: ' + t)

print()
print('=== 4. 合并文件必须与 packs 完全一致，且文件名里的数字要对得上 ===')
for fn, expected in (('all-personal-350.txt', personal_lines),
                     ('all-genre-126.txt', genre_lines)):
    fp = os.path.join(KIT, 'phrases', fn)
    if not os.path.exists(fp):
        bad('MISSING %s' % fn)
        continue
    got = [l.rstrip('\n') for l in io.open(fp, encoding='utf-8') if l.strip()]
    if got != expected:
        bad('%s mismatch: file=%d expected=%d, symmetric-diff=%d'
            % (fn, len(got), len(expected), len(set(got) ^ set(expected))))
        continue
    m = re.search(r'(\d+)(?=\.txt$)', fn)
    if m and int(m.group(1)) != len(got):
        bad('%s claims %s lines but holds %d' % (fn, m.group(1), len(got)))
    else:
        ok('%s matches packs exactly  %d' % (fn, len(got)))

print()
print('=== 5. 禁用的环境变量不得出现在短语里 ===')
banned = ['%COMPUTERNAME%', '%USERNAME%', '%USERDOMAIN%', '%USERPROFILE%',
          'whoami', '%USERDNSDOMAIN%', 'MachineName', '[Environment]::UserName']
hits = []
for l in (personal_lines + genre_lines):
    for b in banned:
        if b.lower() in l.lower():
            hits.append('%s  <- %s' % (l, b))
if hits:
    for h in hits:
        bad('banned identifier: ' + h)
else:
    ok('no machine or user name leakage in %d phrases' % len(seen))

print()
print('=== 6. 必需文件存在 ===')
need = ['README.md', 'PROMPT.md', 'LICENSE',
        'docs/mechanism.md', 'docs/uia-notes.md', 'docs/recipe.md',
        'docs/expression-cheatsheet.md',
        'phrases/all-personal-350.txt', 'phrases/all-genre-126.txt',
        'tools/NekoTrakUIA.psm1', 'tools/add-presets.ps1', 'tools/add-apps.ps1',
        'tools/set-category.ps1', 'tools/scan-installed-apps.ps1',
        'tools/fg-phrase.ps1', 'tools/nk-hardwrite.py',
        'tools/scan-personal-data.py', 'tools/set-category-format.ps1']
for n in need:
    if os.path.exists(os.path.join(KIT, n)):
        ok(n)
    else:
        bad('MISSING ' + n)

print()
print('=== 7. 文档必须讲清楚两点：${} 语法、shell 模式 ===')
readme = io.open(os.path.join(KIT, 'README.md'), encoding='utf-8').read()
prompt = io.open(os.path.join(KIT, 'PROMPT.md'), encoding='utf-8').read()
sheet = io.open(os.path.join(KIT, 'docs', 'expression-cheatsheet.md'),
                encoding='utf-8').read()
for label, blob, needle in (
        ('README 讲 ${} 语法', readme, '${'),
        ('README 讲 shell 模式', readme, 'steamCommandShell'),
        ('PROMPT 讲 shell 模式', prompt, 'steamCommandShell'),
        ('速查表讲 cmd 取值', sheet, 'cmd'),
        ('速查表讲 powershell 取值', sheet, 'powershell'),
        ('速查表讲前导 & 陷阱', sheet, 'unexpected at this time'),
):
    if needle in blob:
        ok(label)
    else:
        bad('%s  missing %r' % (label, needle))

print()
print('=' * 56)
if fails:
    print('RESULT: %d FAILURE(S), %d warning(s)' % (len(fails), len(warns)))
    for f in fails[:40]:
        print('  - ' + f)
    sys.exit(1)
print('RESULT: ALL CHECKS PASSED, %d warning(s)' % len(warns))
for w in warns:
    print('  - ' + w)
