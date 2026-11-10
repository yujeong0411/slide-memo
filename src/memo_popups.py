"""메모 창의 자체 팝업과 떠 있는 카드. SlideMemo-design.md 4.2, 4.4."""
from __future__ import annotations

from PyQt6.QtCore import QDate, QPropertyAnimation, QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from theme import apply as A
from theme import tokens as T
from theme.widgets import PopupPanel, add_float_shadow, line, make_button

# 기준 → (표시 이름, 첫 방향 칩, 둘째 방향 칩)
SORT_CRITERIA = (
    ("수정일순", "최신 먼저", "오래된 먼저"),
    ("만든 날짜순", "최신 먼저", "오래된 먼저"),
    ("제목순", "가나다순", "역순"),
)
# 저장되는 sort_mode 번호와 DB 정렬 키. 앞 4개는 예전 번호 그대로다.
SORT_KEYS = ("updated_desc", "updated_asc", "title_az", "created_desc", "created_asc", "title_za")
_SORT_POSITION = {
    "updated_desc": (0, 0), "updated_asc": (0, 1),
    "created_desc": (1, 0), "created_asc": (1, 1),
    "title_az": (2, 0), "title_za": (2, 1),
}


def sort_index(criterion: int, direction: int) -> int:
    return next(i for i, key in enumerate(SORT_KEYS) if _SORT_POSITION[key] == (criterion, direction))


def sort_description(index: int) -> tuple[str, str]:
    """(기준 이름, 방향 이름)."""
    criterion, direction = _SORT_POSITION[SORT_KEYS[index]]
    return SORT_CRITERIA[criterion][0], SORT_CRITERIA[criterion][1 + direction]


class SortPopup(PopupPanel):
    """목록은 왼쪽 체크(1.2), 방향은 칩. 고르면 바로 정렬되고 닫히지 않는다."""

    changed = pyqtSignal(int)

    def __init__(self, index: int, owner: QWidget | None = None) -> None:
        super().__init__(owner)
        self.body.setContentsMargins(4, 4, 4, 8)
        self.body.setSpacing(0)
        self._criterion, self._direction = _SORT_POSITION[SORT_KEYS[index]]
        self._rows: list[QPushButton] = []
        for position, (label, _first, _second) in enumerate(SORT_CRITERIA):
            row = QPushButton(label)
            row.setObjectName("popupItem")
            row.setIconSize(A.tinted_pixmap("menu_check.svg", A.current()["fg"], 16).deviceIndependentSize().toSize())
            row.clicked.connect(lambda _c=False, p=position: self._choose(p, 0))
            self.body.addWidget(row)
            self._rows.append(row)
        self.body.addSpacing(4)
        self.body.addWidget(line())
        self.body.addSpacing(8)
        chips = QHBoxLayout()
        chips.setContentsMargins(4, 0, 4, 0)
        chips.setSpacing(4)
        self._chips: list[QPushButton] = []
        for direction in (0, 1):
            chip = QPushButton()
            chip.setObjectName("chip")
            chip.clicked.connect(lambda _c=False, d=direction: self._choose(self._criterion, d))
            chips.addWidget(chip)
            self._chips.append(chip)
        self.body.addLayout(chips)
        self._refresh()

    def _choose(self, criterion: int, direction: int) -> None:
        self._criterion, self._direction = criterion, direction
        self._refresh()
        self.changed.emit(sort_index(criterion, direction))

    def _refresh(self) -> None:
        blank = QPixmap(16, 16)
        blank.fill(Qt.GlobalColor.transparent)
        check = A.tinted_pixmap("menu_check.svg", A.current()["fg"], 16)
        for position, row in enumerate(self._rows):
            row.setIcon(QIcon(check if position == self._criterion else blank))
        labels = SORT_CRITERIA[self._criterion][1:]
        for direction, chip in enumerate(self._chips):
            chip.setText(labels[direction])
            chip.setProperty("selected", direction == self._direction)
            A.repolish(chip)


