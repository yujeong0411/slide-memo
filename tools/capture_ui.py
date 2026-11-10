"""SlideMemo UI capture. Runs the real main() against a throwaway DB with fake memos.
Usage: capture_ui.py light|dark OUT_DIR
Nothing is shown on screen (WA_DontShowOnScreen); real clipboard/keyring are never read.
"""
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
SCHEME, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
SRC = Path(str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(SRC))
# fixed 2x regardless of the monitor, so shots are crisp and comparable
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = os.environ.get("CAPTURE_SCALE", "2")

tmp = Path(tempfile.mkdtemp(prefix="sm_ui_"))

import keyring  # noqa: E402

keyring.get_password = lambda *a: "sk-fake-not-a-real-key"


def _blocked(*a, **k):
    raise RuntimeError("keyring write blocked during capture")


keyring.set_password = keyring.delete_password = _blocked

import database  # noqa: E402

database.APP_DIR = tmp
database.DB_PATH = tmp / "memos.db"
database.IMAGES_DIR = tmp / "images"

import main as M  # noqa: E402
import settings_dialog as SD  # noqa: E402
from theme import apply as theme_apply  # noqa: E402

theme_apply.system_mode = lambda: SCHEME
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QColorDialog, QDialog, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QTabWidget, QToolTip, QWidget,
)

for _n, _v in (("APP_DIR", tmp), ("IMAGES_DIR", tmp / "images")):
    if hasattr(M, _n):
        setattr(M, _n, _v)

assert M.APP_DIR == tmp and database.DB_PATH.parent == tmp, "real data dir leaked"

DESK = "#dfe3ea" if SCHEME == "light" else "#1b1e25"
manifest = []
failures = []
NAME = {"v": None}
_ORIG_DLG_EXEC = QDialog.exec


def pump():
    app = QApplication.instance()
    for _ in range(4):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.LayoutRequest)


def save(pm, name, kind, how, src):
    path = OUT / f"{name}__{SCHEME}.png"
    assert pm.save(str(path)), path
    manifest.append({"name": name, "kind": kind, "how": how, "src": src})


def flat(pm, pad=10):
    """Composite a translucent window over a neutral desktop colour."""
    dpr = pm.devicePixelRatio()
    p_px = int(pad * dpr)
    out = QPixmap(pm.width() + 2 * p_px, pm.height() + 2 * p_px)
    out.fill(QColor(DESK))
    p = QPainter(out)
    pm2 = QPixmap(pm)
    pm2.setDevicePixelRatio(1.0)
    p.drawPixmap(p_px, p_px, pm2)
    p.end()
    return out


def grab_unshown(w):
    w.ensurePolished()
    w.adjustSize()
    pump()
    return w.grab()


def grab_top(w):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    w.show()
    pump()
    pm = w.grab()
    w.hide()
    return pm


# ---- things that must never touch the real machine ----
M.UpdateChecker.start = lambda self: None
M.SlideMemoWindow._register_hotkey = lambda self: None
M.SlideMemoWindow._force_topmost = lambda self: None
M.SlideMemoWindow._check_clipboard = lambda self: self._clipboard_banner.hide()
M.QSystemTrayIcon.show = lambda self: None
M.QSystemTrayIcon.showMessage = lambda self, *a: None
M.SlideMemoWindow._screen_rect = lambda self: QRect(0, 0, 1920, 1080)


def _offscreen_show(self):
    self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    QWidget.show(self)


M.SlideMemoWindow.show = _offscreen_show
M.GuideBubble.show = _offscreen_show

_Splash = M.QSplashScreen


class CaptureSplash(_Splash):
    def __init__(self, *a):
        super().__init__(*a)
        QGuiApplication.styleHints().setColorScheme(
            Qt.ColorScheme.Dark if SCHEME == "dark" else Qt.ColorScheme.Light
        )
        pump()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)

    def finish(self, win):
        save(flat(self.grab()), "01_splash", "시작 화면", "앱 실행 직후", "main.py:5203 main()")
        self.close()


M.QSplashScreen = CaptureSplash

TITLE_NAMES = {
    "메모 색이": ("61_msg_palette_notice", "업그레이드 첫 실행 1회", "main.py _show_palette_notice"),
    "업데이트했어요": ("62_msg_whats_new", "업데이트 후 첫 실행 1회", "main.py _show_whats_new"),
    "화면 가장자리에": ("60_msg_welcome", "신규 설치 첫 실행", "main.py _show_welcome"),
}


