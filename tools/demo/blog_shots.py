"""블로그 그림 다섯 장(card, dark-mode, search, ai-toolbar, ai-setting)을 만드는 시연 도구.

- 임시 폴더에 시연용 DB를 새로 만들어 앱 창을 띄운다. 실제 ~/.memo_slide와 메모 DB는 열지 않는다.
- 인터넷 접속은 소켓 단계에서 모두 막는다. 동기화는 연결하지 않고, 업데이트 확인도 하지 않는다.
- 자격 증명 관리자(keyring)는 읽지도 쓰지도 않는다. AI 키 칸에는 가짜 키(DEMO_KEY)를 넣는다.
- 창은 화면에 띄우지 않고(WA_DontShowOnScreen) Qt로 직접 그려(QWidget.grab) PNG로 저장한다.
- 가로·배율은 블로그의 지금 그림에 맞춘다(메모 패널 가로 520을 1.5배 = 780px, 설정 창은 1배).
  메모 패널 높이는 탭 줄과 본문이 스크롤 없이 들어가는 가장 낮은 높이에 여유를 더해 잰다.

실행 (저장소 폴더에서): uv run python tools/demo/blog_shots.py [출력 폴더]   기본: build/blog-shots
"""
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else ROOT / "build" / "blog-shots"
DEMO_KEY = "sk-ant-demo-0000-0000-0000-not-a-real-key"  # 점으로 가려져 보이는 가짜 키
DESK = "#ECEEF2"  # 지금 블로그 그림의 창 바깥 색
PANEL = ("card", "dark-mode", "search", "ai-toolbar")
DESK_DARK = "#1F1F1F"  # 어두운 화면의 바깥 색 = 앱 어두운 토큰 bg_sunken (탭 아래 빈 자리가 밝게 튀지 않게)
MEASURE_H, MARGIN_H = 840, 16  # 높이를 잴 때의 창 높이, 잰 높이에 더하는 여유 (1배 기준)
FONT_PT = 12  # 본문 글자 크기 = 앱 기본값 (지금 블로그 그림의 줄 간격 53.5px@1.5배와 맞다)


def main_driver() -> None:
    """메모 패널(1.5배)과 설정 창(1배)은 배율이 달라 프로세스를 나눠 실행한다."""
    import shutil

    OUT.mkdir(parents=True, exist_ok=True)
    real = Path.home() / ".memo_slide"
    before = _fingerprint(real)
    tmp_root = tempfile.mkdtemp(prefix="slidememo-demo-")  # 시연용 DB는 여기에만 만들고 끝나면 지운다
    try:
        for part, scale, names in (("--panel", "1.5", PANEL), ("--setting", "1", ("ai-setting",))):
            for n in names:
                (OUT / f"{n}.png").unlink(missing_ok=True)
            env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_ENABLE_HIGHDPI_SCALING="0", SLIDEMEMO_DEMO_TMP=tmp_root)
            # ponytail: Qt가 끝나는 단계에서 종료 코드가 깨지는 일이 있어(그림과 무관) 종료 코드 대신 결과 파일로 판단한다
            r = subprocess.run([sys.executable, __file__, part, str(OUT)], env=env)
            missing = [n for n in names if not (OUT / f"{n}.png").exists()]
            if missing:
                raise SystemExit(f"{part} 실패 (종료 코드 {r.returncode}): {missing} 그림이 없어요")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    after = _fingerprint(real)
    changed = sorted(set(before.items()) ^ set(after.items()))
    if not changed:
        print(f"실제 메모 폴더({real}) 그대로예요: 파일 {len(before)}개, 크기·수정 시각 같음")
    elif _slidememo_running():
        # 켜 둔 SlideMemo는 실행 중에도 자기 DB에 저장한다. 이 도구가 바꾼 것인지 구별할 수 없어 알리기만 한다
        names = sorted({Path(p).name for p, _ in changed})
        print(f"알림: 켜 둔 SlideMemo가 있어 실제 메모 폴더의 바뀐 파일을 이 도구와 구별할 수 없어요: {names}")
    else:
        raise SystemExit(f"실제 메모 폴더가 바뀌었어요: {sorted({p for p, _ in changed})}")
    for f in sorted(OUT.glob("*.png")):
        print(f"{f}  {f.stat().st_size:,} bytes")


def _slidememo_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SlideMemo.exe", "/NH"], capture_output=True, text=True)
    return "SlideMemo.exe" in out.stdout


def _fingerprint(folder: Path) -> dict[str, tuple[int, int]]:
    """폴더 안 모든 파일의 (크기, 수정 시각). 열어 보지 않고 목록만 본다."""
    if not folder.exists():
        return {}
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- 실제 PC를 건드리지 않게 막기
def _no_network(*_a, **_k):
    raise OSError("demo: 인터넷 접속을 막았어요")


