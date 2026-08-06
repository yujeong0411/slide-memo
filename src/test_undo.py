# ponytail: minimal self-check for per-memo undo stacks. run: python src/test_undo.py
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
a = db.create(title="A", content="메모A 원본")
b = db.create(title="B", content="메모B 원본")
win = m.SlideMemoWindow(db)

# 메모A에서 타이핑 → 다른 메모 갔다 복귀 → Ctrl+Z가 살아있어야 한다 (이 작업의 목적)
win._load_memo(a)
win.editor.insertPlainText("실수로 추가한 글")
assert "실수로 추가한 글" in win.editor.toPlainText()
win._load_memo(b)
win._load_memo(a)
assert win.editor.document().isUndoAvailable(), "전환 후 복귀했는데 undo 스택이 없다"
win.editor.undo()
assert "실수로 추가한 글" not in win.editor.toPlainText()

# 메모를 처음 열었을 때는 되돌릴 게 없어야 한다 (내용 주입이 undo 대상이 되면 안 됨)
c = db.create(content="메모C 원본")
win._load_memo(c)
assert not win.editor.document().isUndoAvailable()

# 휴지통 미리보기는 임시 문서를 써야 한다 — 캐시된 메모 문서를 덮으면 안 됨
win._load_memo(a)
win.editor.insertPlainText("살아남아야 할 편집")
doc_a = win.editor.document()
db.soft_delete(b.id)
win._preview_trashed(b.id)
assert win.editor.document() is win._scratch_doc, "미리보기가 메모 문서를 붙잡고 있다"
assert "살아남아야 할 편집" in doc_a.toPlainText(), "미리보기가 메모A 문서를 덮었다"

# _clear_editor도 마찬가지 (editor.clear()였다면 메모A 내용이 날아간다)
win._clear_editor()
assert "살아남아야 할 편집" in doc_a.toPlainText()

# LRU: 현재 붙어 있는 문서는 절대 evict되지 않는다 (되면 크래시/내용 소실)
memos = [db.create(content=f"m{i}") for i in range(m.UNDO_CACHE_SIZE + 5)]
for memo in memos:
    win._load_memo(memo)
    assert len(win._doc_cache) <= m.UNDO_CACHE_SIZE, len(win._doc_cache)
    assert win._doc_cache[memo.id] is win.editor.document()

# 버전 복원 후에는 낡은 캐시 문서가 다시 붙으면 안 된다
target = memos[-1]
win._load_memo(target)
db.snapshot(target.id, force=True)
db.update(target.id, content="덮어쓴 내용")
win._forget_doc(target.id)
win._load_memo(db.get(target.id))
assert "덮어쓴 내용" in win.editor.toPlainText(), win.editor.toPlainText()

db.close()
print("undo OK")
