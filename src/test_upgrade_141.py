# ponytail: 1.4.1에서 바로 2.1.0으로 올리는 경우 self-check. 태그 v1.4.1의 database.py로 실제 1.4.1 DB를
# 만들고(그라데이션 색 포함) 지금 코드로 연다. 임시 폴더만 쓴다. run: python src/test_upgrade_141.py
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
tmp = Path(tempfile.mkdtemp())

# 1.4.1의 database.py (그 버전 그대로)
src_141 = subprocess.run(["git", "show", "v1.4.1:src/database.py"], cwd=here, capture_output=True,
                         text=True, encoding="utf-8").stdout
assert "grad:" in src_141, "v1.4.1 코드를 읽지 못함"
(tmp / "database_141.py").write_text(src_141, encoding="utf-8")
spec = importlib.util.spec_from_file_location("database_141", tmp / "database_141.py")
old = importlib.util.module_from_spec(spec)
sys.modules["database_141"] = old
spec.loader.exec_module(old)
old.APP_DIR, old.IMAGES_DIR = tmp, tmp / "images"

path = tmp / "memos.db"
d = old.MemoDatabase(path)
plan = [
    ("예전 프리셋", "<p>sunrise</p>", "sunrise"),
    ("또 다른 프리셋", "<p>lavender</p>", "lavender"),
    ("직접 고른 단색", "<p>hex</p>", "#3366CC"),
    ("그라데이션 두 색", "<p>grad 2</p>", "grad:#FF0000,#0000FF"),
    ("그라데이션 한 색", "<p>grad 1</p>", "grad:#00AA00"),
    ("고정한 메모", "<p>pinned</p>", "mint"),
    ("휴지통 메모", "<p>trash</p>", "peach"),
]
ids = {}
for title, content, color in plan:
    ids[title] = d.create(title, content, color).id
d.snapshot(ids["예전 프리셋"], force=True)
d.update(ids["예전 프리셋"], content="<p>sunrise 고침</p>")
d.snapshot(ids["그라데이션 두 색"], force=True)
d.update(ids["그라데이션 두 색"], content="<p>grad 2 고침</p>")
d.set_pinned(ids["고정한 메모"], True)
d.soft_delete(ids["휴지통 메모"])
d.set_setting_str("user_slots", "#123456|grad:#FF0000,#00FF00|#ABCDEF|grad:#336699")
d.close()

raw = sqlite3.connect(path)
assert raw.execute("PRAGMA user_version").fetchone()[0] == 2, "1.4.1 DB 형식"
before = {r[0]: r[1:] for r in raw.execute("SELECT id, title, content, color, is_pinned, deleted_at FROM memos")}
versions_before = sorted(raw.execute("SELECT memo_id, title, content FROM memo_versions").fetchall())
raw.close()

# ----- 지금 코드로 연다 (1.4.1 → 2.1.0) -----
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import PAPER_NOTICE_KEY, MemoDatabase, paper_color  # noqa: E402
from theme import tokens as T  # noqa: E402

db = MemoDatabase(path)
rows = {r["id"]: r for r in db.conn.execute("SELECT * FROM memos")}
assert set(rows) == set(before), "메모 수가 같다"
for memo_id, (title, content, color, pinned, deleted_at) in before.items():
    r = rows[memo_id]
    assert (r["title"], r["content"]) == (title, content), title
    assert bool(r["is_pinned"]) == bool(pinned) and (r["deleted_at"] is None) == (deleted_at is None), title
    assert r["color"] == paper_color(color), (title, color, r["color"])
    assert r["color"] in T.MEMO_PRESETS or r["color"].startswith("#"), (title, r["color"])
    assert r["color_before_v2"] == (color if paper_color(color) != color else None), "바뀐 색만 옛 색을 color_before_v2에 남긴다"
    assert r["uid"] and len(r["uid"]) == 32, "동기화용 ID"
assert not any(str(r["color"]).startswith("grad:") for r in rows.values()), "그라데이션은 남지 않는다"
assert sorted(tuple(r) for r in db.conn.execute("SELECT memo_id, title, content FROM memo_versions")) == versions_before, "이전 버전 그대로"
slots = db.get_setting_str("user_slots")
assert "grad:" not in slots and "#123456" in slots and "#ABCDEF" in slots, slots
assert db.get_setting_int(PAPER_NOTICE_KEY, 0) == 1, "색을 옮겼다는 안내를 한 번 띄운다"
assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 4
db.close()

# 백업: .bak은 1.4.1 그대로, .bak-v3는 색을 옮긴 뒤·uid 전
bak = sqlite3.connect(Path(str(path) + ".bak"))
assert {r[0]: r[1:] for r in bak.execute("SELECT id, title, content, color, is_pinned, deleted_at FROM memos")} == before
assert bak.execute("PRAGMA user_version").fetchone()[0] == 2
bak.close()
assert Path(str(path) + ".bak-v3").exists()

# 다시 열어도 그대로 (이주가 두 번 돌지 않는다)
db = MemoDatabase(path)
again = {r["id"]: (r["color"], r["color_before_v2"], r["uid"]) for r in db.conn.execute("SELECT * FROM memos")}
assert again == {i: (r["color"], r["color_before_v2"], r["uid"]) for i, r in rows.items()}
db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("upgrade 1.4.1 OK", flush=True)
