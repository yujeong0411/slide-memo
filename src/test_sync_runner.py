# ponytail: 앱에 붙은 동기화 self-check — 고치면 올라가고 받은 변경이 열린 메모에 반영되는지, 경고 단추,
# 트레이 항목, 동기화 탭, 휴지통 비우기. 폴더 하나를 Drive처럼 쓴다. 임시 폴더만. run: python src/test_sync_runner.py
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import main as M  # noqa: E402
from database import MemoDatabase  # noqa: E402
from sync import runner  # noqa: E402
from sync.engine import Syncer  # noqa: E402
from sync.local_folder import LocalFolderTransport  # noqa: E402
from sync.store import SyncStore  # noqa: E402

runner.PUSH_QUIET_S = 1     # 시험: 1초 조용하면 올린다
runner.FOLLOW_UP_S = 2
app = QApplication([])
drive = tmp / "drive"


def pump(until, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.05)
    return False


# 이 PC: 창 + 컨트롤러(작업 줄). 연결은 이미 된 것으로 둔다
db = MemoDatabase(tmp / "me.db")
SyncStore(db.conn).connect("me@example.com")
db.set_setting_str("sync_account_email", "me@example.com")
first = db.create("처음 메모", "<p>안녕</p>")
win = M.SlideMemoWindow(db)
ctl = runner.SyncController(db, lambda store: LocalFolderTransport(drive), available=True)
win.attach_sync(ctl)
win.show()
win._load_memo(db.get(first.id))
win.expand()
cycles = []
ctl.cycle_finished.connect(cycles.append)
assert pump(lambda: cycles), "켠 직후 한 번 동기화"
assert ctl.status == "ok" and ctl.last_ok_ms() > 0
assert any(p.name.startswith("dev_") for p in drive.iterdir())

# 다른 PC (작업 줄 없이 직접)
other_db = MemoDatabase(tmp / "other.db")
other = SyncStore(other_db.conn)
other.connect("me@example.com")
other_sync = Syncer(other, LocalFolderTransport(drive), "다른 PC")
other_sync.sync()
assert other_db.list_all()[0].content == "<p>안녕</p>"

# ----- 이 PC에서 고치면 1초 조용한 뒤 올라가고, 12초(시험 2초) 뒤 한 번 더 확인한다 -----
n = len(cycles)
win.editor.setHtml("<p>이 PC에서 고침</p>")
win.save_now()
assert pump(lambda: len(cycles) > n), "고친 뒤 올리기"
assert cycles[-1]["pushed"], "올릴 것이 있었다"
assert pump(lambda: len(cycles) > n + 1, 6), "올린 직후 한 번 더 확인"
assert not cycles[-1]["pushed"]
other_sync.sync()
assert "이 PC에서 고침" in other_db.list_all()[0].content

# ----- 다른 PC에서 고친 것이 열린 메모에 반영된다 -----
other_db.update(other_db.list_all()[0].id, content="<p>다른 PC에서 고침</p>")
other_sync.sync()
n = len(cycles)
ctl.sync_now()
assert pump(lambda: len(cycles) > n)
assert win.editor.toPlainText() == "다른 PC에서 고침", win.editor.toPlainText()
received = db.get(first.id).content
win.save_now()
assert db.get(first.id).content == received, "받은 내용을 옛 내용으로 덮어쓰면 안 된다"

# 동기화하는 사이 이 PC에서도 고쳤다면: 받은 내용은 이전 버전에, 이 PC 내용은 지킨다
other_db.update(other_db.list_all()[0].id, content="<p>다른 PC 두 번째</p>")
other_sync.sync()
win.about_to_sync_saved = False
ctl.about_to_sync.disconnect(win._save_before_sync)  # 저장 전에 동기화가 끝난 상황을 만든다
win.editor.setHtml("<p>동시에 이 PC에서</p>")
n = len(cycles)
ctl.sync_now()
assert pump(lambda: len(cycles) > n)
ctl.about_to_sync.connect(win._save_before_sync)
assert win.editor.toPlainText() == "동시에 이 PC에서"
assert "다른 PC 두 번째" in [v.content for v in db.list_versions(first.id)][0]
assert "이전 버전" in win._toast_lbl.message.text()

