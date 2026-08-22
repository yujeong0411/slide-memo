# ponytail: minimal self-check for 새 메모 폰트/스크롤/Delete 키.
# run: python src/test_newmemo.py
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.set_setting_str("app_font_family", "Consolas")
db.set_setting_int("app_font_size", 14)
for i in range(15):
    db.create(title=f"x{i}", content="x")

win = m.SlideMemoWindow(db)
win.show()
app.processEvents()

# ----- 새 메모 폰트 -----
# editor.setFont()는 위젯 폰트만 바꾼다. 따로 만든 QTextDocument의 defaultFont까지
# 챙기지 않으면 서식 없는 새 메모가 앱 기본 폰트(더 작고 다른 글꼴)로 찍힌다.
win.create_new_memo()
doc_font = win.editor.document().defaultFont()
assert doc_font.family() == "Consolas", doc_font.family()
assert doc_font.pointSize() == 14, doc_font.pointSize()
typed = win.editor.textCursor().charFormat().font()
assert (typed.family(), typed.pointSize()) == ("Consolas", 14), typed.family()

# ----- 새 메모 탭이 보이도록 스크롤 -----
win.sort_combo.setCurrentIndex(1)  # 수정일 ↑ → 새 메모가 목록 맨 아래
app.processEvents()
sb = win.tab_scroll.verticalScrollBar()
sb.setValue(0)
win.create_new_memo()
# 스크롤 범위는 탭이 만들어진 다음 레이아웃 패스에서야 갱신된다 (실제 앱의
# 이벤트 루프에 해당) → 그 뒤에 예약된 스크롤이 실행된다
for _ in range(5):
    app.processEvents()
assert sb.maximum() > 0, "탭이 넘치지 않아 스크롤 검증이 무의미하다"
assert sb.value() == sb.maximum(), (sb.value(), sb.maximum())

# ----- Delete 키 -----
def press_delete():
    win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))

before = db.count_trashed()
win.editor.setFocus()
app.processEvents()
press_delete()  # 본문 편집 중엔 메모가 지워지면 안 된다
assert db.count_trashed() == before, "본문 포커스인데 Delete가 메모를 지웠다"

win.tab_scroll.setFocus()  # 본문 밖 (탭 클릭 직후와 같은 상태)
app.processEvents()
press_delete()
assert db.count_trashed() == before + 1, "본문 밖 Delete가 메모를 안 지웠다"

print("newmemo OK")
