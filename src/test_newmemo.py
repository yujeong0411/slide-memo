# ponytail: minimal self-check for 새 메모 폰트/스크롤/Delete 키.
# run: python src/test_newmemo.py
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
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
# 고정 메모가 위를 차지하면 새 메모 탭은 목록 중간에 생긴다. 위젯 좌표로 스크롤하면
# 탭이 아직 레이아웃 전(전부 y=0)이라 맨 위로 튀고, 정작 새 탭은 화면 밖에 남는다.
for mid in [mm.id for mm in db.list_all()][:8]:
    db.set_pinned(mid, True)
win._refresh_memo_tabs()
app.processEvents()
sb = win.tab_scroll.verticalScrollBar()
sb.setValue(sb.maximum())
app.processEvents()
assert sb.maximum() > 0, "탭이 넘치지 않아 스크롤 검증이 무의미하다"

win.create_new_memo()
loop = QEventLoop()  # 스크롤 범위 갱신은 다음 레이아웃 패스에서 온다
QTimer.singleShot(200, loop.quit)
loop.exec()

idx = [i for i in range(win.tabs_layout.count())
       if win.tabs_layout.itemAt(i).widget().memo_id == win.current_memo.id][0]
btn = win.tabs_layout.itemAt(idx).widget()
vp = win.tab_scroll.viewport()
top = btn.mapTo(vp, QPoint(0, 0)).y()
assert idx > 0, "고정 메모 아래에 생겨야 검증이 의미 있다"
assert 0 <= top and top + btn.height() <= vp.height(), (idx, top, vp.height())

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

# 위젯을 파이썬이 먼저 놓아버리면 Qt 종료 중에 죽는다 (offscreen에서 재현) →
# 창을 먼저 정리하고 끝낸다.
del btn, vp
win.close()
win.deleteLater()
app.processEvents()

print("newmemo OK")
