# ponytail: minimal self-check for 말풍선 가이드(온보딩). run: python src/test_guide.py
# 한 번 본 사람에게 다시 뜨면 최악이라, 완료 플래그와 단계 진행만 못박아 둔다.
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication


def settle(ms: int = 350) -> None:
    """예약된 가이드 시작 타이머가 실제로 돌게 둔다 (창을 먼저 닫으면 죽는다)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

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

# ----- 신규 설치: 먼저 물어보고 시작 -----
# 예고 없이 튜토리얼이 시작되면 첫 인상이 나쁘다 → 팝업으로 묻는다.
from PyQt6.QtWidgets import QMessageBox


def _answer(label):
    """모달 대신 지정한 버튼을 눌러준다."""
    def fake_exec(self):
        for b in self.buttons():
            if b.text().replace("&", "") == label:
                b.click()
                return 0
        raise AssertionError(f"버튼 없음: {label}")
    QMessageBox.exec = fake_exec


fresh_db = MemoDatabase(Path(tempfile.mkdtemp()) / "new.db")
fresh_win = m.SlideMemoWindow(fresh_db)
_answer("가이드 보기")
m._show_welcome(fresh_win, fresh_db)
assert fresh_win.guide_running(), "가이드 보기를 눌렀는데 시작되지 않았다"
assert fresh_db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 0, "아직 끝나지도 않았는데 완료 처리됐다"
fresh_win._finish_guide()

later_db = MemoDatabase(Path(tempfile.mkdtemp()) / "later.db")
later_win = m.SlideMemoWindow(later_db)
_answer("나중에")
m._show_welcome(later_win, later_db)
assert not later_win.guide_running(), "나중에를 눌렀는데 가이드가 시작됐다"
assert later_db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 1, "거절했는데 다음 실행에 또 뜬다"
assert later_db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 1
fresh_win.close(); later_win.close()

# ----- 업데이트 팝업에서 바로 가이드 보기 -----
# 기존 사용자는 가이드가 생긴 것 자체를 모르므로, '새로운 기능' 팝업이 입구가 된다.
up_db = MemoDatabase(Path(tempfile.mkdtemp()) / "up.db")
up_db.set_setting_str(m.WHATS_NEW_KEY, "1.3.0")  # v1.3.0까지 본 사용자
up_db.set_setting_int(m.GUIDE_BAR_KEY, 1)        # 업그레이드라 가이드는 건너뛴 상태
up_db.set_setting_int(m.GUIDE_BODY_KEY, 1)
up_db.create(title="쓰던 메모")
up_win = m.SlideMemoWindow(up_db)
_answer("사용법 가이드 보기")
m._show_whats_new(up_win, up_db, True)
assert up_db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 0, "가이드를 보겠다는데 완료 상태 그대로다"
assert up_db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 0, "2단계도 이어져야 한다"
assert up_db.get_setting_str(m.WHATS_NEW_KEY, "") == m.APP_VERSION, "안내 기록은 남아야 한다"
settle()  # 예약된 시작이 실제로 도는지까지 확인
assert up_win.guide_running(), "팝업에서 눌렀는데 가이드가 시작되지 않았다"
up_win._finish_guide()
up_win.close()

# ----- 설정에서 다시 보기 -----
win.restart_guide()
assert db.get_setting_int(m.GUIDE_BAR_KEY, 0) == 0
assert db.get_setting_int(m.GUIDE_BODY_KEY, 0) == 0
settle()
assert win.guide_running(), "설정에서 다시 보기를 눌렀는데 시작되지 않았다"
win._finish_guide()

win.close()
win.deleteLater()
app.processEvents()
print("guide OK")