def guard() -> Path:
    socket.getaddrinfo = _no_network
    socket.create_connection = _no_network
    socket.socket.connect = _no_network
    socket.socket.connect_ex = _no_network

    import keyring

    keyring.get_password = lambda service, user: DEMO_KEY if (service, user) == ("memo_slide_ai", "anthropic") else None

    def _no_write(*_a, **_k):
        raise RuntimeError("demo: 자격 증명 관리자에 쓰지 않아요")

    keyring.set_password = keyring.delete_password = _no_write

    tmp = Path(tempfile.mkdtemp(prefix="run-", dir=os.environ["SLIDEMEMO_DEMO_TMP"]))
    sys.path.insert(0, str(SRC))
    import database

    database.APP_DIR, database.DB_PATH, database.IMAGES_DIR = tmp, tmp / "memos.db", tmp / "images"
    real = (Path.home() / ".memo_slide").resolve()
    assert real not in tmp.resolve().parents and tmp.resolve() != real, "실제 메모 폴더를 쓰면 안 돼요"
    return tmp


# ---------------------------------------------------------------- 시연용 데이터
MEMOS = [  # 탭 순서대로 (고정 → 수정일 최근순)
    ("장보기 목록", "yellow", True, "<ul><li>우유</li><li>달걀 한 판</li><li>사과</li></ul>"),
    ("주간 회의 준비", "blue", False,
     "<p><b>11월 셋째 주 회의</b></p><ol><li>지난주 진행 상황 정리</li><li>3분기 예산 집행 검토</li>"
     "<li>신규 고객 미팅 일정 공유</li></ol><p>발표 자료는 수요일까지 팀 폴더에 올리기.<br>회의실은 4층 소회의실.</p>"),
    ("김치찌개 레시피", "orange", False,
     "<p><b>재료</b> (2인분)</p><ul><li>묵은지 1/4포기</li><li>돼지고기 앞다리살 200g</li><li>두부 반 모, 대파 1대</li></ul>"
     "<p><b>순서</b></p><ol><li>고기를 먼저 볶다가 김치를 넣고 함께 볶아요</li><li>물 500ml를 붓고 15분 끓여요</li>"
     "<li>두부와 대파를 넣고 5분 더 끓여요</li></ol>"),
    ("여행 준비", "teal", False,
     "<p>12월 제주 2박 3일</p><ul><li>렌터카 예약</li><li>숙소 체크인 15시</li><li>우산, 보조배터리</li></ul>"),
]
TRASH = [("지난 장보기", "gray", "<p>휴지통 시연용 메모</p>"), ("빈 메모", "gray", "<p>휴지통 시연용 메모 2</p>")]


def seed(db, M, theme: str, ai: bool, height: int = MEASURE_H) -> dict[str, int]:
    from PyQt6.QtGui import QTextDocument

    import memo_document

    from theme import apply as A
    from theme import tokens as T

    def html(body: str) -> str:
        # 앱처럼 문서 기본 글꼴을 앱 글꼴로 정한 뒤 저장한다. 빈 문서로 저장하면 9pt가 박힌다
        doc = QTextDocument()
        doc.setDefaultFont(A.memo_font(T.FONT_FAMILY, FONT_PT))
        doc.setHtml(body)
        return memo_document.saved_html(doc)

    ids: dict[str, int] = {}
    for i, (title, color, pinned, body) in enumerate(MEMOS):
        m = db.create(title, html(body), color)
        if pinned:
            db.set_pinned(m.id, True)
        stamp = f"2026-11-{20 - i:02d}T10:00:00"  # 뒤로 갈수록 오래된 메모
        db.conn.execute("UPDATE memos SET created_at = ?, updated_at = ? WHERE id = ?", (stamp, stamp, m.id))
        ids[title] = m.id
    for title, color, body in TRASH:
        db.soft_delete(db.create(title, html(body), color).id)
    db.conn.commit()
    for key, value in {
        A.THEME_MODE_KEY: theme, "ai_enabled": "1" if ai else "0", "ai_provider": "anthropic",
        "ai_model": "claude-haiku-5-5", "ai_show_preview": "0", M.WHATS_NEW_KEY: M.APP_VERSION,
    }.items():
        db.set_setting_str(key, value)
    for key, value in {
        M.GUIDE_BAR_KEY: 1, M.GUIDE_BODY_KEY: 1, "height_ratio_v2_migrated": 1, "window_width": 520,
        "window_height": height, "window_y": 0, "side": 0, "sort_mode": 0, M.PAPER_NOTICE_KEY: 0,
        "app_font_size": FONT_PT,
    }.items():
        db.set_setting_int(key, value)
    return ids


