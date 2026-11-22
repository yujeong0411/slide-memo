# ponytail: 녹음 파일은 본문(휴지통 포함)·이전 버전 어디에도 [🎤 …] 표시가 없을 때만 지워지는지 self-check.
# 임시 폴더와 임시 DB만 쓴다. run: python src/test_audio_purge.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from PyQt6.QtGui import QTextDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import memo_document  # noqa: E402
from database import MemoDatabase  # noqa: E402

app = QApplication.instance() or QApplication([])
db = MemoDatabase(tmp / "memos.db")
audio = tmp / "audio"
audio.mkdir()


def body(name: str) -> str:
    """앱과 같은 길: setPlainText → 저장용 HTML (main._on_whisper_finished)."""
    doc = QTextDocument()
    doc.setPlainText(f"변환된 글\n\n[🎤 {name}]")
    return memo_document.saved_html(doc)


def rec(name: str) -> Path:
    p = audio / name
    p.write_bytes(b"RIFF")
    return p


a, b, c = (rec(f"recording_2026112{i}_101010.wav") for i in range(3))
other = rec("recording_note.wav")  # 앱이 만든 이름이 아니면 건드리지 않는다

ma = db.create("A", body(a.name))
mb = db.create("B", body(b.name))
mc = db.create("C", body(a.name))  # A의 표시를 복사해 둔 메모

# 1) 본문에 있으면 남는다. 휴지통에 넣어도 남는다 (복원용)
db.soft_delete(ma.id)
assert db.remove_unused_recordings() == [c.name], "표시가 없는 녹음만 지워져야 한다"
assert a.exists() and b.exists() and not c.exists() and other.exists()

# 2) 영구 삭제해도 다른 메모(C)에 같은 표시가 있으면 남는다
db.delete(ma.id)
db.remove_unused_recordings()
assert a.exists()
db.delete(mc.id)
db.remove_unused_recordings()
assert not a.exists(), "어디에도 표시가 없으면 지워져야 한다"

# 3) 표시를 직접 지워도 이전 버전에 남아 있는 동안은 남는다
db.snapshot(mb.id, force=True)
db.update(mb.id, content="<p>표시를 지움</p>")
db.remove_unused_recordings()
assert b.exists(), "이전 버전에 표시가 있으면 남아야 한다"
db.conn.execute("DELETE FROM memo_versions WHERE memo_id = ?", (mb.id,))  # 이전 버전 정리
db.conn.commit()
db.remove_unused_recordings()
assert not b.exists(), "이전 버전이 정리되면 지워져야 한다"
assert other.exists()

db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("test_audio_purge OK")
