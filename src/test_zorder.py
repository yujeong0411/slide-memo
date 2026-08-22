# ponytail: minimal self-check for topmost 강제 가드. run: python src/test_zorder.py
# 툴팁/팝업이 떠 있는데 topmost를 다시 밀어 올리면 그것들이 창 뒤로 깔린다.
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtWidgets import QApplication, QToolTip

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create(title="A", content="a")
win = m.SlideMemoWindow(db)
win.show()

assert not win._zorder_locked(), "평소엔 z-order를 잡아둘 이유가 없다"

QToolTip.showText(QPoint(10, 10), "설정")
assert QToolTip.isVisible()
assert win._zorder_locked(), "툴팁이 떠 있는데 창을 앞으로 올리면 툴팁이 가려진다"
# 툴팁 중 hover(Enter)로도 raise_()를 타면 안 된다 → eventFilter가 즉시 손 뗌
assert win.eventFilter(win.settings_btn, QEvent(QEvent.Type.Enter)) is False

QToolTip.hideText()
app.processEvents()  # 툴팁 숨김은 다음 이벤트 루프에서 반영된다
assert not win._zorder_locked(), "툴팁이 사라졌으면 다시 topmost를 지켜야 한다"

print("zorder OK")
