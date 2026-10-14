# -*- coding: utf-8 -*-
"""把 custom_text_presets 里 cmd 风格表达式迁移成 PowerShell 等价式。

背景：NekoTrak 的 ${...} 交给哪个 shell 由 config.json 的 steamCommandShell 决定，
取值 cmd 或 powershell。两种模式互不兼容，所以换 shell 时必须同步改写数据，
否则原来的表达式会变成纯文本原样显示。

用法：
    python tools/migrate-shell.py --dry-run          # 只报告，不写
    python tools/migrate-shell.py --apply            # 写入
    python tools/migrate-shell.py --apply --to cmd   # 反向迁移

迁移前务必停止 NekoTrak，并先备份 NekoTrak.db。
"""
import argparse
import collections
import io
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# cmd 写法 -> PowerShell 写法
#
# 为什么用 $(...) 子表达式而不是裸命令：
# 不确定 NekoTrak 是把表达式作为裸 argv 元素传入，还是拼进带引号的命令串。
# 实测裸写法 Get-Random -Max 32768 只在裸 argv 下求值，一旦被引号包裹就原样
# 返回字面文本，而且是静默的。$(...) 在裸 argv、双引号包裹、-c 短参数三种
# 传参下都会求值，所以更稳。
TO_PS = [
    ('${echo %RANDOM%}',   '${$(Get-Random -Max 32768)}'),
    ('${echo %TIME:~0,5%}', '${$(Get-Date -Format HH:mm)}'),
    ('${echo %TIME%}',     '${$(Get-Date -Format HH:mm:ss)}'),
    ('${echo %DATE%}',     '${$(Get-Date -Format yyyy-MM-dd)}'),
    ('${echo %COMPUTERNAME%}', '${$env:COMPUTERNAME}'),
    ('${echo %USERNAME%}', '${$env:USERNAME}'),
    ('${echo %USERDOMAIN%}', '${$env:USERDOMAIN}'),
    ('${echo %TEMP%}',     '${$env:TEMP}'),
]

# PowerShell 写法 -> cmd 写法
TO_CMD = [
    ('${$(Get-Random -Max 32768)}',     '${echo %RANDOM%}'),
    ('${$(Get-Date -Format HH:mm:ss)}', '${echo %TIME%}'),
    ('${$(Get-Date -Format HH:mm)}',    '${echo %TIME:~0,5%}'),
    ('${$(Get-Date -Format yyyy-MM-dd)}', '${echo %DATE%}'),
    ('${$env:COMPUTERNAME}', '${echo %COMPUTERNAME%}'),
    ('${$env:USERNAME}',     '${echo %USERNAME%}'),
    ('${$env:USERDOMAIN}',   '${echo %USERDOMAIN%}'),
    ('${$env:TEMP}',         '${echo %TEMP%}'),
]


def load_hardwrite():
    spec = importlib.util.spec_from_file_location(
        'nkhw', os.path.join(HERE, 'nk-hardwrite.py'))
    mod = importlib.util.module_from_spec(spec)
    argv_backup = sys.argv
    sys.argv = ['nk-hardwrite']
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv_backup
    return mod


def read_key(path=None):
    if path:
        return io.open(path, encoding='utf-8').read().strip()
    tmp = os.environ.get('TEMP') or os.environ.get('TMP') or '.'
    for cand in (os.path.join(tmp, 'nkkey.txt'),
                 os.path.join(tmp, 'nekoprobe', 'nkkey.txt'),
                 os.path.join(HERE, '..', 'nkkey.txt')):
        if os.path.exists(cand):
            return io.open(cand, encoding='utf-8').read().strip()
    raise SystemExit('找不到密钥文件。先跑 nk-hardwrite.py key 存一份，或用 --key 指定。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='真正写入，缺省只预演')
    ap.add_argument('--dry-run', action='store_true', help='只报告，这是缺省行为')
    ap.add_argument('--to', choices=['powershell', 'cmd'], default='powershell',
                    help='目标 shell，缺省 powershell')
    ap.add_argument('--db', default=None, help='数据库路径，缺省自动定位')
    ap.add_argument('--key', default=None, help='密钥，缺省读 TEMP\\nkkey.txt')
    args = ap.parse_args()

    table = TO_PS if args.to == 'powershell' else TO_CMD
    mod = load_hardwrite()
    db, db_path = mod.open_db(args.db, read_key(args.key))
    print('数据库 = %s' % db_path)
    print('目标 shell = %s' % args.to)
    print()

    rows = db.query('SELECT id, text, normalized_text FROM custom_text_presets ORDER BY sort_order')
    print('custom_text_presets 共 %d 行' % len(rows))

    # 先确认 normalized_text 是否就是 text 的小写镜像，决定怎么写它
    lower_mirror = all((r[2] or '') == (r[1] or '').lower() for r in rows)
    print('normalized_text 是 text 的小写镜像: %s' % lower_mirror)
    print()

    plan = []
    counter = collections.Counter()
    for rid, text, norm in rows:
        new_text = text or ''
        for a, b in table:
            n = new_text.count(a)
            if n:
                counter[a] += n
                new_text = new_text.replace(a, b)
        if new_text == (text or ''):
            continue
        new_norm = new_text.lower() if lower_mirror else (norm or '')
        if not lower_mirror:
            for a, b in table:
                new_norm = new_norm.replace(a.lower(), b.lower())
        plan.append((rid, text, new_text, new_norm))

    print('=== 将改写的表达式 ===')
    if not counter:
        print('  无需改写。')
    for a, b in table:
        if counter[a]:
            print('  %-24s ->  %-42s %d 次' % (a, b, counter[a]))
    print('  合计 %d 次，涉及 %d 行' % (sum(counter.values()), len(plan)))

    if not plan:
        db.close()
        return 0

    # 改写后 normalized_text 会不会撞车
    final = {}
    for rid, _, _, nn in plan:
        final.setdefault(nn, []).append(rid)
    clashes = {k: v for k, v in final.items() if len(v) > 1}
    if clashes:
        print()
        print('  警告：改写后 normalized_text 出现重复，需要人工确认：')
        for k, v in list(clashes.items())[:10]:
            print('    %s  <- id %s' % (k[:70], v))
    else:
        print('  改写后 normalized_text 无重复。')

    print()
    print('=== 抽样 5 行 ===')
    for rid, old, new, nn in plan[:5]:
        print('  id=%s' % rid)
        print('    旧  %s' % old)
        print('    新  %s' % new)
        print('    规范 %s' % nn)

    if not args.apply:
        print()
        print('预演结束，未写入。加 --apply 才会真正改。')
        db.close()
        return 0

    print()
    print('=== 写入 ===')
    n = 0
    db.exec_raw('BEGIN IMMEDIATE')
    try:
        for rid, _, new_text, new_norm in plan:
            db.run('UPDATE custom_text_presets SET text=?, normalized_text=? WHERE id=?',
                   [new_text, new_norm, int(rid)])
            n += 1
        db.exec_raw('COMMIT')
    except Exception:
        db.exec_raw('ROLLBACK')
        db.close()
        raise
    print('  已更新 %d 行' % n)

    # 回读验证
    left = 0
    for a, _ in table:
        pat = a.replace('%', '')
        r = db.query("SELECT COUNT(*) FROM custom_text_presets WHERE text LIKE '%%%s%%'" % pat)
        left += int(r[0][0])
    print('  回读：仍含旧写法的行 = %d' % left)

    db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
