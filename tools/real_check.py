"""실제 창을 화면에 띄워 OS 테두리·반투명·툴팁 마스크를 확인한다. 임시 DB만 쓴다.
Usage: real_check.py light|dark OUT_DIR"""
import ctypes
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

sys.dont_write_bytecode = True
SCHEME, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
tmp = Path(tempfile.mkdtemp(prefix="sm_ui_"))

import keyring  # noqa: E402

keyring.get_password = lambda *a: "sk-fake-not-a-real-key"

import database  # noqa: E402

database.APP_DIR = tmp
database.DB_PATH = tmp / "memos.db"
database.IMAGES_DIR = tmp / "images"

import main as M  # noqa: E402
import settings_dialog as SD  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QToolTip  # noqa: E402
from theme import apply as A  # noqa: E402
from theme.widgets import ThemedMenu, add_box_button, message_box  # noqa: E402

assert M.database if False else True
app = QApplication(sys.argv)
QGuiApplication.styleHints().setColorScheme(
    Qt.ColorScheme.Dark if SCHEME == "dark" else Qt.ColorScheme.Light
)
M._install_translator(app)
M._register_fonts()
A.apply_theme(app, SCHEME)
db = database.MemoDatabase()
assert str(db.db_path).startswith(str(tmp)), "real data dir leaked"


def pump(n=30):
    for _ in range(n):
        app.processEvents()


def wait(ms):
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(rect: QRect, name: str) -> None:
    screen = QGuiApplication.primaryScreen()
    assert screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(
        str(OUT / f"{name}__{SCHEME}.png")
    )


def dwm_dark(w) -> int:
    value = ctypes.c_int(-1)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(int(w.winId())), 20, ctypes.byref(value), 4)
    return value.value


TOP = Qt.WindowType.WindowStaysOnTopHint
dlg = SD.SettingsDialog(db)
dlg.setWindowFlag(TOP, True)
dlg.move(240, 120)
dlg.show()
dlg.raise_()
wait(500)
print("settings title", repr(dlg.windowTitle()), "DWM dark", dwm_dark(dlg), "size", dlg.width(), dlg.height())
shot(dlg.frameGeometry(), "real_60_settings")

