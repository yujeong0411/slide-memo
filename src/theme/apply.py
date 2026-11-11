"""화면 모드 적용: 팔레트 → app.qss → 아이콘 색. SlideMemo-design.md 6.2."""
from __future__ import annotations

import atexit
import re
import sys
import weakref
from pathlib import Path
from string import Template

from PyQt6.QtCore import QEvent, QObject, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QProxyStyle, QStyle, QWidget

import database
from theme import tokens as T
from theme.memo_tokens import memo_tokens, mix

_mode = "light"
_QSS_SOURCES: dict[str, str] = {}
_RGBA_RE = re.compile(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)")
_TINT_CACHE: dict[tuple[str, str, int, float], QPixmap] = {}
_QSS_ICONS = {"chevron-down": "fg_secondary", "chevron-up": "fg_secondary", "check": "on_accent"}
_CLASS_FONTS = {"QMenu": "body", "QMessageBox": "body"}


def resource_path(name: str) -> Path:
    """배포본이면 번들 폴더, 개발 중이면 프로젝트 루트 기준."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / name


def asset_path(name: str) -> Path:
    return resource_path(f"assets/{name}")


def current() -> dict[str, str]:
    return T.MODES[_mode]


def current_mode() -> str:
    return _mode


def _qss_source(name: str) -> str:
    if name not in _QSS_SOURCES:
        _QSS_SOURCES[name] = (Path(__file__).parent / name).read_text(encoding="utf-8")
    return _QSS_SOURCES[name]


THEME_MODE_KEY = "theme_mode"  # system / light / dark


def resolve_mode(setting: str) -> str:
    """저장된 화면 모드 → 실제 모드. 모르는 값이면 시스템을 따른다."""
    return setting if setting in T.MODES else system_mode()


def request_color_scheme(setting: str) -> None:
    """Qt에도 알린다. Windows 제목 표시줄을 Qt가 이 값에 맞춰 칠한다."""
    schemes = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}
    QGuiApplication.styleHints().setColorScheme(schemes.get(setting, Qt.ColorScheme.Unknown))


def system_mode() -> str:
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return "dark" if dark else "light"


def qcolor(value: str) -> QColor:
    """토큰 값(#RRGGBB 또는 rgba(...)) → QColor."""
    match = _RGBA_RE.fullmatch(value)
    if match is None:
        return QColor(value)
    color = QColor(*(int(match[i]) for i in (1, 2, 3)))
    color.setAlphaF(float(match[4]))
    return color


def base_font(kind: str = "body") -> QFont:
    px, _, weight = T.TYPE[kind]
    font = QFont(T.FONT_FAMILY)
    font.setPixelSize(px)
    font.setWeight(QFont.Weight(weight))
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, T.LETTER_SPACING_PERCENT)
    return refine_font(font)


def refine_font(font: QFont) -> QFont:
    """회색조로 다듬는다 (2.1). 실제 회색조는 main()의 FreeType 글꼴 엔진이 만든다."""
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias
    )
    return font


def memo_font(family: str, point_size: int) -> QFont:
    return refine_font(QFont(family, point_size))


def tabular_font(font: QFont) -> QFont:
    font.setFeature(QFont.Tag("tnum"), 1)
    return font


def set_tabular(widget: QWidget) -> None:
    widget.setFont(tabular_font(widget.font()))


