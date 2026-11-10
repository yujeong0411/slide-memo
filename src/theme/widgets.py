"""화면 모드를 따르는 공용 부품: 메뉴, 콤보 목록, 대화창, 메시지 창."""
from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QMargins, QModelIndex, QObject, QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QAction, QColor, QCursor, QFontMetrics, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
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
_SHADOW_Y, _SHADOW_BLUR, _SHADOW_ALPHA = T.SHADOW["md"]
# 떠 있는 창은 그림자가 그려질 자리만큼 안쪽으로 들여 그린다
_FLOAT_MARGINS = QMargins(_SHADOW_BLUR, _SHADOW_BLUR - _SHADOW_Y, _SHADOW_BLUR, _SHADOW_BLUR + _SHADOW_Y)
_LIST_GAP = 4  # 콤보 칸과 펼친 목록 사이
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


def add_float_shadow(widget: QWidget) -> None:
    """떠 있는 면에 shadow_md를 준다 (2.6)."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(_SHADOW_BLUR)
    effect.setOffset(0, _SHADOW_Y)
    color = QColor(0, 0, 0)
    color.setAlphaF(_SHADOW_ALPHA)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def _paint_soft_shadow(painter: QPainter, panel: QRectF, radius: int) -> None:
    """QMenu 창에는 그래픽 효과를 걸 수 없어 shadow_md를 겹친 사각형으로 근사한다."""
    color = QColor(0, 0, 0)
    color.setAlphaF(_SHADOW_ALPHA / _SHADOW_BLUR)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    shadow = panel.translated(0, _SHADOW_Y)
    for spread in range(_SHADOW_BLUR, 0, -1):
        grown = shadow.adjusted(-spread, -spread, spread, spread)
        painter.drawRoundedRect(grown, radius + spread, radius + spread)


def tip(label: str, shortcut: str) -> str:
    """툴팁: 단축키는 같은 줄에 72% 불투명도로 (4.5)."""
    return f'{label} &nbsp;<span style="color: rgba(255,255,255,0.72);">{shortcut}</span>'


class _AppToolTip(QWidget):
    """투명 창에 둥근 면과 앱 그림자를 그리는 툴팁 (4.5). OS 그림자는 끈다."""

    PADDING_X, PADDING_Y, MAX_TEXT_WIDTH, BESIDE_GAP, CURSOR_GAP = 8, 4, 320, 8, 20

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label = QLabel()
        self.label.setObjectName("appToolTip")
        self.label.setFont(A.base_font("caption"))
        self.label.setMinimumHeight(T.TYPE["caption"][1])
        layout = QVBoxLayout(self)
        m = _FLOAT_MARGINS
        layout.setContentsMargins(
            m.left() + self.PADDING_X, m.top() + self.PADDING_Y,
            m.right() + self.PADDING_X, m.bottom() + self.PADDING_Y,
        )
        layout.addWidget(self.label)

    def set_text(self, text: str) -> None:
        self.label.setWordWrap(False)
        self.label.setMinimumWidth(0)
        self.label.setMaximumWidth(16777215)
        self.label.setText(text)
        if self.label.sizeHint().width() > self.MAX_TEXT_WIDTH:
            self.label.setWordWrap(True)
            self.label.setFixedWidth(self.MAX_TEXT_WIDTH)
        self.layout().invalidate()
        self.adjustSize()

    def place(self, widget: QWidget, beside: str | None) -> None:
        """beside가 있으면 위젯 옆 8px, 세로 가운데. 없으면 마우스 아래."""
        m = _FLOAT_MARGINS
        face_w = self.width() - m.left() - m.right()
        face_h = self.height() - m.top() - m.bottom()
        area = widget.screen().availableGeometry()
        if beside is not None:
            target = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
            x = (
                target.left() - self.BESIDE_GAP - face_w
                if beside == "left"
                else target.right() + 1 + self.BESIDE_GAP
            )
            y = target.center().y() - face_h // 2
        else:
            cursor = QCursor.pos()
            x, y = cursor.x(), cursor.y() + self.CURSOR_GAP
            if y + face_h > area.bottom():
                y = cursor.y() - self.CURSOR_GAP - face_h
        x = max(area.left(), min(x, area.right() - face_w + 1))
        y = max(area.top(), min(y, area.bottom() - face_h + 1))
        self.move(x - m.left(), y - m.top())

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect().marginsRemoved(_FLOAT_MARGINS))
        radius = T.RADIUS["control"]
        _paint_soft_shadow(painter, panel, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(A.qcolor(A.current()["contrast"]))
        painter.drawRoundedRect(panel, radius, radius)
        painter.end()


class _ToolTipManager(QObject):
    """앱의 모든 ToolTip 이벤트를 가로채 _AppToolTip으로 띄운다.
    지연(500ms)은 Qt의 대기 타이머(_AppStyle)가 그대로 맡는다.
    위젯에 tooltip_request()가 있으면 (글, 놓을 쪽) 또는 None을 돌려받는다."""

    _HIDE_ON_ANY = (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
        QEvent.Type.KeyPress,
    )

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.tip = _AppToolTip()
        self.owner: QWidget | None = None

    def hide_tip(self) -> None:
        self.owner = None
        self.tip.hide()

    def show_for(self, widget: QWidget) -> bool:
        request = getattr(widget, "tooltip_request", None)
        if request is None:
            text, beside = widget.toolTip(), None
            if not text:
                return False
        else:
            answer = request()
            if answer is None:
                self.hide_tip()
                return True
            text, beside = answer
        if self.owner is not widget:
            widget.destroyed.connect(self.hide_tip)
        self.owner = widget
        self.tip.set_text(text)
        self.tip.place(widget, beside)
        self.tip.show()
        return True

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            return isinstance(obj, QWidget) and self.show_for(obj)
        if self.owner is not None and (
            kind in self._HIDE_ON_ANY
            or (obj is self.owner and kind in (QEvent.Type.Leave, QEvent.Type.Hide))
        ):
            self.hide_tip()
        return False


_tooltips: _ToolTipManager | None = None


def install_tooltips(app: QApplication) -> _ToolTipManager:
    global _tooltips
    if _tooltips is None:
        _tooltips = _ToolTipManager(app)
        app.installEventFilter(_tooltips)
    return _tooltips


def tooltip_visible() -> bool:
    return _tooltips is not None and _tooltips.tip.isVisible()


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
        self.setContentsMargins(_FLOAT_MARGINS)
        self.setMinimumWidth(200 + _FLOAT_MARGINS.left() + _FLOAT_MARGINS.right())

    def showEvent(self, event) -> None:  # noqa: N802
        # 그림자 자리만큼 창을 옮겨, 면이 원래 뜰 자리에 오게 한다
        self.move(self.pos() - QPoint(_FLOAT_MARGINS.left(), _FLOAT_MARGINS.top()))
        super().showEvent(event)

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
        panel = QRectF(self.rect().marginsRemoved(_FLOAT_MARGINS))
        _paint_soft_shadow(painter, panel, radius)
        painter.setPen(QPen(A.qcolor(t["line"]), 1))
        painter.setBrush(A.qcolor(t["bg_raised"]))
        painter.drawRoundedRect(panel.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
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
        # 펼칠 때 고른 항목이 '선택' 상태로 시작한다. 그 항목은 체크로만 표시한다 (1.2)
        hovering = option.state & QStyle.StateFlag.State_MouseOver
        moved_to = (
            option.state & QStyle.StateFlag.State_Selected
            and index.row() != self._combo.currentIndex()
        )
        if hovering or moved_to:
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


class ThemedCombo(QComboBox):
    """펼친 목록을 칸 바로 아래에, 메뉴 규격(반경 8, shadow_md)으로 띄운다 (4.3, 4.6)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setItemDelegate(_ComboDelegate(self))
        popup = self.view().window()
        popup.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.layout().setContentsMargins(_FLOAT_MARGINS)
        add_float_shadow(self.view())

    def showPopup(self) -> None:  # noqa: N802
        super().showPopup()
        popup = self.view().window()
        if isinstance(popup, QFrame):
            popup.setFrameShape(QFrame.Shape.NoFrame)  # 둥근 모서리 밖에 사각 테두리가 남는다
        below = self.mapToGlobal(QPoint(0, self.height() + _LIST_GAP))
        width = self.width() + _FLOAT_MARGINS.left() + _FLOAT_MARGINS.right()
        popup.setGeometry(
            below.x() - _FLOAT_MARGINS.left(), below.y() - _FLOAT_MARGINS.top(),
            width, popup.height() + _FLOAT_MARGINS.top() + _FLOAT_MARGINS.bottom(),
        )


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


class PopupPanel(QFrame):
    """떠 있는 자체 팝업: 투명 창 안에 그림자 있는 카드를 둔다 (4.4)."""

    def __init__(self, owner: QWidget | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self._owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_FLOAT_MARGINS)
        self.card = QFrame()
        self.card.setObjectName("popupCard")
        add_float_shadow(self.card)
        outer.addWidget(self.card)
        self.body = QVBoxLayout(self.card)

    def show_below(self, anchor: QWidget) -> None:
        """누른 단추 바로 아래에 띄운다. 화면 밖으로 나가면 안쪽으로 민다."""
        self.adjustSize()
        spot = anchor.mapToGlobal(QPoint(0, anchor.height() + _LIST_GAP))
        area = anchor.screen().availableGeometry()
        x = spot.x() - _FLOAT_MARGINS.left()
        self.move(max(area.left(), min(x, area.right() - self.width())), spot.y() - _FLOAT_MARGINS.top())
        self.show()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if self._owner is not None:
            self._owner.window().raise_()


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