def fake_dialog_exec(self):
    if NAME["v"] is not None:
        name, how, src = NAME["v"]
    else:
        name, how, src = next(v for k, v in TITLE_NAMES.items() if k in self.text())
    NAME["v"] = None
    save(grab_top(self), name, "대화창", how, src)
    return QDialog.DialogCode.Rejected


QDialog.exec = fake_dialog_exec
QMessageBox.exec = fake_dialog_exec


def fake_static(icon):
    def f(parent, title, text, buttons=QMessageBox.StandardButton.Ok, *a):
        box = QMessageBox(parent)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        box.exec()
        return QMessageBox.StandardButton.No
    return staticmethod(f)


QMessageBox.question = fake_static(QMessageBox.Icon.Question)
QMessageBox.information = fake_static(QMessageBox.Icon.Information)
QMessageBox.warning = fake_static(QMessageBox.Icon.Warning)


def fake_menu_exec(self, *a):
    name, how, src = NAME["v"]
    NAME["v"] = None
    first = next((x for x in self.actions() if x.isEnabled() and not x.isSeparator()), None)
    if first is not None:
        self.setActiveAction(first)
    save(flat(grab_unshown(self)), name, "메뉴", how, src)
    for act in self.actions():
        if act.menu() is not None:
            save(flat(grab_unshown(act.menu())), name + "_submenu", "메뉴", how + " > 하위 메뉴", src)
    return None


QMenu.exec = fake_menu_exec

# ---- fake data ----
HTML = (
    "<p><b>이번 주 할 일</b></p><ul><li>디자인 시안 검토</li><li>회의 자료 정리</li>"
    "<li><span style='background-color:#fef08a'>금요일까지 제출</span></li></ul>"
    "<p>참고 링크: <a href='https://example.com'>example.com</a></p>"
    "<table border='1' cellspacing='0' cellpadding='4'><tr><th>항목</th><th>담당</th></tr>"
    "<tr><td>기획서</td><td>가나다</td></tr><tr><td>시안</td><td>라마바</td></tr></table>"
    "<p><span style='color:#ef4444'>빨간 글자</span> · <i>기울임</i> · <u>밑줄</u> · <s>취소선</s></p>"
    "<p>동해물과 백두산이 마르고 닳도록 하느님이 보우하사 우리나라 만세. The quick brown fox 0123456789.</p>"
)
from theme import tokens as _T  # noqa: E402

COLOR_MEMO = (
    "<p><b>글자색 10개</b></p><p>"
    + " ".join(f"<span style='color:{light}'>{name}</span>" for name, light, _ in _T.TEXT_COLORS)
    + "</p><p><b>형광펜 5개</b></p><p>"
    + " ".join(f"<span style='background-color:{light}'>{name} 형광펜</span>" for name, light, _ in _T.HIGHLIGHTS)
    + "</p><p><b>목록에 없는 예전 색</b></p><p>"
    "<span style='color:#1f2937'>예전 검정 글자</span> "
    "<span style='color:#ef4444'>예전 빨강 글자</span> "
    "<span style='background-color:#fef08a'>예전 노랑 바탕</span> "
    "<span style='background-color:#bfdbfe'>예전 파랑 바탕</span></p>"
)
db = M.MemoDatabase()
ids = {}
for key, title, color in [
    ("sunrise", "주간 회의 준비", "sunrise"),
    ("blossom", "장보기 목록", "blossom"),
    ("solid_light", "독서 메모", "#FFF2EB"),
    ("solid_mid", "운동 기록", "#7AD0C2"),
    ("solid_dark", "밤 산책 생각", "#2f3650"),
    ("grad_custom", "여행 계획", "grad:#FFD27A,#FF8FB1"),
    ("grad_dark", "프로젝트 아이디어", "grad:#1f2a44,#4b3a6b"),
    ("ivory", "아주 긴 제목을 가진 메모가 탭에서 어떻게 잘리는지 확인", "ivory"),
    ("mint", "레시피", "mint"),
    ("blank", "", "sunrise"),
]:
    ids[key] = db.create(title, HTML if key != "blank" else "").id
    db.conn.execute("UPDATE memos SET color = ? WHERE id = ?", (color, ids[key]))  # 예전 값 그대로