# 충돌 토스트 문구
win._show_sync_conflicts([(first.uid, True)])
assert win._toast_lbl.message.text().startswith("다른 PC에서 같은 메모를 고쳤어요. 이 PC에서 쓴 내용은 이전 버전에 남겼어요.")
win._show_sync_conflicts([(first.uid, False)])
assert win._toast_lbl.message.text().startswith("다른 PC에서 고친 내용은 이전 버전에 남겼어요.")
second = db.create("두 번째")
win._show_sync_conflicts([(first.uid, True), (second.uid, False)])
assert "겹친 메모가 2개" in win._toast_lbl.message.text()

# ----- 경고 단추: 평소엔 없고, 문제가 있을 때만 -----
assert not win.sync_warn_btn.isVisible()
for status, visible in (("quota_full", True), ("reconnect", True), ("network", False)):
    ctl.status = status
    win._update_sync_warning()
    assert win.sync_warn_btn.isVisible() == visible, status
    if visible:
        assert win.sync_warn_btn.toolTip() == runner.STATUS_TEXT[status]
db.set_setting_str(runner.LAST_OK_KEY, str(int((time.time() - 7200) * 1000)))  # 2시간 동안 못 맞춤
win._update_sync_warning()
assert win.sync_warn_btn.isVisible() and "인터넷" in win.sync_warn_btn.toolTip()
ctl.status = "ok"
win._update_sync_warning()
assert not win.sync_warn_btn.isVisible()

# ----- 트레이: 지금 동기화 + 마지막 동기화 -----
tray = M.make_tray_icon(win)
menu = tray.contextMenu()
menu.aboutToShow.emit()
texts = [a.text().split("\t")[0] for a in menu.actions() if a.isVisible()]
assert "지금 동기화" in texts and any(t.startswith("마지막 동기화: ") for t in texts), texts

# ----- 동기화 탭 -----
from settings_dialog import SettingsDialog  # noqa: E402

dlg = SettingsDialog(db, win, tab="sync")
tab = dlg._sync_tab
assert pump(lambda: hasattr(tab, "devices_box") and tab.devices_box.count() >= 2 and
            not any(isinstance(tab.devices_box.itemAt(i).widget(), QLabel) and "읽는 중" in tab.devices_box.itemAt(i).widget().text()
                    for i in range(tab.devices_box.count())))
labels = [w.text() for w in tab.findChildren(QLabel)]
buttons = [b.text() for b in tab.findChildren(QPushButton)]
assert "me@example.com" in labels and "이 PC" in labels and "다른 PC" in labels, labels
assert {"지금 동기화", "연결 끊기", "목록에서 빼기"} <= set(buttons), buttons
# PC 이름은 Windows 컴퓨터 이름을 글자로만 보여 준다 (바꾸는 칸이 없다)
from PyQt6.QtWidgets import QLineEdit  # noqa: E402

assert tab.pc_name_lbl.text() == runner.default_pc_name() and not tab.findChildren(QLineEdit)
assert any(not d["is_self"] and d["name"] == runner.default_pc_name() for d in other_sync.devices()), "다른 PC 목록에 이 PC가 컴퓨터 이름으로 보인다"

# 동기화·정보 탭은 [닫기]만, 일반·AI 탭은 [취소]·[저장하기]
dlg.show()
assert dlg._close_btn.isVisible() and not dlg._save_btn.isVisible() and not dlg._cancel_btn.isVisible()
dlg._tabs.setCurrentIndex(0)
assert dlg._save_btn.isVisible() and dlg._cancel_btn.isVisible() and not dlg._close_btn.isVisible()
dlg._tabs.setCurrentIndex(3)
assert dlg._close_btn.isVisible()
# 저장하지 않은 변경이 있으면 닫을 때 묻는다: [취소]면 그대로, [저장하지 않고 닫기]면 닫힘, [저장하고 닫기]면 저장
from PyQt6.QtCore import QTimer  # noqa: E402

from theme.widgets import AppDialog  # noqa: E402