# 콤보 펼침
dlg._side_combo.showPopup()
wait(350)
popup = dlg._side_combo.view().window()
shot(dlg.frameGeometry().united(popup.frameGeometry()), "real_61_settings_combo")
print("combo popup visible", popup.isVisible(), popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
dlg._side_combo.hidePopup()
wait(100)

# 메뉴: 실제 창 위에 띄워 둥근 모서리 확인
menu = ThemedMenu()
menu.add_section("메모장")
menu.add_item("설정", "settings_icon.svg")
menu.add_item("이전 버전 보기", "menu_history.svg", shortcut="Ctrl+Alt+Z")
menu.addSeparator()
menu.add_item("휴지통으로 옮기기", "menu_delete.svg", shortcut="Delete", danger=True)
menu.popup(dlg.mapToGlobal(QPoint(60, 90)))
wait(350)
shot(menu.frameGeometry().adjusted(-12, -12, 12, 12), "real_62_menu")
menu.close()
wait(100)

# 회색 바탕 위에서 그림자와 둥근 모서리 밖을 확인한다 (흰 창 위에서는 흰 모서리가 안 보인다)
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget  # noqa: E402
from theme.widgets import ThemedCombo  # noqa: E402

BACKDROP = (138, 143, 152)
backdrop = QWidget(None, Qt.WindowType.FramelessWindowHint | TOP)
backdrop.setStyleSheet("background: rgb(%d,%d,%d);" % BACKDROP)
backdrop.setGeometry(800, 120, 620, 440)
backdrop.show()
wait(250)


def corner_report(name, inner):
    img = QGuiApplication.primaryScreen().grabWindow(0, inner.x(), inner.y(), inner.width(), inner.height()).toImage()
    pts = {"tl": (0, 0), "tr": (img.width() - 1, 0), "bl": (0, img.height() - 1), "br": (img.width() - 1, img.height() - 1)}
    print(name, "dpr", img.devicePixelRatio(), {k: img.pixelColor(*v).name() for k, v in pts.items()})


tab_menu = ThemedMenu()
tab_menu.add_item("고정", "menu_keep.svg")
tab_menu.add_item("이전 버전 보기", "menu_history.svg", shortcut="Ctrl+Alt+Z")
tab_menu.add_item("내보내기", "menu_export.svg")
tab_menu.addSeparator()
tab_menu.add_item("휴지통으로 옮기기", "menu_delete.svg", shortcut="Delete", danger=True)
tab_menu.setWindowFlag(TOP, True)
tab_menu.popup(backdrop.mapToGlobal(QPoint(60, 40)))
wait(400)
area = tab_menu.frameGeometry().adjusted(-8, -8, 8, 8)
shot(area, "real_65_menu_tab")
m = tab_menu.contentsMargins()
corner_report("menu panel corners", tab_menu.frameGeometry().adjusted(m.left(), m.top(), -m.right(), -m.bottom()))
tab_menu.close()
wait(100)

host = QDialog(None, Qt.WindowType.FramelessWindowHint | TOP)
host_layout = QVBoxLayout(host)
host_layout.setContentsMargins(12, 12, 12, 12)
combo = ThemedCombo()
combo.addItems(["오른쪽 가장자리", "왼쪽 가장자리"])
host_layout.addWidget(combo)
host.setFixedWidth(320)
host.move(backdrop.mapToGlobal(QPoint(120, 60)))
host.show()
wait(300)
combo.showPopup()
wait(400)
popup = combo.view().window()
area = host.frameGeometry().united(popup.frameGeometry()).adjusted(-16, -16, 16, 16)
shot(area, "real_66_combo_open")
print("combo below field", popup.frameGeometry().top() >= combo.mapToGlobal(QPoint(0, combo.height())).y() - 10,
      "view", combo.view().size().width(), combo.width())
view = combo.view()
tl = view.mapToGlobal(QPoint(0, 0))
corner_report("combo panel corners", QRect(tl, view.size()))
combo.hidePopup()
host.hide()
backdrop.hide()
wait(100)
dlg.show()
wait(250)

# 실제 메인 창 (임시 DB)
M.SlideMemoWindow._register_hotkey = lambda self: None
for key, color in (("장보기 목록", "pink"), ("주간 회의 준비 자료 정리", "blue"), ("레시피", "green"), ("아주 긴 제목을 가진 메모가 탭에서 어떻게 보이는지 확인하기", "yellow")):
    db.create(key, "<p>가짜 메모입니다.</p><ul><li>첫째</li><li>둘째</li></ul>", color)
db.set_setting_int(M.GUIDE_BAR_KEY, 1)
db.set_setting_int(M.GUIDE_BODY_KEY, 1)
main_win = M.SlideMemoWindow(db)
main_win.show()
wait(300)
# 창 뒤에 회색을 깔아 바탕화면이 찍히지 않게 한다
backdrop.setGeometry(main_win.frameGeometry().adjusted(-16, -16, 16, 16))
backdrop.show()
main_win.raise_()
wait(300)
shot(main_win.tab_column.frameGeometry().translated(main_win.frameGeometry().topLeft()), "real_70_bar_collapsed")
main_win.select_memo(main_win.db.list_all()[1].id)
wait(600)
shot(main_win.frameGeometry(), "real_71_main_expanded")
main_win.sort_combo._open_popup()
wait(350)
shot(main_win.sort_combo._popup.frameGeometry().adjusted(-4, -4, 4, 4), "real_72_popup_sort")
main_win.sort_combo._popup.close()
wait(120)
main_win._show_toast("메모를 휴지통으로 옮겼어요", on_click=lambda: None)
wait(400)
shot(main_win.frameGeometry(), "real_73_toast")
# 화면 모드 전환: 켜 둔 창이 바뀌는지
other = "light" if SCHEME == "dark" else "dark"
main_win.db.set_setting_str(A.THEME_MODE_KEY, other)
main_win.apply_screen_mode()
wait(500)
shot(main_win.frameGeometry(), "real_75_mode_switched")
print("switched to", A.current_mode(), "DWM dark", dwm_dark(main_win))
main_win.db.set_setting_str(A.THEME_MODE_KEY, SCHEME)
main_win.apply_screen_mode()
wait(300)

# 왼쪽에 붙은 창
main_win.db.set_setting_int("side", 1)
main_win.apply_side_settings()
backdrop.setGeometry(main_win.frameGeometry().adjusted(-16, -16, 16, 16))
main_win.raise_()
wait(400)
shot(main_win.frameGeometry(), "real_74_main_left")
main_win._apply_tab_width(48)
wait(300)
backdrop.setGeometry(main_win.frameGeometry().adjusted(-16, -16, 16, 16))
main_win.raise_()
wait(250)
shot(main_win.frameGeometry(), "real_81_width48_left")
main_win.db.set_setting_int("side", 0)
main_win.apply_side_settings()
backdrop.setGeometry(main_win.frameGeometry().adjusted(-16, -16, 16, 16))
main_win.raise_()
wait(400)
shot(main_win.frameGeometry(), "real_80_width48_right")
main_win._apply_tab_width(40)
wait(200)
for i in range(10):
    db.create(f"메모 {i}", "<p>가짜 메모입니다.</p>", "gray")
main_win._refresh_memo_tabs()
main_win._update_tabs_selected()
wait(300)
main_win.tab_scroll.verticalScrollBar().setValue(224)
wait(300)
shot(main_win.frameGeometry(), "real_82_bar_chevrons")
main_win.hide()
backdrop.hide()
wait(100)

# 툴팁 마스크
QToolTip.showText(dlg.mapToGlobal(QPoint(120, 40)), "새 메모 Ctrl+N", dlg)
wait(300)
tips = [w for w in app.topLevelWidgets() if w.objectName() == "qtooltip_label"]
print("tooltip mask empty", tips[0].mask().isEmpty(), "font", tips[0].font().family(), tips[0].font().pixelSize())
shot(tips[0].frameGeometry().adjusted(-8, -8, 8, 8), "real_63_tooltip")
QToolTip.hideText()
dlg.hide()
wait(100)

# 위험 확인 창
box = message_box(None, "휴지통을 비울까요?", "메모 3개를 지워요. 비운 메모는 되돌릴 수 없습니다.")
cancel = add_box_button(box, "취소", QMessageBox.ButtonRole.RejectRole)
add_box_button(box, "비우기", QMessageBox.ButtonRole.AcceptRole, "danger")
box.setDefaultButton(cancel)
box.setWindowFlag(TOP, True)
box.move(300, 200)
box.show()
wait(500)
print("box title", repr(box.windowTitle()), "DWM dark", dwm_dark(box), "focus", app.focusWidget().text() if app.focusWidget() else None)
shot(box.frameGeometry(), "real_64_confirm")
box.hide()

sys.stdout.flush()
os._exit(0)