db.set_pinned(ids["blossom"], True)
db.snapshot(ids["sunrise"], force=True)
db.update(ids["sunrise"], content=HTML + "<p>수정된 내용</p>")
db.snapshot(ids["sunrise"], force=True)
db.update(ids["sunrise"], content=HTML + "<p>수정된 내용 2</p>")
for t in ("지난달 영수증", "오래된 아이디어", "삭제한 초안"):
    ids[t] = db.create(t, "<p>휴지통에 있는 가짜 메모입니다.</p>", "blossom").id
    db.soft_delete(ids[t])
trashed_one = ids["지난달 영수증"]
ids["color_pairs"] = db.create("색 바꿔 칠하기 확인", COLOR_MEMO, "yellow").id
db.set_setting_str(M.USER_SLOTS_KEY, "#7AD0C2|grad:#FFD27A,#FF8FB1")
db.set_setting_int(M.GUIDE_BAR_KEY, 1)
db.set_setting_int(M.GUIDE_BODY_KEY, 1)
db.set_setting_str(M.WHATS_NEW_KEY, "1.3.9")
db.conn.execute("PRAGMA user_version = 2")  # 업그레이드 경로를 실제로 태운다
db.conn.commit()
db.close()


def S(name, how, src):
    NAME["v"] = (name, how, src)