old_opacity = db.get_setting_int("window_opacity", 100)
dlg._opacity_slider.setValue(70 if old_opacity != 70 else 80)
assert dlg.has_unsaved_changes()


def answer(text):
    def press():
        for w in app.topLevelWidgets():
            if isinstance(w, AppDialog) and w.isVisible() and w.head_label.text() == "저장하지 않은 변경이 있어요":
                next(b for b in w.findChildren(QPushButton) if b.text() == text).click()
    QTimer.singleShot(200, press)


answer("취소")
dlg.reject()
assert dlg.isVisible() and dlg.result() == 0, "취소하면 설정 창이 그대로"
answer("저장하지 않고 닫기")
dlg.reject()
assert not dlg.isVisible() and db.get_setting_int("window_opacity", 100) == old_opacity, "저장하지 않음"
dlg = SettingsDialog(db, win)
dlg.show()
dlg._opacity_slider.setValue(75)
answer("저장하고 닫기")
dlg.reject()
assert not dlg.isVisible() and db.get_setting_int("window_opacity", 100) == 75, "저장하고 닫음"
dlg = SettingsDialog(db, win)
dlg._opacity_slider.setValue(90)
dlg._discard()   # [취소]는 묻지 않고 버린다
assert db.get_setting_int("window_opacity", 100) == 75
db.set_setting_int("window_opacity", old_opacity)
dlg2 = SettingsDialog(db, None, tab="sync")   # 컨트롤러가 없거나 OAuth 설정이 없는 빌드
assert "이 빌드에서는 동기화를 쓸 수 없어요" in [w.text() for w in dlg2._sync_tab.findChildren(QLabel)]
dlg2.reject()

# 연결 끊기 확인 창: Drive 메모도 지우기를 체크했을 때만 빨간 위험 단추, 기본 포커스는 취소
from sync.settings_tab import _Ask  # noqa: E402

ask = _Ask("동기화를 끊을까요?", "설명", "끊기", "취소", None, check="Drive에 올린 메모도 지우기")
ask.check.toggled.connect(ask.set_danger)
assert ask.action_btn.property("variant") == "primary" and ask.action_btn.isDefault()
ask.check.setChecked(True)
assert ask.action_btn.property("variant") == "danger" and ask.cancel_btn.isDefault() and not ask.action_btn.isDefault()
ask.check.setChecked(False)
assert ask.action_btn.property("variant") == "primary" and ask.action_btn.isDefault()
ask.reject()

# ----- 휴지통 비우기: 한 번에 묶어 저장, 연결된 PC는 그림을 바로 지우지 않는다 -----
pic = database.IMAGES_DIR / "img_test.png"
pic.parent.mkdir(parents=True, exist_ok=True)
pic.write_bytes(b"png")
ids = [db.create(f"버릴 {i}", f'<p><img src="{pic.as_posix()}"></p>').id for i in range(50)]
for i in ids:
    db.soft_delete(i)
M.confirm = lambda *a, **k: True
win._enter_trash_mode()
win._empty_trash()
assert db.count_trashed() == 0 and pic.exists(), "연결된 PC는 그림을 180일 정리에 맡긴다"
ctl.shutdown()
win.sync = None
db.soft_delete(db.create("또 버릴", f'<p><img src="{pic.as_posix()}"></p>').id)
win._enter_trash_mode()
win._empty_trash()
assert not pic.exists(), "연결하지 않은 PC는 지금처럼 바로 지운다"

win._quitting = True
win.close()
other_db.close()
shutil.rmtree(tmp, ignore_errors=True)
tray.hide()
print("sync runner OK", flush=True)
# 실제 앱처럼 정상 종료한다. os._exit로 끝내면 받은 변경으로 문서를 다시 그린 뒤에는 Qt 객체가 살아 있는 채
# 프로세스가 끊겨 접근 오류가 기록됐다(종료 코드는 0). 앱의 종료 경로(main)와 같이 감시자를 떼고 나간다.
app.quit()
from theme import apply as theme_apply  # noqa: E402

theme_apply.release_watchers()
sys.exit(0)
