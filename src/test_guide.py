# ponytail: minimal self-check for 말풍선 가이드(온보딩). run: python src/test_guide.py
# 한 번 본 사람에게 다시 뜨면 최악이라, 완료 플래그와 단계 진행만 못박아 둔다.
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create(title="A", content="a")
win = m.SlideMemoWindow(db)
win.show()

# ----- 1단계: 바 사용법 -----
win.start_guide("bar")
total = len(win._guide_script("bar"))
assert total == 4, total  # 한 자리에서 4개를 넘기지 않는다
assert win._guide.isVisible(), "말풍선이 안 떴다"
assert win._guide.step_lbl.text() == f"1/{total}"
# 말풍선이 떠 있는 동안엔 바가 topmost를 재점령하면 안 된다 (툴팁과 같은 이유)
assert win._zorder_locked(), "말풍선이 떴는데 z-order를 잡지 않았다"

for i in range(2, total + 1):
    win._guide.next_btn.click()
    assert win._guide.step_lbl.text() == f"{i}/{total}", win._guide.step_lbl.text()
assert win._guide.next_btn.text() == "완료"
win._guide.next_btn.click()
assert not win._guide.isVisible(), "마지막에도 말풍선이 남았다"
assert db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 1, "완료 기록이 안 남았다"
assert not win.guide_running()

# ----- 2단계: 펼치면 본문 사용법 (1단계를 끝낸 뒤에만) -----
assert db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 0
win.start_guide("body")
assert len(win._guide_steps_queue) == 4
win._guide.skip_btn.click()  # 건너뛰어도 완료 처리 = 다시 안 뜬다
assert db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 1
win.expand()
win._maybe_start_body_guide()
assert not win.guide_running(), "이미 본 가이드가 다시 떴다"

# ----- 설정에서 다시 보기 -----
win.restart_guide()
assert db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 0
assert db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 0

win.close()
win.deleteLater()
app.processEvents()
print("guide OK")