class _InkSwatch(QAbstractButton):
    """글자색·형광펜 견본 24. color가 None이면 사선 견본이다."""

    SIZE = 32  # 견본 24 + 고리 자리 4씩. 견본 사이가 8이 된다

    def __init__(self, stored: str | None, display: str | None, tooltip: str) -> None:
        super().__init__()
        self.stored, self._display = stored, display
        self.selected = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip(tooltip)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = A.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(4, 4, 24, 24)
        radius = T.RADIUS["small"]
        painter.setPen(QPen(A.qcolor(t["line"]), 1))
        painter.setBrush(QColor(self._display) if self._display else A.qcolor(t["bg_canvas"]))
        painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self._display is None:
            painter.setPen(QPen(A.qcolor(t["danger"]), 1.5))
            painter.drawLine(box.bottomLeft() + QPoint(3, -3).toPointF(), box.topRight() + QPoint(-3, 3).toPointF())
        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(A.qcolor(t["overlay_hover"]))
            painter.drawRoundedRect(box, radius, radius)
        if self.selected:  # 2px 틈 + 2px 고리
            painter.setPen(QPen(A.qcolor(t["fg"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        painter.end()


class InkPopup(PopupPanel):
    """글자색·형광펜: 견본 6열, "없음"은 사선, "직접 고르기"는 글자 단추."""

    picked = pyqtSignal(object)  # 저장할 밝은 화면 값 또는 None
    custom_requested = pyqtSignal()

    COLUMNS = 6

    def __init__(self, title: str, pairs, current: str | None, mode: str, owner: QWidget | None = None) -> None:
        super().__init__(owner)
        self.body.setContentsMargins(12, 12, 12, 8)
        self.body.setSpacing(4)
        heading = QLabel(title)
        heading.setProperty("role", "group")
        self.body.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(0)
        entries = [(None, None, "없음")] + [
            (light, dark if mode == "dark" else light, name) for name, light, dark in pairs
        ]
        for index, (stored, display, name) in enumerate(entries):
            swatch = _InkSwatch(stored, display, name)
            swatch.selected = stored == current if stored else current is None
            swatch.clicked.connect(lambda _c=False, value=stored: self.picked.emit(value))
            grid.addWidget(swatch, index // self.COLUMNS, index % self.COLUMNS)
        self.body.addLayout(grid)
        custom = QPushButton("직접 고르기")
        custom.setObjectName("textBtn")
        custom.setCursor(Qt.CursorShape.PointingHandCursor)
        custom.clicked.connect(self.custom_requested)
        row = QHBoxLayout()
        row.addWidget(custom)
        row.addStretch(1)
        self.body.addLayout(row)


class DatePopup(PopupPanel):
    """달력. "넣기"는 YYYY-MM-DD로 넣는다 (9장 5)."""

    chosen = pyqtSignal(QDate)

    _WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")

    def __init__(self, owner: QWidget | None = None) -> None:
        super().__init__(owner)
        self._today = QDate.currentDate()
        self._selected = self._today
        self._month = QDate(self._today.year(), self._today.month(), 1)
        self.body.setContentsMargins(16, 12, 16, 12)
        self.body.setSpacing(8)

        header = QHBoxLayout()
        self._title = QLabel()
        self._title.setProperty("role", "popupTitle")
        A.set_tabular(self._title)
        header.addWidget(self._title)
        header.addStretch(1)
        for asset, step, tip in (("chevron_left.svg", -1, "이전 달"), ("chevron_right.svg", 1, "다음 달")):
            nav = make_button("", "iconSm")
            nav.setIcon(QIcon(A.tinted_pixmap(asset, A.current()["fg_secondary"], 16)))
            nav.setToolTip(tip)
            nav.clicked.connect(lambda _c=False, s=step: self._shift(s))
            header.addWidget(nav)
        self.body.addLayout(header)

        self._grid = QGridLayout()
        self._grid.setSpacing(0)
        for column, name in enumerate(self._WEEKDAYS):
            weekday = QLabel(name)
            weekday.setProperty("role", "weekday")
            weekday.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(weekday, 0, column)
        self.body.addLayout(self._grid)
        self.body.addWidget(line())

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        today = make_button("오늘", "ghost")
        today.clicked.connect(self._go_today)
        footer.addWidget(today)
        insert = make_button("넣기", "primary")
        insert.clicked.connect(lambda: self.chosen.emit(self._selected))
        footer.addWidget(insert)
        self.body.addLayout(footer)
        self._cells: list[QPushButton] = []
        self._rebuild()

    def _shift(self, months: int) -> None:
        self._month = self._month.addMonths(months)
        self._rebuild()

    def _go_today(self) -> None:
        self._selected = self._today
        self._month = QDate(self._today.year(), self._today.month(), 1)
        self._rebuild()

    def _pick(self, day: QDate) -> None:
        self._selected = day
        self._rebuild()

    def _rebuild(self) -> None:
        for cell in self._cells:
            self._grid.removeWidget(cell)
            cell.deleteLater()
        self._cells = []
        self._title.setText(f"{self._month.year()}년 {self._month.month()}월")
        first_column = self._month.dayOfWeek() % 7  # Qt는 월=1 … 일=7
        for offset in range(self._month.daysInMonth()):
            day = self._month.addDays(offset)
            position = first_column + offset
            cell = QPushButton(str(day.day()))
            cell.setObjectName("dayCell")
            cell.setProperty("today", day == self._today)
            cell.setProperty("selected", day == self._selected)
            A.set_tabular(cell)
            cell.clicked.connect(lambda _c=False, d=day: self._pick(d))
            self._grid.addWidget(cell, 1 + position // 7, position % 7)
            self._cells.append(cell)
        self.adjustSize()


class ElideLabel(QLabel):
    """폭이 모자라면 끝을 말줄임하는 한 줄 라벨."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = " ".join(text.split())
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        QLabel.setText(self, QFontMetrics(self.font()).elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(0, self.width())
        ))

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class Toast(QFrame):
    """창 위쪽 가운데에서 내려오는 안내. 동작 단추는 하나만 둔다 (4.2)."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        add_float_shadow(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)
        self.action = QPushButton()
        self.action.setObjectName("toastAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(self.clicked)
        layout.addWidget(self.action)
        self._drop = QPropertyAnimation(self, b"pos", self)
        self._drop.setDuration(T.MOTION_FAST_MS)

    def show_message(self, text: str, action_text: str = "") -> None:
        self.message.setText(text)
        self.action.setText(action_text)
        self.action.setVisible(bool(action_text))
        action_width = self.action.sizeHint().width() + 16 if action_text else 0
        room = max(80, self.parentWidget().width() - 24 - 32 - action_width)
        # 글자 폭에 맞추고, 창보다 길 때만 줄바꿈한다
        self.message.setFixedWidth(min(room, self.message.fontMetrics().horizontalAdvance(text) + 2))
        self.adjustSize()
        x = (self.parentWidget().width() - self.width()) // 2
        self.raise_()
        self.show()
        self._drop.stop()
        self._drop.setStartValue(QPoint(x, 4))
        self._drop.setEndValue(QPoint(x, 12))
        self._drop.start()

    def finish_animation(self) -> None:
        self._drop.setCurrentTime(self._drop.duration())


class Spinner(QWidget):
    """끝나는 시점을 모르므로 막대 대신 도는 원 (4.2)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._step)

    def _step(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802
        accent = A.qcolor(A.current()["accent"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        ring = QColor(accent)
        ring.setAlphaF(0.2)
        painter.setPen(QPen(ring, 2.5))
        painter.drawEllipse(area)
        pen = QPen(accent, 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(area, (90 - self._angle) * 16, -90 * 16)
        painter.end()


class ProgressCard(QFrame):
    """AI·음성 변환 진행. 1초가 넘을 때만 본문 가운데에 나타난다 (2.8, 4.2)."""

    canceled = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("floatCard")
        add_float_shadow(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(Spinner(self))
        self.message = QLabel()
        layout.addWidget(self.message)
        self.cancel = make_button("취소", "ghost")
        self.cancel.clicked.connect(self.canceled)
        layout.addWidget(self.cancel)
        self._anchor: QWidget | None = None
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(1000)
        self._delay.timeout.connect(self.show_now)
        self.hide()

    def begin(self, text: str, anchor: QWidget, *, cancellable: bool = True) -> None:
        self._anchor = anchor
        self.message.setText(text)
        self.cancel.setVisible(cancellable)
        if self.isVisible():
            self.place()
        elif not self._delay.isActive():
            self._delay.start()

    def show_now(self) -> None:
        self._delay.stop()
        self.place()
        self.raise_()
        self.show()

    def place(self) -> None:
        if self._anchor is None:
            return
        self.adjustSize()
        center = self._anchor.mapTo(self.parentWidget(), self._anchor.rect().center())
        self.move(center - QPoint(self.width() // 2, self.height() // 2))

    def hide(self) -> None:
        self._delay.stop()
        super().hide()

