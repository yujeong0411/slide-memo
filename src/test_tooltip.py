# ponytail: 툴팁 self-check. run: python src/test_tooltip.py
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import QApplication, QPushButton

import main as m
from database import MemoDatabase
from theme import apply as A
from theme import widgets as W

app = QApplication([])
A.apply_theme(app, "light")
tips = W.install_tooltips(app)
tip = tips.tip


def hover(widget) -> None:
    app.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), widget.mapToGlobal(QPoint(1, 1))))


button = QPushButton("x")
button.setToolTip("새 메모")
button.show()
hover(button)
assert tip.isVisible() and tip.label.text() == "새 메모"
app.sendEvent(button, QEvent(QEvent.Type.Leave))
assert not tip.isVisible(), "벗어나면 바로 사라진다"

db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
long_memo = db.create("아주 긴 제목 " * 20, "", "blue")
short_memo = db.create("짧음", "", "blue")
win = m.SlideMemoWindow(db)
win.show()
app.processEvents()

short = m.MemoTabButton(short_memo, win)
short.resize(40, 112)
short.show()
hover(short)
assert not tip.isVisible(), "다 보이는 제목은 띄우지 않는다"

for side, beside_left in (("right", True), ("left", False)):
    m.MemoTabButton.side = side
    tab = m.MemoTabButton(long_memo, win)
    tab.move(300 if beside_left else 10, 200)
    tab.resize(40, 112)
    tab.show()
    hover(tab)
    assert tip.isVisible() and tip.label.text() == long_memo.title.strip()
    mar = W._FLOAT_MARGINS
    rect = tab.mapToGlobal(QPoint(0, 0))
    face_left = tip.x() + mar.left()
    face_right = tip.x() + tip.width() - mar.right()
    if beside_left:
        assert face_right == rect.x() - 8, (face_right, rect.x())
    else:
        assert face_left == rect.x() + 40 + 8, (face_left, rect.x())
    tips.hide_tip()
m.MemoTabButton.side = "right"

# 배지: 아이콘 아래 2/3를 가리지 않는다
db.soft_delete(short_memo.id)
win._update_trash_btn()
badge, btn = win._trash_badge, win.trash_btn
icon_top = btn.geometry().center().y() - m.BAR_ICON // 2
assert badge.geometry().bottom() + 1 <= icon_top + m.BAR_ICON // 3
print("tooltip OK", flush=True)
os._exit(0)
