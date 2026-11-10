"""화면 모드를 따르는 공용 부품: 메뉴, 콤보 목록, 대화창, 메시지 창."""
from __future__ import annotations

import re

from PyQt6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QAction, QFontMetrics, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from theme import apply as A
from theme import tokens as T

APP_NAME = "SlideMemo"
_MENU_ICON = 16
_MNEMONIC_RE = re.compile(r"\(&\w\)")
# Qt 기본 편집 메뉴의 objectName → 아이콘
_STANDARD_ICONS = {
    "edit-undo": "menu_undo.svg",
    "edit-redo": "menu_redo.svg",
    "edit-cut": "menu_cut.svg",
    "edit-copy": "menu_copy.svg",
    "edit-paste": "menu_paste.svg",
    "edit-delete": "menu_delete.svg",
    "select-all": "menu_select_all.svg",
    "link-copy": "menu_link.svg",
}


class ThemedMenu(QMenu):
    """QSS로는 항목별 색(위험 항목, 단축키, 묶음 제목)을 줄 수 없어 직접 그린다 (4.3)."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(200)

    def add_item(
        self, text: str, icon: str = "", *, shortcut: str = "", danger: bool = False
    ) -> QAction:
        action = self.addAction(f"{text}\t{shortcut}" if shortcut else text)
        action.setProperty("icon_asset", icon)
        action.setProperty("danger", danger)
        return action

    def add_section(self, title: str) -> QAction:
        action = self.addAction(title)
        action.setEnabled(False)
        action.setProperty("section", True)
        return action

    def add_submenu(self, title: str, icon: str = "") -> "ThemedMenu":
        submenu = ThemedMenu(title, self)
        self.addMenu(submenu)
        submenu.menuAction().setProperty("icon_asset", icon)
        return submenu

    def adopt_standard_actions(self, source: QMenu) -> None:
        """Qt 기본 편집 메뉴의 항목을 옮겨 온다. source는 이 메뉴의 자식으로 남긴다."""
        source.setParent(self, source.windowFlags())
        for action in source.actions():
            action.setText(_MNEMONIC_RE.sub("", action.text()).replace("&", ""))
            action.setProperty("icon_asset", _STANDARD_ICONS.get(action.objectName(), ""))
            self.addAction(action)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = A.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = T.RADIUS["control"]
        painter.setPen(QPen(A.qcolor(t["line"]), 1))
        painter.setBrush(A.qcolor(t["bg_raised"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        for action in self.actions():
            if action.isVisible():
                self._paint_action(painter, action, t, radius)
        painter.end()

    def _paint_action(self, painter: QPainter, action: QAction, t: dict[str, str], radius: int) -> None:
        rect = self.actionGeometry(action)
        if action.isSeparator():
            painter.setPen(A.qcolor(t["line"]))
            y = rect.center().y()
            painter.drawLine(rect.left() + 4, y, rect.right() - 4, y)
            return
        if action.property("section"):
            painter.setFont(A.base_font("label"))
            painter.setPen(A.qcolor(t["fg_secondary"]))
            painter.drawText(
                rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                action.text(),
            )
            return

        enabled = action.isEnabled()
        if enabled and self.activeAction() == action:
            pressed = QApplication.mouseButtons() & Qt.MouseButton.LeftButton
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(A.qcolor(t["overlay_press" if pressed else "overlay_hover"]))
            painter.drawRoundedRect(QRectF(rect), radius, radius)

        danger = bool(action.property("danger")) and enabled
        text_color = t["fg_disabled"] if not enabled else t["danger"] if danger else t["fg"]
        icon_color = t["danger"] if danger else t["fg_disabled"] if not enabled else t["fg_secondary"]
        icon = action.property("icon_asset")
        center_y = rect.center().y()
        icon_top = center_y - _MENU_ICON // 2 + 1
        if icon:
            painter.drawPixmap(
                rect.left() + 8, icon_top, A.tinted_pixmap(icon, icon_color, _MENU_ICON)
            )

        label, _, shortcut = action.text().partition("\t")
        shortcut = shortcut or action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        content = rect.adjusted(8 + _MENU_ICON + 8, 0, -12, 0)
        painter.setFont(A.base_font("body"))
        painter.setPen(A.qcolor(text_color))
        painter.drawText(content, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        if action.menu() is not None:
            painter.drawPixmap(
                rect.right() - 12 - _MENU_ICON + 1, icon_top,
                A.tinted_pixmap("chevron_right.svg", t["fg_secondary"], _MENU_ICON),
            )
        elif shortcut:
            painter.setFont(A.tabular_font(A.base_font("caption")))
            painter.setPen(A.qcolor(t["fg_hint"]))
            painter.drawText(content, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, shortcut)


class _ComboDelegate(QStyledItemDelegate):
    """콤보 목록: 고른 항목은 왼쪽 체크로만 표시한다 (1.2)."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: N802
        text_w = QFontMetrics(option.font).horizontalAdvance(str(index.data()))
        return QSize(8 + _MENU_ICON + 8 + text_w + 12, T.CONTROL["md"][0])

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        t = A.current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect: QRect = option.rect
        if option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(A.qcolor(t["overlay_hover"]))
            painter.drawRoundedRect(QRectF(rect), T.RADIUS["control"], T.RADIUS["control"])
        if index.row() == self._combo.currentIndex():
            painter.drawPixmap(
                rect.left() + 8, rect.center().y() - _MENU_ICON // 2 + 1,
                A.tinted_pixmap("menu_check.svg", t["fg"], _MENU_ICON),
            )
        painter.setPen(A.qcolor(t["fg"]))
        painter.drawText(
            rect.adjusted(8 + _MENU_ICON + 8, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(index.data()),
        )
        painter.restore()


def themed_combo(combo: QComboBox) -> QComboBox:
    combo.setItemDelegate(_ComboDelegate(combo))
    popup = combo.view().window()
    popup.setWindowFlags(
        Qt.WindowType.Popup
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return combo


def line() -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "line")
    frame.setFixedHeight(1)
    return frame


def role_label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label


def make_button(text: str, variant: str = "secondary") -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", variant)
    return button


class AppDialog(QDialog):
    """확인·입력 대화창. OS 제목 표시줄에는 앱 이름만, 창 안 머리에 문장을 쓴다 (9장 11)."""

    def __init__(self, head: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(500)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head_box = QWidget()
        head_box.setFixedHeight(56)
        head_layout = QHBoxLayout(head_box)
        head_layout.setContentsMargins(24, 0, 24, 0)
        self.head_label = role_label(head, "dialogTitle")
        head_layout.addWidget(self.head_label)
        outer.addWidget(head_box)

        body_box = QWidget()
        self.body = QVBoxLayout(body_box)
        self.body.setContentsMargins(24, 0, 24, 24)
        self.body.setSpacing(8)
        outer.addWidget(body_box, 1)

        outer.addWidget(line())
        self._footer = QHBoxLayout()
        self._footer.setContentsMargins(24, 16, 24, 16)
        self._footer.setSpacing(8)
        self._footer.addStretch(1)
        outer.addLayout(self._footer)

    def add_button(self, text: str, variant: str = "secondary") -> QPushButton:
        button = make_button(text, variant)
        self._footer.addWidget(button)
        return button

    def add_actions(self, action: str, cancel: str = "취소", *, danger: bool = False) -> QPushButton:
        """바로 왼쪽이 취소, 오른쪽 끝이 주된 동작. 위험하면 기본 포커스는 취소에 둔다."""
        cancel_button = self.add_button(cancel)
        cancel_button.clicked.connect(self.reject)
        action_button = self.add_button(action, "danger" if danger else "primary")
        action_button.clicked.connect(self.accept)
        (cancel_button if danger else action_button).setDefault(True)
        return action_button


def message_box(parent: QWidget | None, head: str, detail: str = "", *, warning: bool = False) -> QMessageBox:
    box = QMessageBox(parent)
    box.setWindowTitle(APP_NAME)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setText(head)
    box.setInformativeText(detail)
    head_label = box.findChild(QLabel, "qt_msgbox_label")
    if head_label is not None:
        head_label.setWordWrap(True)  # 18px 제목이 길면 잘리지 않고 줄바꿈
    if warning:
        box.setIconPixmap(A.tinted_pixmap("alert.svg", A.current()["danger"], 24))
    return box


def add_box_button(
    box: QMessageBox, text: str, role: QMessageBox.ButtonRole, variant: str = "secondary"
) -> QPushButton:
    button = box.addButton(text, role)
    button.setProperty("variant", variant)
    A.repolish(button)  # 창에 붙는 순간 이미 스타일이 적용돼 있을 수 있다
    return button


def confirm(parent: QWidget | None, head: str, detail: str, action: str, *, danger: bool = False) -> bool:
    box = message_box(parent, head, detail)
    cancel = add_box_button(box, "취소", QMessageBox.ButtonRole.RejectRole)
    accept = add_box_button(
        box, action, QMessageBox.ButtonRole.AcceptRole, "danger" if danger else "primary"
    )
    box.setDefaultButton(cancel if danger else accept)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is accept


def notify(parent: QWidget | None, head: str, detail: str = "", *, warning: bool = False) -> None:
    box = message_box(parent, head, detail, warning=warning)
    add_box_button(box, "확인", QMessageBox.ButtonRole.AcceptRole, "primary")
    box.exec()
