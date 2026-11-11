# ponytail: 변경 기록을 놓치지 않는지(처음 연결, 다시 연결, 2.0.x 되돌림, 중간 실패) self-check.
# 임시 폴더만 쓴다. run: python src/test_sync_store.py
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
from sync.core import materialize  # noqa: E402
from sync.store import SyncStore  # noqa: E402

T0 = 1_762_000_000_000


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        self.ms += 1
        return self.ms


def fields(ops):
    return sorted((o.uid, o.f) for o in ops)


def check_matches_db(db, store):
    """head로 계산한 모습이 DB의 메모와 같아야 한다 (빠진 기록이 없다)."""
    heads = store.heads()
    rows = db.conn.execute("SELECT * FROM memos").fetchall()
    for r in rows:
        st = materialize(r["uid"], heads[r["uid"]], T0)
        assert (st.title, st.content, st.color or database.DEFAULT_COLOR, st.pinned, st.font_family, st.font_size) == (
            r["title"], r["content"], r["color"], bool(r["is_pinned"]), r["font_family"], r["font_size"]
        ), r["title"]
        assert (st.trashed_at is not None) == (r["deleted_at"] is not None), r["title"]
    alive = {u for u, h in heads.items() if not u.startswith("settings:") and materialize(u, h, T0)}
    assert alive == {r["uid"] for r in rows}, "기록엔 있는데 DB에 없는(또는 반대) 메모"


path = tmp / "memos.db"
db = MemoDatabase(path)
store = SyncStore(db.conn, Clock(T0))

# 연결 전에는 아무것도 기록하지 않는다
a = db.create("장보기", "<p>우유</p>", "blue")
b = db.create("버릴 메모")
db.soft_delete(b.id)
c = db.create("고정")
db.set_pinned(c.id, True)
db.update(c.id, font_family="Pretendard", font_size=14)
db.set_setting_str("user_slots", '["#123456"]')
assert store.reconcile() == [] and store.pending() == []

# ----- 1. 처음 연결: 그 전에 있던 메모 전체(휴지통 포함)와 직접 만든 색을 한 번 올린다 -----
store.connect("me@example.com")
first = store.reconcile()
assert {o.uid for o in first} == {a.uid, b.uid, c.uid, "settings:user_slots"}
for m in (a, b, c):
    got = {o.f for o in first if o.uid == m.uid}
    assert {"created", "body"} <= got, (m.title, got)
assert "color" in {o.f for o in first if o.uid == a.uid} and "color" not in {o.f for o in first if o.uid == b.uid}, "기본 색이면 색 기록이 없다"
assert ("trash" in {o.f for o in first if o.uid == b.uid}) and ("pin" in {o.f for o in first if o.uid == c.uid})
assert all(o.base is None for o in first), "처음 올리는 기록은 이전 기록이 없다"
check_matches_db(db, store)
assert store.reconcile() == [], "바뀐 게 없으면 기록도 없다"
assert len(store.pending()) == len(first)

# 앱에서 고치면 다음 reconcile에 정확히 그 필드만, 직전 기록을 base로
before = store.heads()
db.update(a.id, content="<p>우유 빵</p>")
db.set_pinned(a.id, True)
db.restore(b.id)
d = db.create("새 메모")
db.delete(c.id)
ops = store.reconcile()
assert fields(ops) == sorted([
    (a.uid, "body"), (a.uid, "pin"), (b.uid, "trash"),
    (d.uid, "created"), (d.uid, "body"), (c.uid, "purge"),
]), fields(ops)
for o in ops:
    prev = before.get(o.uid, {}).get(o.f)
    assert o.base == (prev.id if prev else None), o
check_matches_db(db, store)