def capture(win, db, tray, env):
    def step(fn):
        try:
            fn()
        except Exception:
            failures.append(fn.__name__ + "\n" + traceback.format_exc())
        pump()

    def expanded(key):
        win._load_memo(db.get(ids[key]))
        win.expand()
        win.fade_anim.stop()
        win.body_opacity.setOpacity(1.0)
        win._on_fade_done()
        win._update_tabs_selected()
        pump()

    def collapsed():
        win.collapse(exit_trash=False)
        win.fade_anim.stop()
        win.body_opacity.setOpacity(0.0)
        win._on_fade_done()
        pump()

    def main_shot(name, how, src="main.py SlideMemoWindow"):
        pump()
        save(flat(win.grab()), name, "메인 창", how, src)

    def bar_shot(name, how):
        pump()
        save(flat(win.tab_column.grab()), name, "접힌 바", how, "main.py SlideMemoWindow.tab_column")

    tb = win.format_toolbar
    env["style"] = QApplication.style().objectName()
    env["app_font"] = QApplication.font().family()
    env["app_font_pt"] = QApplication.font().pointSize()
    env["scheme_effective"] = QGuiApplication.styleHints().colorScheme().name
    env["editor_font"] = win.editor.font().family()
    env["editor_font_pt"] = win.editor.font().pointSize()
    env["title_font"] = win.title_input.font().family()
    env["tab_font_family"] = M.MemoTabButton.app_font_family
    env["palette_window"] = QApplication.palette().window().color().name()
    env["palette_text"] = QApplication.palette().windowText().color().name()

    def bars():
        bar_shot("02_bar_collapsed_right", "기본 상태 (오른쪽 가장자리)")
        db.set_setting_int("side", 1)
        win.apply_side_settings()
        bar_shot("03_bar_collapsed_left", "설정 > 앱 위치: 왼쪽")
        db.set_setting_int("side", 0)
        win.apply_side_settings()

    def themes():
        for i, (key, label) in enumerate([
            ("sunrise", "기본 그라데이션 sunrise"), ("blossom", "그라데이션 blossom, 고정 메모"),
            ("solid_light", "밝은 단색"), ("solid_mid", "중간 단색"), ("solid_dark", "어두운 단색"),
            ("grad_custom", "사용자 그라데이션"), ("grad_dark", "어두운 사용자 그라데이션"),
            ("color_pairs", "글자색·형광펜 바꿔 칠하기 확인"),
        ]):
            expanded(key)
            main_shot(f"1{i}_main_{key}", f"탭 클릭으로 펼침: {label}")

    def variants():
        db.set_setting_int("side", 1)
        win.apply_side_settings()
        expanded("sunrise")
        main_shot("20_main_left_side", "왼쪽 가장자리에서 펼침")
        db.set_setting_int("side", 0)
        win.apply_side_settings()
        g = win.geometry()
        win.setGeometry(g.right() - M.MIN_W + 1, g.y(), M.MIN_W, g.height())
        pump()
        expanded("sunrise")
        main_shot("21_main_narrow", f"창을 최소 폭({M.MIN_W}px)까지 줄임, 서식바 줄바꿈")
        win._clipboard_banner_label.setText("복사한 글 “3분기 실적 보고서 초안 공유드립니다. 확인 부탁드려요”")
        win._clipboard_banner.show()
        main_shot("23b_main_banner_narrow", "좁은 창의 클립보드 배너", "main.py _clipboard_banner")
        win._clipboard_banner.hide()
        win.setGeometry(g)
        expanded("blank")
        main_shot("22_main_empty_memo", "새 메모 (자리표시자)")

    def transient():
        expanded("sunrise")
        win._clipboard_banner_label.setText("복사한 글 “3분기 실적 보고서 초안 공유드립니다. 확인 부탁드려요”")
        win._clipboard_banner.show()
        main_shot("23_main_clipboard_banner", "클립보드에 텍스트가 있을 때 펼침", "main.py:2644 _clipboard_banner")
        win._clipboard_banner.hide()
        win._show_toast("메모를 휴지통으로 옮겼어요", on_click=lambda: None)
        win._toast_timer.stop()
        win._toast_lbl.finish_animation()
        main_shot("24_main_toast", "메모 삭제 직후 토스트", "main.py:2826 _toast_lbl")
        win._toast_lbl.hide()
        win._update_mic_button_state(recording=True, elapsed=12)
        main_shot("25_main_recording", "녹음 중 (마이크 버튼 강조)", "main.py:3384")
        win._update_mic_button_state(recording=False)
        db.set_setting_str("ai_enabled", "1")
        win._refresh_ai_bar()
        win._show_ai_progress("요약하는 중이에요")
        win._ai_status_lbl.show_now()
        main_shot("26_main_ai_bar_progress", "AI 사용 켬: AI 버튼 줄 + 진행 표시", "main.py:2797 _ai_bar")
        win._ai_status_lbl.hide()
        win.search_input.setText("회의")
        main_shot("27_main_search_result", "검색어 입력", "main.py:4803")
        win.search_input.setText("")

    def guide():
        collapsed()
        win.start_guide("bar")
        for i in range(4):
            pump()
            save(flat(win._guide.grab()), f"28_guide_bar_{i+1}", "가이드 말풍선", f"가이드 1단계 {i+1}/4", "main.py:2148 GuideBubble")
            win._next_guide_step()
        expanded("sunrise")
        win.start_guide("body")
        for i in range(4):
            pump()
            save(flat(win._guide.grab()), f"29_guide_body_{i+1}", "가이드 말풍선", f"가이드 2단계 {i+1}/4", "main.py:2148 GuideBubble")
            win._next_guide_step()

    def trash():
        expanded("sunrise")
        win._enter_trash_mode()
        win.fade_anim.stop()
        win.body_opacity.setOpacity(0.0)
        win._on_fade_done()
        bar_shot("30_bar_trash_mode", "휴지통 모드 (접힘)")
        win._preview_trashed(trashed_one)
        win.fade_anim.stop()
        win.body_opacity.setOpacity(1.0)
        win._on_fade_done()
        main_shot("31_main_trash_preview", "휴지통 메모 미리보기 (읽기 전용)", "main.py:4185")
        btn = next(
            win.tabs_layout.itemAt(i).widget() for i in range(win.tabs_layout.count())
            if isinstance(win.tabs_layout.itemAt(i).widget(), M.MemoTabButton)
        )
        S("47_menu_trash_tab", "휴지통 모드에서 탭 우클릭", "main.py:4217 _show_trash_menu")
        win._show_trash_menu(trashed_one, btn)
        S("66_msg_empty_trash", "휴지통 모드 > 전체 비우기", "main.py:4080 _empty_trash")
        win._empty_trash()
        S("67_msg_purge_confirm", "휴지통 메모 영구 삭제", "main.py:4109")
        win._delete_current_memo()
        win._exit_trash_mode()

    def popups():
        expanded("sunrise")
        save(flat(grab_unshown(win.sort_combo._make_popup())), "40_popup_sort", "자체 팝업", "정렬 버튼 클릭", "main.py:1992 _SortSelector")
        save(flat(grab_unshown(win._make_color_popup())), "44b_popup_memo_color", "자체 팝업", "제목 옆 색 단추", "memo_color.py")
        tb._sync_font_combos()
        save(flat(grab_unshown(tb._font_popup)), "41_popup_font", "자체 팝업", "서식바 Aa", "main.py:1618 _build_font_popup")
        save(flat(grab_unshown(tb._make_ink_popup("bg"))), "42_popup_color_bg", "자체 팝업", "서식바 형광펜", "memo_popups.py InkPopup")
        save(flat(grab_unshown(tb._make_ink_popup("text"))), "42_popup_color_text", "자체 팝업", "서식바 글자색", "memo_popups.py InkPopup")
        save(flat(grab_unshown(tb._make_date_popup())), "43_popup_datetime", "자체 팝업", "서식바 달력", "memo_popups.py DatePopup")

    def tooltip():
        QToolTip.showText(QPoint(100, 100), "새 메모 (Ctrl+N)", win.new_tab_btn)
        pump()
        tips = [w for w in QApplication.topLevelWidgets() if w.objectName() == "qtooltip_label"]
        save(flat(tips[0].grab()), "44_tooltip", "툴팁", "버튼에 마우스 올림", "main.py:347 STYLE QToolTip")
        QToolTip.hideText()

    def menus():
        expanded("sunrise")
        S("45_menu_bar", "바 우클릭", "main.py:3866 _show_column_menu")
        win._show_column_menu(QPoint(5, 5))
        btns = {
            win.tabs_layout.itemAt(i).widget().memo_id: win.tabs_layout.itemAt(i).widget()
            for i in range(win.tabs_layout.count())
            if isinstance(win.tabs_layout.itemAt(i).widget(), M.MemoTabButton)
        }
        S("46_menu_tab", "메모 탭 우클릭", "main.py:4432 _show_tab_context_menu")
        win._show_tab_context_menu(QPoint(5, 5), ids["sunrise"], btns[ids["sunrise"]])
        S("46_menu_tab_pinned", "고정된 메모 탭 우클릭", "main.py:4432 _show_tab_context_menu")
        win._show_tab_context_menu(QPoint(5, 5), ids["blossom"], btns[ids["blossom"]])
        S("48_menu_color_slot", "추가한 색 점 우클릭", "main.py:4625 _show_slot_menu")
        win._show_slot_menu("#7AD0C2")
        win.editor.selectAll()
        S("49_menu_editor_ai", "본문 우클릭 (AI 켬)", "main.py:3173 _show_editor_context_menu")
        win._show_editor_context_menu(QPoint(5, 5))
        db.set_setting_str("ai_enabled", "0")
        S("49_menu_editor", "본문 우클릭 (AI 끔)", "main.py:3173 _show_editor_context_menu")
        win._show_editor_context_menu(QPoint(5, 5))
        expanded("solid_mid")
        S("49_menu_editor_on_solid_memo", "단색 메모의 본문 우클릭", "main.py:3173 _show_editor_context_menu")
        win._show_editor_context_menu(QPoint(5, 5))
        expanded("sunrise")
        db.set_setting_str("ai_enabled", "1")
        tc = win.editor.textCursor()
        tc.clearSelection()
        win.editor.setTextCursor(tc)
        menu = tray.contextMenu()
        save(flat(grab_unshown(menu)), "4a_menu_tray", "메뉴", "트레이 아이콘 우클릭", "main.py:4936 make_tray_icon")

    def settings():
        db.set_setting_str("ai_enabled", "0")
        dlg = SD.SettingsDialog(db, win)
        tabs = dlg.findChild(QTabWidget)
        tabs.setCurrentIndex(0)
        save(grab_top(dlg), "50_settings_general", "설정", "바 우클릭 > 설정 > 일반", "settings_dialog.py:104")
        popup = dlg._side_combo.view().window()
        popup.resize(dlg._side_combo.width(), 2 * 32 + 10)
        pump()
        save(flat(popup.grab()), "50b_settings_combo_open", "설정", "일반 > 콤보 펼침", "theme/widgets.py themed_combo")
        tabs.setCurrentIndex(1)
        save(grab_top(dlg), "51_settings_ai_off", "설정", "설정 > AI (AI 끔)", "settings_dialog.py:214")
        tabs.setCurrentIndex(2)
        for lbl in dlg.findChildren(QLabel):
            if lbl.text().startswith("데이터 위치:"):
                lbl.setText(r"데이터 위치: C:\Users\사용자\.memo_slide")  # hide real user path
        save(grab_top(dlg), "53_settings_info", "설정", "설정 > 정보", "settings_dialog.py:419")
        db.set_setting_str("ai_enabled", "1")
        dlg2 = SD.SettingsDialog(db, win)
        tabs2 = dlg2.findChild(QTabWidget)
        tabs2.setCurrentIndex(1)
        save(grab_top(dlg2), "52_settings_ai_on", "설정", "설정 > AI (AI 켬, 스크롤 상단)", "settings_dialog.py:214")
        dlg2.resize(dlg2.width(), 900)
        save(grab_top(dlg2), "52_settings_ai_on_full", "설정", "설정 > AI 전체 (창을 늘려 스크롤 없이)", "settings_dialog.py:214")

    def dialogs():
        expanded("sunrise")
        S("54_dlg_link", "서식바 링크 (선택 없음) / Ctrl+K", "main.py:922 LinkDialog")
        tb.insert_link()
        S("55_dlg_link_url", "텍스트 선택 후 링크", "main.py LinkDialog")
        M.LinkDialog("선택한 글자", win, show_text=False).exec()
        S("56_dlg_table", "서식바 표", "main.py:947 TableDialog")
        tb.insert_table()
        S("57_dlg_versions", "탭 우클릭 > 이전 버전 / Ctrl+Alt+Z", "main.py:983 VersionDialog")
        win._show_versions(ids["sunrise"])
        S("58_dlg_memo_color_gradient", "색 점 옆 +", "main.py:1113 MemoColorDialog")
        win._add_color_slot()
        S("58_dlg_memo_color_solid", "색 점 옆 + (색 1개)", "main.py:1113 MemoColorDialog")
        M.MemoColorDialog("#7AD0C2", win).exec()
        c = QColorDialog(QColor("#FFD27A"), win)
        c.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        c.setWindowTitle("색 선택")
        save(grab_top(c), "59_dlg_color_picker", "대화창", "색 지정 > 색 버튼, 사용자 정의", "main.py:1182 QColorDialog")
        S("5a_dlg_ai_preview", "AI 결과 미리보기", "main.py:3421 _show_ai_preview")
        win._show_ai_preview("summarize", "가짜 요약 결과입니다.\n이번 주 할 일은 디자인 시안 검토와 회의 자료 정리입니다.")
        S("5b_dlg_update", "새 버전 발견 시", "main.py:5040 UpdateDialog")
        M.UpdateDialog("1.4.1", "1.5.0", win).exec()
        mime = QMimeData()
        img = QImage(40, 40, QImage.Format.Format_RGB32)
        img.fill(QColor("#ffffff"))
        mime.setImageData(img)
        mime.setText("가짜 표 복사")
        S("5c_dlg_paste_format", "엑셀 등 이미지+텍스트 붙여넣기", "main.py:839 insertFromMimeData")
        win.editor.insertFromMimeData(mime)
        S("63_msg_trash_empty", "휴지통이 비었을 때", "main.py:4015")
        M.notify(win, "휴지통이 비어 있어요")
        S("68_msg_save_failed", "종료 중 저장 실패", "main.py:4831")
        M.notify(win, "마지막 내용을 저장하지 못했어요", "(가짜 오류 메시지)", warning=True)
        M._show_welcome(win, db)

    for fn in (bars, themes, variants, transient, guide, popups, tooltip, menus, trash, settings, dialogs):
        step(fn)


env = {}


def _fake_app_exec(*_a):
    app = QApplication.instance()
    win = next(w for w in app.topLevelWidgets() if isinstance(w, M.SlideMemoWindow))
    capture(win, win.db, win._tray, env)
    # finish here: returning through main() tears Qt objects down and crashes silently
    (Path(__file__).parent / f"_manifest_{SCHEME}.json").write_text(
        json.dumps({"env": env, "shots": manifest, "failures": failures}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(SCHEME, "shots", len(manifest), "failures", len(failures))
    print(json.dumps(env, ensure_ascii=False))
    for f in failures:
        print(f)
    sys.stdout.flush()
    os._exit(0)


QApplication.exec = _fake_app_exec
M.main()