def repolish(widget: QWidget) -> None:
    """동적 속성을 바꾼 뒤 QSS를 다시 적용한다."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def tinted_pixmap(asset_name: str, color: str, size: int) -> QPixmap:
    """SVG 아이콘에 토큰 색을 입힌다. SVG에는 색을 넣지 않는다 (4.9)."""
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    key = (asset_name, color, size, dpr)
    cached = _TINT_CACHE.get(key)
    if cached is not None:
        return cached
    base = QIcon(str(asset_path(asset_name))).pixmap(QSize(size, size), dpr)
    tinted = QPixmap(base.size())
    tinted.setDevicePixelRatio(base.devicePixelRatio())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    _TINT_CACHE[key] = tinted
    return tinted


class _AppStyle(QProxyStyle):
    """QSS로 못 정하는 값: 단추 순서(오른쪽 끝이 주된 동작), 툴팁 지연."""

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_DialogButtonLayout:
            return QDialogButtonBox.ButtonLayout.MacLayout.value
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 500
        return super().styleHint(hint, option, widget, return_data)


_RELEASES: list = []


def release_watchers() -> None:
    """등록된 감시자를 모두 지금 뗀다. main()이 끝날 때 한 번 부른다."""
    for release in list(_RELEASES):
        release()


def release_on_quit(watcher: QObject, before=None, after=None) -> None:
    """앱 전체 감시자(installEventFilter)를 종료 때 먼저 뗀다.

    떼지 않으면 Python이 종료하며 모듈을 치우는 중에도 Qt가 이벤트를 보내고,
    감시자 안에서 난 예외 때문에 PyQt가 프로세스를 중단한다(0xC0000409).
    순서: before(타이머 멈춤) → 감시 해제 → after(창 숨기고 지우기).
    정상 종료(aboutToQuit), main()의 끝(release_watchers), 이벤트 루프 없이 끝나는 경우(atexit) 중
    먼저 오는 쪽에서 한 번만 한다. main()이 끝나며 앱 객체가 정리될 때 감시자가 남아 있으면
    이미 지워진 창을 건드려 같은 중단이 난다.
    감시자는 약한 참조로만 들고 있어 수명을 늘리지 않는다."""
    ref = weakref.ref(watcher)
    done: list[bool] = []

    def release() -> None:
        obj = ref()
        if done or obj is None:
            return
        done.append(True)
        try:
            if before is not None:
                before(obj)
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(obj)
            if after is not None:
                after(obj)
        except RuntimeError:  # Qt 쪽 객체가 이미 지워졌다
            pass

    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(release)
    atexit.register(release)
    _RELEASES.append(release)


class _WindowPolisher(QObject):
    """Qt가 직접 만드는 창에 글꼴을 준다. 클래스별 시스템 글꼴은 테마 변경 때 되돌아가므로
    뜰 때마다 지정한다."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind != QEvent.Type.Polish:
            return False
        class_name = obj.metaObject().className()
        if kind == QEvent.Type.Polish and class_name in _CLASS_FONTS:
            obj.setFont(base_font(_CLASS_FONTS[class_name]))
        return False


def _palette(t: dict[str, str]) -> QPalette:
    """Windows 강조색이 끼어들지 않게 팔레트를 토큰으로 고정한다."""
    role = QPalette.ColorRole
    palette = QPalette()
    for r, token in (
        (role.Window, "bg_canvas"), (role.Base, "bg_canvas"), (role.AlternateBase, "bg_sunken"),
        (role.Button, "bg_canvas"), (role.WindowText, "fg"), (role.Text, "fg"),
        (role.ButtonText, "fg"), (role.BrightText, "fg"), (role.PlaceholderText, "fg_hint"),
        (role.ToolTipBase, "contrast"), (role.Accent, "accent"),
        (role.Link, "accent_text"), (role.LinkVisited, "accent_text"),
    ):
        palette.setColor(r, qcolor(t[token]))
    palette.setColor(role.ToolTipText, QColor(T.WHITE))
    palette.setColor(role.Highlight, QColor(T.SELECTION_BG))
    palette.setColor(role.HighlightedText, QColor(T.SELECTION_FG))
    for r in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, r, qcolor(t["fg_disabled"]))
    return palette


def _write_qss_icons(mode: str, t: dict[str, str]) -> dict[str, str]:
    """QSS의 url()은 파일만 받으므로 모드별로 색을 넣은 SVG를 만들어 둔다."""
    folder = Path(database.APP_DIR) / "theme_cache" / mode
    folder.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name, token in _QSS_ICONS.items():
        svg = asset_path(f"{name}.svg").read_text(encoding="utf-8")
        target = folder / f"{name}.svg"
        target.write_text(svg.replace("currentColor", t[token]), encoding="utf-8")
        paths[f"icon_{name.replace('-', '_')}"] = target.as_posix()
    return paths