# ----- 2. 끊었다가 다시 연결: 끊긴 동안 고친 것만 -----
store.disconnect()
db.update(a.id, title="장보기(끊긴 동안)")
e = db.create("끊긴 동안 만든 메모")
db.soft_delete(d.id)
assert store.reconcile() == [], "끊겨 있을 때는 기록하지 않는다"
store.connect("me@example.com")
ops = store.reconcile()
assert fields(ops) == sorted([(a.uid, "body"), (d.uid, "trash"), (e.uid, "created"), (e.uid, "body")])
check_matches_db(db, store)

# 다른 계정으로 연결하면 그 계정 Drive에는 아무것도 없으니 전부 새로 올린다
store.connect("other@example.com")
ops = store.reconcile()
assert {o.uid for o in ops} == {a.uid, b.uid, d.uid, e.uid, "settings:user_slots"} and all(o.base is None for o in ops)
check_matches_db(db, store)
store.connect("me@example.com")
store.reconcile()

# ----- 3. 2.0.x로 되돌렸다가 다시 올림: 2.0.x는 기록을 모른다 -----
db.close()
raw = sqlite3.connect(path)  # 2.0.x가 하는 일과 같은 SQL
raw.execute("UPDATE memos SET content = '<p>2.0에서 고침</p>', updated_at = 'x' WHERE id = ?", (a.id,))
raw.execute("UPDATE memos SET deleted_at = '2026-11-01T09:00:00' WHERE id = ?", (e.id,))
raw.execute("UPDATE memos SET is_pinned = 0 WHERE id = ?", (a.id,))
raw.execute("DELETE FROM memos WHERE id = ?", (b.id,))
raw.execute("INSERT INTO memos (title, content, color, created_at, updated_at) VALUES ('2.0 메모', '', 'paper', '2026-11-01T08:00:00', 'x')")
raw.execute("UPDATE settings SET value = '[\"#654321\"]' WHERE key = 'user_slots'")
raw.execute("PRAGMA user_version = 3")
raw.commit()
raw.close()
db = MemoDatabase(path)  # uid를 채운다 (1단계)
store = SyncStore(db.conn, Clock(T0 + 10_000))
new_uid = db.conn.execute("SELECT uid FROM memos WHERE title = '2.0 메모'").fetchone()[0]
ops = store.reconcile()
assert fields(ops) == sorted([
    (a.uid, "body"), (a.uid, "pin"), (e.uid, "trash"), (b.uid, "purge"),
    (new_uid, "created"), (new_uid, "body"), (new_uid, "color"), ("settings:user_slots", "value"),
]), fields(ops)
trash_op = next(o for o in ops if o.uid == e.uid)
assert trash_op.v["at"] == int(__import__("datetime").datetime.fromisoformat("2026-11-01T09:00:00").timestamp() * 1000)
check_matches_db(db, store)

# 기록 번호와 시계는 앱을 다시 켜도 이어진다
seqs = [o.seq for o in store.pending()]
assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
hlcs = [o.hlc for o in store.pending()]
assert hlcs == sorted(hlcs), "기록 시계가 뒤로 감"

# ----- 중간에 실패하면 아무것도 남지 않고, 다음에 다시 잡힌다 -----
db.update(a.id, content="<p>실패 시험</p>")
db.set_pinned(a.id, True)
heads_before = store.heads()
pending_before = len(store.pending())
real_record, calls = store._record, []


def boom(op):
    calls.append(op)
    if len(calls) == 2:
        raise RuntimeError("시험: 기록 중 꺼짐")
    real_record(op)


store._record = boom
try:
    store.reconcile()
    raise AssertionError("실패해야 함")
except RuntimeError:
    pass
store._record = real_record
assert store.heads() == heads_before and len(store.pending()) == pending_before, "반쯤 기록됨"
ops = store.reconcile()
assert fields(ops) == sorted([(a.uid, "body"), (a.uid, "pin")])
check_matches_db(db, store)

# 기록한 op는 Drive를 거쳐도 그대로 읽힌다 (모양 검사 통과)
from sync.core import Op  # noqa: E402

for o in store.pending():
    assert Op.from_json(o.to_json()) == o
db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("sync store OK", flush=True)
