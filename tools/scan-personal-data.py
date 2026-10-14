#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan-personal-data.py —— 把「这台机器上真实的你」扫成一份 Markdown 画像。

短语好笑的关键是具体。泛泛的「正在摸鱼」没人笑，「正在找回 hotmail，第 47 次」才会。
这个脚本唯一的职责就是把原料摆到桌面上，**不生成任何短语**。短语由 AI 拿着这份
画像现写，流程见 PROMPT.md 阶段三。

用法：

    python scan-personal-data.py
    python scan-personal-data.py --out D:\\me.md
    python scan-personal-data.py --browser opera
    python scan-personal-data.py --top 150 --recent 300

只读。浏览器在运行时其 History 会被独占，脚本会复制一份副本再读，绝不写回原文件。
不联网，不上传任何东西。仅依赖标准库，Windows 加 Python 3.8 以上即可。
"""

import argparse
import collections
import glob
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time

IS_WIN = os.name == 'nt'
APPDATA = os.environ.get('APPDATA', '')
LOCALAPPDATA = os.environ.get('LOCALAPPDATA', '')

CHROMIUM_PROFILES = {
    'opera':    [r'Opera Software\Opera GX Stable', r'Opera Software\Opera Stable'],
    'chrome':   [r'Google\Chrome\User Data'],
    'edge':     [r'Microsoft\Edge\User Data'],
    'brave':    [r'BraveSoftware\Brave-Browser\User Data'],
    'vivaldi':  [r'Vivaldi\User Data'],
    'waterfox': [r'Waterfox\User Data'],
}

PROGID_HINTS = {
    'opera': 'Opera', 'chrome': 'Chrome', 'edge': 'Edge',
    'brave': 'Brave', 'vivaldi': 'Vivaldi', 'waterfox': 'Waterfox',
    'firefox': 'Firefox',
}

NOISY = re.compile(
    r'(?i)(\.NET|VC\+\+|Visual C\+\+|Redistributable|Runtime|SDK|Windows Software Development Kit'
    r'|Installer|Uninstall|卸载|Package Cache|Telemetry|Language Pack|Service Pack'
    r'|Microsoft Edge Update|Bonjour|Host Package|Update for)')

BAD_EXE = re.compile(
    r'(?i)\\(unins[^\\]*|uninstall[^\\]*|uninst[^\\]*|setup|installer|install|update'
    r'|updater|upgrade|patch|repair|msiexec|vcredist[^\\]*)\.exe$')

SYS_JUNK = re.compile(
    r'(?i)^C:\\Windows\\(System32|SysWOW64)\\(control|rundll32|msiexec|dllhost|taskmgr'
    r'|regedit|mmc|wscript|cscript|mshta|colorcpl|SystemSettings)\.exe$')


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def default_browser_progid():
    """注册表里 http 协议的默认处理程序 ProgId，例如 Opera GXStable。"""
    if not IS_WIN:
        return ''
    import winreg
    path = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, 'ProgId')[0]
    except Exception:
        return ''


def find_chromium_history(family):
    """返回 History 路径与说明。family 取自 CHROMIUM_PROFILES 的键。"""
    subs = CHROMIUM_PROFILES.get(family, [])
    roots = []
    for base in (APPDATA, LOCALAPPDATA):
        if not base:
            continue
        for sub in subs:
            roots.append(os.path.join(base, sub))
    for root in roots:
        for prof in ('Default', 'Profile 1', 'Profile 2'):
            h = os.path.join(root, prof, 'History')
            if os.path.isfile(h):
                return h, '%s / %s' % (family, prof)
    return None, ''


def find_firefox_places():
    root = os.path.join(APPDATA, r'Mozilla\Firefox\Profiles')
    if not os.path.isdir(root):
        return None, ''
    best = None
    best_name = ''
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d, 'places.sqlite')
        if not os.path.isfile(p):
            continue
        if best is None or d.endswith('.default-release'):
            best, best_name = p, d
        if d.endswith('.default-release'):
            break
    return best, best_name


def pick_browser(forced):
    """决定读哪个浏览器。返回 kind, path, label，kind 取 chromium 或 firefox。"""
    progid = default_browser_progid()

    if forced and forced != 'auto':
        if forced == 'firefox':
            p, lab = find_firefox_places()
            return ('firefox', p, lab) if p else (None, None, '')
        p, lab = find_chromium_history(forced)
        return ('chromium', p, lab) if p else (None, None, '')

    low = progid.lower()
    for fam, hint in PROGID_HINTS.items():
        if hint.lower() in low:
            if fam == 'firefox':
                p, lab = find_firefox_places()
                if p:
                    return 'firefox', p, lab
            else:
                p, lab = find_chromium_history(fam)
                if p:
                    return 'chromium', p, lab

    for fam in ('opera', 'chrome', 'edge', 'brave', 'vivaldi', 'waterfox'):
        p, lab = find_chromium_history(fam)
        if p:
            return 'chromium', p, lab
    p, lab = find_firefox_places()
    if p:
        return 'firefox', p, lab
    return None, None, ''


def open_history_readonly(path):
    """浏览器在跑时 History 会被独占，所以先复制到临时目录再打开。"""
    if not path:
        return None, None
    tmpdir = tempfile.mkdtemp(prefix='nk-profile-')
    base = os.path.join(tmpdir, os.path.basename(path))
    try:
        shutil.copyfile(path, base)
    except Exception:
        return None, None
    for ext in ('-wal', '-shm'):
        try:
            if os.path.isfile(path + ext):
                shutil.copyfile(path + ext, base + ext)
        except Exception:
            pass
    return sqlite3.connect(base), tmpdir


def read_chromium(con, top, recent):
    """Chromium 系浏览器共用同一套表结构。"""
    res = {}
    cur = con.cursor()

    res['total_visits'] = safe(lambda: cur.execute(
        'SELECT COUNT(*) FROM visits;').fetchone()[0], 0)
    res['total_urls'] = safe(lambda: cur.execute(
        'SELECT COUNT(*) FROM urls;').fetchone()[0], 0)

    rows = safe(lambda: cur.execute("""
        SELECT urls.url, COUNT(*) c
        FROM visits JOIN urls ON urls.id = visits.url
        GROUP BY urls.url ORDER BY c DESC LIMIT 4000;
    """).fetchall(), []) or []
    dom = collections.Counter()
    for u, c in rows:
        m = re.match(r'^[a-zA-Z]+://([^/]+)', u or '')
        if m:
            dom[m.group(1).lower()] += c
    res['domains'] = dom.most_common(top)

    res['searches'] = safe(lambda: cur.execute("""
        SELECT term, COUNT(*) c FROM keyword_search_terms
        GROUP BY lower(term) ORDER BY c DESC, term LIMIT 400;
    """).fetchall(), []) or []

    res['recent'] = safe(lambda: cur.execute("""
        SELECT urls.title, urls.url, visits.visit_time
        FROM visits JOIN urls ON urls.id = visits.url
        ORDER BY visits.visit_time DESC LIMIT ?;
    """, (recent,)).fetchall(), []) or []

    ts = safe(lambda: cur.execute('SELECT visit_time FROM visits;').fetchall(), []) or []
    hours = collections.Counter()
    for (vt,) in ts:
        if vt:
            unixt = vt / 1000000.0 - 11644473600.0
            if unixt > 0:
                hours[int((unixt // 3600) % 24)] += 1
    res['hours'] = hours
    return res


def read_firefox(con, top, recent):
    """
    Firefox 用 places.sqlite。它没有 keyword_search_terms 这样的搜索词表，
    搜索词混在 URL 参数里，所以额外从 q、wd、word 这类参数中抠出来。
    """
    res = {}
    cur = con.cursor()
    res['total_visits'] = safe(lambda: cur.execute(
        'SELECT COUNT(*) FROM moz_historyvisits;').fetchone()[0], 0)
    res['total_urls'] = safe(lambda: cur.execute(
        'SELECT COUNT(*) FROM moz_places;').fetchone()[0], 0)

    rows = safe(lambda: cur.execute("""
        SELECT p.url, COUNT(*) c
        FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
        GROUP BY p.url ORDER BY c DESC LIMIT 4000;
    """).fetchall(), []) or []
    dom = collections.Counter()
    for u, c in rows:
        m = re.match(r'^[a-zA-Z]+://([^/]+)', u or '')
        if m:
            dom[m.group(1).lower()] += c
    res['domains'] = dom.most_common(top)

    se = collections.Counter()
    has_kw = safe(lambda: cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='moz_keywords';"
    ).fetchone(), None)
    if has_kw:
        rows2 = safe(lambda: cur.execute("""
            SELECT k.keyword, COUNT(*) c FROM moz_keywords k
            JOIN moz_places p ON p.keyword_id = k.id
            JOIN moz_historyvisits v ON v.place_id = p.id
            GROUP BY lower(k.keyword) ORDER BY c DESC LIMIT 300;
        """).fetchall(), []) or []
        for t, c in rows2:
            se[t] += c
    import urllib.parse
    for u, _c in rows:
        m = re.search(r'[?&](?:q|wd|word|query|search_query|keyword)=([^&#]+)', u or '')
        if m:
            t = m.group(1).replace('+', ' ').strip()
            t = safe(lambda: urllib.parse.unquote(t), t) or t
            if t:
                se[t] += 1
    res['searches'] = se.most_common(300)

    res['recent'] = safe(lambda: cur.execute("""
        SELECT p.title, p.url, v.visit_date
        FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
        ORDER BY v.visit_date DESC LIMIT ?;
    """, (recent,)).fetchall(), []) or []

    ts = safe(lambda: cur.execute(
        'SELECT visit_date FROM moz_historyvisits;').fetchall(), []) or []
    hours = collections.Counter()
    for (vt,) in ts:
        if vt:
            hours[int((vt / 1000000.0 // 3600) % 24)] += 1
    res['hours'] = hours
    return res


def scan_installed_apps():
    """注册表 Uninstall 三处加开始菜单快捷方式加运行中进程，合并去重并过滤噪声。"""
    found = {}

    def add_exe(exe, name):
        if not exe:
            return
        exe = exe.strip('"').strip()
        exe = re.sub(r',-?\d+$', '', exe)
        exe = re.sub(r'^@', '', exe)
        if not exe.lower().endswith('.exe'):
            return
        if not os.path.isfile(exe):
            return
        if BAD_EXE.search(exe) or SYS_JUNK.match(exe):
            return
        if NOISY.search(name or ''):
            return
        found.setdefault(exe.lower(), (exe, (name or os.path.basename(exe)).strip()))

    if IS_WIN:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_CURRENT_USER,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]
        for hive, path in keys:
            try:
                with winreg.OpenKey(hive, path) as root:
                    n = winreg.QueryInfoKey(root)[0]
                    for i in range(n):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                                def q(nm):
                                    try:
                                        return winreg.QueryValueEx(sub, nm)[0]
                                    except Exception:
                                        return ''
                                if str(q('SystemComponent')) == '1':
                                    continue
                                disp = q('DisplayName')
                                if not disp:
                                    continue
                                add_exe(q('DisplayIcon') or q('InstallLocation'), disp)
                        except Exception:
                            continue
            except Exception:
                pass

    for base in (os.path.join(APPDATA, r'Microsoft\Windows\Start Menu\Programs'),
                 r'C:\ProgramData\Microsoft\Windows\Start Menu\Programs'):
        for p in glob.glob(os.path.join(base, '**', '*.lnk'), recursive=True):
            nm = os.path.splitext(os.path.basename(p))[0]
            if not NOISY.search(nm):
                found.setdefault('lnk:' + p.lower(), (p, nm))

    try:
        import subprocess
        txt = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                             capture_output=True).stdout.decode('gbk', 'replace')
        running = sorted(set(r.split(',')[0].strip('"') for r in txt.splitlines() if r.strip()))
    except Exception:
        running = []
    return found, running


def scan_steam_games():
    games = []
    pats = [r'C:\Program Files (x86)\Steam\steamapps\*.acf',
            r'C:\Program Files\Steam\steamapps\*.acf']
    for pat in pats:
        for acf in glob.glob(os.path.abspath(pat)):
            txt = safe(lambda: io.open(acf, encoding='utf-8', errors='replace').read(), '') or ''
            m = re.search(r'"name"\s+"([^"]+)"', txt)
            s = re.search(r'"SizeOnDisk"\s+"(\d+)"', txt)
            if m:
                gb = int(s.group(1)) / 1073741824.0 if s else 0.0
                games.append((m.group(1), gb))
    games.sort(key=lambda x: -x[1])
    return games


def build_report(args):
    L = []
    progid = default_browser_progid()
    kind, path, label = pick_browser(args.browser)

    L.append('# 我的机器画像')
    L.append('')
    L.append('由 `scan-personal-data.py` 生成，时间 %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    L.append('')
    L.append('这份文件只在本机生成，没有被上传到任何地方。里面会有你搜索过什么、')
    L.append('玩过什么、装了什么。给 AI 看之前请自己过一遍，划掉你不想被拿来开玩笑的部分。')
    L.append('')

    L.append('## 1. 浏览器')
    L.append('')
    L.append('- 注册表默认浏览器 ProgId：`%s`' % (progid or '未读到'))
    if path:
        L.append('- 实际读取：%s' % label)
        L.append('- 历史库：`%s`' % path)
    else:
        L.append('- 没找到任何浏览器历史库。用 `--browser chrome|edge|opera|firefox` 手动指定。')
    L.append('')

    if path:
        con, tmpdir = open_history_readonly(path)
        if con is None:
            L.append('打不开历史库，被占用且复制失败。')
        else:
            data = read_chromium(con, args.top, args.recent) if kind == 'chromium' \
                else read_firefox(con, args.top, args.recent)
            con.close()

            L.append('### 1.1 访问量')
            L.append('')
            L.append('- 总访问条数：%s' % data.get('total_visits', 0))
            L.append('- 去重后 URL 数：%s' % data.get('total_urls', 0))
            L.append('')

            L.append('### 1.2 域名 TOP %d，按访问次数' % args.top)
            L.append('')
            L.append('这一节回答「我最常在哪」。')
            L.append('')
            for d, c in data.get('domains', []):
                L.append('- `%s` 共 %d 次' % (d, c))
            L.append('')

            L.append('### 1.3 搜索词，这是金矿')
            L.append('')
            L.append('这一节回答「我最想知道什么」。人的搜索框比什么都诚实。')
            L.append('')
            for t, c in data.get('searches', []):
                L.append('- %s%s' % (t, (' 共 %d 次' % c) if c > 1 else ''))
            L.append('')

            L.append('### 1.4 最近 %d 条访问' % args.recent)
            L.append('')
            L.append('这一节回答「我最近在忙什么」。')
            L.append('')
            for t, u, _ts in data.get('recent', []):
                L.append('- %s — `%s`' % ((t or '无标题')[:90], (u or '')[:150]))
            L.append('')

            L.append('### 1.5 一天里什么时候最活跃')
            L.append('')
            hrs = data.get('hours', collections.Counter())
            mx = max(hrs.values()) if hrs else 1
            for h in range(24):
                n = hrs.get(h, 0)
                bar = '#' * int(round(40.0 * n / mx)) if mx else ''
                L.append('%02d 时 |%-40s| %d' % (h, bar, n))
            L.append('')
            if tmpdir:
                safe(lambda: shutil.rmtree(tmpdir, ignore_errors=True))

    L.append('## 2. Steam 游戏')
    L.append('')
    games = scan_steam_games()
    if games:
        for g, gb in games:
            L.append('- %s — %.2f GB' % (g, gb))
    else:
        L.append('没找到 steamapps 下的 acf 文件。')
    L.append('')

    L.append('## 3. 装了什么，正在跑什么')
    L.append('')
    found, running = scan_installed_apps()
    L.append('### 3.1 装了什么')
    L.append('')
    L.append('已过滤 .NET、VC++、SDK、卸载器这类噪声。')
    L.append('')
    apps = sorted(set(v[1] for v in found.values() if not v[0].startswith('lnk:')))
    L.append('共 %d 项，下面列出前 %d 项：' % (len(apps), min(len(apps), 400)))
    L.append('')
    for a in apps[:400]:
        L.append('- %s' % a)
    L.append('')

    L.append('### 3.2 现在正在跑什么')
    L.append('')
    L.append(', '.join(running) if running else '未读到')
    L.append('')

    L.append('## 4. 接下来怎么用这份文件')
    L.append('')
    L.append('把这份 Markdown 原样丢给 AI，配合 `PROMPT.md` 的阶段三。')
    L.append('')
    L.append('要提醒 AI 的是：短语必须从这个文件里的具体东西长出来，不许套模板。')
    L.append('')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(
        description='把本机真实使用痕迹扫成一份 Markdown 画像。只读，不联网。')
    ap.add_argument('--out', default='personal-profile.md', help='输出路径')
    ap.add_argument('--browser', default='auto',
                    choices=['auto', 'opera', 'chrome', 'edge', 'brave', 'vivaldi',
                             'waterfox', 'firefox'],
                    help='强制指定浏览器，默认按注册表自动判断')
    ap.add_argument('--top', type=int, default=120, help='域名 TOP N，默认 120')
    ap.add_argument('--recent', type=int, default=250, help='最近访问条数，默认 250')
    args = ap.parse_args()

    text = build_report(args)
    path = os.path.abspath(args.out)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('wrote %s, %d chars' % (path, len(text)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