def _qss_values(mode: str, t: dict[str, str]) -> dict[str, object]:
    secondary_bg = t["bg_canvas"] if mode == "light" else t["bg_muted"]
    values: dict[str, object] = dict(t)
    values.update(
        white=T.WHITE,
        selection_bg=T.SELECTION_BG,
        selection_fg=T.SELECTION_FG,
        secondary_bg=secondary_bg,
        secondary_border=t["line_strong"] if mode == "light" else "transparent",
        secondary_hover=mix(t["fg"], secondary_bg, 0.08),
        secondary_press=mix(t["fg"], secondary_bg, 0.16),
        primary_hover=mix(t["fg"], t["accent"], 0.08),
        danger_hover=mix(t["fg"], t["danger_fill"], 0.08),
        danger_press=mix(t["fg"], t["danger_fill"], 0.16),
        caption_px=T.TYPE["caption"][0],
        label_px=T.TYPE["label"][0],
        body_px=T.TYPE["body"][0],
        title_px=T.TYPE["title"][0],
        md_h=T.CONTROL["md"][0],
        md_inner=T.CONTROL["md"][0] - 2,  # 투명 테두리 1px씩을 뺀 안쪽 높이
        md_pad=T.CONTROL["md"][1] - 1,
        sm_inner=T.CONTROL["sm"][0] - 2,
        sm_pad=T.CONTROL["sm"][1] - 1,
        r_control=T.RADIUS["control"],
        r_small=T.RADIUS["small"],
        r_surface=T.RADIUS["surface"],
    )
    values.update(_write_qss_icons(mode, t))
    return values


def apply_theme(app: QApplication, mode: str) -> None:
    global _mode
    if mode not in T.MODES:
        raise ValueError(f"잘못된 화면 모드: {mode!r}")
    _mode = mode
    t = current()
    if not isinstance(app.style(), _AppStyle):
        app.setStyle(_AppStyle("Fusion"))
        app._window_polisher = _WindowPolisher(app)
        app.installEventFilter(app._window_polisher)
        release_on_quit(app._window_polisher)
    app.setFont(base_font("body"))
    app.setPalette(_palette(t))
    app.setStyleSheet(Template(_qss_source("app.qss")).substitute(_qss_values(mode, t)))


def _body_corners(side: str) -> str:
    """모니터 쪽(바와 맞닿는 면)은 각지게, 안쪽만 둥글게. 맞닿는 면에는 테두리가 없다 (4.1)."""
    r = T.RADIUS["surface"]
    near, far = ("right", "left") if side == "right" else ("left", "right")
    return (
        f"border-top-{far}-radius: {r}px; border-bottom-{far}-radius: {r}px;"
        f" border-top-{near}-radius: 0; border-bottom-{near}-radius: 0; border-{near}: none;"
    )


def apply_memo(body: QWidget, color: str, side: str) -> dict[str, str]:
    """메모 창 안쪽에 memo.qss를 적용하고 계산한 토큰을 돌려준다."""
    tokens = memo_tokens(color, _mode)
    values: dict[str, object] = dict(tokens)
    values.update(
        body_corners=_body_corners(side),
        danger_fill=current()["danger_fill"],
        selection_bg=T.SELECTION_BG,
        selection_fg=T.SELECTION_FG,
        title_px=T.TYPE["title"][0],
        r_control=T.RADIUS["control"],
        md_inner=T.CONTROL["md"][0] - 2,
        md_pad=T.CONTROL["md"][1] - 1,
        sm_inner=T.CONTROL["sm"][0] - 2,
        sm_pad=T.CONTROL["sm"][1] - 1,
    )
    body.setStyleSheet(Template(_qss_source("memo.qss")).substitute(values))
    return tokens
