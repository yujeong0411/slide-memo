# ponytail: 앱을 켤 때 차이 맞추기(reconcile)가 1초 안에 끝나는지 self-check. 임시 폴더만 쓴다.
# 메모 1,000개 중 100개는 본문 5만 자 이상. run: python src/test_sync_speed.py
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import MemoDatabase  # noqa: E402
from sync.store import SyncStore  # noqa: E402

path = tmp / "memos.db"
MemoDatabase(path).close()
raw = sqlite3.connect(path)
big = "<p>" + "가나다라마바사아자차 " * 5500 + "</p>"  # 약 6만 자
assert len(big) >= 50_000
raw.executemany(
    "INSERT INTO memos (title, content, color, created_at, updated_at) VALUES (?, ?, 'paper', ?, ?)",
    [(f"메모 {i}", big if i % 10 == 0 else f"<p>짧은 본문 {i}</p>" * 20, "2026-11-01T09:00:00", "2026-11-01T09:00:00")
     for i in range(1000)],
)
raw.commit()
raw.close()


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


db = MemoDatabase(path)  # uid 채우기
store = SyncStore(db.conn)
store.connect("me@example.com")
first, t_first = timed(store.reconcile)
assert len({o.uid for o in first}) == 1000
db.close()

# 앱을 켤 때: DB 열기 + 차이 맞추기 (변경 없음)
(db, t_open) = timed(lambda: MemoDatabase(path))
store = SyncStore(db.conn)
none, t_none = timed(store.reconcile)
assert none == []

# 10개만 바뀌었을 때 (그중 큰 메모 5개)
ids = [r[0] for r in db.conn.execute("SELECT id FROM memos ORDER BY id LIMIT 100")]
for memo_id in ids[0:50:10] + ids[1:6]:
    db.update(memo_id, content=db.get(memo_id).content + "<p>추가</p>")
ten, t_ten = timed(store.reconcile)
assert len(ten) == 10, len(ten)

print(f"처음 연결(1,000개 전부 기록): {t_first * 1000:.0f} ms")
print(f"DB 열기: {t_open * 1000:.0f} ms | 비교(변경 없음): {t_none * 1000:.0f} ms | 비교(10개 바뀜): {t_ten * 1000:.0f} ms")
assert t_none < 1.0 and t_ten < 1.0, "앱을 켤 때 비교가 1초를 넘는다"
db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("sync speed OK", flush=True)
