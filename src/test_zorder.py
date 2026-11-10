# ponytail: minimal self-check for topmost 강제 가드. run: python src/test_zorder.py
# 툴팁/팝업이 떠 있는데 topmost를 다시 밀어 올리면 그것들이 창 뒤로 깔린다.
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import main as m
from theme.widgets import install_tooltips
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create(title="A", content="a")
win = m.SlideMemoWindow(db)
win.show()

assert not win._zorder_locked(), "평소엔 z-order를 잡아둘 이유가 없다"

tips = install_tooltips(app)
tips.show_for(win.new_tab_btn)
assert tips.tip.isVisible()
assert win._zorder_locked(), "툴팁이 떠 있는데 창을 앞으로 올리면 툴팁이 가려진다"
# 툴팁 중 hover(Enter)로도 raise_()를 타면 안 된다 → eventFilter가 즉시 손 뗌
assert win.eventFilter(win.new_tab_btn, QEvent(QEvent.Type.Enter)) is False

tips.hide_tip()
app.processEvents()  # 툴팁 숨김은 다음 이벤트 루프에서 반영된다
assert not win._zorder_locked(), "툴팁이 사라졌으면 다시 topmost를 지켜야 한다"

print("zorder OK", flush=True)
os._exit(0)  # 인터프리터 종료 중의 Qt 정리 순서에 결과가 흔들리지 않게 한다