# ---------------------------------------------------------------- 그리기
def setup_app():
    tmp = guard()
    os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"  # 앱과 같은 글꼴 엔진 (main.py)
    import main as M

    for name in ("APP_DIR", "IMAGES_DIR"):
        setattr(M, name, tmp if name == "APP_DIR" else tmp / "images")
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtWidgets import QApplication, QWidget

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([])
    app.setCursorFlashTime(0)  # 커서가 깜박이지 않게 (보일 때는 늘 보이고, 포커스를 빼면 안 보인다)
    M.install_tooltips(app)
    M._register_fonts()

    def offscreen_show(self):  # 화면에 띄우지 않고 그리기만
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        QWidget.show(self)

    M.UpdateChecker.start = lambda self: None
    M.SlideMemoWindow._register_hotkey = lambda self: None  # 전역 단축키를 잡지 않는다
    M.SlideMemoWindow._force_topmost = lambda self: None
    M.SlideMemoWindow._screen_rect = lambda self: QRect(0, 0, 1920, 1080)
    M.SlideMemoWindow.show = offscreen_show
    M.EdgeLogoButton.show = offscreen_show
    return tmp, M, app


def wait(ms: int = 400) -> None:
    from PyQt6.QtTest import QTest

    QTest.qWait(ms)


def on_desk(pm, desk: str = DESK):
    """반투명 창을 바깥 색 위에 얹는다. 알파 없는 RGB 그림.
    탭 아래 빈 자리도 이 색으로 보여서, 어두운 화면은 어두운 바깥 색(DESK_DARK)을 쓴다."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    img = QImage(pm.size(), QImage.Format.Format_RGB32)
    img.fill(QColor(desk))
    p = QPainter(img)
    pm2 = pm.copy()
    pm2.setDevicePixelRatio(1.0)
    p.drawPixmap(0, 0, pm2)
    p.end()
    return img.convertToFormat(QImage.Format.Format_RGB888)


def save_png(img, name: str) -> None:
    """화질 손실 없이 가장 세게 압축한다 (PNG, zlib 9 + Pillow optimize)."""
    from io import BytesIO

    from PIL import Image
    from PyQt6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    pil = Image.open(BytesIO(bytes(buf.data()))).convert("RGB")
    pil.save(OUT / f"{name}.png", optimize=True, compress_level=9)


def panel_shots() -> None:
    import math

    tmp, M, app = setup_app()
    # 1) 높은 창으로 띄워, 탭 줄과 본문(+AI 단추 줄)에 남는 높이를 잰다
    need = 0
    for name in PANEL:
        win, db = open_panel(tmp, M, app, name, MEASURE_H)
        tabs = win.tab_scroll
        tab_slack = tabs.viewport().height() - tabs.widget().sizeHint().height()
        doc_h = math.ceil(win.editor.document().size().height())
        body_slack = win.editor.viewport().height() - doc_h
        need = max(need, MEASURE_H - min(tab_slack, body_slack))
        close_panel(win, db)
    # 2) 가장 많이 필요한 높이 + 여유. 1.5배에서 픽셀이 딱 떨어지게 짝수로
    height = need + MARGIN_H
    height += height % 2
    print(f"메모 패널 높이: 필요 {need} + 여유 {MARGIN_H} → {height} (그림 {int(height * 1.5)}px)")
    for name in PANEL:
        win, db = open_panel(tmp, M, app, name, height)
        check_panel(win, name)
        save_png(on_desk(win.grab(), DESK_DARK if name == "dark-mode" else DESK), name)
        close_panel(win, db)


def open_panel(tmp, M, app, name: str, height: int):
    """시연용 DB를 새로 만들어 이 그림의 메모를 연 창을 띄운다."""
    db = M.MemoDatabase(tmp / f"{name}-{height}.db")
    theme = "dark" if name == "dark-mode" else "light"
    ids = seed(db, M, theme, ai=(name == "ai-toolbar"), height=height)
    from theme import apply as A

    A.request_color_scheme(theme)
    A.apply_theme(app, A.resolve_mode(theme))
    win = M.SlideMemoWindow(db)
    win.show()
    open_title = {"card": "주간 회의 준비", "search": "주간 회의 준비",
                  "dark-mode": "여행 준비", "ai-toolbar": "김치찌개 레시피"}[name]
    win.select_memo(ids[open_title])
    win.expand()
    wait(600)
    if name == "search":
        win.search_input.setFocus()
        win.search_input.setText("회의")
        win.search_input.end(False)
    else:
        win.setFocus()  # 검색 칸·본문에서 포커스를 빼 커서가 보이지 않게
    wait(600)
    return win, db


def close_panel(win, db) -> None:
    from PyQt6.QtWidgets import QApplication

    win._quitting = True
    win.close()
    db.close()
    QApplication.processEvents()


def check_panel(win, name: str) -> None:
    """탭 제목이 잘리거나 탭 바가 스크롤되면 멈춘다 (맞추지 않고 알린다)."""
    from PyQt6.QtWidgets import QAbstractScrollArea

    for area in win.findChildren(QAbstractScrollArea):  # 탭 줄과 본문 모두
        bar = area.verticalScrollBar()
        if bar.maximum() > 0 and area.isVisible():
            raise SystemExit(f"{name}: {area.objectName() or type(area).__name__}이(가) 스크롤돼요 ({bar.maximum()})")
    if name == "card":  # 블로그는 위쪽 500px만 보여 줄 때가 있다: 검색 칸·제목·툴바·본문 첫 줄이 그 안에
        from PyQt6.QtGui import QTextCursor

        first = win.editor.cursorRect(QTextCursor(win.editor.document()))
        bottom = win.editor.viewport().mapTo(win, first.bottomLeft()).y() * 1.5
        if bottom > 500:
            raise SystemExit(f"card: 본문 첫 줄이 위쪽 500px 밖이에요 ({bottom:.0f}px)")
    if name == "ai-toolbar":
        bar = win._ai_bar
        assert bar.isVisible(), "AI 단추 줄이 안 보여요"
        need = bar.sizeHint().width()
        if need > bar.width():
            raise SystemExit(f"AI 단추 다섯 개가 한 줄에 안 들어가요 (필요 {need}, 자리 {bar.width()})")


def setting_shot() -> None:
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
    from PyQt6.QtWidgets import QScrollArea, QTabWidget

    tmp, M, app = setup_app()
    import settings_dialog as SD

    db = M.MemoDatabase(tmp / "setting.db")
    seed(db, M, "light", ai=True)
    from theme import apply as A

    A.request_color_scheme("light")
    A.apply_theme(app, A.resolve_mode("light"))
    dlg = SD.SettingsDialog(db, tab="ai")
    tabs = dlg.findChild(QTabWidget)
    tabs.setCurrentIndex(1)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dlg.show()
    wait(300)
    # AI 탭 내용이 스크롤 없이 다 보이는 높이로 (앱이 정한 창 높이를 그대로 쓰고, 모자라면 알린다)
    area = tabs.currentWidget() if isinstance(tabs.currentWidget(), QScrollArea) else tabs.currentWidget().findChild(QScrollArea)
    if area is not None and area.verticalScrollBar().maximum() > 0:
        print(f"알림: 설정 창 기본 높이에서는 AI 탭이 {area.verticalScrollBar().maximum()}px 스크롤돼요. 높이를 늘려 그려요.")
        dlg.resize(dlg.width(), dlg.height() + area.verticalScrollBar().maximum())
        wait(300)
        assert area.verticalScrollBar().maximum() == 0, "늘려도 스크롤이 남아요"
    dlg._model_combo.lineEdit().setCursorPosition(0)
    dlg.setFocus()
    wait(200)
    body = dlg.grab()
    # Qt는 Windows가 그리는 제목 표시줄을 그리지 않는다 → 지금 블로그 그림과 같은 모양으로 그려 붙인다
    dpr = body.devicePixelRatio()
    title_h, edge = 45, 2
    w, h = body.width() / dpr + 2 * edge, body.height() / dpr + title_h + edge
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_RGB32)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor("#F3F3F3"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon = M.load_app_icon()
    if icon is not None:
        p.drawPixmap(14, 13, icon.pixmap(20, 20))
    font = QFont(app.font())
    font.setPointSizeF(app.font().pointSizeF() * 1.25)
    p.setFont(font)
    p.setPen(QColor("#1A1A1A"))
    p.drawText(QRect(44, 0, 200, title_h), Qt.AlignmentFlag.AlignVCenter, "설정")
    p.setPen(QPen(QColor("#1A1A1A"), 1.2))
    cx, cy = w - 24, title_h / 2
    p.drawLine(int(cx - 7), int(cy - 7), int(cx + 7), int(cy + 7))
    p.drawLine(int(cx - 7), int(cy + 7), int(cx + 7), int(cy - 7))
    body.setDevicePixelRatio(dpr)
    p.drawPixmap(edge, title_h, body)
    p.end()
    save_png(img.convertToFormat(QImage.Format.Format_RGB888), "ai-setting")
    dlg.close()
    db.close()


if __name__ == "__main__":
    if "--panel" in sys.argv or "--setting" in sys.argv:
        OUT = Path(sys.argv[-1])
        panel_shots() if "--panel" in sys.argv else setting_shot()
        sys.stdout.flush()
    else:
        main_driver()
