"""메모 색: 제목 옆 색 단추, 색 팝업, 메모 색 만들기 대화창. SlideMemo-design.md 3.0, 4.4, 4.7."""
from __future__ import annotations

import re

from PyQt6.QtCore import QRectF, QRegularExpression, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QAbstractButton,
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from theme import apply as A
from theme import tokens as T
from theme.memo_tokens import face_and_band, memo_tokens
from theme.widgets import AppDialog, PopupPanel, make_button, role_label

_HEX_RE = re.compile(r"#[0-9A-F]{6}")
_SWATCH = 36
_SWATCH_RADIUS = T.RADIUS["control"]
_BAND_HEIGHT = 6
_CELL = 44  # 견본 36 + 고리 자리 4씩. 견본 사이가 8이 된다


def normalized_hex(text: str) -> str | None:
    value = text.strip().upper()
    if not value.startswith("#"):
        value = "#" + value
    return value if _HEX_RE.fullmatch(value) else None


class ColorSwatch(QAbstractButton):
    """면 색 + 아래 띠 견본. color가 None이면 + 단추로 그린다."""

    def __init__(self, color: str | None, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.selected = False
        self.setFixedSize(_CELL, _CELL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip(tooltip)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_CELL, _CELL)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = A.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = (_CELL - _SWATCH) / 2
        box = QRectF(inset, inset, _SWATCH, _SWATCH)
        path = QPainterPath()
        path.addRoundedRect(box, _SWATCH_RADIUS, _SWATCH_RADIUS)

        if self.color is None:
            painter.setPen(QPen(A.qcolor(t["line_strong"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            plus = A.tinted_pixmap("plus.svg", t["fg_secondary"], 16)
            painter.drawPixmap(int((_CELL - 16) / 2), int((_CELL - 16) / 2), plus)
        else:
            face, band = face_and_band(self.color, A.current_mode())
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(box, QColor(face))
            painter.fillRect(
                QRectF(inset, inset + _SWATCH - _BAND_HEIGHT, _SWATCH, _BAND_HEIGHT), QColor(band)
            )
            painter.restore()
            painter.setPen(QPen(A.qcolor(t["line"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(A.qcolor(t["overlay_hover"]))
            painter.drawPath(path)
        if self.selected:  # 2px 틈 + 2px 고리
            painter.setPen(QPen(A.qcolor(t["fg"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        painter.end()


class MemoColorPopup(PopupPanel):
    """고르면 바로 바뀌고 닫히지 않는다. 바깥을 누르거나 Esc로 닫는다."""

    picked = pyqtSignal(str)
    add_requested = pyqtSignal()
    menu_requested = pyqtSignal(str)

    def __init__(self, current: str, customs: list[str], owner: QWidget | None = None) -> None:
        super().__init__(owner)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(4)
        self._swatches: list[ColorSwatch] = []

        self.body.addWidget(role_label("메모 색", "group"))
        grid = QGridLayout()
        grid.setSpacing(0)
        for index, (key, preset) in enumerate(T.MEMO_PRESETS.items()):
            grid.addWidget(self._swatch(key, preset[0]), index // 4, index % 4)
        self.body.addLayout(grid)

        self.body.addSpacing(4)
        self.body.addWidget(role_label("직접 만든 색", "group"))
        custom_row = QHBoxLayout()
        custom_row.setSpacing(0)
        for color in customs:
            swatch = self._swatch(color, color)
            swatch.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            swatch.customContextMenuRequested.connect(
                lambda _pos, c=color: self.menu_requested.emit(c)
            )
            custom_row.addWidget(swatch)
        add = ColorSwatch(None, "색 만들기")
        add.clicked.connect(self.add_requested)
        custom_row.addWidget(add)
        custom_row.addStretch(1)
        self.body.addLayout(custom_row)
        self.set_current(current)

    def _swatch(self, color: str, tooltip: str) -> ColorSwatch:
        swatch = ColorSwatch(color, tooltip)
        swatch.clicked.connect(lambda _checked=False, c=color: self.picked.emit(c))
        self._swatches.append(swatch)
        return swatch

    def set_current(self, color: str) -> None:
        for swatch in self._swatches:
            swatch.set_selected(swatch.color == color)


class MemoColorButton(QToolButton):
    """제목 옆 색 단추: 지름 14 띠 색 원 + 셰브런."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("colorBtn")
        self.setFixedSize(44, T.CONTROL["sm"][0])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("메모 색")
        self._band = T.MEMO_PRESETS[T.DEFAULT_MEMO_COLOR][2]
        self._chevron = T.LIGHT["fg_secondary"]

    def set_appearance(self, band: str, chevron: str) -> None:
        self._band, self._chevron = band, chevron
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._band))
        painter.drawEllipse(QRectF(6, (self.height() - 14) / 2, 14, 14))
        painter.drawPixmap(
            24, (self.height() - 16) // 2, A.tinted_pixmap("chevron-down.svg", self._chevron, 16)
        )
        painter.end()


class _Preview(QWidget):
    """메모 면과 탭 미리 보기."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        self._color: str | None = None

    def set_color(self, color: str | None) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._color is None:
            return
        tokens = memo_tokens(self._color, A.current_mode())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(area, T.RADIUS["control"], T.RADIUS["control"])
        painter.setClipPath(path)
        painter.fillRect(area, QColor(tokens["memo_face"]))
        tab_left = area.right() - 32
        painter.fillRect(QRectF(area.right() - 4, 0, 4, area.height()), QColor(tokens["memo_band"]))

        painter.setPen(QColor(tokens["memo_fg"]))
        painter.setFont(A.base_font("body_strong"))
        painter.drawText(QRectF(12, 12, area.width() - 60, 22), Qt.AlignmentFlag.AlignVCenter, "미리 보기")
        painter.setPen(QColor(tokens["memo_fg_secondary"]))
        painter.setFont(A.base_font("caption"))
        painter.drawText(
            QRectF(12, 36, area.width() - 60, 18), Qt.AlignmentFlag.AlignVCenter,
            "메모 면은 고른 색을 옅게 풀어 자동으로 만들어요",
        )
        painter.setPen(QColor(tokens["memo_fg"]))
        painter.setFont(A.base_font("label"))
        painter.drawText(QRectF(tab_left, 8, 28, 18), Qt.AlignmentFlag.AlignCenter, "메")
        painter.drawText(QRectF(tab_left, 26, 28, 18), Qt.AlignmentFlag.AlignCenter, "모")
        painter.setClipping(False)
        painter.setPen(QPen(A.qcolor(A.current()["line"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), T.RADIUS["control"], T.RADIUS["control"])
        painter.end()


class _HexSwatch(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._color: str | None = None

    def set_color(self, color: str | None) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(A.qcolor(A.current()["line"]), 1))
        painter.setBrush(QColor(self._color) if self._color else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        painter.end()


class MemoColorDialog(AppDialog):
    """사용자는 색 하나만 고른다. 띠와 면은 앱이 계산한다 (3.0.1)."""

    def __init__(self, color: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__("메모 색 바꾸기" if color else "메모 색 만들기", parent)
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(QLabel("색"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self._swatch = _HexSwatch()
        row.addWidget(self._swatch)
        self.hex_edit = QLineEdit(color or T.CUSTOM_COLOR_START)
        self.hex_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("#?[0-9a-fA-F]{0,6}"))
        )
        A.set_tabular(self.hex_edit)
        row.addWidget(self.hex_edit, 1)
        pick: QPushButton = make_button("색 고르기")
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        box.addLayout(row)
        self.body.addLayout(box)
        self.body.addWidget(role_label("글자가 잘 보이도록 띠 색의 밝기는 앱이 조금 고칠 수 있어요.", "hint"))
        self._preview = _Preview()
        self.body.addWidget(self._preview)

        self._action = self.add_actions("바꾸기" if color else "만들기")
        self.hex_edit.textChanged.connect(self._refresh)
        self._refresh()
        self.hex_edit.setFocus()
        self.hex_edit.selectAll()

    def _refresh(self) -> None:
        color = normalized_hex(self.hex_edit.text())
        self._swatch.set_color(color)
        self._preview.set_color(color)
        self._action.setEnabled(color is not None)

    def _pick(self) -> None:
        start = QColor(normalized_hex(self.hex_edit.text()) or T.CUSTOM_COLOR_START)
        chosen = QColorDialog.getColor(
            start, self, "색 고르기", QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        if chosen.isValid():
            self.hex_edit.setText(chosen.name().upper())

    def value(self) -> str:
        return normalized_hex(self.hex_edit.text()) or T.CUSTOM_COLOR_START
