# ponytail: 스키마 v4(uid) 이주 self-check. 임시 폴더만 쓴다. run: python src/test_sync_schema.py
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import MemoDatabase  # noqa: E402

# 2.0.x(v3) 형식 DB를 직접 만든다 — uid 열 없음
path = tmp / "memos.db"
old = sqlite3.connect(path)
old.executescript("""
CREATE TABLE memos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'paper', is_pinned INTEGER NOT NULL DEFAULT 0,
  deleted_at TEXT DEFAULT NULL, font_family TEXT NOT NULL DEFAULT '', font_size INTEGER NOT NULL DEFAULT 0,
  color_before_v2 TEXT DEFAULT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE memo_versions (id INTEGER PRIMARY KEY AUTOINCREMENT,
  memo_id INTEGER NOT NULL REFERENCES memos(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
INSERT INTO memos (title, content, color, is_pinned, created_at, updated_at)
  VALUES ('a', '<p>1</p>', 'blue', 1, '2026-01-01T00:00:00', '2026-01-02T00:00:00');
INSERT INTO memos (title, content, color, deleted_at, created_at, updated_at)
  VALUES ('b', '<p>2</p>', '#112233', '2026-02-01T00:00:00', '2026-01-01T00:00:00', '2026-01-03T00:00:00');
INSERT INTO memo_versions (memo_id, title, content, created_at) VALUES (1, 'a', '<p>0</p>', '2026-01-01T00:05:00');
INSERT INTO settings VALUES ('user_slots', '["#123456"]');
PRAGMA user_version = 3;
""")
old.commit()
old.close()
before = sqlite3.connect(path).execute("SELECT * FROM memos ORDER BY id").fetchall()

db = MemoDatabase(path)
memos = db.list_all() + db.list_trashed_memos()
assert len(memos) == 2 and len(db.list_versions(1)) == 1 and db.count_trashed() == 1
assert db.get_setting_str("user_slots") == '["#123456"]', "직접 만든 색이 바뀜 (종이 톤 이주가 다시 돌면 안 된다)"
uids = {m.uid for m in memos}
assert len(uids) == 2 and all(len(u) == 32 for u in uids)
after = db.conn.execute("SELECT * FROM memos ORDER BY id").fetchall()
assert [tuple(r)[:-1] for r in after] == [tuple(r) for r in before], "기존 열 값이 바뀜"
assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 4
bak = sqlite3.connect(Path(str(path) + ".bak-v3"))
assert "uid" not in {r[1] for r in bak.execute("PRAGMA table_info(memos)")}, "백업은 이주 전 상태여야 한다"
assert bak.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 2
bak.close()
assert not Path(str(path) + ".bak").exists(), "2.0.0 이주 백업 이름을 쓰면 안 된다"
new = db.create("c")
assert len(new.uid) == 32 and new.uid not in uids
db.close()

# 2.0.x로 되돌려 메모를 만들면(uid 없이 INSERT, user_version=3) 다시 올릴 때 채운다
c = sqlite3.connect(path)
c.execute("INSERT INTO memos (title, created_at, updated_at) VALUES ('d', 'x', 'x')")
c.execute("PRAGMA user_version = 3")
c.commit()
c.close()
db = MemoDatabase(path)
rows = db.conn.execute("SELECT uid FROM memos").fetchall()
assert len(rows) == 4 and all(r["uid"] for r in rows) and len({r["uid"] for r in rows}) == 4
assert db.get_setting_str("user_slots") == '["#123456"]'
try:
    db.conn.execute("UPDATE memos SET uid = ? WHERE id = 2", (rows[0]["uid"],))
    raise AssertionError("uid가 겹쳐도 저장됨")
except sqlite3.IntegrityError:
    pass
db.close()

# 새 DB는 백업 없이 처음부터 v4
fresh = MemoDatabase(tmp / "fresh.db")
assert len(fresh.create().uid) == 32 and not Path(str(tmp / "fresh.db") + ".bak-v3").exists()
fresh.close()
shutil.rmtree(tmp, ignore_errors=True)
print("sync schema OK", flush=True)
