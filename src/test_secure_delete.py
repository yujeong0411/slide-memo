# ponytail: 지운·고친 메모 내용이 DB 파일에 남지 않는지 self-check. 임시 폴더만 쓴다. run: python src/test_secure_delete.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import MemoDatabase  # noqa: E402

path = tmp / "memos.db"
db = MemoDatabase(path)
assert db.conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
keep = db.create("남길 메모", "<p>KEEP-1234</p>")
gone = db.create("지울 메모", "<p>" + "SECRET-DELETED " * 300 + "</p>")
edit = db.create("고칠 메모", "<p>" + "SECRET-OLD-TEXT " * 300 + "</p>")
db.snapshot(gone.id, force=True)              # 이전 버전에도 같은 내용 (CASCADE로 함께 지워진다)
db.soft_delete(gone.id)
db.delete(gone.id)                            # 휴지통 비우기·영구 삭제와 같은 길
db.update(edit.id, content="<p>새 내용</p>")  # 덮어쓴 옛 내용
db.close()
data = path.read_bytes()
assert b"KEEP-1234" in data, "남긴 메모는 있어야 한다 (시험이 파일을 제대로 읽는지)"
assert b"SECRET-DELETED" not in data, "지운 메모 내용이 DB 파일에 남음"
assert b"SECRET-OLD-TEXT" not in data, "고치기 전 내용이 DB 파일에 남음"
shutil.rmtree(tmp, ignore_errors=True)
print("secure delete OK", flush=True)
