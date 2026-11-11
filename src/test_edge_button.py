# ponytail: 숨겼을 때 남는 로고 단추 self-check. run: python src/test_edge_button.py
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import database

database.APP_DIR = Path(tempfile.mkdtemp())
import edge_button as E
import main as m
from database import MemoDatabase
from theme import apply as A

assert E.covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080))
assert not E.covers_monitor((0, 0, 1920, 1040), (0, 0, 1920, 1080)), "최대화는 전체 화면이 아니다"

app = QApplication([])
A.apply_theme(app, "light")
button = E.EdgeLogoButton()
assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
area = QRect(0, 0, 800, 600)
for side in ("right", "left"):
    button.place(area, side, 100)
    assert button.face_top() == 100
    face = button._face().translated(button.pos())
    assert (face.right() == 799) if side == "right" else (face.left() == 0), "가장자리에 붙는다"
button.place(area, "right", 100)
button.show()
clicks, moves = [], []
button.clicked.connect(lambda: clicks.append(1))
button.moved.connect(moves.append)
center = button._face().center()
QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=center)
assert clicks == [1] and moves == [], "누르면 clicked"

QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=center)
QTest.mouseMove(button, center + QPoint(0, 50))
app.processEvents()
top_after_drag = button.face_top()
QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=center + QPoint(0, 50))
assert clicks == [1], "끄는 중에는 누름이 아니다"
assert moves == [top_after_drag] and top_after_drag != 100, (moves, top_after_drag)

# 메인 창과 연결
E.is_foreign_fullscreen = lambda _hwnd: False
m.is_foreign_fullscreen = E.is_foreign_fullscreen
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create("메모", "", "blue")
win = m.SlideMemoWindow(db)
win.show()
app.processEvents()
win.hide_bar()
assert win._edge_button.isVisible() and not win.isVisible()
m.is_foreign_fullscreen = lambda _hwnd: True
win._sync_edge_button()
assert not win._edge_button.isVisible(), "다른 앱이 전체 화면이면 숨긴다"
m.is_foreign_fullscreen = lambda _hwnd: False
win._sync_edge_button()
assert win._edge_button.isVisible()
win._edge_button.moved.emit(222)
assert db.get_setting_int(m.EDGE_BUTTON_Y_KEY, -1) == 222
win._edge_button.clicked.emit()
assert win.isVisible() and not win._edge_button.isVisible(), "누르면 바가 돌아온다"
assert not win._edge_timer.isActive()
print("edge button OK", flush=True)
os._exit(0)
