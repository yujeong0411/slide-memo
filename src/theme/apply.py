"""화면 모드 적용: 팔레트 → app.qss → 아이콘 색. SlideMemo-design.md 6.2."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from string import Template

from PyQt6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QRegion,
)
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QProxyStyle, QStyle, QWidget

import database
from theme import tokens as T
from theme.memo_tokens import mix

_mode = "light"
_RGBA_RE = re.compile(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)")
_TINT_CACHE: dict[tuple[str, str, int, float], QPixmap] = {}
_QSS_ICONS = {"chevron_down": "fg_secondary", "chevron_up": "fg_secondary", "check": "on_accent"}
_CLASS_FONTS = {"QMenu": "body", "QMessageBox": "body", "QTipLabel": "caption"}


def resource_path(name: str) -> Path:
    """배포본이면 번들 폴더, 개발 중이면 프로젝트 루트 기준."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / name


def asset_path(name: str) -> Path:
    return resource_path(f"assets/{name}")


def current() -> dict[str, str]:
    return T.MODES[_mode]


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
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


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


class _WindowPolisher(QObject):
    """Qt가 직접 만드는 창에 글꼴을 준다. 클래스별 시스템 글꼴은 테마 변경 때 되돌아가므로
    뜰 때마다 지정한다. 툴팁 창은 투명 처리가 안 먹어 마스크로 모서리를 둥글게 깎는다."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind not in (QEvent.Type.Polish, QEvent.Type.Resize):
            return False
        class_name = obj.metaObject().className()
        if kind == QEvent.Type.Polish and class_name in _CLASS_FONTS:
            obj.setFont(base_font(_CLASS_FONTS[class_name]))
        elif kind == QEvent.Type.Resize and class_name == "QTipLabel":
            path = QPainterPath()
            path.addRoundedRect(QRectF(obj.rect()), T.RADIUS["control"], T.RADIUS["control"])
            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
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
        paths[f"icon_{name}"] = target.as_posix()
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
    app.setFont(base_font("body"))
    app.setPalette(_palette(t))
    source = (Path(__file__).parent / "app.qss").read_text(encoding="utf-8")
    app.setStyleSheet(Template(source).substitute(_qss_values(mode, t)))
