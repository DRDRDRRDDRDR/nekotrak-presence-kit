# -*- coding: utf-8 -*-
"""NekoTrak hard-write toolkit — talk straight to the encrypted DB, no UI clicking.

The database is SQLCipher-encrypted. The key lives in NekoTrak.exe's memory as a
raw-key PRAGMA string:  x'<64 hex key><32 hex salt>'
The first 32 bytes are the AES key, the last 16 are the per-file salt that is also
stored in the first 16 bytes of the .db file.

Usage (NekoTrak may stay running — the app re-reads the table live):

    python nk-hardwrite.py key                 # recover the key from process memory
    python nk-hardwrite.py presets <file.txt>  # append every line as a preset
    python nk-hardwrite.py presets <file.txt> --replace   # wipe first
    python nk-hardwrite.py formats <map.tsv>   # category  "name<TAB>format"
    python nk-hardwrite.py dump                # show what's in there
    python nk-hardwrite.py sql "SELECT ..."    # read-only query

Every mutating command backs the DB up first.
"""
from __future__ import print_function

import ctypes
import ctypes.wintypes as wt
import io
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---------------------------------------------------------------- paths
APPDATA = os.environ.get('APPDATA', r'C:\Users\Default\AppData\Roaming')
NK_ROOT = os.path.join(APPDATA, 'NekoTrak')


def _steam_id(root):
    local = os.path.join(root, 'local.json')
    if os.path.exists(local):
        m = re.search(r'"steam_id"\s*:\s*(\d+)', io.open(local, encoding='utf-8').read())
        if m:
            return m.group(1)
    users = os.path.join(root, 'users')
    if os.path.isdir(users):
        subs = [d for d in os.listdir(users) if d.isdigit()]
        if subs:
            return subs[0]
    return None


def user_db_path(root=None):
    root = root or NK_ROOT
    sid = _steam_id(root)
    if sid:
        p = os.path.join(root, 'users', sid, 'data', 'NekoTrak.db')
        if os.path.exists(p):
            return p
    return os.path.join(root, 'data', 'NekoTrak.db')


