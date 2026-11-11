# ponytail: 가이드를 두 번 연달아 돌려도 말풍선은 늘 하나인지 self-check. run: python src/test_guide_once.py
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import database

database.APP_DIR = Path(tempfile.mkdtemp())
import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create("메모", "<p>본문</p>", "blue")
win = m.SlideMemoWindow(db)
win._force_topmost = lambda: None
win.show()
starts = []
_start = win.start_guide
win.start_guide = lambda which="bar": (starts.append(which), _start(which))


def bubbles() -> int:
    return sum(isinstance(w, m.GuideBubble) and w.isVisible() for w in QApplication.topLevelWidgets())


def walk(which: str) -> None:
    assert win.guide_running() and win._guide_which == which and win._guide_index == 0
    total = len(win._guide_steps_queue)
    for step in range(total):
        assert bubbles() == 1, (which, step, bubbles())
        assert win._guide_index == step, "중간에 처음으로 되돌아갔다"
        win._guide.next_btn.click()
        QTest.qWait(30)
        assert bubbles() <= 1
    QTest.qWait(700)  # 늦게 도착한 예약이 다시 시작하지 않는지
    assert bubbles() == 0 and not win.guide_running(), (which, bubbles())


for round_no in (1, 2):
    starts.clear()
    win.collapse()
    win.restart_guide()
    win.restart_guide()  # 두 번 눌러도 한 번만 시작
    QTest.qWait(300)
    walk("bar")
    win.expand()
    win._maybe_start_body_guide()
    win._maybe_start_body_guide()
    QTest.qWait(700)
    walk("body")
    assert starts == ["bar", "body"], (round_no, starts)

print("guide once OK", flush=True)
os._exit(0)
