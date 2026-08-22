# ponytail: minimal self-check for 잠깐 숨기기(트레이 복귀). run: python src/test_hide.py
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase


class TrayStub:
    """offscreen에서는 진짜 QSystemTrayIcon.isVisible()이 신뢰 불가 → 기록만 한다."""
    visible = None
    messages = 0

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def icon(self):
        return None

    def showMessage(self, *args):  # noqa: N802
        self.messages += 1


app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
db.create(title="A", content="a")
win = m.SlideMemoWindow(db)
win._tray = TrayStub()
win.show()
assert win.isVisible()

# 접힌 채 숨김 → 복귀해도 접힌 상태(mask) 그대로
win.hide_bar()
assert not win.isVisible(), "hide_bar 후에도 창이 보인다"
assert win._tray.visible is True, "숨김 동안 트레이가 안 켜졌다"
win.show_bar()
assert win.isVisible()
assert not win.is_expanded and not win.mask().isEmpty(), "복귀 후 접힘 상태가 풀렸다"
assert win._tray.visible is True, "tray 모드에서는 복귀 후에도 트레이가 켜져 있어야 한다"

# taskbar 모드: 숨김 동안만 임시로 트레이가 켜졌다가 복귀하면 다시 꺼진다
win.display_mode = "taskbar"
win.hide_bar()
assert win._tray.visible is True, "taskbar 모드 숨김 중엔 트레이가 켜져야 복귀 경로가 생긴다"
win.show_bar()
assert win.isVisible()
assert win._tray.visible is False, "taskbar 모드 복귀 후 임시 트레이가 안 꺼졌다"

# 숨김 상태에서 expand() 경로(트레이 '열기 / 접기', 새 메모 등)로도 복귀된다
win.hide_bar()
win.expand()
assert win.isVisible() and win.is_expanded, "expand()가 숨김 상태를 못 풀었다"
assert win._tray.visible is False, "expand() 복귀가 임시 트레이를 안 껐다"

# 숨기기 버튼 → hide_bar와 같은 경로, 화살표는 가장자리(side) 방향
win.hide_btn.click()
assert not win.isVisible(), "숨기기 버튼이 hide_bar를 안 탔다"
win.show_bar()
assert win.hide_btn.text() == ("»" if win.side == "right" else "«")

# 복귀 방법 안내는 숨길 때마다 (no-op인 중복 hide_bar에는 안 뜬다)
_msg_db = MemoDatabase(Path(tempfile.mkdtemp()) / "hint.db")
_msg_win = m.SlideMemoWindow(_msg_db)
_msg_win._tray = TrayStub()
for _i in range(3):
    _msg_win.show()
    _msg_win.hide_bar()
    _msg_win.hide_bar()  # 이미 숨김 → 알림도 없어야
assert _msg_win._tray.messages == 3, _msg_win._tray.messages

# 전역 단축키 등록은 offscreen(가짜 hwnd)에서도 조용히 넘어가야 한다
win._register_hotkey()

# 이미 보이는 상태에서 show_bar / 이미 숨은 상태에서 hide_bar는 no-op
win.show_bar()
assert win.isVisible() and win.is_expanded
win.hide_bar()
win.hide_bar()
assert not win.isVisible()

print("hide/show OK")