def find_dll():
    """SQLCipher-enabled sqlite3 DLL. Any build that exports sqlite3_key works."""
    env = os.environ.get('NK_SQLCIPHER_DLL')
    cands = []
    if env:
        cands.append(env)
    cands += [
        os.path.join(HERE, 'sqlcipher.dll'),
        r'C:\Program Files\i4Tools9\sqlcipher.dll',
        r'C:\Program Files (x86)\i4Tools9\sqlcipher.dll',
        r'C:\Program Files\Common Files\Apple\Mobile Device Support\sqlcipher.dll',
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise SystemExit(
        'SQLCipher DLL not found. Set NK_SQLCIPHER_DLL to a sqlite3 build that\n'
        'exports sqlite3_key (e.g. the one shipped with i4Tools / AnyTrans).')


# ---------------------------------------------------------------- sqlcipher binding
def _bind(dll_path):
    sql = ctypes.CDLL(dll_path)
    sigs = [
        ('sqlite3_open', [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int),
        ('sqlite3_key', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_int),
        ('sqlite3_exec', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        ('sqlite3_prepare_v2', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        ('sqlite3_step', [ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_column_text', [ctypes.c_void_p, ctypes.c_int], ctypes.c_char_p),
        ('sqlite3_column_count', [ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_finalize', [ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_errmsg', [ctypes.c_void_p], ctypes.c_char_p),
        ('sqlite3_close', [ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_changes', [ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_bind_text', [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                               ctypes.c_void_p], ctypes.c_int),
        ('sqlite3_bind_int', [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], ctypes.c_int),
    ]
    for fn, arg, ret in sigs:
        f = getattr(sql, fn)
        f.argtypes = arg
        f.restype = ret
    return sql


SQLITE_ROW, SQLITE_DONE = 100, 101
SQLITE_TRANSIENT = ctypes.cast(-1, ctypes.c_void_p)

_SQL = None


def sql():
    global _SQL
    if _SQL is None:
        _SQL = _bind(find_dll())
    return _SQL


class Db(object):
    def __init__(self, path, key):
        self.s = sql()
        self.path = path
        self.handle = ctypes.c_void_p()
        rc = self.s.sqlite3_open(path.encode('utf-8'), ctypes.byref(self.handle))
        if rc != 0:
            raise RuntimeError('sqlite3_open rc=%d' % rc)
        rc = self.s.sqlite3_key(self.handle, key.encode('utf-8'), len(key))
        if rc != 0:
            raise RuntimeError('sqlite3_key rc=%d' % rc)
        # fail early and loudly if the key is wrong
        self.query('SELECT count(*) FROM sqlite_master;')

    def errmsg(self):
        v = self.s.sqlite3_errmsg(self.handle)
        return v.decode('utf-8', 'replace') if v else ''

    def query(self, text, params=None):
        st = ctypes.c_void_p()
        rc = self.s.sqlite3_prepare_v2(self.handle, text.encode('utf-8'), -1, ctypes.byref(st), None)
        if rc != 0:
            raise RuntimeError(self.errmsg())
        self._bind(st, params)
        cols = self.s.sqlite3_column_count(st)
        rows = []
        while self.s.sqlite3_step(st) == SQLITE_ROW:
            row = []
            for i in range(cols):
                v = self.s.sqlite3_column_text(st, i)
                row.append(v.decode('utf-8', 'replace') if v else '')
            rows.append(row)
        self.s.sqlite3_finalize(st)
        return rows

    def run(self, text, params=None):
        st = ctypes.c_void_p()
        rc = self.s.sqlite3_prepare_v2(self.handle, text.encode('utf-8'), -1, ctypes.byref(st), None)
        if rc != 0:
            raise RuntimeError(self.errmsg())
        self._bind(st, params)
        rc = self.s.sqlite3_step(st)
        self.s.sqlite3_finalize(st)
        if rc not in (SQLITE_DONE, SQLITE_ROW):
            raise RuntimeError(self.errmsg())
        return self.s.sqlite3_changes(self.handle)

    def _bind(self, st, params):
        if not params:
            return
        for i, p in enumerate(params, 1):
            if isinstance(p, int):
                self.s.sqlite3_bind_int(st, i, p)
            else:
                b = p.encode('utf-8')
                # SQLITE_TRANSIENT: sqlite must copy now — a Python bytes object
                # dies the moment this call returns, and SQLITE_STATIC would leave
                # a dangling pointer (that is how you get mojibake in the table).
                self.s.sqlite3_bind_text(st, i, b, len(b), SQLITE_TRANSIENT)

    def exec_raw(self, text):
        err = ctypes.c_char_p()
        rc = self.s.sqlite3_exec(self.handle, text.encode('utf-8'), None, None, ctypes.byref(err))
        if rc != 0:
            msg = err.value.decode('utf-8', 'replace') if err.value else self.errmsg()
            raise RuntimeError(msg)

    def close(self):
        self.s.sqlite3_close(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ---------------------------------------------------------------- key recovery
def recover_key(pid=None, db_path=None):
    """Scan NekoTrak.exe memory for the raw SQLCipher key string.

    NekoTrak builds  PRAGMA key = 'x'<64 hex><32 hex>''  and the salt half always
    equals the first 16 bytes of the target .db file, which is what lets us tell a
    real key from any other hex blob in memory.
    """
    import ctypes.wintypes

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    MEM_COMMIT = 0x1000
    PAGE_NOACCESS = 0x01
    PAGE_GUARD = 0x100
    READABLE = (0x02, 0x04, 0x20, 0x40)  # RO, RW, WRITECOPY, EXECUTE_READWRITE

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [('BaseAddress', ctypes.c_void_p),
                    ('AllocationBase', ctypes.c_void_p),
                    ('AllocationProtect', wt.DWORD),
                    ('RegionSize', ctypes.c_size_t),
                    ('State', wt.DWORD),
                    ('Protect', wt.DWORD),
                    ('Type', wt.DWORD)]

    if pid is None:
        # find NekoTrak's pid
        import subprocess
        out = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq NekoTrak.exe', '/FO', 'CSV', '/NH'],
                                      stderr=subprocess.DEVNULL).decode('utf-8', 'replace')
        m = re.search(r'"NekoTrak\.exe","(\d+)"', out)
        if not m:
            raise SystemExit('NekoTrak.exe is not running — start it once, then rerun.')
        pid = int(m.group(1))

    salt = None
    if db_path and os.path.exists(db_path):
        salt = open(db_path, 'rb').read(16).hex()

    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed (%d). Run as administrator.' % ctypes.get_last_error())

    pattern = re.compile(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'")
    hits = []
    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    max_addr = 0x7FFFFFFFFFFF
    try:
        while addr < max_addr:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                addr += 0x1000
                continue
            size = mbi.RegionSize
            if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                    and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)) and size > 0):
                buf = ctypes.create_string_buffer(size)
                read = ctypes.c_size_t(0)
                if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read)):
                    data = buf.raw[:read.value]
                    for m in pattern.finditer(data):
                        key_hex, salt_hex = m.group(1).decode(), m.group(2).decode()
                        hits.append((key_hex, salt_hex))
                        if salt and salt_hex == salt:
                            return "x'%s%s'" % (key_hex, salt_hex)
            addr += size if size else 0x1000
    finally:
        k32.CloseHandle(h)

    if hits:
        # no salt match — fall back to the most frequent candidate
        from collections import Counter
        best = Counter(hits).most_common(1)[0][0]
        sys.stderr.write('warning: no salt match; using most common candidate\n')
        return "x'%s%s'" % best
    raise SystemExit("No raw SQLCipher key found in NekoTrak's memory.")


# ---------------------------------------------------------------- helpers
def backup(db_path):
    d = os.path.join(os.path.dirname(db_path),
                     'dbbackup-%s' % time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(d, exist_ok=True)
    for suf in ('', '-wal', '-shm'):
        src = db_path + suf
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, os.path.basename(db_path) + suf))
    return d


def read_lines(path):
    raw = open(path, 'rb').read()
    if raw[:3] == b'\xef\xbb\xbf':
        raw = raw[3:]
    text = raw.decode('utf-8')
    return [ln.strip() for ln in text.replace('\r\n', '\n').split('\n')]


def open_db(db_path=None, key=None):
    db_path = db_path or user_db_path()
    key = key or os.environ.get('NK_KEY') or recover_key(db_path=db_path)
    return Db(db_path, key), db_path


# ---------------------------------------------------------------- commands
def cmd_key(args):
    key = recover_key(db_path=user_db_path())
    print(key)
    print('')
    print('Save it if you like:  set NK_KEY=%s' % key, file=sys.stderr)


def cmd_presets(args):
    path = args[0]
    replace = '--replace' in args
    lines = [l for l in read_lines(path) if l]
    db, db_path = open_db()
    with db:
        bak = backup(db_path)
        print('backup -> %s' % bak)
        if replace:
            n = db.run('DELETE FROM custom_text_presets;')
            print('cleared %d existing preset(s)' % n)
        existing = set(r[0] for r in db.query('SELECT normalized_text FROM custom_text_presets;'))
        mx = int(db.query('SELECT COALESCE(MAX(sort_order), -1) FROM custom_text_presets;')[0][0])
        added = skipped = 0
        for text in lines:
            norm = text.lower()
            if norm in existing:
                skipped += 1
                continue
            mx += 1
            db.run('INSERT INTO custom_text_presets (text, normalized_text, sort_order) VALUES (?1, ?2, ?3)',
                   [text, norm, mx])
            existing.add(norm)
            added += 1
        print('added %d, skipped %d duplicate(s)' % (added, skipped))
        print('table now holds %s preset(s)' % db.query('SELECT count(*) FROM custom_text_presets;')[0][0])


def cmd_formats(args):
    path = args[0]
    pairs = []
    for ln in read_lines(path):
        if not ln or ln.startswith('#'):
            continue
        parts = re.split(r'\t|=', ln, 1)
        if len(parts) == 2:
            pairs.append((parts[0].strip(), parts[1].strip()))
    db, db_path = open_db()
    with db:
        bak = backup(db_path)
        print('backup -> %s' % bak)
        ok = bad = 0
        for name, fmt in pairs:
            rows = db.query('SELECT id FROM categories WHERE name = ?1;', [name])
            if not rows:
                print('  MISS  %s (no such category)' % name)
                bad += 1
                continue
            try:
                db.run('UPDATE categories SET presence_format = ?1 WHERE id = ?2;', [fmt, int(rows[0][0])])
                print('  OK    %s -> %s' % (name, fmt))
                ok += 1
            except Exception as e:
                print('  FAIL  %s : %s' % (name, e))
                bad += 1
        print('done  ok=%d  bad=%d' % (ok, bad))


def cmd_dump(args):
    db, db_path = open_db()
    with db:
        print('db  = %s' % db_path)
        presets = db.query('SELECT count(*) FROM custom_text_presets;')[0][0]
        print('presets = %s' % presets)
        for r in db.query('SELECT id, sort_order, text FROM custom_text_presets ORDER BY sort_order LIMIT 5;'):
            print('   #%s  %s' % (r[1], r[2]))
        if int(presets) > 5:
            print('   ...')
            for r in db.query('SELECT id, sort_order, text FROM custom_text_presets ORDER BY sort_order DESC LIMIT 3;'):
                print('   #%s  %s' % (r[1], r[2]))
        print('\ncategories:')
        for r in db.query('SELECT id, name, presence_format FROM categories '
                          'ORDER BY COALESCE(parent_id, id), id;'):
            print('   %-6s %s' % (r[1], r[2]))
        n = db.query('SELECT count(*) FROM apps;')[0][0]
        print('\napps = %s' % n)
        print('tables = %s' % len(db.query("SELECT name FROM sqlite_master WHERE type='table';")))


def cmd_sql(args):
    db, _ = open_db()
    with db:
        for r in db.query(args[0]):
            print(' | '.join(r))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, rest = argv[1], argv[2:]
    table = {'key': cmd_key, 'presets': cmd_presets, 'formats': cmd_formats,
             'dump': cmd_dump, 'sql': cmd_sql}
    if cmd not in table:
        print('unknown command: %s' % cmd)
        print(__doc__)
        return 2
    table[cmd](rest)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
