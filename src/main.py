"""Slide Memo - Windows 데스크탑용 슬라이드 메모장."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt,
    QEasingCurve,
    QDate,
    QEvent,
    QLibraryInfo,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QThread,
    QTimer,
    QTranslator,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextDocumentWriter,
    QTextFormat,
    QTextImageFormat,
    QTextListFormat,
    QTextTableFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QSplashScreen,
    QStyle,
    QSystemTrayIcon,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from database import (
    APP_DIR,
    DEFAULT_COLOR,
    IMAGES_DIR,
    PAPER_NOTICE_KEY,
    USER_SLOTS_KEY,
    Memo,
    MemoDatabase,
    MemoVersion,
    normalize_color,
)
import memo_document
from memo_color import MemoColorButton, MemoColorDialog, MemoColorPopup
from memo_popups import (
    SORT_CRITERIA,
    SORT_KEYS,
    DatePopup,
    InkPopup,
    ProgressCard,
    SortPopup,
    Toast,
    sort_description,
)
from edge_button import EdgeLogoButton, is_foreign_fullscreen
from theme import apply as theme_apply
from theme import tokens as T
from theme.apply import resource_path as _resource_path
from theme.apply import tinted_pixmap
from theme.memo_tokens import memo_tokens
from theme.widgets import (
    AppDialog,
    PopupPanel,
    ThemedCombo,
    ThemedMenu,
    add_box_button,
    add_float_shadow,
    confirm,
    make_button,
    message_box,
    notify,
    install_tooltips,
    role_label,
    tip,
    tooltip_visible,
)


# ----- 상수 -----
TAB_WIDTH = T.TAB_WIDTH_DEFAULT   # 인덱스 가로 (기본값; 설정에서 조절)
TAB_WIDTH_MIN = 24
TAB_WIDTH_MAX = 100
EXPANDED_WIDTH = 520
HEIGHT_RATIO = 0.55
AUTOSAVE_DELAY = 600
# 메모별 undo 스택 유지 개수. 문서를 캐시해두면 메모를 전환했다 돌아와도 Ctrl+Z가
# 살아있다. 이미지가 붙은 문서는 메모리를 먹으므로 LRU로 제한한다.
UNDO_CACHE_SIZE = 10
MEMO_TAB_HEIGHT = T.TAB_HEIGHT_DEFAULT   # 인덱스 세로 (기본값; 설정에서 조절)
MEMO_TAB_HEIGHT_MIN = 60
MEMO_TAB_HEIGHT_MAX = 200
BAR_BUTTON_HEIGHT = T.CONTROL["md"][0]
BAR_ICON = 18
GRIP_HEIGHT = 40

# 8-4 표시 방식: tray=트레이만(Tool 플래그) / taskbar=작업표시줄만 / both=둘 다
DISPLAY_MODE_DEFAULT = "tray"
DISPLAY_MODES = ("tray", "taskbar", "both")

# 리사이즈
MIN_W = 280
MIN_SEARCH_WIDTH = 120  # 이보다 좁아지면 정렬 콤보를 아이콘으로 바꾼다
MIN_H = 200
RESIZE_GRIP = 6  # 가장자리 드래그 핸들 두께(px)
EDGE_BUTTON_Y_KEY = "edge_button_y"  # 숨겼을 때 남는 로고 단추의 위치
HIDE_HOTKEY_LABEL = "Ctrl+Shift+Z"  # 잠깐 숨기기/복귀 전역 단축키 (표시용)

WEEKDAYS_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

MAX_USER_SLOTS = T.MAX_CUSTOM_COLORS


def parse_color_slots(raw: str) -> list[str]:
    """저장된 슬롯 문자열 → 직접 만든 색 목록. DB 값도 신뢰 경계라 정규화를 통과 못하면 버린다."""
    slots = [p.strip() for p in raw.split("|")]
    return [p for p in slots if p.startswith("#") and normalize_color(p) == p][:MAX_USER_SLOTS]


SORT_OPTIONS = [(key, SORT_CRITERIA[0][0]) for key in SORT_KEYS]  # sort_mode 번호 = 이 순서

def _inner_rounded_path(rect: QRectF, radius: float, side: str) -> QPainterPath:
    """화면 안쪽 모서리만 둥근 사각형. side는 바가 붙은 모니터 쪽 (4.1)."""
    path = QPainterPath()
    left, right, top, bottom = rect.left(), rect.right(), rect.top(), rect.bottom()
    if side == "right":  # 안쪽 = 왼쪽
        path.moveTo(right, top)
        path.lineTo(left + radius, top)
        path.quadTo(left, top, left, top + radius)
        path.lineTo(left, bottom - radius)
        path.quadTo(left, bottom, left + radius, bottom)
        path.lineTo(right, bottom)
    else:
        path.moveTo(left, top)
        path.lineTo(right - radius, top)
        path.quadTo(right, top, right, top + radius)
        path.lineTo(right, bottom - radius)
        path.quadTo(right, bottom, right - radius, bottom)
        path.lineTo(left, bottom)
    return path


def _inner_edge_path(rect: QRectF, radius: float, side: str) -> QPainterPath:
    """닫힌 탭의 선: 안쪽 변과 둥근 모서리, 아래쪽 선. 위쪽은 윗 탭의 아래쪽 선이 맡는다."""
    path = QPainterPath()
    left, right, top, bottom = rect.left(), rect.right(), rect.top(), rect.bottom()
    if side == "right":
        path.moveTo(left + radius, top)
        path.quadTo(left, top, left, top + radius)
        path.lineTo(left, bottom - radius)
        path.quadTo(left, bottom, left + radius, bottom)
        path.lineTo(right, bottom)
    else:
        path.moveTo(right - radius, top)
        path.quadTo(right, top, right, top + radius)
        path.lineTo(right, bottom - radius)
        path.quadTo(right, bottom, right - radius, bottom)
        path.lineTo(left, bottom)
    return path


class MemoTabButton(QPushButton):
    """세로 탭. 모니터 쪽 4px은 띠 색, 글자는 세워 쌓는다 (4.1, 9장 2)."""

    side = "right"  # 클래스 변수: 윈도우가 좌/우 전환 시 갱신
    button_height = MEMO_TAB_HEIGHT  # 클래스 변수: 설정에서 조절 시 갱신

    BAND_WIDTH = 4
    TEXT_PADDING = 8  # 글자 줄의 앞뒤 여백
    SIDE_PADDING = 8  # 줄 수 계산에서 빼는 안쪽 여백
    LINE_HEIGHT = T.TYPE["label"][1]
    RIBBON_WIDTH, RIBBON_LENGTH, RIBBON_NOTCH, RIBBON_GAP = 10, 14, 4, 4  # 띠와 같은 색이라 띄운다

    @classmethod
    def line_count(cls, width: int) -> int:
        """폭 40이면 한 줄, 48이면 두 줄."""
        return max(1, (width - cls.BAND_WIDTH - cls.SIDE_PADDING) // cls.LINE_HEIGHT)

    @staticmethod
    def wrap_title(title: str, metrics: QFontMetrics, length: int, max_lines: int) -> list[str]:
        """띄어쓰기에서 줄을 나누고, 마지막 줄 끝에서만 말줄임한다.
        띄어쓰기 없이 줄보다 긴 낱말만 글자 단위로 자른다."""
        lines: list[str] = []
        rest = title.strip()
        while rest and len(lines) < max_lines - 1 and metrics.horizontalAdvance(rest) > length:
            fit = 0
            for end in range(1, len(rest) + 1):
                if metrics.horizontalAdvance(rest[:end]) > length:
                    break
                fit = end
            space = rest.rfind(" ", 0, fit + 1)
            split = space if space > 0 else max(1, fit)
            lines.append(rest[:split].rstrip())
            rest = rest[split:].lstrip()
        if rest:
            lines.append(metrics.elidedText(rest, Qt.TextElideMode.ElideRight, length))
        return lines

    def __init__(self, memo: Memo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.memo_id = memo.id
        self.color_name = memo.color
        self._tokens = memo_tokens(normalize_color(memo.color), theme_apply.current_mode())
        self.memo_title = memo.title.strip() or "제목 없음"
        self.is_untitled = not memo.title.strip()
        self.is_pinned = memo.is_pinned
        self._selected = False
        self.setFixedHeight(MemoTabButton.button_height)
        # 탭 폭은 컬럼이 정한다. 기본 정책이면 크기 힌트가 하한이 되어 컬럼을 밀어낸다.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def _title_lines(self, font: QFont) -> tuple[list[str], int]:
        """지금 크기에서 보이는 줄과 한 줄 길이."""
        length = max(1, self.height() - 2 * self.TEXT_PADDING)
        lines = MemoTabButton.wrap_title(
            self.memo_title, QFontMetrics(font), length, MemoTabButton.line_count(self.width())
        )
        return lines, length

    def _tab_font(self) -> QFont:
        font = theme_apply.base_font("label")
        if self._selected:
            font.setWeight(QFont.Weight.Bold)
        return font

    def tooltip_request(self) -> tuple[str, str] | None:
        """제목이 잘렸을 때만 창 안쪽에 전체 제목을 보여 준다."""
        shown = "".join("".join(self._title_lines(self._tab_font())[0]).split())
        if shown == "".join(self.memo_title.split()) and not self.is_pinned:
            return None
        text = f"{self.memo_title} · 고정됨" if self.is_pinned else self.memo_title
        return text, "left" if MemoTabButton.side == "right" else "right"

    def ribbon_points(self) -> list[QPointF]:
        """고정 표시: 읽기 시작 쪽(위) 끝, 띠에서 띄워 매달린 책갈피. 끝은 가운데가 파인 V."""
        w, h, notch = self.RIBBON_WIDTH, self.RIBBON_LENGTH, self.RIBBON_NOTCH
        inset = self.BAND_WIDTH + self.RIBBON_GAP
        left = self.width() - inset - w if MemoTabButton.side == "right" else inset
        return [
            QPointF(left, 0), QPointF(left + w, 0), QPointF(left + w, h),
            QPointF(left + w / 2, h - notch), QPointF(left, h),
        ]

    def update_style(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = self._tokens
        side = MemoTabButton.side
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        area = QRectF(self.rect())
        radius = T.RADIUS["tab_inner"]
        shape = _inner_rounded_path(area, radius, side)
        shape.closeSubpath()
        if self._selected:  # 열린 탭은 창과 이어진다: 둥근 모서리도 안쪽 선도 없다
            shape = QPainterPath()
            shape.addRect(area)

        painter.save()
        painter.setClipPath(shape)
        hovered = self.underMouse() and not self._selected
        painter.fillRect(area, QColor(t["memo_hover"] if hovered else t["memo_face"]))
        band_x = area.right() - self.BAND_WIDTH + 1 if side == "right" else area.left()
        painter.fillRect(QRectF(band_x, 0, self.BAND_WIDTH, area.height()), QColor(t["memo_band"]))
        painter.restore()

        # 탭은 붙어 있고 사이는 아래쪽 선 하나로 나눈다. 위쪽 선을 그으면 2px이 된다.
        painter.setPen(QPen(QColor(t["memo_edge"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        stroke = area.adjusted(0.5, 0.5, -0.5, -0.5)
        if self._selected:
            painter.drawLine(stroke.bottomLeft(), stroke.bottomRight())
        else:
            painter.drawPath(_inner_edge_path(stroke, radius, side))

        content_left = 0 if side == "right" else self.BAND_WIDTH
        center_x = content_left + (self.width() - self.BAND_WIDTH) / 2
        font = self._tab_font()
        start = self.TEXT_PADDING
        if self.is_pinned:  # 글자 아래에 깔리도록 먼저 그린다
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["memo_band"]))
            painter.drawPolygon(QPolygonF(self.ribbon_points()))
        lines, length = self._title_lines(font)

        # 시계방향 90도: 위에서 아래로 읽고, 첫 줄이 오른쪽이다 (양쪽 가장자리 모두 같다)
        painter.setFont(font)
        painter.setPen(QColor(theme_apply.current()["fg_secondary"] if self.is_untitled else t["memo_fg"]))
        painter.translate(center_x, start)
        painter.rotate(90)
        block_top = -len(lines) * self.LINE_HEIGHT / 2
        for index, line in enumerate(lines):
            rect = QRectF(0, block_top + index * self.LINE_HEIGHT, length, self.LINE_HEIGHT)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, line)
        painter.end()


class _InkToolButton(QToolButton):
    """글자색·배경색 단추. 아이콘 아래에 마지막으로 쓴 색을 3px 막대로 보여 준다."""

    ICON, BAR_HEIGHT = 16, 3

    def __init__(self, kind: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.kind = kind
        self.last_ink: str | None = None  # 저장되는 밝은 화면 값

    def set_ink(self, value: str | None) -> None:
        self.last_ink = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.last_ink is None:
            return
        shown = memo_document.display_text_color if self.kind == "text" else memo_document.display_highlight
        painter = QPainter(self)
        painter.fillRect(
            (self.width() - self.ICON) // 2, (self.height() + self.ICON) // 2,
            self.ICON, self.BAR_HEIGHT, QColor(shown(self.last_ink, theme_apply.current_mode())),
        )
        painter.end()


class RichPasteTextEdit(QTextEdit):
    """클립보드 이미지를 파일로 저장 후 에디터에 바로 표시하는 리치 텍스트 에디터."""

    IMG_MAX_WIDTH = 440  # 에디터 폭에 맞춘 이미지 표시 최대 폭
    BULLET_GAP = 7  # 글머리표와 글자 사이 (시안 6~8px)
    _bullet_colors: tuple[QColor, QColor] | None = None  # (메모 면, 글자)

    def set_bullet_colors(self, face: str, ink: str) -> None:
        self._bullet_colors = (QColor(face), QColor(ink))
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._bullet_colors is not None:
            self._repaint_bullets(*self._bullet_colors)

    def _repaint_bullets(self, face: QColor, ink: QColor) -> None:
        """Qt는 기호 뒤 간격을 공백 한 칸으로 고정한다. 저장 내용을 바꾸지 않으려고
        기호 자리(첫 줄 왼쪽 빈 칸)만 지우고 간격을 띄워 다시 그린다."""
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = self.document().documentLayout()
        offset = QPointF(-self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
        bottom = self.viewport().height()
        block = self.cursorForPosition(QPoint(0, 0)).block()
        while block.isValid():
            box = layout.blockBoundingRect(block).translated(offset)
            if box.top() > bottom:
                break
            text_list = block.textList()
            if (
                text_list is not None
                and text_list.format().style() == QTextListFormat.Style.ListDisc
                and block.layout().lineCount() > 0
            ):
                line = block.layout().lineAt(0)
                metrics = QFontMetricsF(block.charFormat().font())
                size = metrics.lineSpacing() / 3
                left = box.left() + line.x()
                top = box.top() + line.y()
                painter.fillRect(QRectF(left - 40, top, 39, metrics.height()), face)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ink)
                painter.drawEllipse(
                    QRectF(left - self.BULLET_GAP - size, top + (metrics.height() - size) / 2, size, size)
                )
            block = block.next()
        painter.end()

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source is None:
            super().insertFromMimeData(source)
            return

        has_image = source.hasImage()
        has_text = source.hasText()

        # 이미지+텍스트 동시 → 엑셀/표 복사 케이스: 선택 다이얼로그
        if has_image and has_text:
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                dlg = AppDialog("어떤 형식으로 붙여넣을까요?", self.window())
                dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                dlg.body.addWidget(role_label("복사한 내용에 글자와 이미지가 함께 들어 있어요.", "description"))
                result = [None]

                def _pick(kind: str) -> None:
                    result[0] = kind
                    dlg.accept()

                dlg.add_button("텍스트로 붙여넣기").clicked.connect(lambda: _pick("text"))
                dlg.add_button("이미지로 붙여넣기", "primary").clicked.connect(lambda: _pick("image"))
                dlg.exec()

                if result[0] == "text":
                    self.textCursor().insertText(source.text(), QTextCharFormat())
                elif result[0] == "image":
                    self._insert_image(image)
                return

        if has_image:
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self._insert_image(image)
                return

        if has_text:
            self.textCursor().insertText(source.text(), QTextCharFormat())
            return

        # text/plain 없이 text/html만 주는 소스(일부 웹앱·아웃룩 웹 등).
        # 그대로 super()에 넘기면 원본 글꼴/크기/색이 통째로 따라 붙으므로
        # html에서 평문만 뽑아 서식 없이 넣는다.
        if source.hasHtml():
            plain = QTextDocumentFragment.fromHtml(source.html()).toPlainText()
            self.textCursor().insertText(plain, QTextCharFormat())
            return

        super().insertFromMimeData(source)

    def _insert_image(self, image: QImage) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        path = IMAGES_DIR / f"img_{ts}.png"
        if not image.save(str(path), "PNG"):
            return
        fmt = QTextImageFormat()
        fmt.setName(path.as_posix())  # 절대경로 → toHtml 시 <img src=...>
        w, h = image.width(), image.height()
        if w > self.IMG_MAX_WIDTH:
            ratio = self.IMG_MAX_WIDTH / w
            fmt.setWidth(self.IMG_MAX_WIDTH)
            fmt.setHeight(h * ratio)
        else:
            fmt.setWidth(w)
            fmt.setHeight(h)
        self.textCursor().insertImage(fmt)


def _labeled_field(dlg: AppDialog, text: str, field: QWidget) -> None:
    """입력 칸: 라벨을 위에 두고 사이 6 (4.7)."""
    box = QVBoxLayout()
    box.setSpacing(6)
    box.addWidget(QLabel(text))
    box.addWidget(field)
    dlg.body.addLayout(box)


class LinkDialog(AppDialog):
    """링크 넣기. 글자를 선택하고 열면 주소만 묻는다."""

    def __init__(
        self, display_text: str = "", parent: QWidget | None = None, *, show_text: bool = True
    ) -> None:
        super().__init__("링크 넣기", parent)
        self.text_edit = QLineEdit(display_text)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://")
        if show_text:
            _labeled_field(self, "보이는 글자", self.text_edit)
        _labeled_field(self, "주소", self.url_edit)
        self.add_actions("넣기")
        (self.text_edit if show_text else self.url_edit).setFocus()

    def values(self) -> tuple[str, str]:
        return self.text_edit.text().strip(), self.url_edit.text().strip()


class TableDialog(AppDialog):
    """표 넣기 (행/열/머리글)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("표 넣기", parent)
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(QLabel("행"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 20)
        self.rows_spin.setValue(3)
        size_row.addWidget(self.rows_spin)
        size_row.addSpacing(12)
        size_row.addWidget(QLabel("열"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 10)
        self.cols_spin.setValue(3)
        size_row.addWidget(self.cols_spin)
        size_row.addStretch(1)
        self.body.addLayout(size_row)
        self.header_check = QCheckBox("머리글 행 넣기")
        self.header_check.setChecked(True)
        self.body.addWidget(self.header_check)
        self.add_actions("넣기")
        self.rows_spin.setFocus()

    def values(self) -> tuple[int, int, bool]:
        return self.rows_spin.value(), self.cols_spin.value(), self.header_check.isChecked()


class VersionDialog(AppDialog):
    """이전 버전 목록 + 미리보기. 선택한 버전으로 되돌린다."""

    def __init__(self, versions: list[MemoVersion], parent: QWidget | None = None) -> None:
        super().__init__("이전 버전 보기", parent)
        self.setFixedWidth(660)
        self.resize(660, 480)
        self._versions = versions

        self.body.addWidget(
            role_label(
                f"자동 저장된 이전 내용이 {len(versions)}개 있어요. "
                "되돌려도 지금 내용이 버전으로 남으니 다시 취소할 수 있어요.",
                "description",
            )
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        self.list = QListWidget()
        self.list.setFixedWidth(180)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme_apply.set_tabular(self.list)
        for v in versions:
            self.list.addItem(_version_label(v))
        row.addWidget(self.list)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        row.addWidget(self.preview, 1)
        self.body.addLayout(row, 1)

        self._ok_btn = self.add_actions("이 버전으로 되돌리기", "닫기")
        self.list.setFocus()

        self.list.currentRowChanged.connect(self._on_row_changed)
        if versions:
            self.list.setCurrentRow(0)
        else:
            self._ok_btn.setEnabled(False)

    def _on_row_changed(self, row: int) -> None:
        v = self.selected()
        self._ok_btn.setEnabled(v is not None)
        if v is None:
            self.preview.clear()
        elif v.content and Qt.mightBeRichText(v.content):
            self.preview.setHtml(v.content)
        else:
            self.preview.setPlainText(v.content)

    def selected(self) -> MemoVersion | None:
        row = self.list.currentRow()
        return self._versions[row] if 0 <= row < len(self._versions) else None


_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_filename(name: str) -> str:
    """제목을 파일명으로 쓸 수 있게 정리. Windows 금지문자·끝점 제거 후 길이 제한."""
    cleaned = _UNSAFE_FILENAME_RE.sub("", name).strip().rstrip(". ")
    return cleaned[:80] or "메모"


def _embed_images(doc: QTextDocument) -> None:
    """문서 안 이미지를 리소스로 등록한다. 에디터에 붙지 않은 QTextDocument는 이미지를
    스스로 로드하지 않아서, 이 과정을 빼면 ODF 내보내기에서 이미지가 통째로 사라진다."""
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                name = fragment.charFormat().toImageFormat().name()
                image = QImage(name)
                if not image.isNull():  # 파일이 지워졌으면 조용히 건너뛴다
                    doc.addResource(
                        QTextDocument.ResourceType.ImageResource, QUrl(name), image
                    )
            it += 1
        block = block.next()


def _memo_document(memo: Memo) -> QTextDocument:
    """메모를 QTextDocument로. 제목이 있으면 맨 앞에 제목 문단(heading)으로 넣는다.
    heading level을 지정해두면 md는 '# 제목', ODF/HTML은 제목 스타일로 나간다."""
    doc = QTextDocument()
    if memo.content and Qt.mightBeRichText(memo.content):
        doc.setHtml(memo.content)
    else:
        doc.setPlainText(memo.content)
    title = memo.title.strip()
    if title:
        cursor = QTextCursor(doc)
        cursor.setPosition(0)
        cursor.insertBlock()  # 본문 앞에 빈 블록을 만들고 그 블록을 제목으로 쓴다
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        block_fmt = QTextBlockFormat()
        block_fmt.setHeadingLevel(1)
        cursor.setBlockFormat(block_fmt)
        char_fmt = QTextCharFormat()
        char_fmt.setFontWeight(QFont.Weight.Bold)
        char_fmt.setFontPointSize(18)
        cursor.insertText(title, char_fmt)
    _embed_images(doc)
    return doc


def _memo_as_text(memo: Memo, markdown: bool) -> str:
    """메모를 내보내기용 텍스트로. 변환은 Qt가 한다(외부 의존성 없음)."""
    doc = _memo_document(memo)
    if markdown:
        return doc.toMarkdown()
    # toPlainText()는 이미지 자리에 U+FFFC(보이지 않는 자리표시자)를 남기므로 걷어낸다
    return doc.toPlainText().replace("\ufffc", "")


def _version_label(v: MemoVersion) -> str:
    try:
        stamp = datetime.fromisoformat(v.created_at).strftime("%m-%d %H:%M")
    except ValueError:
        stamp = v.created_at
    title = v.title.strip() or "(제목 없음)"
    return f"{stamp}  {title[:12]}"


class FlowLayout(QLayout):
    """가로로 채우다 폭이 부족하면 다음 줄로 wrap. Qt 공식 FlowLayout 기반.
    추가 보정:
    - fixed-size 위젯의 sizeHint 우회 (_effective_size)
    - width<=0인 첫 layout 패스에서 한 줄 높이 fallback (heightForWidth) — 부모 layout이
      비정상으로 큰 wrap 높이를 받아 윈도우 자식들이 어긋난 위치에 잠시 그려지는
      "공중부양" 현상 방지."""

    _QWIDGETSIZE_MAX = 16777215

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = -1,
        v_spacing: int = -1,
    ) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list = []

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def addSpacing(self, size: int) -> None:  # noqa: N802
        self.addItem(
            QSpacerItem(
                size, 1,
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum,
            )
        )

    def horizontalSpacing(self) -> int:  # noqa: N802
        if self._h_spacing >= 0:
            return self._h_spacing
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self) -> int:  # noqa: N802
        if self._v_spacing >= 0:
            return self._v_spacing
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        # 첫 layout 패스에서 width가 결정되기 전 0으로 호출되면 wrap이 극단적으로
        # 일어나 매우 큰 높이를 반환 → 부모 layout이 그 값을 받아 잠깐 비정상 배치 →
        # 윈도우 자식 위젯들이 "공중부양"하는 시각 글리치. 한 줄 높이 fallback.
        if width <= 0:
            return self._single_row_height()
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def _single_row_height(self) -> int:
        h = 0
        for item in self._items:
            h = max(h, self._effective_size(item).height())
        margins = self.contentsMargins()
        return h + margins.top() + margins.bottom()

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(self._effective_size(item))
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _effective_size(self, item) -> QSize:
        sh = item.sizeHint()
        w = item.widget()
        if w is None:
            return sh
        width = (
            w.minimumWidth()
            if w.minimumWidth() == w.maximumWidth()
            and w.maximumWidth() < self._QWIDGETSIZE_MAX
            else sh.width()
        )
        height = (
            w.minimumHeight()
            if w.minimumHeight() == w.maximumHeight()
            and w.maximumHeight() < self._QWIDGETSIZE_MAX
            else sh.height()
        )
        return QSize(width, height)

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(),
            -margins.right(), -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        for index, item in enumerate(self._items):
            wid = item.widget()
            if wid is not None and wid.property("flow_sep"):
                # 다음 묶음이 이 줄에 안 들어가면 구분선을 그리지 않고 넘어간다
                following = self._effective_size(self._items[index + 1]).width()
                needed = self._effective_size(item).width() + self.horizontalSpacing() + following
                if x == effective.x() or x + needed > effective.right():
                    if not test_only:
                        item.setGeometry(QRect(x, y, 0, 0))
                    continue
            space_x = self.horizontalSpacing()
            if space_x == -1 and wid is not None:
                space_x = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Horizontal,
                )
            space_y = self.verticalSpacing()
            if space_y == -1 and wid is not None:
                space_y = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Vertical,
                )
            esize = self._effective_size(item)
            next_x = x + esize.width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + esize.width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), esize))
            x = next_x
            line_height = max(line_height, esize.height())
        return y + line_height - rect.y() + margins.bottom()

    def _smart_spacing(self, pm) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        return parent.spacing()


class FormatToolbar(QWidget):
    """리치텍스트 서식바: 굵게/기울임/밑줄/취소선 + 불릿/번호 리스트.
    폭이 부족하면 FlowLayout이 자동으로 다음 줄로 wrap한다."""

    def __init__(self, editor: QTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        layout = FlowLayout(self, margin=0, h_spacing=4, v_spacing=2)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        # 첫 표시 시 한 줄 높이를 보장해 wrap된 큰 값이 부모로 전파되지 않게 한다.
        self.setMinimumHeight(T.CONTROL["sm"][0])
        self._ink_buttons: dict[str, _InkToolButton] = {}
        self.memo_icons: list[tuple[QToolButton, str]] = []  # 메모 색이 바뀌면 다시 칠한다
        self._group_layout: QHBoxLayout | None = None

        # 좁은 폭에서는 묶음째 다음 줄로 넘어간다 (4.2)
        self._begin_group()
        self._state_buttons = {
            "bold": self._add_icon_btn("bold.svg", tip("굵게", "Ctrl+B"), self.toggle_bold),
            "italic": self._add_icon_btn("italic.svg", tip("기울임", "Ctrl+I"), self.toggle_italic),
            "underline": self._add_icon_btn("underline.svg", tip("밑줄", "Ctrl+U"), self.toggle_underline),
            "strike": self._add_icon_btn("strikethrough.svg", "취소선", self.toggle_strike),
        }
        self._begin_group()
        self._add_font_btn()
        self._add_color_menu_btn("baseline.svg", "글자색", kind="text")
        self._add_color_menu_btn("highlighter.svg", "배경색", kind="bg")
        self._begin_group()
        self._state_buttons["bullet"] = self._add_icon_btn("list.svg", "글머리 목록", self.bullet_list)
        self._state_buttons["numbered"] = self._add_icon_btn("list-ordered.svg", "번호 목록", self.numbered_list)
        self._begin_group()
        self._add_icon_btn("text-align-start.svg", "왼쪽 정렬", lambda: self.set_alignment("left"))
        self._add_icon_btn("text-align-center.svg", "가운데 정렬", lambda: self.set_alignment("center"))
        self._add_icon_btn("text-align-end.svg", "오른쪽 정렬", lambda: self.set_alignment("right"))
        self._begin_group()
        self._add_icon_btn("link.svg", tip("링크 넣기", "Ctrl+K"), self.insert_link)
        self._add_icon_btn("table.svg", "표 넣기", self.insert_table)
        self._begin_group()
        self._add_datetime_btn()
        # 음성 녹음 (Phase 9-2) — 부모 윈도우의 toggle_recording 호출
        self.mic_btn = self._add_icon_btn(
            "mic.svg", "음성 녹음 (시작/종료)", self._on_mic_clicked
        )
        editor.currentCharFormatChanged.connect(lambda _fmt: self.sync_states())
        editor.cursorPositionChanged.connect(self.sync_states)
        # FlowLayout은 좌측 정렬 + 자동 wrap이라 stretch가 필요 없다.

    def sync_states(self) -> None:
        """켜진 서식 단추를 표시한다 (4.2)."""
        editor = self.editor
        current_list = editor.textCursor().currentList()
        list_style = current_list.format().style() if current_list is not None else None
        states = {
            "bold": editor.fontWeight() > int(QFont.Weight.Normal),
            "italic": editor.fontItalic(),
            "underline": editor.fontUnderline(),
            "strike": editor.currentCharFormat().fontStrikeOut(),
            "bullet": list_style == QTextListFormat.Style.ListDisc,
            "numbered": list_style == QTextListFormat.Style.ListDecimal,
        }
        for key, on in states.items():
            button = self._state_buttons[key]
            if bool(button.property("on")) != on:
                button.setProperty("on", on)
                theme_apply.repolish(button)

    def _on_mic_clicked(self) -> None:
        win = self.editor.window()
        if hasattr(win, "toggle_recording"):
            win.toggle_recording()

    # ----- height for width 위임 (FlowLayout이 폭에 따라 wrap된 높이 계산) -----
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self.layout().heightForWidth(width)

    # ----- 서식 토글 (선택 영역 있으면 그 영역, 없으면 이후 입력에 적용) -----
    def toggle_bold(self) -> None:
        normal = int(QFont.Weight.Normal)
        is_bold = self.editor.fontWeight() > normal
        self.editor.setFontWeight(
            QFont.Weight.Normal if is_bold else QFont.Weight.Bold
        )
        self.editor.setFocus()

    def toggle_italic(self) -> None:
        self.editor.setFontItalic(not self.editor.fontItalic())
        self.editor.setFocus()

    def toggle_underline(self) -> None:
        self.editor.setFontUnderline(not self.editor.fontUnderline())
        self.editor.setFocus()

    def toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(
            not self.editor.currentCharFormat().fontStrikeOut()
        )
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def bullet_list(self) -> None:
        self._toggle_list(QTextListFormat.Style.ListDisc)

    def numbered_list(self) -> None:
        self._toggle_list(QTextListFormat.Style.ListDecimal)

    def _toggle_list(self, style: QTextListFormat.Style) -> None:
        cursor = self.editor.textCursor()
        doc = self.editor.document()

        # 커서가 커버하는 블록 목록 수집 (선택 없으면 현재 블록 하나)
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        blocks = []
        block = doc.findBlock(start)
        while block.isValid():
            blocks.append(block)
            if block.position() + block.length() > end:
                break
            block = block.next()

        # 모든 블록이 이미 같은 스타일 목록 안에 있으면 → 해제
        all_same = all(
            b.textList() is not None and b.textList().format().style() == style
            for b in blocks
        )

        if all_same:
            cursor.beginEditBlock()
            for b in blocks:
                tl = b.textList()
                if tl:
                    tl.remove(b)
                    bc = QTextCursor(b)
                    fmt = bc.blockFormat()
                    fmt.setIndent(0)
                    bc.setBlockFormat(fmt)
            cursor.endEditBlock()
        else:
            cursor.createList(style)

        self.editor.setFocus()

    # ----- 정렬 (선택영역 또는 현재 줄) -----
    def set_alignment(self, where: str) -> None:
        mapping = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }
        fmt = QTextBlockFormat()
        fmt.setAlignment(mapping.get(where, Qt.AlignmentFlag.AlignLeft))
        # mergeBlockFormat은 선택영역이 있으면 그 영역의 모든 블록, 없으면 현재 블록에 적용.
        self.editor.textCursor().mergeBlockFormat(fmt)
        self.editor.setFocus()

    # ----- 글자색 / 배경색 (선택영역 필수) -----
    def _toast_no_selection(self) -> None:
        win = self.editor.window()
        if hasattr(win, "_show_toast"):
            win._show_toast("색을 입힐 글자를 먼저 골라 주세요.")

    def apply_text_color(self, color_hex: str | None) -> None:
        """color_hex는 저장되는 밝은 화면 값. None이면 기본 글자색."""
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            self._toast_no_selection()
            return
        cursor.mergeCharFormat(
            memo_document.text_color_format(color_hex, theme_apply.current_mode())
        )
        self._remember_ink("text", color_hex)
        self.editor.setFocus()

    def apply_bg_color(self, color_hex: str | None) -> None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            self._toast_no_selection()
            return
        cursor.mergeCharFormat(
            memo_document.clear_highlight_format() if color_hex is None
            else memo_document.highlight_format(color_hex, theme_apply.current_mode())
        )
        self._remember_ink("bg", color_hex)
        self.editor.setFocus()

    def pick_custom_text_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(T.TEXT_COLORS[0][1]), self, "글자색 고르기",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if chosen.isValid():
            self.apply_text_color(chosen.name())

    def pick_custom_bg_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(T.HIGHLIGHTS[0][1]), self, "형광펜 고르기",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if chosen.isValid():
            self.apply_bg_color(chosen.name())

    def _add_font_btn(self) -> QToolButton:
        """글꼴(family) + 크기(size) 팝업."""
        btn = QToolButton(self)
        btn.setObjectName("fmtBtn")
        self._icon(btn, "a-large-small.svg")
        btn.setToolTip("글꼴 / 크기")
        btn.setFixedSize(T.CONTROL["sm"][0], T.CONTROL["sm"][0])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._font_popup = self._build_font_popup()
        btn.clicked.connect(lambda: self._toggle_popup(btn, self._font_popup))
        self._group_layout.addWidget(btn)
        return btn

    def _build_font_popup(self) -> PopupPanel:
        popup = PopupPanel(self)
        popup.body.setContentsMargins(16, 12, 16, 12)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._font_family_combo = ThemedCombo(popup)
        self._font_family_combo.setMaxVisibleItems(15)
        self._font_family_combo.setFixedWidth(184)
        self._font_family_combo.addItems(sorted(set(QFontDatabase.families())))
        self._font_family_combo.currentTextChanged.connect(self._apply_font_family)
        form.addRow("글꼴", self._font_family_combo)

        self._font_size_combo = ThemedCombo(popup)
        self._font_size_combo.setFixedWidth(184)
        for size in (8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24,
                     26, 28, 32, 36, 40, 48, 56, 64, 72):
            self._font_size_combo.addItem(f"{size}pt", size)
        self._font_size_combo.currentTextChanged.connect(self._apply_font_size)
        form.addRow("크기", self._font_size_combo)
        popup.body.addLayout(form)
        return popup

    def _sync_font_combos(self) -> None:
        cur = self.editor.font()
        self._font_family_combo.blockSignals(True)
        idx = self._font_family_combo.findText(cur.family())
        if idx >= 0:
            self._font_family_combo.setCurrentIndex(idx)
        self._font_family_combo.blockSignals(False)
        self._font_size_combo.blockSignals(True)
        self._font_size_combo.setCurrentText(f"{cur.pointSize() or T.MEMO_BODY_DEFAULT_PT}pt")
        self._font_size_combo.blockSignals(False)

    def _selected_font_size(self) -> int:
        return self._font_size_combo.currentData() or self.editor.font().pointSize() or T.MEMO_BODY_DEFAULT_PT

    def _apply_font_family(self, family: str) -> None:
        if not family:
            return
        win = self.editor.window()
        if hasattr(win, "_apply_app_font"):
            win._apply_app_font(family, self._selected_font_size())
        self.editor.setFocus()
        self._font_popup.hide()

    def _apply_font_size(self, _text: str) -> None:
        win = self.editor.window()
        if hasattr(win, "_apply_app_font"):
            family = self._font_family_combo.currentText() or self.editor.font().family()
            win._apply_app_font(family, self._selected_font_size())
        self.editor.setFocus()
        self._font_popup.hide()

    def _add_color_menu_btn(self, svg_name: str, tip: str, *, kind: str) -> QToolButton:
        """kind='text' or 'bg'. 클릭 시 8색 그리드 + 사용자 정의 팝업."""
        btn = _InkToolButton(kind, self)
        self._ink_buttons[kind] = btn
        btn.setObjectName("fmtBtn")
        btn.setToolTip(tip)
        btn.setFixedSize(T.CONTROL["sm"][0], T.CONTROL["sm"][0])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon(btn, svg_name)
        btn.clicked.connect(lambda: self._open_ink_popup(btn, kind))
        self._group_layout.addWidget(btn)
        return btn

    def _remember_ink(self, kind: str, value: str | None) -> None:
        self._ink_buttons[kind].set_ink(value)
        win = self.editor.window()
        if hasattr(win, "db"):
            win.db.set_setting_str(f"last_ink_{kind}", value or "")

    def load_last_inks(self, db: MemoDatabase) -> None:
        for kind, button in self._ink_buttons.items():
            button.set_ink(db.get_setting_str(f"last_ink_{kind}", "") or None)

    def _current_ink(self, kind: str) -> str | None:
        """지금 글자의 색(저장 값). 고리 표시용."""
        fmt = self.editor.textCursor().charFormat()
        original = memo_document.ORIGINAL_FG if kind == "text" else memo_document.ORIGINAL_BG
        if fmt.hasProperty(original):
            return fmt.stringProperty(original) or None
        prop = QTextFormat.Property.ForegroundBrush if kind == "text" else QTextFormat.Property.BackgroundBrush
        if not fmt.hasProperty(prop):
            return None
        return (fmt.foreground() if kind == "text" else fmt.background()).color().name().upper()

    def _make_ink_popup(self, kind: str) -> InkPopup:
        title, pairs = ("글자색", T.TEXT_COLORS) if kind == "text" else ("형광펜", T.HIGHLIGHTS)
        popup = InkPopup(title, pairs, self._current_ink(kind), theme_apply.current_mode(), self)

        def pick(value) -> None:
            popup.close()
            if kind == "text":
                self.apply_text_color(value)
            else:
                self.apply_bg_color(value)

        def custom() -> None:
            popup.close()
            if kind == "text":
                self.pick_custom_text_color()
            else:
                self.pick_custom_bg_color()

        popup.picked.connect(pick)
        popup.custom_requested.connect(custom)
        return popup

    def _open_ink_popup(self, btn: QToolButton, kind: str) -> None:
        self._active_popup = self._make_ink_popup(kind)
        self._active_popup.show_below(btn)

    def _toggle_popup(self, btn: QWidget, popup: PopupPanel) -> None:
        if popup.isVisible():
            popup.hide()
            return
        if popup is self._font_popup:
            self._sync_font_combos()
        popup.show_below(btn)

    # ----- 구분선 / 드롭다운 헬퍼 -----
    def _begin_group(self) -> None:
        if self._group_layout is not None:
            sep = QFrame(self)
            sep.setObjectName("fmtSep")
            sep.setProperty("flow_sep", True)
            sep.setFixedSize(1, 16)
            self.layout().addWidget(sep)
        group = QWidget(self)
        self._group_layout = QHBoxLayout(group)
        self._group_layout.setContentsMargins(0, 0, 0, 0)
        self._group_layout.setSpacing(2)
        self.layout().addWidget(group)

    def _icon(self, btn: QToolButton, asset: str) -> None:
        btn.setIconSize(QSize(16, 16))
        self.memo_icons.append((btn, asset))

    def _add_icon_btn(self, svg_name: str, tip: str, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("fmtBtn")
        btn.setToolTip(tip)
        btn.setFixedSize(T.CONTROL["sm"][0], T.CONTROL["sm"][0])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon(btn, svg_name)
        btn.clicked.connect(slot)
        self._group_layout.addWidget(btn)
        return btn

    def _add_datetime_btn(self) -> None:
        btn = QToolButton(self)
        btn.setObjectName("fmtBtn")
        btn.setToolTip("날짜 넣기")
        btn.setFixedSize(T.CONTROL["sm"][0], T.CONTROL["sm"][0])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon(btn, "calendar.svg")
        btn.clicked.connect(lambda: self._open_date_popup(btn))
        self._group_layout.addWidget(btn)

    def _make_date_popup(self) -> DatePopup:
        popup = DatePopup(self)

        def insert(day: QDate) -> None:
            popup.close()
            self.editor.textCursor().insertText(day.toString("yyyy-MM-dd"))
            self.editor.setFocus()

        popup.chosen.connect(insert)
        return popup

    def _open_date_popup(self, btn: QToolButton) -> None:
        self._active_popup = self._make_date_popup()
        self._active_popup.show_below(btn)

    # ----- 링크 삽입 -----
    def insert_link(self) -> None:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().strip()

        dlg = LinkDialog(selected, self.window(), show_text=not selected)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.editor.setFocus()
            return
        display, url = dlg.values()
        if not url:
            self.editor.setFocus()
            return

        if url and not url.startswith(("http://", "https://", "ftp://", "mailto:")):
            url = "https://" + url

        fmt = memo_document.link_format(url, theme_apply.current_mode())

        cursor = self.editor.textCursor()
        if selected:
            cursor.mergeCharFormat(fmt)
        else:
            cursor.insertText(display if display else url, fmt)

        # 링크 삽입 후 서식 초기화
        reset = QTextCharFormat()
        reset.setAnchor(False)
        reset.setAnchorHref("")
        reset.setFontUnderline(False)
        self.editor.setCurrentCharFormat(reset)
        self.editor.setFocus()

    # ----- 표 삽입 -----
    def insert_table(self) -> None:
        dlg = TableDialog(parent=self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.editor.setFocus()
            return

        rows, cols, has_header = dlg.values()

        fmt = QTextTableFormat()
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        fmt.setBorderStyle(QTextTableFormat.BorderStyle.BorderStyle_Solid)
        fmt.setBorder(1)
        fmt.setWidth(QTextTableFormat.WidthType.PercentageWidth if False else fmt.width())

        cursor = self.editor.textCursor()
        table = cursor.insertTable(rows, cols, fmt)

        if has_header:
            header_fmt = QTextCharFormat()
            header_fmt.setFontWeight(QFont.Weight.Medium)
            for col in range(cols):
                cell = table.cellAt(0, col)
                cell_cursor = cell.firstCursorPosition()
                cell_cursor.mergeCharFormat(header_fmt)
                cell_cursor.insertText(f"헤더{col + 1}")

        memo_document.decorate_table(table, theme_apply.current_mode())
        # 첫 셀로 커서 이동
        first_cell = table.cellAt(0, 0).firstCursorPosition()
        self.editor.setTextCursor(first_cell)
        self.editor.setFocus()

    # ----- 날짜/시간 삽입 -----
    def insert_datetime(self, fmt_key: str) -> None:
        now = datetime.now()
        if fmt_key == "notepad":
            raw = now.strftime("%p %I:%M %Y-%m-%d")
            text = raw.replace("AM", "오전").replace("PM", "오후")
        elif fmt_key == "date":
            text = now.strftime("%Y-%m-%d")
        elif fmt_key == "time":
            text = now.strftime("%H:%M")
        elif fmt_key == "iso":
            text = now.strftime("%Y-%m-%dT%H:%M:%S")
        else:  # korean
            text = f"{now.strftime('%Y년 %m월 %d일')} {WEEKDAYS_KO[now.weekday()]}"

        self.editor.textCursor().insertText(text)
        self.editor.setFocus()


class _SortSelector(QWidget):
    """정렬 콤보. 좁으면 아이콘 단추로 바뀐다."""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._index = 0
        self._compact = False
        self._icon_color = T.LIGHT["fg_secondary"]
        self._btn = QToolButton(self)
        self._btn.setObjectName("sortCombo")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn.setIconSize(QSize(16, 16))
        self._btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # 셰브런을 글자 뒤로
        self._btn.setFixedHeight(T.CONTROL["md"][0])
        self._btn.clicked.connect(self._open_popup)
        layout.addWidget(self._btn)
        self._apply()

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(SORT_KEYS):
            self._index = index
            self._apply()

    def full_width(self) -> int:
        """글자가 다 보일 때의 폭. 가장 긴 이름 기준이라 고를 때마다 폭이 안 변한다."""
        metrics = self._btn.fontMetrics()
        text = max(metrics.horizontalAdvance(c[0]) for c in SORT_CRITERIA)
        return text + 16 + 4 + 2 * T.CONTROL["md"][1] + 2

    def set_compact(self, compact: bool) -> None:
        if compact != self._compact:
            self._compact = compact
            self._apply()

    def set_icon_color(self, color: str) -> None:
        self._icon_color = color
        self._apply()

    def _apply(self) -> None:
        criterion, direction = sort_description(self._index)
        self._btn.setToolTip(f"정렬: {criterion} · {direction}")
        self._btn.setProperty("compact", self._compact)
        asset = "arrow-down-wide-narrow.svg" if self._compact else "chevron-down.svg"
        self._btn.setIcon(QIcon(tinted_pixmap(asset, self._icon_color, 16)))
        if self._compact:
            self._btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self._btn.setFixedWidth(T.CONTROL["md"][0])
        else:
            self._btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self._btn.setText(criterion)
            self._btn.setFixedWidth(self.full_width())
        theme_apply.repolish(self._btn)

    def _make_popup(self) -> SortPopup:
        popup = SortPopup(self._index, self)
        popup.changed.connect(self._select)
        return popup

    def _open_popup(self) -> None:
        self._popup = self._make_popup()
        self._popup.show_below(self._btn)

    def _select(self, index: int) -> None:
        if index != self._index:
            self.setCurrentIndex(index)
            self.currentIndexChanged.emit(index)


class DragGrip(QWidget):
    """탭 컬럼 상단의 세로 이동 그립 (크기 변경 없이 y 위치만 이동)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(GRIP_HEIGHT)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("끌어서 위아래로 옮기기")
        self._press_global = None
        self._start_geom = None

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme_apply.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = _inner_rounded_path(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), T.RADIUS["surface"], MemoTabButton.side
        )
        fill = QPainterPath(outline)
        fill.closeSubpath()
        painter.fillPath(fill, QColor(t["bg_canvas"]))
        painter.setPen(QPen(QColor(t["line"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)
        icon = tinted_pixmap("grip-vertical.svg", t["fg_secondary"], BAR_ICON)
        painter.drawPixmap((self.width() - BAR_ICON) // 2, (self.height() - BAR_ICON) // 2, icon)
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_geom = self.window().geometry()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press_global is None:
            return super().mouseMoveEvent(event)
        win = self.window()
        if not isinstance(win, SlideMemoWindow):
            return
        dy = event.globalPosition().toPoint().y() - self._press_global.y()
        g = self._start_geom
        screen = win._screen_rect()
        new_y = g.y() + dy
        new_y = max(
            screen.y(),
            min(new_y, screen.y() + screen.height() - g.height()),
        )
        win.setGeometry(g.x(), new_y, g.width(), g.height())
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press_global is not None:
            self._press_global = None
            self._start_geom = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            win = self.window()
            if isinstance(win, SlideMemoWindow):
                win._save_user_size()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ClickableLabel(QLabel):
    """클릭할 수 있는 라벨. 토스트의 '되돌리기'에만 쓴다."""

    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


GUIDE_BAR_KEY = "guide_bar_done"    # 1단계(바 다루기) 안내 완료
GUIDE_BODY_KEY = "guide_body_done"  # 2단계(메모 쓰기) 안내 완료


class _GuideTail(QWidget):
    """말풍선 꼬리 8×16. direction은 뾰족한 쪽."""

    WIDTH, HEIGHT = 9, 16

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.direction = "right"

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme_apply.current()
        w, h = self.width(), self.height()
        base, tip_x = (0.0, w - 1.0) if self.direction == "right" else (float(w), 1.0)
        points = (QPointF(base, 0), QPointF(tip_x, h / 2), QPointF(base, h))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["bg_raised"]))
        painter.drawPolygon(QPolygonF(points))
        painter.setPen(QPen(QColor(t["line"]), 1))
        painter.drawLine(points[0], points[1])
        painter.drawLine(points[1], points[2])
        painter.end()


class GuideBubble(QWidget):
    """가이드 말풍선. 설명할 위젯 옆에 붙는다.

    바 자체가 항상 위(topmost) 창이라 말풍선도 같은 급이어야 뒤로 안 숨는다.
    (_zorder_locked가 이 창이 떠 있는 동안 바의 topmost 재점령을 막는다)"""

    CARD_WIDTH = 260
    MARGIN = 12  # 그림자·꼬리 자리

    def __init__(self, win: "SlideMemoWindow") -> None:
        # 부모를 win으로 두되 Tool 플래그라 독립 창이다 — 부모가 정리될 때 같이
        # 사라지므로 종료 중에 홀로 남아 죽는 일이 없다.
        super().__init__(
            win,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._win = win
        self._on_next = None
        self._on_skip = None
        self.setFixedWidth(self.CARD_WIDTH + 2 * self.MARGIN)
        # 부모의 메모 창 스타일을 물려받지 않도록 카드 이름은 팝업과 같게 쓴다
        shell = QVBoxLayout(self)
        shell.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN + 4)
        self.card = QFrame()
        self.card.setObjectName("popupCard")
        add_float_shadow(self.card)
        shell.addWidget(self.card)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        self.title_lbl = role_label("", "guideTitle")
        self.title_lbl.setWordWrap(True)
        lay.addWidget(self.title_lbl)
        self.text_lbl = role_label("", "description")
        self.text_lbl.setWordWrap(True)
        lay.addWidget(self.text_lbl)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.step_lbl = role_label("", "step")
        theme_apply.set_tabular(self.step_lbl)
        row.addWidget(self.step_lbl)
        row.addStretch(1)
        self.skip_btn = make_button("건너뛰기", "ghost")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(lambda: self._on_skip and self._on_skip())
        row.addWidget(self.skip_btn)
        self.next_btn = make_button("다음", "primary")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(lambda: self._on_next and self._on_next())
        row.addWidget(self.next_btn)
        lay.addLayout(row)
        self.tail = _GuideTail(self)

    def show_step(self, title, text, anchor, index, total, on_next, on_skip) -> None:
        self.title_lbl.setText(title)
        self.text_lbl.setText(text)
        self.step_lbl.setText(f"{index}/{total}")
        self.next_btn.setText("완료" if index == total else "다음")
        self._on_next, self._on_skip = on_next, on_skip
        self.adjustSize()
        self.layout().activate()
        self._place_beside(anchor)
        self.show()
        self.raise_()

    def _place_beside(self, anchor: QWidget) -> None:
        """설명 대상의 높이에 맞추되, 가로로는 창 바깥에 둔다.

        대상 위젯 기준으로 밀면 말풍선이 본문 위를 덮어 정작 가리키는 것을 가린다.
        접힘 상태에서는 창 폭이 아니라 실제로 보이는 컬럼이 기준이다
        (접힘=마스크로 컬럼만 노출, 나머지 폭은 투명).
        """
        g = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        scr = self._win._screen_rect()
        if self._win.is_expanded:
            ref = self._win.geometry()
        else:
            col = self._win.tab_column
            ref = QRect(col.mapToGlobal(QPoint(0, 0)), col.size())
        gap = 8
        if self._win.side == "right":
            x = ref.left() - self.width() - gap
        else:
            x = ref.right() + gap
        x = max(scr.x() + 8, min(x, scr.x() + scr.width() - self.width() - 8))
        y = g.center().y() - self.height() // 2
        y = max(scr.y() + 8, min(y, scr.y() + scr.height() - self.height() - 8))
        self.move(x, y)
        # 꼬리는 카드 가장자리에서 설명 대상을 가리킨다
        self.tail.direction = "right" if self._win.side == "right" else "left"
        card = self.card.geometry()
        tail_x = card.right() if self._win.side == "right" else card.left() - self.tail.width() + 1
        wanted = g.center().y() - y - self.tail.height() // 2
        margin = T.RADIUS["control"] + 2
        tail_y = max(card.top() + margin, min(wanted, card.bottom() - margin - self.tail.height()))
        self.tail.move(tail_x, tail_y)
        self.tail.raise_()
        self.tail.update()


class ResizeHandle(QWidget):
    """창 가장자리에 깔리는 투명 드래그 핸들. edge ∈ {left, top, bottom}."""

    def __init__(self, parent: QWidget, edge: str) -> None:
        super().__init__(parent)
        self.edge = edge
        if edge in ("left", "right", "tab"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._press_global = None
        self._start_geom = None
        self._start_tab_w = 0

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_geom = self.window().geometry()
            self._start_tab_w = getattr(self.window(), "tab_width", 0)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press_global is None:
            return super().mouseMoveEvent(event)
        win = self.window()
        if not isinstance(win, SlideMemoWindow):
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if self.edge == "tab":
            # 접힘 상태: 컬럼 안쪽 가장자리 드래그 → 바(인덱스 컬럼) 폭 조절.
            # 창 geometry는 그대로고 mask만 넓어진다 (접힘=mask 폭이 곧 바 폭).
            dx = delta.x() if win.side == "left" else -delta.x()
            win._apply_tab_width(self._start_tab_w + dx)
            event.accept()
            return
        g = self._start_geom
        screen = win._screen_rect()

        if self.edge == "left":
            # 우측 모드: 좌측 가장자리 드래그 → 폭 조절 (우측 끝 고정)
            new_w = max(MIN_W, min(g.width() - delta.x(), screen.width()))
            new_x = g.x() + (g.width() - new_w)
            new_x = max(screen.x(), new_x)
            win.setGeometry(new_x, g.y(), new_w, g.height())
        elif self.edge == "right":
            # 좌측 모드: 우측 가장자리 드래그 → 폭 조절 (좌측 끝 고정)
            new_w = max(MIN_W, min(g.width() + delta.x(), screen.width()))
            if g.x() + new_w > screen.x() + screen.width():
                new_w = screen.x() + screen.width() - g.x()
            win.setGeometry(g.x(), g.y(), new_w, g.height())
        elif self.edge == "top":
            new_h = max(MIN_H, min(g.height() - delta.y(), screen.height()))
            new_y = g.y() + (g.height() - new_h)
            new_y = max(screen.y(), new_y)
            win.setGeometry(g.x(), new_y, g.width(), new_h)
        elif self.edge == "bottom":
            new_h = max(MIN_H, min(g.height() + delta.y(), screen.height()))
            max_bottom = screen.y() + screen.height()
            if g.y() + new_h > max_bottom:
                new_h = max_bottom - g.y()
            win.setGeometry(g.x(), g.y(), g.width(), new_h)
        if not win.is_expanded:  # 접힘 = 보이는 건 마스크라 높이 변화를 따라가야
            win.setMask(win._collapsed_mask_region())
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press_global is not None:
            self._press_global = None
            self._start_geom = None
            win = self.window()
            if isinstance(win, SlideMemoWindow):
                if self.edge == "tab":
                    win.db.set_setting_int("tab_width", win.tab_width)
                else:
                    win._save_user_size()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ----- Windows always-on-top 강제 -----
# WindowStaysOnTopHint(WS_EX_TOPMOST)는 best-effort라 다른 topmost 창이나
# 시스템 이벤트(오버레이/알림/explorer 재시작 등)에 의해 z-order에서 밀려날 수
# 있다. 밀려나려는 순간 Windows가 보내는 WM_WINDOWPOSCHANGING을 가로채 삽입
# 위치를 HWND_TOPMOST로 되돌려, 실제로 가려지기 전에 막는다.
# (폴링 없이 z-order가 바뀔 때만 반응 → 펼침/접힘 상태 무관하게 동작)
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _WM_WINDOWPOSCHANGING = 0x0046
    _SWP_NOZORDER = 0x0004
    _HWND_TOPMOST = -1
    _WM_HOTKEY = 0x0312

    class _WINDOWPOS(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_ssize_t),
            ("hwndInsertAfter", ctypes.c_ssize_t),
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("cx", ctypes.c_int),
            ("cy", ctypes.c_int),
            ("flags", ctypes.c_uint),
        ]


class SlideMemoWindow(QWidget):
    def __init__(self, db: MemoDatabase) -> None:
        super().__init__()
        self.db = db
        self.current_memo: Memo | None = None
        self.is_expanded = False
        self.trash_mode = False
        self._trash_preview_id: int | None = None  # 휴지통에서 미리보기 중인 메모
        self._quitting = False
        # 가이드(말풍선) 상태
        self._guide: GuideBubble | None = None
        self._guide_steps_queue: list[tuple[str, object]] = []
        self._guide_index = 0
        self._guide_which = "bar"
        self._ai_worker: object | None = None
        self._ai_pending: str | None = None  # 진행 중인 feature_key
        # 음성 녹음 상태 (Phase 9-2)
        self._recorder: object | None = None
        self._whisper_worker: object | None = None
        self._recording_timer: QTimer | None = None
        # 0=오른쪽, 1=왼쪽 가장자리
        self.side = "left" if db.get_setting_int("side", 0) == 1 else "right"
        self._edge_button = EdgeLogoButton()
        self._edge_button.clicked.connect(self.show_bar)
        self._edge_button.moved.connect(lambda top: self.db.set_setting_int(EDGE_BUTTON_Y_KEY, top))
        self._edge_timer = QTimer(self)  # 전체 화면 앱을 살핀다. 숨겨 둔 동안만 돈다
        self._edge_timer.setInterval(1000)
        self._edge_timer.timeout.connect(self._sync_edge_button)

        self._load_tab_geometry()  # tab_width 등을 _setup_window/_build_ui 전에 결정
        self._load_display_mode()  # Tool 플래그 결정에 필요
        self._setup_window()
        self._setup_fonts()
        self._color_slots = parse_color_slots(self.db.get_setting_str(USER_SLOTS_KEY, ""))
        self._memo_icon_color = T.LIGHT["fg_secondary"]
        self._build_ui()
        self._setup_animation()
        self._setup_shortcuts()
        self._setup_autosave()
        self._apply_memo_theme(DEFAULT_COLOR)  # 초기 테마
        self._load_user_size()  # DB에서 사용자 사이즈 로드 (없으면 기본값)
        # body는 항상 visible 유지 — layout 자리 차지하게 두고 opacity(0)로만
        # 가리고, 시각/클릭 차단은 setMask로 처리. hide()는 layout 자리를 줄여
        # tab_column 위치가 변동되니 쓰지 않는다.
        self.handle_left.hide()
        self.handle_right.hide()
        self.handle_top.hide()
        self.handle_bottom.hide()
        self._position_collapsed()
        self._refresh_memo_tabs(select_first=True)
        self._refresh_ai_bar()
        # 첫 expand 시 발생하는 lazy init 버벅임을 줄이기 위해 사용자가 안 보는
        # 사이 (윈도우 show 직전) body 위젯을 offscreen pixmap에 한 번 render.
        # → editor의 QTextDocument 초기화, stylesheet 적용, FlowLayout 첫 패스,
        # 폰트 캐시가 미리 트리거된다.
        self._warm_up_body()
        QApplication.instance().installEventFilter(self)
        self._register_hotkey()  # Ctrl+Shift+Z 전역 숨기기/복귀

    def _warm_up_body(self) -> None:
        try:
            self.body.ensurePolished()
            self.format_toolbar.ensurePolished()
            self.editor.ensurePolished()
            self.title_input.ensurePolished()
            self.body.layout().activate()
            warm_size = self._expanded_geometry().size()
            if warm_size.width() > 0 and warm_size.height() > 0:
                pix = QPixmap(warm_size)
                pix.fill(Qt.GlobalColor.transparent)
                # 두 번 render — 첫 패스는 layout 계산, 둘째 패스는 polish 완료 상태
                self.body.render(pix)
                self.body.layout().activate()
                self.body.render(pix)
        except Exception:
            pass  # warm-up은 실패해도 앱 동작에 무관

    # ----- setup -----
    def _load_tab_geometry(self) -> None:
        """DB에서 인덱스 탭 폭/각 탭 높이 로드. 범위 밖 값은 clamp."""
        w = self.db.get_setting_int("tab_width", TAB_WIDTH)
        self.tab_width = max(TAB_WIDTH_MIN, min(w, TAB_WIDTH_MAX))
        h = self.db.get_setting_int("memo_tab_height", MEMO_TAB_HEIGHT)
        self.memo_tab_height = max(MEMO_TAB_HEIGHT_MIN, min(h, MEMO_TAB_HEIGHT_MAX))
        MemoTabButton.button_height = self.memo_tab_height

    def _tint_chrome_icons(self) -> None:
        """메모 색과 무관한 바·카드 아이콘. 화면 모드가 바뀌면 다시 칠한다."""
        t = theme_apply.current()
        for button, asset in self._bar_icons:
            self._set_bar_icon(button, asset)
        self._set_bar_icon(self.hide_btn, self.hide_icon_asset())
        self._rec_stop_btn.setIcon(QIcon(tinted_pixmap("square.svg", t["fg"], 16)))
        self.drag_grip.update()

    def _set_bar_icon(self, button: QPushButton, asset: str) -> None:
        button.setIcon(QIcon(tinted_pixmap(asset, theme_apply.current()["fg_secondary"], BAR_ICON)))

    def _load_display_mode(self) -> None:
        """display_mode: 'tray' / 'taskbar' / 'both'."""
        m = self.db.get_setting_str("display_mode", DISPLAY_MODE_DEFAULT)
        self.display_mode = m if m in DISPLAY_MODES else DISPLAY_MODE_DEFAULT

    def _window_flags_for_mode(self) -> Qt.WindowType:
        """display_mode에 맞는 윈도우 플래그 조합."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Tool 플래그가 있으면 작업표시줄에 안 뜸 (트레이 전용에 적합).
        if self.display_mode == "tray":
            flags |= Qt.WindowType.Tool
        return flags

    _HOTKEY_ID = 1

    def _register_hotkey(self) -> None:
        """Ctrl+Shift+Z 전역 토글(잠깐 숨기기/복귀).

        다른 앱이 선점했으면 등록만 실패하고 앱은 정상 동작한다.
        setWindowFlags가 native 창을 재생성하면 등록이 창과 함께 사라지므로
        그때마다 다시 불러야 한다."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            # MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT(꾹 누를 때 반복 토글 방지), 'Z'
            ctypes.windll.user32.RegisterHotKey(
                int(self.winId()), self._HOTKEY_ID, 0x0002 | 0x0004 | 0x4000, 0x5A
            )
        except Exception:
            pass

    def _zorder_locked(self) -> bool:
        """z-order를 건드리면 안 되는 상태. 지금 topmost를 다시 밀어 올리면
        방금 뜬 팝업/모달/툴팁이 그 아래로 깔려 가려진다."""
        return (
            QApplication.activePopupWidget() is not None
            or QApplication.activeModalWidget() is not None
            or tooltip_visible()  # 툴팁도 topmost 창이라 순서 싸움에 진다
            or (self._guide is not None and self._guide.isVisible())
        )

    def _force_topmost(self) -> None:
        """Qt raise_() + Windows API SetWindowPos로 TOPMOST z-order 강제 재설정."""
        self.raise_()
        try:
            import ctypes
            ctypes.windll.user32.SetWindowPos(
                int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001  # HWND_TOPMOST, SWP_NOMOVE|SWP_NOSIZE
            )
        except Exception:
            pass

    def nativeEvent(self, eventType, message):  # noqa: N802
        # z-order가 바뀌려는 순간 삽입 위치를 topmost로 되돌려 가려짐을 막는다.
        # (다른 topmost 창에 밀려나는 것을 발생 전에 차단 — 펼침/접힘 모두 적용)
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                # 전역 단축키 (Ctrl+Shift+Z) → 잠깐 숨기기/복귀 토글.
                # hide()된 창에도 메시지가 오므로 숨김 상태에서 복귀 트리거로 동작.
                if msg.message == _WM_HOTKEY and msg.wParam == self._HOTKEY_ID:
                    if self.isVisible():
                        self.hide_bar()
                    else:
                        self.show_bar()
                    return True, 0
                # 다이얼로그/팝업/툴팁이 떠 있으면 topmost를 강제하지 않는다 —
                # 안 그러면 메모창이 그 위로 올라가 방금 뜬 것을 가린다.
                # (툴팁이 뜰 때 Windows가 보내는 z-order 변경 알림에 그대로
                #  반응하면, 툴팁이 뜬 순간 창이 다시 앞으로 나와 덮어버린다)
                if msg.message == _WM_WINDOWPOSCHANGING and not self._zorder_locked():
                    wp = _WINDOWPOS.from_address(msg.lParam)
                    # SWP_NOZORDER가 없을 때(=z-order가 실제로 바뀌는 경우)만 개입.
                    # 단순 이동/리사이즈는 건드리지 않는다.
                    if not (wp.flags & _SWP_NOZORDER):
                        wp.hwndInsertAfter = _HWND_TOPMOST
            except Exception:
                pass
        # 구조체만 in-place 수정하고 기본 처리를 계속하게 둔다.
        # (PyQt6에서 super().nativeEvent() 호출/반환은 하드 크래시를 유발하므로 금지)
        return False, 0

    def _apply_window_opacity(self) -> None:
        pct = max(50, min(self.db.get_setting_int("window_opacity", 100), 100))
        self.setWindowOpacity(pct / 100.0)

    def _setup_window(self) -> None:
        self.setWindowFlags(self._window_flags_for_mode())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Slide Memo")
        # 폭이 tab_width~사용자 드래그 폭 사이로 변경 가능 (접힘=tab_width, 펼침=user_width).
        # 화면 안에 항상 전체가 들어오도록 폭 자체가 슬라이드함.
        self.setMinimumWidth(self.tab_width)
        # setMaximumWidth 안 둠 - 사용자가 좌측 드래그로 키울 수 있어야 함
        self._apply_window_opacity()

    def _setup_fonts(self) -> None:
        families = set(QFontDatabase.families())
        saved_family = self.db.get_setting_str("app_font_family", "")
        saved_size = self.db.get_setting_int("app_font_size", T.MEMO_BODY_DEFAULT_PT)
        family = saved_family if saved_family and saved_family in families else T.FONT_FAMILY
        self.editor_font = theme_apply.memo_font(family, saved_size)
        # 메모 탭의 회전 텍스트도 같은 family 사용 (크기는 paintEvent에서 작게 고정)
        MemoTabButton.app_font_family = self.editor_font.family()

    def _apply_app_font(self, family: str, size: int) -> None:
        """글꼴/크기 메뉴에서 변경 시 **현재 메모만** 적용.
        본문은 selectAll + mergeCharFormat (HTML inline style로 저장),
        제목/탭은 위젯 폰트 + DB 컬럼 저장. 다른 메모는 영향 없음.
        앱 기본값(새 메모)은 app_font_family/size 설정 키 갱신."""
        if not family or size <= 0:
            return
        if self.current_memo is None:
            return
        # 앱 default 갱신 (새 메모 만들 때 사용)
        self.db.set_setting_str("app_font_family", family)
        self.db.set_setting_int("app_font_size", size)
        # 본문: 모든 문자에 char format 적용 (커서 위치 보존)
        cursor = self.editor.textCursor()
        anchor = cursor.anchor()
        position = cursor.position()
        self.editor.blockSignals(True)
        sel = QTextCursor(self.editor.document())
        sel.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setFontFamily(family)
        fmt.setFontPointSize(size)
        sel.mergeCharFormat(fmt)
        # 커서 복원
        restored = QTextCursor(self.editor.document())
        restored.setPosition(anchor)
        restored.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(restored)
        self.editor.blockSignals(False)
        # 위젯 + 문서 기본 폰트 (서식 없는 새 입력에도 적용)
        memo_font = theme_apply.memo_font(family, size)
        self.editor.document().setDefaultFont(memo_font)
        self.editor.setFont(memo_font)
        # 메모 객체 + DB 저장 + 탭 갱신
        self.current_memo.font_family = family
        self.current_memo.font_size = size
        self.current_memo = self.db.update(
            self.current_memo.id,
            content=memo_document.saved_html(self.editor.document()),
            font_family=family,
            font_size=size,
        )
        self._refresh_memo_tabs()
        self._update_tabs_selected()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("mainContainer")
        self.container.setMinimumWidth(self.tab_width)
        outer.addWidget(self.container)

        root = QHBoxLayout(self.container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 본문 (좌측, 펼친 상태에서만 보임) ----
        self.body = QWidget(self.container)
        self.body.setObjectName("bodyPanel")
        self.body.setMinimumWidth(0)  # 폭 0까지 줄어들 수 있어야 슬라이드 가능
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)
        root.addWidget(self.body, stretch=1)

        # 상단: 검색바 (일반 모드) / 돌아가기 버튼 (휴지통 모드)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("제목·본문 검색")
        self._search_icon = self.search_input.addAction(
            QIcon(), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search_input.textChanged.connect(self._on_search_changed)
        top.addWidget(self.search_input, stretch=1)

        # 휴지통 닫기 / 전체 비우기는 인덱스 컬럼에 있다 (col_back_btn, col_empty_btn)
        # — 본문 상단은 휴지통 모드에서도 검색/정렬 그대로 유지한다.

        # 정렬 드롭다운
        self.sort_combo = _SortSelector()
        saved = self.db.get_setting_int("sort_mode", 0)
        self.sort_combo.setCurrentIndex(max(0, min(saved, len(SORT_OPTIONS) - 1)))
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top.addWidget(self.sort_combo)

        # 정렬 옆: 고정 토글 + 내보내기
        self.pin_btn = QPushButton()
        self.pin_btn.setObjectName("iconBtn")
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setFixedSize(T.CONTROL["md"][0], T.CONTROL["md"][0])
        self.pin_btn.setIconSize(QSize(16, 16))
        self.pin_btn.clicked.connect(self._toggle_pin_current)
        top.addWidget(self.pin_btn)

        self.export_btn = QPushButton()
        self.export_btn.setObjectName("iconBtn")
        self.export_btn.setToolTip(tip("내보내기", "Ctrl+E"))
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setFixedSize(T.CONTROL["md"][0], T.CONTROL["md"][0])
        self.export_btn.setIconSize(QSize(16, 16))
        self.export_btn.clicked.connect(self._export_current_memo)
        top.addWidget(self.export_btn)

        body_layout.addLayout(top)

        # 에디터 패널 (제목+색상 / 본문 / 미리보기 버튼)
        editor_panel = QWidget()
        ep = QVBoxLayout(editor_panel)
        ep.setContentsMargins(0, 0, 0, 0)
        ep.setSpacing(8)

        # 제목 줄: 제목 입력 + 색상 dot들 + 사용자 정의(+) 가로 배치
        self.title_input = QLineEdit()
        self.title_input.setObjectName("titleInput")
        self.title_input.setPlaceholderText("제목")
        self.title_input.textChanged.connect(self._on_text_changed)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self.title_input, stretch=1)
        # 색 단추 하나 + 팝업 (4.2, 4.4)
        self.color_btn = MemoColorButton()
        self.color_btn.clicked.connect(self._open_color_popup)
        title_row.addWidget(self.color_btn)
        ep.addLayout(title_row)

        divider = QFrame()
        divider.setObjectName("bodyDivider")
        divider.setFixedHeight(1)
        ep.addWidget(divider)

        # 에디터 (서식바가 참조하므로 먼저 생성)
        self.editor = RichPasteTextEdit()
        self.editor.setObjectName("editor")
        self.editor.setFont(self.editor_font)
        self.editor.setAcceptRichText(True)  # 이미지 붙여넣기 + 서식 지원
        self.editor.setPlaceholderText("여기에 메모를 적어 보세요")
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.textChanged.connect(self._refresh_search_marks)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._show_editor_context_menu)
        # 메모마다 문서를 따로 두고 갈아끼운다 (undo 스택이 문서에 붙어 있으므로).
        # 부모는 반드시 창 — 에디터 자식이면 setDocument가 이전 문서를 지워버린다.
        self._doc_cache: dict[int, QTextDocument] = {}
        self._scratch_doc = QTextDocument(self)  # 메모 아닌 내용(빈 화면·휴지통 미리보기)용

        # 서식바: 서식 버튼들만 (색상 dot/사용자 정의는 제목 줄로 분리)
        self.format_toolbar = FormatToolbar(self.editor)
        self.format_toolbar.load_last_inks(self.db)

        ep.addWidget(self.format_toolbar)

        # 녹음 줄: 서식바 아래 떠 있는 카드 (4.2). 평소엔 숨김
        self._rec_card = QFrame()
        self._rec_card.setObjectName("floatCard")
        add_float_shadow(self._rec_card)
        rec_layout = QHBoxLayout(self._rec_card)
        rec_layout.setContentsMargins(12, 8, 8, 8)
        rec_layout.setSpacing(8)
        rec_dot = QLabel()
        rec_dot.setObjectName("recDot")
        rec_dot.setFixedSize(8, 8)
        rec_layout.addWidget(rec_dot)
        self._rec_time = QLabel()
        theme_apply.set_tabular(self._rec_time)
        rec_layout.addWidget(self._rec_time, 1)
        self._rec_stop_btn = make_button("중지하기", "secondary")
        self._rec_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_stop_btn.clicked.connect(self.toggle_recording)
        rec_layout.addWidget(self._rec_stop_btn)
        self._rec_card.hide()
        ep.addWidget(self._rec_card)
        ep.addWidget(self.editor, stretch=1)

        # AI 기능 바 (에디터 하단, AI 활성 시만 표시)
        self._ai_bar = QWidget()
        ai_bar_layout = QHBoxLayout(self._ai_bar)
        ai_bar_layout.setContentsMargins(0, 0, 0, 0)
        ai_bar_layout.setSpacing(8)
        self._ai_spark = QLabel()
        ai_bar_layout.addWidget(self._ai_spark)
        from ai_features import AI_FEATURES
        for _key, _info in AI_FEATURES.items():
            _btn = QPushButton(_info["button"])
            _btn.setObjectName("aiFeatureBtn")
            _btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn.clicked.connect(lambda _checked, k=_key: self._run_ai_feature(k))
            ai_bar_layout.addWidget(_btn)
        ai_bar_layout.addStretch(1)
        self._ai_bar.hide()
        ep.addWidget(self._ai_bar)

        # AI 진행: 1초가 넘으면 본문 가운데에 카드 하나를 띄운다 (4.2)
        self._ai_status_lbl = ProgressCard(self.body)
        self._ai_status_lbl.canceled.connect(self._cancel_ai)

        body_layout.addWidget(editor_panel, stretch=1)

        # 토스트: 창 위쪽 가운데 (4.2). 평소엔 숨김
        self._toast_lbl = Toast(self.body)
        self._toast_action = None  # 되돌리기를 누르면 실행할 동작
        self._toast_lbl.clicked.connect(self._on_toast_clicked)
        self._toast_lbl.hide()
        self._toast_timer = self._toast_lbl.timer

        # ---- 우측 탭 컬럼 (항상 보임) ----
        self.tab_column = QWidget(self.container)
        self.tab_column.setObjectName("tabColumn")
        self.tab_column.setFixedWidth(self.tab_width)
        col_layout = QVBoxLayout(self.tab_column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)

        # 세로 이동 그립 (맨 위)
        self._bar_icons: list[tuple[QPushButton, str]] = []
        self.drag_grip = DragGrip(self.tab_column)
        col_layout.addWidget(self.drag_grip)
        col_layout.addSpacing(4)

        # 컬럼 우클릭 → 잠깐 숨기기 메뉴 (자기 메뉴 없는 자식 위젯의 우클릭은
        # 컬럼까지 버블링되므로 그립·설정·휴지통 버튼 위에서도 동작)
        self.tab_column.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_column.customContextMenuRequested.connect(self._show_column_menu)

        # 스크롤 가능한 탭 목록
        self.tab_scroll = QScrollArea(self.tab_column)
        self.tab_scroll.setObjectName("tabScroll")
        self.tab_scroll.setWidgetResizable(True)
        self.tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 띠가 모니터 끝에 닿아야 하므로 스크롤바 자리를 두지 않는다. 휠 스크롤은 된다.
        self.tab_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tab_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.tabs_container = QWidget()
        self.tabs_container.setObjectName("tabsContainer")
        self.tabs_layout = QVBoxLayout(self.tabs_container)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(0)  # 인덱스를 하나의 띠처럼 붙임
        self.tabs_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tab_scroll.setWidget(self.tabs_container)
        # 새 탭이 생기면 스크롤 범위는 레이아웃이 끝난 뒤에야 갱신된다.
        # 그 순간을 잡아 예약된 스크롤을 처리한다 (_scroll_to_memo 참고).
        self._pending_scroll: tuple[int, int] | None = None
        self.tab_scroll.verticalScrollBar().rangeChanged.connect(
            self._apply_pending_scroll
        )
        # 스크롤 막대 대신, 탭이 더 있는 쪽 끝에만 셰브런 단추를 보여 준다
        self.tab_up_btn = self._tab_arrow("chevron-up.svg", "위쪽 탭 보기", -1)
        col_layout.addWidget(self.tab_up_btn)
        col_layout.addWidget(self.tab_scroll, stretch=1)
        self.tab_down_btn = self._tab_arrow("chevron-down.svg", "아래쪽 탭 보기", 1)
        col_layout.addWidget(self.tab_down_btn)
        _tab_bar = self.tab_scroll.verticalScrollBar()
        _tab_bar.rangeChanged.connect(lambda *_a: self._update_tab_arrows())
        _tab_bar.valueChanged.connect(lambda *_a: self._update_tab_arrows())

        col_layout.addSpacing(4)

        # 아래 묶음: 새 메모 + 휴지통 + 잠깐 숨기기(모두 접기 자리)
        self.bar_group = QFrame(self.tab_column)
        self.bar_group.setObjectName("barGroup")
        group_layout = QVBoxLayout(self.bar_group)
        group_layout.setContentsMargins(0, 2, 0, 2)
        group_layout.setSpacing(0)
        col_layout.addWidget(self.bar_group)

        def bar_button(asset: str, tooltip: str, slot) -> QPushButton:
            button = QPushButton(self.bar_group)
            button.setObjectName("barBtn")
            button.setFixedHeight(BAR_BUTTON_HEIGHT)
            button.setIconSize(QSize(BAR_ICON, BAR_ICON))
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if asset:
                self._bar_icons.append((button, asset))
            button.clicked.connect(slot)
            group_layout.addWidget(button)
            return button

        # 새 메모는 자주 쓰니 탭 바로 아래, 숨기기는 잘못 누르지 않게 맨 끝
        self.new_tab_btn = bar_button("plus.svg", tip("새 메모", "Ctrl+N"), self.create_new_memo)
        self.trash_btn = bar_button("trash-2.svg", "휴지통", self._toggle_trash_mode)
        # 휴지통 갯수 배지. 단추 위로 조금 나가므로 묶음의 자식으로 둔다. 클릭은 아래로 통과시킨다
        self._trash_badge = QLabel(self.bar_group)
        self._trash_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.trash_btn.installEventFilter(self)
        self._trash_badge.setObjectName("trashBadge")
        self._trash_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_apply.set_tabular(self._trash_badge)
        self._trash_badge.hide()
        # 휴지통 모드 전용 (평소엔 숨김). 본문 상단이 아니라 컬럼에 두어
        # 본문은 일반 모드와 같은 검색/정렬 화면을 유지한다.
        self.col_empty_btn = bar_button("brush-cleaning.svg", "휴지통 비우기", self._empty_trash)
        self.col_empty_btn.hide()
        self.col_back_btn = bar_button("arrow-left.svg", "휴지통 닫기", self._exit_trash_mode)
        self.col_back_btn.hide()
        self.hide_btn = bar_button("", tip("잠깐 숨기기", HIDE_HOTKEY_LABEL), self.hide_bar)

        root.addWidget(self.tab_column)

        # 본문 영역 가장자리 드래그 핸들 (펼친 상태에서만 표시)
        self.handle_left = ResizeHandle(self.container, "left")
        self.handle_right = ResizeHandle(self.container, "right")
        self.handle_top = ResizeHandle(self.container, "top")
        self.handle_bottom = ResizeHandle(self.container, "bottom")
        # 접힘 상태 전용: 바 폭(tab_width) 조절
        self.handle_tab = ResizeHandle(self.container, "tab")

        # 좌/우 가장자리 레이아웃 적용
        self._apply_side_layout()
        self._tint_chrome_icons()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_handles()
        self._fit_top_row()
        if hasattr(self, "_trash_badge"):
            self._update_trash_btn()

    def _tab_arrow(self, asset: str, tooltip: str, direction: int) -> QPushButton:
        button = QPushButton(self.tab_column)
        button.setObjectName("tabArrow")
        button.setFixedHeight(T.CONTROL["sm"][0])
        button.setIconSize(QSize(BAR_ICON, BAR_ICON))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._step_tabs(direction))
        button.hide()
        self._bar_icons.append((button, asset))
        return button

    def _step_tabs(self, direction: int) -> None:
        bar = self.tab_scroll.verticalScrollBar()
        bar.setValue(bar.value() + direction * MemoTabButton.button_height)

    def _update_tab_arrows(self) -> None:
        bar = self.tab_scroll.verticalScrollBar()
        self.tab_up_btn.setVisible(bar.value() > 0)
        self.tab_down_btn.setVisible(bar.value() < bar.maximum())

    def _fit_top_row(self) -> None:
        """폭이 모자라면 정렬 콤보를 아이콘 단추로 바꿔 검색 칸에 자리를 준다."""
        if not hasattr(self, "sort_combo"):
            return
        icons = 2 * T.CONTROL["md"][0]
        needed = self.sort_combo.full_width() + icons + 3 * 8 + MIN_SEARCH_WIDTH + 2 * 12
        self.sort_combo.set_compact(self.width() - self.tab_width < needed)

    def _apply_side_layout(self) -> None:
        """side에 따라 [본문][탭] 또는 [탭][본문] 순서로 재배치."""
        MemoTabButton.side = self.side
        root = self.container.layout()
        root.removeWidget(self.body)
        root.removeWidget(self.tab_column)
        if self.side == "right":
            root.addWidget(self.body, stretch=1)
            root.addWidget(self.tab_column)
        else:
            root.addWidget(self.tab_column)
            root.addWidget(self.body, stretch=1)
        # 세로 스크롤바는 기본으로 뷰포트 오른쪽에 붙는다. 왼쪽 정렬이면 그 자리가
        # 본문과 맞닿는 면이라 탭 테두리를 4px 잘라먹는다 → 방향을 뒤집어 화면
        # 가장자리 쪽으로 보낸다. 탭은 세로 한 줄이라 내용 배치에는 영향이 없다.
        self.tab_scroll.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if self.side == "left"
            else Qt.LayoutDirection.LeftToRight
        )
        # 숨기기 화살표는 화면 가장자리(밀어 넣는 방향)를 가리킨다
        self._set_bar_icon(self.hide_btn, self.hide_icon_asset())
        # 라운드 방향은 side에만 의존한다 → side가 바뀌는 이 지점에서만 갱신
        self._update_column_style()

    def hide_icon_asset(self) -> str:
        return "chevrons-right.svg" if self.side == "right" else "chevrons-left.svg"

    def _update_handles(self) -> None:
        """리사이즈 핸들 위치 + 가시성 갱신 (side / 펼침 상태 반영).
        - 좌/우 핸들: 펼친 상태에서만 본문 가장자리 폭 조절용
        - handle_top/bottom: 세로 길이 조절. 펼침이면 본문 위/아래, 접힘이면
          컬럼 위/아래 (마스크 안이라야 잡힌다)
        - handle_tab: 접힘 상태에서만, 컬럼 안쪽 가장자리 = 바 폭 조절"""
        if not hasattr(self, "handle_left"):
            return
        w = self.container.width()
        h = self.container.height()
        body_w = max(0, w - self.tab_width)
        grip_h = max(0, h - 2 * RESIZE_GRIP)
        show = self.is_expanded
        if self.side == "right":
            body_x = 0  # 본문이 좌측에 위치
            self.handle_left.setGeometry(0, RESIZE_GRIP, RESIZE_GRIP, grip_h)
            self.handle_left.setVisible(show)
            self.handle_right.setVisible(False)
        else:
            body_x = self.tab_width  # 본문이 우측에 위치
            self.handle_right.setGeometry(
                w - RESIZE_GRIP, RESIZE_GRIP, RESIZE_GRIP, grip_h
            )
            self.handle_right.setVisible(show)
            self.handle_left.setVisible(False)
        # 세로 길이는 접힘/펼침 모두 조절 가능 — 다만 접힘일 땐 마스크 밖(본문
        # 영역)에 깔면 잡을 수 없으니 컬럼 위/아래로 옮긴다.
        grip_x, grip_w = (body_x, body_w) if show else (
            (body_w if self.side == "right" else 0), self.tab_width
        )
        self.handle_top.setGeometry(grip_x, 0, grip_w, RESIZE_GRIP)
        self.handle_bottom.setGeometry(grip_x, h - RESIZE_GRIP, grip_w, RESIZE_GRIP)
        self.handle_top.setVisible(True)
        self.handle_bottom.setVisible(True)
        # 접힘 전용 폭 핸들: 컬럼의 본문 쪽(안쪽) 가장자리
        self.handle_tab.setGeometry(
            body_w if self.side == "right" else self.tab_width - RESIZE_GRIP,
            RESIZE_GRIP, RESIZE_GRIP, grip_h,
        )
        self.handle_tab.setVisible(not show)
        for hw in (
            self.handle_left, self.handle_right,
            self.handle_top, self.handle_bottom, self.handle_tab,
        ):
            hw.raise_()

    def _setup_animation(self) -> None:
        # 윈도우 폭은 즉시 변경하고 body의 opacity만 페이드.
        # → 슬라이드 효과 없음, 본문만 부드럽게 나타났다 사라짐.
        self.body_opacity = QGraphicsOpacityEffect(self.body)
        self.body_opacity.setOpacity(0.0)
        self.body.setGraphicsEffect(self.body_opacity)
        self.fade_anim = QPropertyAnimation(self.body_opacity, b"opacity")
        self.fade_anim.setDuration(T.MOTION_BASE_MS)
        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
        x1, y1, x2, y2 = T.EASING_BEZIER
        curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
        self.fade_anim.setEasingCurve(curve)
        self.fade_anim.finished.connect(self._on_fade_done)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        t = event.type()
        if obj is getattr(self, "trash_btn", None) and t in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place_trash_badge()
        # 팝업/모달/툴팁이 떠 있으면 z-order를 건드리지 않는다. raise_()가 창
        # 그룹을 재정렬하면서 방금 뜬 것을 덮어버려 "드롭다운이 내려왔다 바로
        # 사라지는" / "툴팁이 바 뒤로 숨는" 현상이 생긴다.
        # (nativeEvent의 topmost 강제도 같은 이유로 건너뛴다)
        if self._zorder_locked():
            return False
        if t == QEvent.Type.Enter:
            w = obj
            while w is not None:
                if w is self:
                    self.raise_()
                    break
                w = w.parent()
        elif t == QEvent.Type.ApplicationActivate:
            self.raise_()
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Delete = 지금 메모를 휴지통으로 (휴지통 모드에선 영구 삭제).

        본문/제목/검색창이 포커스를 쥐고 있으면 그쪽이 Delete를 먼저 먹으므로
        글자 지우기와 충돌하지 않는다. 탭을 클릭한 직후처럼 포커스가 본문 밖에
        있을 때만 여기까지 올라온다."""
        if event.key() == Qt.Key.Key_Delete and not self._focus_in_body():
            self._delete_current_memo()
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_in_body(self) -> bool:
        w = QApplication.focusWidget()
        return w is not None and (w is self.body or self.body.isAncestorOf(w))

    def _maybe_start_body_guide(self) -> None:
        """메모를 처음 펼친 순간이 본문 사용법을 알려주기 좋은 자리다."""
        if self.trash_mode or self.guide_running():
            return
        if self.db.get_setting_int(GUIDE_BODY_KEY, 0):
            return
        if not self.db.get_setting_int(GUIDE_BAR_KEY, 0):
            return  # 1단계부터 끝나고 나서
        QTimer.singleShot(500, self._start_body_guide)

    def _start_body_guide(self) -> None:
        self.start_guide("body")

    def _on_fade_done(self) -> None:
        # 접힘 fade-out 종료 → setMask로 tab_column만 노출. 윈도우 폭은 그대로
        # (펼친 폭). setGeometry 호출 없음 → layered window 깜빡임 없음.
        if not self.is_expanded:
            self.setMask(self._collapsed_mask_region())
            self._update_handles()
            self.raise_()  # B안: 탭으로 접힌 직후 z-order 재점령
        else:
            self.body_opacity.setEnabled(False)  # 다 펼치면 끈다. 켜 두면 카드 그림자와 겹친다

    def restart_guide(self) -> None:
        """설정의 '가이드 다시 보기'. 1단계부터, 2단계는 다음 펼침 때 이어진다."""
        self.db.set_setting_int(GUIDE_BAR_KEY, 0)
        self.db.set_setting_int(GUIDE_BODY_KEY, 0)
        QTimer.singleShot(200, self._start_bar_guide)

    def _start_bar_guide(self) -> None:
        self.start_guide("bar")

    def _open_settings(self) -> None:
        from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.db, self)
        dlg.exec()
        self.apply_side_settings()
        self.apply_tab_geometry_settings()
        self.apply_display_mode_settings()
        self._apply_window_opacity()
        self._refresh_ai_bar()
        self.apply_screen_mode()
        self._force_topmost()
        if getattr(dlg, "restart_guide_requested", False):
            self.restart_guide()

    # ----- 화면 모드 (6.2) -----
    def apply_screen_mode(self) -> None:
        """설정 값을 적용한다. 저장하기를 누른 뒤와 처음 켤 때 부른다."""
        setting = self.db.get_setting_str(theme_apply.THEME_MODE_KEY, "system")
        theme_apply.request_color_scheme(setting)
        self._switch_mode(theme_apply.resolve_mode(setting))

    def on_system_scheme_changed(self, _scheme=None) -> None:
        if self.db.get_setting_str(theme_apply.THEME_MODE_KEY, "system") not in T.MODES:
            self._switch_mode(theme_apply.system_mode())

    def _switch_mode(self, mode: str) -> None:
        if mode == theme_apply.current_mode():
            return
        self.save_now()
        # 순서: 팔레트 → app.qss → 메모 창 memo.qss → 아이콘
        theme_apply.apply_theme(QApplication.instance(), mode)
        # 문서에는 표시용 색이 칠해져 있어 다시 만든다 (이때 Ctrl+Z 기록은 비워진다)
        self.editor.blockSignals(True)
        for memo_id in list(self._doc_cache):
            self._forget_doc(memo_id)
        self.editor.blockSignals(False)
        self._tint_chrome_icons()
        if self.trash_mode and self._trash_preview_id is not None:
            memo = self.db.get(self._trash_preview_id)
            self.editor.blockSignals(True)
            self._show_scratch(memo.content)
            self.editor.blockSignals(False)
            self._apply_memo_theme(memo.color)
        elif self.current_memo is not None:
            self._load_memo(self.db.get(self.current_memo.id))
        else:
            self._clear_editor()
        self._refresh_memo_tabs()
        self._update_tabs_selected()

    def _refresh_ai_bar(self) -> None:
        enabled = self.db.get_setting_str("ai_enabled", "0") == "1"
        self._ai_bar.setVisible(enabled)

    def _on_escape(self) -> None:
        if self._ai_pending is not None:
            self._cancel_ai()
        else:
            self.collapse()

    def _setup_shortcuts(self) -> None:
        self._edit_shortcuts: list[QShortcut] = []  # 휴지통 미리 보기에서는 끈다
        for keys, slot in [
            ("Escape", self._on_escape),
            ("Ctrl+N", self.create_new_memo),
            ("Ctrl+F", self.focus_search),
            ("Ctrl+S", self.save_now),
            ("Ctrl+Shift+C", self._copy_memo_text),
            ("Ctrl+B", self.format_toolbar.toggle_bold),
            ("Ctrl+I", self.format_toolbar.toggle_italic),
            ("Ctrl+U", self.format_toolbar.toggle_underline),
            # 링크
            ("Ctrl+K", self.format_toolbar.insert_link),
            # 날짜/시간
            ("F5", lambda: self.format_toolbar.insert_datetime("notepad")),
            ("Ctrl+;", lambda: self.format_toolbar.insert_datetime("date")),
            ("Ctrl+Shift+;", lambda: self.format_toolbar.insert_datetime("time")),
            ("Ctrl+Alt+;", lambda: self.format_toolbar.insert_datetime("iso")),
            ("Ctrl+Shift+H", lambda: self.format_toolbar.insert_datetime("korean")),
            # 메모 삭제 (모드별로 다른 동작)
            ("Ctrl+Shift+D", self._delete_current_memo),
            # 이전 버전 (Ctrl+Z가 닿지 않는 범위를 되돌린다)
            ("Ctrl+Alt+Z", self._show_current_versions),
            # 내보내기
            ("Ctrl+E", self._export_current_memo),
            # AI 기능
            ("Ctrl+Alt+S", lambda: self._run_ai_feature("summarize")),
            ("Ctrl+Alt+T", lambda: self._run_ai_feature("translate")),
            ("Ctrl+Alt+P", lambda: self._run_ai_feature("spellcheck")),
            ("Ctrl+Alt+H", lambda: self._run_ai_feature("title")),
            ("Ctrl+Alt+K", lambda: self._run_ai_feature("keywords")),
        ]:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(slot)
            if keys not in ("Ctrl+N", "Ctrl+F", "Ctrl+S", "Ctrl+Shift+C", "Ctrl+Shift+D"):
                self._edit_shortcuts.append(sc)

    # ----- AI 컨텍스트 메뉴 -----
    def _show_editor_context_menu(self, pos) -> None:
        from ai_features import AI_FEATURES

        menu = ThemedMenu()
        menu.adopt_standard_actions(self.editor.createStandardContextMenu())

        if self.db.get_setting_str("ai_enabled", "0") == "1":
            menu.addSeparator()
            ai_menu = menu.add_submenu("AI로 다듬기", "sparkles.svg")
            for key, info in AI_FEATURES.items():
                act = ai_menu.add_item(info["button"])
                act.triggered.connect(lambda _checked, k=key: self._run_ai_feature(k))

            if self._ai_pending is not None:
                menu.addSeparator()
                menu.add_item("AI 취소", shortcut="Esc").triggered.connect(self._cancel_ai)

        menu.exec(self.editor.mapToGlobal(pos))

    # ----- AI 실행 -----
    def _run_ai_feature(self, feature_key: str) -> None:
        from ai_features import AI_FEATURES, AIWorker

        if self.db.get_setting_str("ai_enabled", "0") != "1":
            self._show_toast("AI가 꺼져 있어요. 설정 > AI에서 켤 수 있어요.")
            return

        if self._ai_worker is not None and self._ai_worker.isRunning():
            self._show_toast("AI가 다른 일을 하는 중이에요. 잠시 뒤에 다시 해 주세요.")
            return

        feature = AI_FEATURES.get(feature_key)
        if not feature:
            return

        # 텍스트 수집: 선택 영역 우선, 없으면 전체 본문
        cursor = self.editor.textCursor()
        text = cursor.selectedText() if cursor.hasSelection() else self.editor.toPlainText()
        # toPlainText/selectedText는 이미지를 U+FFFC로, 줄바꿈을 U+2029로 준다.
        # 그대로 보내면 모델이 정체불명의 문자를 그대로 옮겨 적는다.
        text = text.replace("\ufffc", "").replace("\u2029", "\n").strip()
        if not text:
            self._show_toast("다듬을 글이 없어요. 글을 먼저 적어 주세요.")
            return

        provider = self.db.get_setting_str("ai_provider", "anthropic")
        model = self.db.get_setting_str("ai_model", "")
        if not model:
            from ai_provider import PROVIDERS
            model = PROVIDERS.get(provider, {}).get("default_model", "")

        show_preview = self.db.get_setting_str("ai_show_preview", "0") == "1"

        self._ai_pending = feature_key
        self._show_ai_progress(feature["progress"])

        # 직전 워커 정리. parent=self라 재할당만으로는 안 죽고 창의 자식으로 쌓인다.
        # 여기 도달했다는 건 위 isRunning() 검사를 통과했다는 뜻이라 안전하다.
        # (커스텀 finished 시그널이 QThread.finished를 가려서 그쪽엔 못 붙인다)
        if self._ai_worker is not None:
            self._ai_worker.deleteLater()
        self._ai_worker = AIWorker(feature_key, provider, model, text, parent=self)
        self._ai_worker.finished.connect(
            lambda k, r, t: self._on_ai_finished(k, r, t, show_preview)
        )
        self._ai_worker.errored.connect(self._on_ai_error)
        self._ai_worker.progress.connect(self._show_ai_progress)
        self._ai_worker.start()

    def _cancel_ai(self) -> None:
        if self._ai_worker is not None:
            self._ai_worker.cancel()
        self._ai_pending = None
        self._ai_status_lbl.hide()
        self._show_toast("AI 작업을 취소했어요.")

    # ----- 음성 녹음 (Phase 9-2) -----
    def toggle_recording(self) -> None:
        if self._recorder is not None and getattr(self._recorder, "is_recording", False):
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self.db.get_setting_int("recording_enabled", 0) != 1:
            self._show_toast("음성 녹음이 꺼져 있어요. 설정 > AI에서 켤 수 있어요.")
            return
        if self.db.get_setting_str("ai_enabled", "0") != "1":
            self._show_toast("AI를 먼저 켜 주세요. 설정 > AI에서 켤 수 있어요.")
            return
        from ai_provider import load_api_key
        api_key = load_api_key("openai")
        if not api_key:
            self._show_toast(
                "녹음에는 OpenAI 키가 필요해요. 설정 > AI에서 넣어 주세요."
            )
            return
        from audio_recorder import AudioRecorder, has_microphone
        ok, msg = has_microphone()
        if not ok:
            self._show_toast(msg)
            return
        max_s = self.db.get_setting_int("recording_max_seconds", 300)
        self._recorder = AudioRecorder(max_seconds=max_s)
        try:
            self._recorder.start()
        except Exception as e:
            self._show_toast(f"녹음을 시작하지 못했어요: {e}")
            self._recorder = None
            return
        self._update_mic_button_state(recording=True)
        self._recording_timer = QTimer(self)
        self._recording_timer.timeout.connect(self._tick_recording)
        self._recording_timer.start(1000)

    def _tick_recording(self) -> None:
        if self._recorder is None or not self._recorder.is_recording:
            return
        elapsed = self._recorder.elapsed_seconds
        max_s = self.db.get_setting_int("recording_max_seconds", 300)
        self._update_mic_button_state(recording=True, elapsed=elapsed)
        if elapsed >= max_s:
            self._show_toast("최대 녹음 시간이 지나 녹음을 멈췄어요.")
            self._stop_recording()

    def _stop_recording(self) -> None:
        if self._recording_timer is not None:
            self._recording_timer.stop()
            self._recording_timer = None
        if self._recorder is None:
            self._update_mic_button_state(recording=False)
            return
        # 임시 파일 경로
        from datetime import datetime
        from database import APP_DIR
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = APP_DIR / "temp" / f"recording_{ts}.wav"
        try:
            saved = self._recorder.stop_and_save(temp_path)
        except Exception as e:
            self._show_toast(f"녹음을 저장하지 못했어요: {e}")
            self._recorder = None
            self._update_mic_button_state(recording=False)
            return
        self._recorder = None
        self._update_mic_button_state(recording=False)
        if saved is None:
            self._show_toast("녹음된 소리가 없어요.")
            return
        # Whisper 호출
        from ai_provider import load_api_key
        api_key = load_api_key("openai")
        if not api_key:
            self._show_toast(
                "OpenAI 키가 없어 글자로 바꾸지 못했어요. 녹음 파일은 남겨 두었어요."
            )
            return
        from audio_recorder import WhisperWorker
        # 직전 워커 정리 (위 _ai_worker와 같은 이유). 아직 변환 중이면 두고 간다.
        if self._whisper_worker is not None and not self._whisper_worker.isRunning():
            self._whisper_worker.deleteLater()
        self._whisper_worker = WhisperWorker(saved, api_key, parent=self)
        self._whisper_worker.finished.connect(
            lambda text: self._on_whisper_finished(text, saved)
        )
        self._whisper_worker.errored.connect(
            lambda msg: self._on_whisper_error(msg, saved)
        )
        self._show_ai_progress("음성을 글자로 바꾸는 중이에요", cancellable=False)
        self._whisper_worker.start()

    def _on_whisper_finished(self, text: str, audio_path: Path) -> None:
        self._ai_status_lbl.hide()
        keep_audio = self.db.get_setting_int("recording_keep_audio", 0) == 1
        attached_name: str | None = None
        if keep_audio:
            from database import APP_DIR
            audio_dir = APP_DIR / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            new_path = audio_dir / audio_path.name
            try:
                audio_path.replace(new_path)
                attached_name = new_path.name
            except OSError:
                attached_name = None
        else:
            try:
                audio_path.unlink()
            except OSError:
                pass
        # 새 메모로
        from datetime import datetime
        title = f"음성 메모 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        body = text if text else "(변환된 텍스트 없음)"
        if attached_name:
            body += f"\n\n[🎤 {attached_name}]"
        self.save_now()
        if self.trash_mode:
            self._exit_trash_mode()
        memo = self.db.create()
        self._load_memo(memo)
        self.title_input.setText(title)
        self.editor.setPlainText(body)
        self._refresh_memo_tabs()
        self._update_tabs_selected()
        self.expand()

    def _on_whisper_error(self, msg: str, audio_path: Path) -> None:
        self._ai_status_lbl.hide()
        self._show_toast(f"글자로 바꾸지 못했어요: {msg} (녹음 파일은 남겨 두었어요)")

    def _update_mic_button_state(self, *, recording: bool, elapsed: int = 0) -> None:
        if not hasattr(self, "format_toolbar"):
            return
        btn = getattr(self.format_toolbar, "mic_btn", None)
        if btn is None:
            return
        self._recording_now = recording
        minutes, seconds = divmod(elapsed, 60)
        btn.setProperty("recording", recording)
        theme_apply.repolish(btn)
        btn.setToolTip(
            f"녹음 중 {minutes:02d}:{seconds:02d}" if recording else "음성 녹음 (시작/종료)"
        )
        self._rec_time.setText(f"녹음 중 {minutes:02d}:{seconds:02d}")
        self._rec_card.setVisible(recording)
        self._tint_mic()

    def _tint_mic(self) -> None:
        color = T.WHITE if getattr(self, "_recording_now", False) else self._memo_icon_color
        self.format_toolbar.mic_btn.setIcon(QIcon(tinted_pixmap("mic.svg", color, 16)))

    def _on_ai_finished(self, feature_key: str, result: str, tokens: int, show_preview: bool) -> None:
        self._ai_pending = None
        self._ai_status_lbl.hide()

        # 토큰 사용량 누적
        # get_setting_int는 값이 깨졌을 때 기본값으로 떨어진다. 문자열로 읽어
        # int()를 돌리면 시그널 핸들러 안에서 ValueError가 나 앱이 죽는다.
        prev = self.db.get_setting_int("ai_usage_tokens", 0)
        self.db.set_setting_str("ai_usage_tokens", str(prev + tokens))

        if show_preview:
            self._show_ai_preview(feature_key, result)
        else:
            self._apply_ai_result(feature_key, result)

    def _on_ai_error(self, feature_key: str, msg: str) -> None:
        self._ai_pending = None
        self._ai_status_lbl.hide()
        self._show_toast(f"AI가 답하지 못했어요: {msg}")

    def _show_ai_preview(self, feature_key: str, result: str) -> None:
        from ai_features import AI_FEATURES

        feature = AI_FEATURES.get(feature_key, {})
        label = feature.get("label", feature_key)

        dlg = AppDialog(f"{label} 결과를 넣을까요?", self)
        dlg.resize(500, 360)
        preview = QTextBrowser()
        preview.setPlainText(result)
        dlg.body.addWidget(preview, 1)
        dlg.add_actions("넣기")

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_ai_result(feature_key, result)

    def _apply_ai_result(self, feature_key: str, result: str) -> None:
        from ai_features import AI_FEATURES

        feature = AI_FEATURES.get(feature_key, {})
        output = feature.get("output", "replace")
        cursor = self.editor.textCursor()

        # AI 결과는 평문이라 본문을 덮어쓰면 이미지·서식이 함께 사라진다.
        # 되돌릴 수 있게 적용 직전 상태를 버전으로 남긴다 (Ctrl+Alt+Z).
        # save_now를 먼저 불러 편집 중이던 내용을 DB에 반영한 뒤 스냅샷을 떠야
        # 자동저장 이후 친 내용까지 정확히 보존된다.
        if self.current_memo is not None:
            self.save_now()
            self.db.snapshot(self.current_memo.id, force=True)

        if output == "title":
            self.title_input.setText(result)
            self._show_toast("제목을 지었어요.")
        elif output == "replace":
            # AI 응답은 평문이라 그대로 덮어쓰면 첨부 이미지가 같이 사라진다.
            # 교체 대상 안에 있던 <img>를 모아 뒀다가 결과 뒤에 다시 붙인다.
            # 원래 자리는 못 지킨다 — 응답에 이미지 위치 표시가 없기 때문.
            # (자리까지 지키려면 자리표시자를 넣어 보내고 응답에서 되찾아야 하는데,
            #  모델이 표시자를 지우면 그대로 유실된다. 뒤에 붙이는 쪽이 안전하다.)
            if not cursor.hasSelection():
                cursor.select(QTextCursor.SelectionType.Document)
            imgs = re.findall(r"<img[^>]*>", cursor.selection().toHtml())
            cursor.insertText(result)
            if imgs:
                cursor.insertHtml("<br>" + "".join(imgs))
            self.editor.setTextCursor(cursor)
            self._show_toast(
                "결과를 넣었어요. 이미지는 아래로 옮겼어요. (Ctrl+Alt+Z로 되돌리기)"
                if imgs else "결과를 넣었어요. Ctrl+Alt+Z로 되돌릴 수 있어요."
            )
        elif output == "append":
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(f"\n\n{result}")
            self.editor.setTextCursor(cursor)

        self.editor.setFocus()

    def _show_ai_progress(self, msg: str, cancellable: bool = True) -> None:
        self._ai_status_lbl.begin(msg, self.editor, cancellable=cancellable)

    # ----- 가이드 (말풍선 투어) -----
    def _guide_script(self, which: str) -> list[tuple[str, str, object]]:
        """(제목, 설명, 대상 위젯을 돌려주는 함수) 목록. 한 번에 4개를 넘기지 않는다 —
        길어지면 끝까지 보는 사람이 급격히 줄어서, 나머지는 만든 적 없는 셈이 된다."""
        if which == "bar":
            return [
                ("탭을 눌러 메모를 펼쳐요", "한 번 더 누르거나 Esc를 누르면 접혀요.",
                 lambda: self._first_tab_btn() or self.tab_scroll),
                ("새 메모를 만들어요", "아래쪽 더하기 단추나 Ctrl+N으로 바로 만들 수 있어요.",
                 lambda: self.new_tab_btn),
                ("바 크기를 바꿔요", "바 안쪽 가장자리를 끌면 폭이, 위아래 끝을 끌면 길이가 바뀌어요.",
                 lambda: self.tab_column),
                ("바를 잠깐 숨겨요",
                 "화살표 단추나 Ctrl+Shift+Z로 숨기고, 트레이 아이콘으로 되돌려요. 바를 우클릭하면 설정이 있어요.",
                 lambda: self.hide_btn),
            ]
        return [
            ("저절로 저장돼요", "바로 저장하고 싶으면 Ctrl+S를 눌러요.", lambda: self.title_input),
            ("글자를 꾸며요", "굵게(Ctrl+B), 기울임, 색, 목록, 표를 쓸 수 있어요.", lambda: self.format_toolbar),
            ("메모 색을 바꿔요", "제목 옆 색 단추로 고르거나 나만의 색을 만들어요.", lambda: self.color_btn),
            ("찾고 정리해요", "검색(Ctrl+F), 정렬, 고정, 내보내기는 맨 위 줄에 있어요.", lambda: self.search_input),
        ]

    def _first_tab_btn(self) -> QWidget | None:
        for i in range(self.tabs_layout.count()):
            w = self.tabs_layout.itemAt(i).widget()
            if isinstance(w, MemoTabButton):
                return w
        return None

    def guide_running(self) -> bool:
        return bool(self._guide_steps_queue)

    def start_guide(self, which: str = "bar") -> None:
        self._guide_which = which
        self._guide_steps_queue = self._guide_script(which)
        self._guide_index = 0
        self._show_guide_step()

    def _show_guide_step(self) -> None:
        if self._guide_index >= len(self._guide_steps_queue):
            self._finish_guide()
            return
        title, text, anchor_of = self._guide_steps_queue[self._guide_index]
        anchor = anchor_of()
        if anchor is None:  # 그 위젯이 지금 없으면 건너뛴다 (휴지통 모드 등)
            self._guide_index += 1
            self._show_guide_step()
            return
        if self._guide is None:
            self._guide = GuideBubble(self)
        self._guide.show_step(
            title, text, anchor,
            self._guide_index + 1, len(self._guide_steps_queue),
            self._next_guide_step, self._finish_guide,
        )

    def _next_guide_step(self) -> None:
        self._guide_index += 1
        self._show_guide_step()

    def _finish_guide(self) -> None:
        """끝까지 봤든 건너뛰었든 다시 뜨지 않는다 (설정에서 다시 볼 수 있음)."""
        if self._guide is not None:
            self._guide.hide()
        self.db.set_setting_int(
            GUIDE_BAR_KEY if self._guide_which == "bar" else GUIDE_BODY_KEY, 1
        )
        self._guide_steps_queue = []
        self._force_topmost()

    def _on_toast_clicked(self) -> None:
        action, self._toast_action = self._toast_action, None
        if action is None:
            return
        self._toast_timer.stop()
        self._toast_lbl.hide()
        action()

    def _show_toast(self, msg: str, on_click=None, action: str = "되돌리기") -> None:
        self._toast_action = on_click
        # 검색 칸과 정렬을 덮지 않게 서식바 바로 아래에 띄운다
        below_toolbar = self.format_toolbar.mapTo(self.body, QPoint(0, self.format_toolbar.height())).y()
        self._toast_lbl.show_message(msg, action if on_click else "", below_toolbar + 8)

    def _setup_autosave(self) -> None:
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.save_now)

    # ----- geometry -----
    def _screen_rect(self) -> QRect:
        screen = QGuiApplication.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _load_user_size(self) -> None:
        rect = self._screen_rect()
        default_h = int(rect.height() * HEIGHT_RATIO)
        default_y = rect.y() + (rect.height() - default_h) // 2
        # 기본 세로 비율을 0.70 → 0.55로 줄이면서 기존 사용자의 저장된 user_height를
        # 한 번만 새 기본값으로 리셋. 이후 사용자가 드래그한 값은 그대로 유지된다.
        if not self.db.get_setting_int("height_ratio_v2_migrated", 0):
            self.db.set_setting_int("window_height", default_h)
            self.db.set_setting_int("window_y", default_y)
            self.db.set_setting_int("height_ratio_v2_migrated", 1)
        self.user_width = self.db.get_setting_int("window_width", EXPANDED_WIDTH)
        self.user_height = self.db.get_setting_int("window_height", default_h)
        self.user_y = self.db.get_setting_int("window_y", default_y)
        # 화면 범위로 clamp (해상도 변경 대응)
        self.user_width = max(MIN_W, min(self.user_width, rect.width()))
        self.user_height = max(MIN_H, min(self.user_height, rect.height()))
        self.user_y = max(
            rect.y(),
            min(self.user_y, rect.y() + rect.height() - self.user_height),
        )

    def _save_user_size(self) -> None:
        g = self.geometry()
        # 접힌 상태에선 폭이 tab_width라 user_width를 덮어쓰면 안 됨
        # (접힌 채 세로 이동 그립을 드래그한 경우)
        if self.is_expanded:
            self.user_width = g.width()
        self.user_height = g.height()
        self.user_y = g.y()
        self.db.set_setting_int("window_width", self.user_width)
        self.db.set_setting_int("window_height", self.user_height)
        self.db.set_setting_int("window_y", self.user_y)

    def apply_side_settings(self) -> None:
        """side(좌/우 가장자리) 변경 즉시 반영. toggle_side와 거의 동일하지만
        DB에서 값을 다시 읽어 적용한다."""
        new_side_int = self.db.get_setting_int("side", 0)
        new_side = "left" if new_side_int == 1 else "right"
        if new_side == self.side:
            return
        self.side = new_side
        self._apply_side_layout()
        self.setGeometry(self._expanded_geometry())
        if not self.is_expanded:
            # 좌/우 side 따라 mask 위치 다름 → 다시 적용
            self.setMask(self._collapsed_mask_region())
        else:
            self.clearMask()
        self._update_handles()
        self._refresh_memo_tabs()
        self._update_tabs_selected()
        # body의 비대칭 라운드 (side 면 쪽만 라운드 0) 다시 적용
        if self.current_memo is not None:
            self._apply_memo_theme(self.current_memo.color)

    def apply_display_mode_settings(self) -> None:
        """display_mode 재로드 후 윈도우 플래그/트레이 가시성 즉시 갱신."""
        prev = self.display_mode
        self._load_display_mode()
        if self.display_mode == prev:
            return
        was_visible = self.isVisible()
        self.setWindowFlags(self._window_flags_for_mode())
        self._register_hotkey()  # setWindowFlags가 native 창 재생성 → 등록도 날아감
        # 트레이 가시성
        tray = getattr(self, "_tray", None)
        if tray is not None:
            if self.display_mode == "taskbar":
                tray.hide()
            else:
                tray.show()
        # setWindowFlags 호출 후엔 윈도우가 hide되므로 show 재호출 + geometry 복구
        if was_visible:
            self.setGeometry(self._expanded_geometry())
            if not self.is_expanded:
                self.setMask(self._collapsed_mask_region())
            else:
                self.clearMask()
            self.show()
            self._force_topmost()
            self._update_handles()

    def _apply_tab_width(self, w: int) -> None:
        """바(인덱스 컬럼) 폭 즉시 반영. DB 저장은 호출측 담당."""
        self.tab_width = w = max(TAB_WIDTH_MIN, min(w, TAB_WIDTH_MAX))
        self.tab_column.setFixedWidth(w)
        self.container.setMinimumWidth(w)
        self.setMinimumWidth(w)
        if not self.is_expanded:  # 접힘 = mask 폭이 곧 바 폭
            self.setMask(self._collapsed_mask_region())
        self._update_handles()

    def apply_tab_geometry_settings(self) -> None:
        """설정 다이얼로그 OK 후 호출. 인덱스 탭 폭/각 탭 높이를 DB에서 재로드해 반영.
        접힌 상태면 윈도우 폭도 즉시 반영, 펼친 상태면 다음 접기 때 반영.
        """
        self._load_tab_geometry()
        if not self.is_expanded:
            self.setGeometry(self._collapsed_geometry())
        self._apply_tab_width(self.tab_width)
        # 각 메모 탭 높이 갱신 → 탭 다시 그리기
        MemoTabButton.button_height = self.memo_tab_height
        self._refresh_memo_tabs()
        self._update_tabs_selected()

    def _expanded_geometry(self) -> QRect:
        rect = self._screen_rect()
        if self.side == "right":
            x = rect.right() - self.user_width + 1
        else:
            x = rect.x()
        return QRect(x, self.user_y, self.user_width, self.user_height)

    def _collapsed_geometry(self) -> QRect:
        # 윈도우 자체 크기는 펼친 폭으로 고정 — 시각적 접힘은 setMask로 처리.
        # setGeometry로 폭이 갑자기 변할 때 layered window가 깜빡이던 문제를
        # 방지한다 (mask는 paint를 차단할 뿐 native window resize 안 일으킴).
        return self._expanded_geometry()

    def _collapsed_mask_region(self) -> QRegion:
        """접힘 상태에서 보일 영역(tab_column 부분)만 마스크로 노출."""
        if self.side == "right":
            x = self.user_width - self.tab_width
        else:
            x = 0
        return QRegion(QRect(x, 0, self.tab_width, self.height()))

    def _position_collapsed(self) -> None:
        self.setGeometry(self._collapsed_geometry())
        self.setMask(self._collapsed_mask_region())

    # ----- expand / collapse -----
    def toggle(self) -> None:
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def toggle_side(self) -> None:
        """좌/우 가장자리 전환."""
        self.side = "left" if self.side == "right" else "right"
        self.db.set_setting_int("side", 1 if self.side == "left" else 0)
        self._apply_side_layout()
        self.setGeometry(self._expanded_geometry())
        if not self.is_expanded:
            self.setMask(self._collapsed_mask_region())
        else:
            self.clearMask()
        self._update_handles()
        self._refresh_memo_tabs()
        self._update_tabs_selected()
        if self.current_memo is not None:
            self._apply_memo_theme(self.current_memo.color)
        if self._edge_timer.isActive():
            self._show_edge_button()

    def expand(self) -> None:
        if not self.isVisible():
            self.show_bar()  # 잠깐 숨김 중에 호출돼도 임시 트레이까지 원상 복구
        if self.is_expanded:
            self.raise_()
            self.activateWindow()
            return
        self.is_expanded = True
        # 펼침 — 현재 메모의 인디케이터 다시 표시
        self._update_tabs_selected()
        if self.current_memo is not None and not self.trash_mode:
            self._scroll_to_memo(self.current_memo.id)
        # setMask 해제 → body 영역도 보이게 됨. 윈도우 폭은 이미 펼친 폭이라
        # setGeometry 호출 불필요 (mask만으로 시각적 펼침).
        self.clearMask()
        self._update_handles()
        # body opacity 0 → 1 페이드 인
        self.body_opacity.setEnabled(True)
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.body_opacity.opacity())
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()
        self.raise_()
        self.activateWindow()
        self._maybe_start_body_guide()

    def collapse(self, *, exit_trash: bool = True) -> None:
        if not self.is_expanded:
            return
        self.save_now()
        if exit_trash and self.trash_mode:
            self._exit_trash_mode()  # 접을 때 휴지통 모드 해제
        self.is_expanded = False
        # 모든 메모 탭의 인디케이터 제거 (접힘 상태에서는 아무 것도 선택돼있지 않게)
        self._update_tabs_selected()
        # body opacity → 0 페이드 아웃. 끝나면 _on_fade_done에서 윈도우 축소.
        self.body_opacity.setEnabled(True)
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.body_opacity.opacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()

    # ----- 잠깐 숨기기 / 복귀 (트레이) -----
    def hide_bar(self) -> None:
        """바 전체를 잠깐 숨긴다. 복귀는 트레이 아이콘 클릭. 세션 한정(저장 안 함)."""
        if not self.isVisible():
            return
        self.save_now()
        if self._guide is not None and self._guide.isVisible():
            self._finish_guide()  # 바가 사라지면 가리킬 대상도 없다
        # taskbar 모드는 평소 트레이가 꺼져 있어 숨기면 돌아올 길이 없다 →
        # 숨김 동안만 트레이를 켠다 (show_bar에서 모드대로 복원).
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.show()
        self._show_edge_button()
        self.hide()
        # 숨기면 안내를 띄울 화면이 사라진다 → 복귀 방법은 트레이 풍선으로만
        # 알릴 수 있다. 숨김은 드문 의도적 동작이라 매번 띄운다.
        if tray is not None:
            tray.showMessage(
                "Slide Memo를 숨겼어요",
                f"{HIDE_HOTKEY_LABEL} 또는 트레이 아이콘 클릭으로 다시 꺼냅니다.",
                tray.icon(),
                5000,
            )

    def _show_edge_button(self) -> None:
        """바가 있던 높이, 붙어 있던 쪽 가장자리. 끌어 옮긴 적이 있으면 그 자리."""
        top = self.db.get_setting_int(EDGE_BUTTON_Y_KEY, -1)
        self._edge_button.place(self.screen().geometry(), self.side, top if top >= 0 else self.y())
        self._sync_edge_button()
        self._edge_timer.start()

    def _sync_edge_button(self) -> None:
        self._edge_button.setVisible(not is_foreign_fullscreen(int(self._edge_button.winId())))

    def show_bar(self) -> None:
        """hide_bar로 숨긴 바를 이전 상태(펼침/접힘) 그대로 다시 꺼낸다."""
        if self.isVisible():
            return
        self.setGeometry(self._expanded_geometry())
        if self.is_expanded:
            self.clearMask()
        else:
            self.setMask(self._collapsed_mask_region())
        self.show()
        self._edge_timer.stop()
        self._edge_button.hide()
        self._force_topmost()
        self._update_handles()
        tray = getattr(self, "_tray", None)
        if tray is not None and self.display_mode == "taskbar":
            tray.hide()

    def _show_column_menu(self, pos) -> None:
        """바(탭 열) 우클릭 메뉴. 상시 아이콘에서 뺀 기능들이 여기에 모인다.
        (설정은 트레이 아이콘 우클릭 메뉴에도 그대로 있다)"""
        menu = ThemedMenu()
        menu.add_section("메모장")
        settings_act = menu.add_item("설정", "settings.svg")
        n = self.db.count_trashed()
        trash_act = menu.add_item(f"휴지통 보기 ({n})" if n else "휴지통 보기", "trash-2.svg")
        trash_act.setEnabled(n > 0)
        menu.addSeparator()
        menu.add_section("위치")
        side_act = menu.add_item("반대쪽 가장자리로 옮기기", "arrow-left-right.svg")
        hide_act = menu.add_item("잠깐 숨기기", shortcut=HIDE_HOTKEY_LABEL)
        chosen = menu.exec(self.tab_column.mapToGlobal(pos))
        self.raise_()
        if chosen == settings_act:
            self._open_settings()
        elif chosen == trash_act:
            self._toggle_trash_mode()
        elif chosen == side_act:
            self.toggle_side()
        elif chosen == hide_act:
            self.hide_bar()

    # ----- memo tab column -----
    def _refresh_memo_tabs(self, *, select_first: bool = False) -> None:
        if self.trash_mode:
            memos = self.db.list_trashed_memos()
        else:
            keyword = self.search_input.text() if hasattr(self, "search_input") else ""
            memos = self.db.search(keyword, sort=self._current_sort_key())

        # 기존 탭 제거
        while self.tabs_layout.count():
            item = self.tabs_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # 접힘(collapse) 상태면 인디케이터 표시 안 함
        current_id = (
            self.current_memo.id
            if (self.current_memo and self.is_expanded)
            else None
        )
        for memo in memos:
            btn = MemoTabButton(memo)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            if self.trash_mode:
                # 휴지통: 좌클릭=내용 미리보기 / 우클릭=복원·영구삭제 메뉴
                btn.update_style(selected=(memo.id == self._trash_preview_id))
                btn.clicked.connect(
                    lambda _c, mid=memo.id: self._preview_trashed(mid)
                )
                btn.customContextMenuRequested.connect(
                    lambda _pos, mid=memo.id, b=btn: self._show_trash_menu(mid, b)
                )
            else:
                btn.update_style(selected=(memo.id == current_id))
                btn.clicked.connect(lambda _c, mid=memo.id: self.select_memo(mid))
                btn.customContextMenuRequested.connect(
                    lambda pos, mid=memo.id, b=btn: self._show_tab_context_menu(pos, mid, b)
                )
            self.tabs_layout.addWidget(btn)

        self._update_trash_btn()

        if self.trash_mode:
            return

        # 현재 선택된 메모가 검색/삭제로 사라지면 에디터 정리
        if current_id is not None and current_id not in {m.id for m in memos}:
            self._clear_editor()

        # 비어 있을 때 첫 항목 자동 선택
        if select_first and self.current_memo is None and memos:
            self._load_memo(memos[0])
            self._update_tabs_selected()

    def _scroll_to_memo(self, memo_id: int) -> None:
        """그 메모의 탭이 보이도록 탭 목록을 스크롤한다. 목록이 길면 새로 만든
        메모가 화면 밖에 생겨 "아무 일도 안 일어난 것처럼" 보인다.

        위젯 좌표 대신 '몇 번째 탭인가'로 목표 위치를 계산한다 — 탭을 방금 다시
        만든 참이면 위젯 좌표가 아직 전부 0이라 그걸로 스크롤하면 맨 위로 튄다.
        (탭 높이는 고정, 간격·여백 0이라 index × 높이가 곧 위치)
        """
        idx = None
        for i in range(self.tabs_layout.count()):
            w = self.tabs_layout.itemAt(i).widget()
            if isinstance(w, MemoTabButton) and w.memo_id == memo_id:
                idx = i
                break
        if idx is None:  # 검색 필터 등으로 목록에 없음
            self._pending_scroll = None
            return
        tab_h = MemoTabButton.button_height
        vp_h = self.tab_scroll.viewport().height()
        # 뷰포트 가운데쯤에 오도록 (맨 끝 탭이면 아래 clamp가 알아서 붙인다)
        target = max(0, idx * tab_h - max(0, (vp_h - tab_h) // 2))
        self._pending_scroll = (target, 5)
        self._apply_pending_scroll()

    def _apply_pending_scroll(self, *_args) -> None:
        """예약된 스크롤 적용. 탭이 막 늘어난 직후엔 스크롤 범위가 아직 옛 값이라
        목표에 못 닿는다 → 범위가 갱신되는 순간(rangeChanged)에 다시 불린다."""
        if self._pending_scroll is None:
            return
        target, tries = self._pending_scroll
        sb = self.tab_scroll.verticalScrollBar()
        sb.setValue(target)
        if sb.value() == target or tries <= 0:
            self._pending_scroll = None
        else:
            self._pending_scroll = (target, tries - 1)

    def _update_trash_btn(self) -> None:
        """휴지통 아이콘은 늘 있다. 휴지통 모드일 땐 나가는 길이 col_back_btn이므로 숨긴다."""
        n = self.db.count_trashed()
        self.trash_btn.setToolTip(f"휴지통 (메모 {n}개)" if n else "휴지통 (비어 있음)")
        self.trash_btn.setVisible(not self.trash_mode)
        if n > 0:
            self._trash_badge.setText(str(n) if n < 100 else "99+")
            self._trash_badge.adjustSize()
            self._place_trash_badge()
        self._trash_badge.setVisible(n > 0 and not self.trash_mode)
        self._trash_badge.raise_()

    def _place_trash_badge(self) -> None:
        """중심을 아이콘 오른쪽 위 꼭짓점 쪽에 두고, 아이콘 아래 2/3는 가리지 않는다."""
        button, badge = self.trash_btn.geometry(), self._trash_badge
        icon_right = button.center().x() + BAR_ICON // 2
        icon_top = button.center().y() - BAR_ICON // 2
        x = min(icon_right - badge.width() // 2, self.bar_group.width() - badge.width() - 1)
        badge.move(x, icon_top + BAR_ICON // 3 - badge.height())

    # ----- 휴지통 모드 -----
    def _toggle_trash_mode(self) -> None:
        if self.trash_mode:
            self._exit_trash_mode()
        else:
            self._enter_trash_mode()

    def _set_editing_enabled(self, enabled: bool) -> None:
        self.editor.setReadOnly(not enabled)
        self.title_input.setReadOnly(not enabled)
        for widget in (self.format_toolbar, self.color_btn, self._ai_bar):
            widget.setEnabled(enabled)
        for shortcut in self._edit_shortcuts:
            shortcut.setEnabled(enabled)

    def _enter_trash_mode(self) -> None:
        if self.trash_mode:
            return
        if self.db.count_trashed() == 0:
            notify(self, "휴지통이 비어 있어요")
            return
        self.save_now()
        self.trash_mode = True
        self._trash_preview_id = None
        self._set_editing_enabled(False)  # 휴지통 메모는 보기 전용
        # 검색/정렬은 일반 모드와 동일하게 유지 — 휴지통에서도 찾고 정렬해야 한다.
        # 휴지통 메모엔 의미 없는 것만 숨긴다.
        self.pin_btn.hide()
        self.export_btn.hide()
        self.new_tab_btn.hide()
        # 휴지통 진입 버튼은 감춘다 — 나가는 길은 아래 '닫기' 하나로 충분하다
        self.trash_btn.hide()
        self.col_empty_btn.show()
        self.col_back_btn.show()
        self._refresh_memo_tabs()
        # 진입 시 펼침 상태였다면 접음 (휴지통 메모 클릭하면 다시 펼치며 미리보기)
        if self.is_expanded:
            self.collapse(exit_trash=False)

    def _exit_trash_mode(self) -> None:
        if not self.trash_mode:
            return
        self.trash_mode = False
        self._trash_preview_id = None
        self._set_editing_enabled(True)
        self._update_trash_btn()  # 남은 항목이 있으면 다시 나타난다
        self.col_empty_btn.hide()
        self.col_back_btn.hide()
        self.pin_btn.show()
        self.export_btn.show()
        self.new_tab_btn.show()
        # 휴지통 진입 전에 보던 메모로 에디터 복원.
        # 그 메모가 그 사이 삭제됐거나 아예 메모가 0개면 활성 메모를 보장한다.
        # (init의 `if not db.list_all(): db.create()` 와 같은 원칙 — 일반 모드는
        # 항상 최소 1개. 안 그러면 휴지통 비운 직후 인덱스는 비었는데 본문은
        # 빈 에디터가 떠 있는 어색한 상태가 됨.)
        restored = False
        if self.current_memo is not None:
            try:
                self._load_memo(self.db.get(self.current_memo.id))
                restored = True
            except KeyError:
                pass
        if not restored:
            active = self.db.list_all(sort=self._current_sort_key())
            self._load_memo(active[0] if active else self.db.create())
        self._refresh_memo_tabs()
        self._update_tabs_selected()

    def _after_trash_change(self) -> None:
        """휴지통 변경(복원/영구삭제) 후 갱신. 휴지통이 비면 일반 모드로 복귀."""
        if self.trash_mode and self.db.count_trashed() == 0:
            self._exit_trash_mode()  # 빈 화면 대신 일반 모드로 자동 복귀
        else:
            self._refresh_memo_tabs()

    def _empty_trash(self) -> None:
        """휴지통 모드에서 호출. 휴지통 전체 메모 + 첨부 이미지 영구 삭제."""
        n = self.db.count_trashed()
        if n == 0:
            return
        if not confirm(
            self, "휴지통을 비울까요?",
            f"메모 {n}개를 지워요. 비운 메모는 되돌릴 수 없습니다.", "비우기", danger=True,
        ):
            return
        for memo in self.db.list_trashed_memos():
            _delete_memo_images(memo.content)
            self.db.delete(memo.id)
        self._trash_preview_id = None
        self._exit_trash_mode()
        self._show_toast(f"휴지통을 비웠어요. ({n}개)")

    def _delete_current_memo(self) -> None:
        """Ctrl+Shift+D 단축키. 모드에 따라 다른 동작:
        - 일반 모드: 현재 편집 중인 메모를 휴지통으로 이동
        - 휴지통 모드: 미리보기 중인 메모를 영구 삭제"""
        if self.trash_mode:
            memo_id = self._trash_preview_id
            if memo_id is None:
                self._show_toast("지울 메모를 먼저 골라 주세요.")
                return
            try:
                memo = self.db.get(memo_id)
            except KeyError:
                return
            if not self._confirm_purge(memo):
                return
            # 삭제 전 이웃 메모 (일반 모드와 같은 패턴)
            trashed = self.db.list_trashed_memos()
            ids = [m.id for m in trashed]
            neighbor: Memo | None = None
            if memo_id in ids:
                idx = ids.index(memo_id)
                if idx > 0:
                    neighbor = trashed[idx - 1]
                elif len(trashed) > 1:
                    neighbor = trashed[1]
            _delete_memo_images(memo.content)
            self.db.delete(memo_id)
            self._trash_preview_id = None
            self._after_trash_change()
            # 휴지통이 비어있으면 _after_trash_change가 일반 모드로 복귀 → 그땐 패스
            if self.trash_mode and neighbor is not None:
                self._preview_trashed(neighbor.id)
            return
        # 일반 모드: 현재 메모 → 휴지통.
        # 확인창은 두지 않는다 — 휴지통으로 가는 되돌릴 수 있는 동작이라,
        # 물어보는 것보다 바로 하고 되돌릴 길을 주는 쪽이 빠르고 안전하다.
        if self.current_memo is None:
            return
        memo_id = self.current_memo.id
        all_memos = self.db.list_all(sort=self._current_sort_key())
        ids = [m.id for m in all_memos]
        neighbor: Memo | None = None
        if memo_id in ids:
            idx = ids.index(memo_id)
            if idx > 0:
                neighbor = all_memos[idx - 1]
            elif len(all_memos) > 1:
                neighbor = all_memos[1]
        self.db.soft_delete(memo_id)
        self.current_memo = None
        self._refresh_memo_tabs()
        if neighbor is not None:
            self._load_memo(neighbor)
            self._update_tabs_selected()
        else:
            self.collapse()
            self._clear_editor()
        self._toast_deleted(memo_id)

    def _toast_deleted(self, memo_id: int) -> None:
        """삭제 직후 되돌릴 기회를 준다. 접힘 상태에선 토스트가 뜰 본문이 안 보이므로,
        그땐 컬럼에 나타나는 휴지통 아이콘이 복구 경로 역할을 한다."""
        if not self.is_expanded:
            return
        self._show_toast("메모를 휴지통으로 옮겼어요", on_click=lambda: self._undo_delete(memo_id))

    def _undo_delete(self, memo_id: int) -> None:
        try:
            memo = self.db.restore(memo_id)
        except KeyError:
            self._show_toast("이미 지워진 메모예요.")
            return
        self._refresh_memo_tabs()
        self._load_memo(memo)
        self._update_tabs_selected()
        self._scroll_to_memo(memo_id)
        self._show_toast("되돌렸어요.")

    def _preview_trashed(self, memo_id: int) -> None:
        """휴지통 메모 내용을 읽기 전용으로 에디터에 표시 (current_memo는 안 건드림)."""
        # 이미 같은 메모 미리보기 중이고 펼친 상태면 토글로 접기
        if self._trash_preview_id == memo_id and self.is_expanded:
            self.collapse(exit_trash=False)
            return
        try:
            memo = self.db.get(memo_id)
        except KeyError:
            return
        self._trash_preview_id = memo_id
        self.title_input.blockSignals(True)
        self.editor.blockSignals(True)
        self.title_input.setText(memo.title)
        self._show_scratch(memo.content)  # 휴지통 미리보기는 임시 문서에
        self.title_input.blockSignals(False)
        self.editor.blockSignals(False)
        self._apply_memo_theme(memo.color)
        # 미리보기 중인 탭만 강조
        for i in range(self.tabs_layout.count()):
            w = self.tabs_layout.itemAt(i).widget()
            if isinstance(w, MemoTabButton):
                w.update_style(selected=(w.memo_id == memo_id))
        self._scroll_to_memo(memo_id)
        # 접힌 상태에서 휴지통 메모를 누른 경우 본문을 펼친다
        self.expand()

    def _confirm_purge(self, memo: Memo) -> bool:
        return confirm(
            self, "메모를 완전히 지울까요?",
            f"'{memo.title or '(제목 없음)'}' 메모와 첨부 이미지를 지워요. "
            "지운 메모는 되돌릴 수 없습니다.",
            "지우기", danger=True,
        )

    def _show_trash_menu(self, memo_id: int, button: QPushButton) -> None:
        try:
            memo = self.db.get(memo_id)
        except KeyError:
            return
        menu = ThemedMenu()
        restore_act = menu.add_item("복원하기", "archive-restore.svg")
        menu.addSeparator()
        purge_act = menu.add_item("영구 삭제", "trash-2.svg", danger=True)
        chosen = menu.exec(button.mapToGlobal(button.rect().center()))
        self.raise_()

        if chosen == restore_act:
            self.db.restore(memo_id)
            if self._trash_preview_id == memo_id:
                self._trash_preview_id = None
            self._after_trash_change()
        elif chosen == purge_act:
            if not self._confirm_purge(memo):
                return
            # 삭제 전 이웃 메모 — 미리보기 자동 이동용
            trashed = self.db.list_trashed_memos()
            ids = [m.id for m in trashed]
            neighbor: Memo | None = None
            if memo_id in ids:
                idx = ids.index(memo_id)
                if idx > 0:
                    neighbor = trashed[idx - 1]
                elif len(trashed) > 1:
                    neighbor = trashed[1]
            _delete_memo_images(memo.content)
            self.db.delete(memo_id)
            if self._trash_preview_id == memo_id:
                self._trash_preview_id = None
            self._after_trash_change()
            if self.trash_mode and neighbor is not None:
                self._preview_trashed(neighbor.id)

    def _update_column_style(self) -> None:
        """아래 묶음의 둥근 면을 현재 side에 맞춘다. 손잡이는 직접 그리므로 다시 칠만 한다."""
        for widget in (self.bar_group, self.tab_up_btn, self.tab_down_btn):
            widget.setProperty("side", MemoTabButton.side)
            theme_apply.repolish(widget)
        self.drag_grip.update()

    def _update_tabs_selected(self) -> None:
        # 접힘(collapse) 상태에서는 인디케이터를 보이지 않게 — 펼친 메모가 없으니
        # 어떤 탭에도 selected 표시가 남지 않도록.
        if not self.is_expanded:
            current_id = None
        else:
            current_id = self.current_memo.id if self.current_memo else None
        for i in range(self.tabs_layout.count()):
            w = self.tabs_layout.itemAt(i).widget()
            if isinstance(w, MemoTabButton):
                w.update_style(selected=(w.memo_id == current_id))

    def select_memo(self, memo_id: int) -> None:
        # 이미 선택된 메모를 다시 누르면 토글 (열려있으면 접고, 접혀있으면 펴기)
        if self.current_memo and self.current_memo.id == memo_id:
            if self.is_expanded:
                self.collapse()
            else:
                self.expand()
            return
        # 다른 메모 → 전환하면서 펼침
        self.save_now()
        try:
            memo = self.db.get(memo_id)
        except KeyError:
            return
        self._load_memo(memo)
        self._update_tabs_selected()
        self._scroll_to_memo(memo_id)
        self.expand()

    # ----- 메모별 문서(undo 스택) 캐시 -----
    def _document_for(self, memo: Memo) -> QTextDocument:
        """메모 전용 문서를 돌려준다. 문서마다 undo 스택을 따로 들고 있어서
        다른 메모에 갔다 돌아와도 Ctrl+Z가 그대로 동작한다."""
        doc = self._doc_cache.pop(memo.id, None)  # pop 후 재삽입 = LRU 갱신
        if doc is None:
            doc = QTextDocument(self)
            self._fill_document(doc, memo.content)
        self._doc_cache[memo.id] = doc
        # 방금 넣은 항목이 맨 뒤이므로 앞에서 버리면 현재 문서는 절대 안 걸린다
        while len(self._doc_cache) > UNDO_CACHE_SIZE:
            self._doc_cache.pop(next(iter(self._doc_cache))).deleteLater()
        return doc

    @staticmethod
    def _fill_document(doc: QTextDocument, content: str) -> None:
        """내용을 넣고 화면 모드에 맞춰 칠한다. 이 과정은 취소 대상이 아니다."""
        memo_document.prepare_document(doc)
        if content and Qt.mightBeRichText(content):
            doc.setHtml(content)
        else:
            doc.setPlainText(content)
        memo_document.decorate(doc, theme_apply.current_mode())
        doc.clearUndoRedoStacks()

    def _show_scratch(self, content: str) -> None:
        """메모가 아닌 내용을 임시 문서에 띄운다. 캐시된 메모 문서를
        건드리지 않기 위한 것 — 직접 setHtml하면 그 메모의 undo 스택이 날아간다."""
        self.editor.setDocument(self._scratch_doc)
        self._fill_document(self._scratch_doc, content)

    def _forget_doc(self, memo_id: int) -> None:
        """캐시된 문서를 버린다. 에디터 밖에서 내용이 바뀐 경우(버전 복원) 필수 —
        안 버리면 낡은 문서가 다시 붙는다."""
        doc = self._doc_cache.pop(memo_id, None)
        if doc is None:
            return
        if doc is self.editor.document():
            self.editor.setDocument(self._scratch_doc)
        doc.deleteLater()

    def _load_memo(self, memo: Memo) -> None:
        self.current_memo = memo
        self.title_input.blockSignals(True)
        self.editor.blockSignals(True)
        self.title_input.setText(memo.title)
        # 메모별 폰트 적용 (없으면 글로벌 default)
        family = memo.font_family or self.editor_font.family()
        size = memo.font_size or self.editor_font.pointSize() or T.MEMO_BODY_DEFAULT_PT
        editor_font = theme_apply.memo_font(family, size)
        # 메모 전용 문서로 교체 (내용도 문서가 들고 온다)
        doc = self._document_for(memo)
        # 문서마다 기본 폰트를 직접 박아준다. editor.setFont()는 위젯 폰트만 바꿀 뿐
        # 따로 만든 QTextDocument의 defaultFont까지 따라오지 않아서, 서식이 없는
        # 새 메모에 입력하면 앱 기본 폰트(더 작고 다른 글꼴)로 찍혔다.
        doc.setDefaultFont(editor_font)
        self.editor.setDocument(doc)
        self.editor.setFont(editor_font)
        self.title_input.blockSignals(False)
        self.editor.blockSignals(False)
        # round-trip된 HTML로 동기화 → 불필요한 자동저장 방지
        self.current_memo.content = memo_document.saved_html(self.editor.document())
        self._apply_memo_theme(memo.color)
        self._refresh_search_marks()
        # 메모 탭의 회전 텍스트도 그 메모의 family를 따라가도록 클래스 변수 갱신
        MemoTabButton.app_font_family = family
        self._update_pin_btn()

    def _clear_editor(self) -> None:
        self.current_memo = None
        self.title_input.blockSignals(True)
        self.editor.blockSignals(True)
        self.title_input.clear()
        self._show_scratch("")  # editor.clear()는 붙어 있는 메모 문서를 지워버린다
        self.title_input.blockSignals(False)
        self.editor.blockSignals(False)
        self._apply_memo_theme(DEFAULT_COLOR)
        self._update_pin_btn()

    def _apply_memo_theme(self, color_name: str | None) -> None:
        """선택된 메모 색을 메모 창에 반영한다. 저장값은 신뢰 경계라 정규화를 거친다."""
        tokens = theme_apply.apply_memo(self.body, normalize_color(color_name), self.side)
        self._memo_icon_color = tokens["memo_fg_secondary"]
        for button, asset in self.format_toolbar.memo_icons + [(self.export_btn, "file-output.svg")]:
            button.setIcon(QIcon(tinted_pixmap(asset, self._memo_icon_color, 16)))
        self._search_icon.setIcon(QIcon(tinted_pixmap("search.svg", self._memo_icon_color, 16)))
        self._ai_spark.setPixmap(tinted_pixmap("sparkles.svg", self._memo_icon_color, 16))
        self.color_btn.set_appearance(tokens["memo_band"], self._memo_icon_color)
        self.editor.set_bullet_colors(tokens["memo_face"], tokens["memo_fg"])
        self.sort_combo.set_icon_color(self._memo_icon_color)
        self._tint_mic()
        self._update_pin_btn()

    def _refresh_search_marks(self) -> None:
        """본문의 검색어를 강조한다. ExtraSelection이라 저장되지 않는다 (9장 17)."""
        term = self.search_input.text().strip()
        marks: list[QTextEdit.ExtraSelection] = []
        if term:
            doc = self.editor.document()
            cursor = doc.find(term)
            while not cursor.isNull() and len(marks) < 500:
                mark = QTextEdit.ExtraSelection()
                mark.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(theme_apply.current()["highlight"]))
                fmt.setForeground(QColor(T.HIGHLIGHT_FG))
                mark.format = fmt
                marks.append(mark)
                cursor = doc.find(term, cursor)
        self.editor.setExtraSelections(marks)

    # ----- new / delete -----
    def create_new_memo(self) -> None:
        if self.trash_mode:
            self._exit_trash_mode()
        # 새 메모는 제목·본문이 비어 어떤 검색어와도 매칭되지 않음.
        # 검색 필터가 걸려 있으면 새 메모가 탭에서 사라지므로 검색어를 비운다.
        # (_refresh_memo_tabs가 아래에서 명시적으로 호출되므로 시그널은 막아둠)
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
        self.save_now()
        memo = self.db.create()
        # _load_memo가 title/editor를 빈 값으로 세팅 + 색 테마 적용까지 처리.
        # (예전엔 current_memo만 갈아끼워서 UI에 직전 메모 내용이 남아있었음)
        self._load_memo(memo)
        self._refresh_memo_tabs()
        self._update_tabs_selected()
        self._scroll_to_memo(memo.id)
        self.expand()
        self.title_input.setFocus()

    def _show_tab_context_menu(self, pos, memo_id: int, button: QPushButton) -> None:
        try:
            memo = self.db.get(memo_id)
        except KeyError:
            return
        menu = ThemedMenu()
        pin_act = menu.add_item(
            "고정 풀기" if memo.is_pinned else "고정",
            "pin-off.svg" if memo.is_pinned else "pin.svg",
        )
        hist_act = menu.add_item("이전 버전 보기", "history.svg", shortcut="Ctrl+Alt+Z")
        export_act = menu.add_item("내보내기", "file-output.svg")
        menu.addSeparator()
        del_act = menu.add_item("휴지통으로 옮기기", "trash-2.svg", shortcut="Delete", danger=True)
        chosen = menu.exec(button.mapToGlobal(pos))
        self.raise_()

        if chosen == hist_act:
            self._show_versions(memo_id)
            return

        if chosen == export_act:
            self._export_memo(memo_id)
            return

        if chosen == pin_act:
            self._set_pinned(memo_id, not memo.is_pinned)
            return

        if chosen == del_act:
            # 확인창 없이 바로 휴지통으로 (되돌리기는 토스트/휴지통)
            is_current = bool(self.current_memo and self.current_memo.id == memo_id)

            # 삭제 전에 이웃 메모 확인
            neighbor: Memo | None = None
            if is_current:
                all_memos = self.db.list_all(sort=self._current_sort_key())
                ids = [m.id for m in all_memos]
                if memo_id in ids:
                    idx = ids.index(memo_id)
                    if idx > 0:
                        neighbor = all_memos[idx - 1]
                    elif len(all_memos) > 1:
                        neighbor = all_memos[1]

            self.db.soft_delete(memo_id)

            if is_current:
                self.current_memo = None
                self._refresh_memo_tabs()
                if neighbor is not None:
                    self._load_memo(neighbor)
                    self._update_tabs_selected()
                else:
                    self.collapse()   # body 숨긴 뒤 clear → 노란 화면 안 보임
                    self._clear_editor()
            else:
                self._refresh_memo_tabs()
            self._toast_deleted(memo_id)

    # ----- 고정 -----
    def _set_pinned(self, memo_id: int, pinned: bool) -> None:
        """고정 상태 변경 + 화면 갱신. 탭 우클릭 메뉴와 상단 버튼이 함께 쓴다."""
        self.db.set_pinned(memo_id, pinned)
        if self.current_memo and self.current_memo.id == memo_id:
            self.current_memo.is_pinned = pinned
        self._refresh_memo_tabs()
        self._update_pin_btn()

    def _toggle_pin_current(self) -> None:
        if self.current_memo is None:
            self._show_toast("고정할 메모를 먼저 골라 주세요.")
            return
        self._set_pinned(self.current_memo.id, not self.current_memo.is_pinned)

    def _update_pin_btn(self) -> None:
        """버튼은 '누르면 일어날 일'을 보여준다 — 고정 상태면 해제 아이콘."""
        if not hasattr(self, "pin_btn"):
            return
        pinned = bool(self.current_memo and self.current_memo.is_pinned)
        asset = "pin-off.svg" if pinned else "pin.svg"
        self.pin_btn.setIcon(QIcon(tinted_pixmap(asset, self._memo_icon_color, 16)))
        self.pin_btn.setToolTip("고정 풀기" if pinned else "메모 고정")
        self.pin_btn.setEnabled(self.current_memo is not None)

    # ----- 내보내기 -----
    def _export_current_memo(self) -> None:
        if self.current_memo is None:
            self._show_toast("내보낼 메모를 먼저 골라 주세요.")
            return
        self._export_memo(self.current_memo.id)

    def _export_memo(self, memo_id: int) -> None:
        """메모를 .md 또는 .txt 파일로 저장. 확장자로 형식을 정한다."""
        if self.current_memo and self.current_memo.id == memo_id:
            self.save_now()  # 편집 중인 내용까지 내보내려면 먼저 확정
        try:
            memo = self.db.get(memo_id)
        except KeyError:
            return
        suggested = Path.home() / f"{_safe_filename(memo.title)}.odt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "메모 내보내기",
            str(suggested),
            # Qt가 .docx를 못 쓴다 (지원: HTML/ODF/markdown/plaintext). ODF는 Word가
            # 그대로 여는 개방 표준이라 이걸 쓴다 — 라벨에 용도를 밝힌다.
            "문서 — Word에서 열기 (*.odt);;마크다운 (*.md);;텍스트 (*.txt)",
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".odt":
                # ODF는 Qt가 직접 파일로 쓴다 (zip 컨테이너라 텍스트로는 못 씀)
                writer = QTextDocumentWriter(path)
                writer.setFormat(b"ODF")
                if not writer.write(_memo_document(memo)):
                    self._show_toast("내보내지 못했어요. 다른 위치를 골라 주세요.")
                    return
            else:
                Path(path).write_text(
                    _memo_as_text(memo, markdown=suffix != ".txt"), encoding="utf-8"
                )
        except OSError as e:
            self._show_toast(f"내보내지 못했어요: {e}")
            return
        self._show_toast(f"저장했어요: {Path(path).name}")

    # ----- 버전 히스토리 -----
    def _show_current_versions(self) -> None:
        if self.current_memo is None:
            self._show_toast("메모를 먼저 골라 주세요.")
            return
        self._show_versions(self.current_memo.id)

    def _show_versions(self, memo_id: int) -> None:
        """이전 버전 목록을 열고, 고른 버전으로 되돌린다."""
        is_current = bool(self.current_memo and self.current_memo.id == memo_id)
        if is_current:
            self.save_now()  # 편집 중인 내용을 확정해야 목록이 최신 상태를 반영한다
        versions = self.db.list_versions(memo_id)
        if not versions:
            self._show_toast("아직 저장된 이전 버전이 없어요.")
            return
        dlg = VersionDialog(versions, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        version = dlg.selected()
        if version is None:
            return
        memo = self.db.restore_version(version.id)
        self._forget_doc(memo_id)  # 캐시된 문서는 되돌리기 전 내용을 들고 있다
        if is_current:
            self._load_memo(memo)
        self._refresh_memo_tabs()
        self._show_toast(f"{_version_label(version)} 버전으로 되돌렸어요.")

    # ----- text change / autosave -----
    def _on_text_changed(self) -> None:
        if self.current_memo is None or self.trash_mode:
            return
        self.autosave_timer.start(AUTOSAVE_DELAY)

    def _on_color_changed(self, color: str) -> None:
        if self.current_memo is None or self.trash_mode:
            return
        self.current_memo = self.db.update(self.current_memo.id, color=color)
        self._apply_memo_theme(self.current_memo.color)  # DB가 정규화한 최종 색
        self._refresh_memo_tabs()

    def _make_color_popup(self) -> MemoColorPopup:
        current = self.current_memo.color if self.current_memo else DEFAULT_COLOR
        popup = MemoColorPopup(current, self._color_slots, self)

        def pick(color: str) -> None:
            self._on_color_changed(color)
            popup.set_current(color)

        def add() -> None:
            popup.close()
            self._add_color_slot()

        popup.picked.connect(pick)
        popup.add_requested.connect(add)
        popup.menu_requested.connect(lambda color: self._show_slot_menu(color, popup))
        return popup

    def _open_color_popup(self) -> None:
        self._color_popup = self._make_color_popup()
        self._color_popup.show_below(self.color_btn)

    def _save_color_slots(self) -> None:
        self.db.set_setting_str(USER_SLOTS_KEY, "|".join(self._color_slots))

    def _show_slot_menu(self, color: str, popup: MemoColorPopup | None = None) -> None:
        menu = ThemedMenu()
        edit_act = menu.add_item("색 바꾸기")
        del_act = menu.add_item("지우기", "trash-2.svg", danger=True)
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if popup is not None:
            popup.close()
        self.raise_()
        if chosen == edit_act:
            self._edit_color_slot(color)
        elif chosen == del_act:
            self._delete_color_slot(color)

    def _add_color_slot(self) -> None:
        """새 색을 "직접 만든 색" 맨 앞에 넣고 현재 메모에 바로 적용. 최근 6개까지 남는다."""
        dlg = MemoColorDialog(None, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value = dlg.value()
        self._color_slots = ([value] + [c for c in self._color_slots if c != value])[:MAX_USER_SLOTS]
        self._save_color_slots()
        self._on_color_changed(value)

    def _edit_color_slot(self, color: str) -> None:
        dlg = MemoColorDialog(color, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value = dlg.value()
        self._color_slots = [value if c == color else c for c in self._color_slots]
        self._save_color_slots()
        if self.current_memo is not None and self.current_memo.color == color:
            self._on_color_changed(value)

    def _delete_color_slot(self, color: str) -> None:
        self._color_slots = [c for c in self._color_slots if c != color]
        self._save_color_slots()

    def save_now(self) -> None:
        self.autosave_timer.stop()
        # 휴지통 미리 보기 중의 에디터 내용은 current_memo의 것이 아니다
        if self.current_memo is None or self.trash_mode:
            return
        title = self.title_input.text()
        content = memo_document.saved_html(self.editor.document())  # 이미지 포함 위해 HTML로 저장
        if title == self.current_memo.title and content == self.current_memo.content:
            return
        try:
            # 덮어쓰기 전에 이전 내용을 버전으로 보관 (간격 제한은 db.snapshot이 판단)
            self.db.snapshot(self.current_memo.id)
            self.current_memo = self.db.update(
                self.current_memo.id, title=title, content=content
            )
        except KeyError:
            self.current_memo = None
            return
        # 제목 변경 시 tooltip 갱신을 위해 탭 다시 그림
        self._refresh_memo_tabs()

    # ----- sort -----
    def _current_sort_key(self) -> str:
        idx = self.sort_combo.currentIndex()
        if 0 <= idx < len(SORT_OPTIONS):
            return SORT_OPTIONS[idx][0]
        return SORT_OPTIONS[0][0]

    def _on_sort_changed(self, index: int) -> None:
        self.db.set_setting_int("sort_mode", index)  # 즉시 저장
        self._refresh_memo_tabs()
        self._update_tabs_selected()

    # ----- copy -----
    def _copy_memo_text(self) -> None:
        # 현재 메모 본문 전체를 plain text로 클립보드에 복사 (빈 메모도 안전)
        text = self.editor.toPlainText()
        QApplication.clipboard().setText(text)
        # 버튼이 내보내기로 바뀌어 아이콘 피드백을 줄 자리가 없다 → 토스트로 알린다
        self._show_toast("본문을 복사했어요.")

    # ----- search -----
    def _on_search_changed(self, _text: str) -> None:
        self._refresh_memo_tabs()
        self._refresh_search_marks()

    def focus_search(self) -> None:
        if self.trash_mode:
            return
        if not self.is_expanded:
            self.expand()
        self.search_input.setFocus()
        self.search_input.selectAll()

    # ----- shutdown -----
    def request_quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting:
            event.ignore()
            self.collapse()
            return
        try:
            self.save_now()
        except Exception as e:
            # 예외가 올라가면 event.accept()에 못 닿아 창은 안 닫히는데 DB만
            # 닫힌 먹통 상태가 된다. 종료는 진행하되 조용히 넘기지는 않는다 —
            # 마지막 편집이 날아가는 상황이라 사용자가 알아야 한다.
            print(f"[close] 종료 중 저장 실패: {e}")
            notify(self, "마지막 내용을 저장하지 못했어요", str(e), warning=True)
        finally:
            self.db.close()
        event.accept()
        QApplication.instance().quit()


def _memo_image_paths(html: str) -> list[Path]:
    """메모 HTML(content)에서 ~/.memo_slide/images/ 안의 첨부 이미지 경로 추출."""
    out: list[Path] = []
    try:
        images_root = IMAGES_DIR.resolve()
    except OSError:
        return out
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', html or ""):
        src = m.group(1)
        for prefix in ("file:///", "file://"):
            if src.startswith(prefix):
                src = src[len(prefix):]
        try:
            p = Path(src)
            if p.exists() and p.resolve().parent == images_root:
                out.append(p)
        except OSError:
            continue
    return out


def _cleanup_old_recordings(days: int = 30) -> None:
    """변환 실패로 temp/에 남은 녹음 파일 정리 (휴지통과 같은 30일 기준).

    Whisper 실패·키 없음일 때는 일부러 파일을 남긴다 — 그래야 사용자가 되찾을
    수 있다. 다만 지금까지 아무도 안 지워서 계속 쌓이기만 했다.
    """
    cutoff = datetime.now().timestamp() - days * 86400
    for p in (APP_DIR / "temp").glob("recording_*.wav"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                print(f"[temp] {days}일 경과 → 임시 녹음 삭제: {p.name}")
        except OSError:
            pass


def _delete_memo_images(html: str) -> None:
    """메모에 첨부된 이미지 파일들을 디스크에서 삭제."""
    for p in _memo_image_paths(html):
        try:
            p.unlink()
            print(f"[trash] 첨부 이미지 삭제: {p.name}")
        except OSError as e:
            print(f"[trash] 이미지 삭제 실패: {p.name} ({e})")


def _asset(name: str) -> Path:
    """assets/ 폴더 내 리소스 경로."""
    return _resource_path(f"assets/{name}")


def load_app_icon() -> QIcon | None:
    path = _asset("icons/SlideMemo.ico")
    return QIcon(str(path)) if path.exists() else None


def load_tray_icon() -> QIcon:
    """배율에 맞는 판을 고르도록 작은 크기를 모두 넣는다 (8장)."""
    icon = QIcon()
    for size in (16, 20, 24, 32):
        icon.addFile(str(_asset(f"icons/slidememo-{size}.png")), QSize(size, size))
    return icon


def make_tray_icon(window: SlideMemoWindow, icon: QIcon | None = None) -> QSystemTrayIcon:
    from settings_dialog import SettingsDialog

    tray = QSystemTrayIcon(icon or load_tray_icon(), window)
    tray.setToolTip("Slide Memo")

    menu = ThemedMenu()
    toggle_act = menu.add_item("열기 / 접기")
    toggle_act.triggered.connect(window.toggle)
    hide_act = menu.add_item("잠깐 숨기기", shortcut=HIDE_HOTKEY_LABEL)

    def _toggle_hidden() -> None:
        if window.isVisible():
            window.hide_bar()
        else:
            window.show_bar()

    hide_act.triggered.connect(_toggle_hidden)
    menu.aboutToShow.connect(
        lambda: hide_act.setText(
            f"{'잠깐 숨기기' if window.isVisible() else '다시 보이기'}\t{HIDE_HOTKEY_LABEL}"
        )
    )
    side_act = menu.add_item("반대쪽 가장자리로 옮기기", "arrow-left-right.svg")
    side_act.triggered.connect(window.toggle_side)
    menu.addSeparator()
    settings_act = menu.add_item("설정", "settings.svg")

    def _open_settings_from_tray() -> None:
        dlg = SettingsDialog(window.db, window)
        dlg.exec()
        window.apply_side_settings()
        window.apply_tab_geometry_settings()
        window.apply_display_mode_settings()
        window._apply_window_opacity()
        window._refresh_ai_bar()
        window.apply_screen_mode()
        window._force_topmost()
        if getattr(dlg, "restart_guide_requested", False):
            window.restart_guide()

    settings_act.triggered.connect(_open_settings_from_tray)
    menu.addSeparator()
    menu.add_item("종료").triggered.connect(window.request_quit)
    tray.setContextMenu(menu)

    def on_activate(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if window.isVisible():
                window.toggle()
            else:
                window.show_bar()

    tray.activated.connect(on_activate)
    tray.messageClicked.connect(window.show_bar)
    return tray


def _set_windows_app_user_model_id() -> None:
    """Windows 작업표시줄이 logo.ico를 쓰게 한다.
    AppUserModelID를 명시 안 하면 호스트(python.exe) 아이콘이 표시됨."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "anthropic.slidememo.app"
        )
    except (OSError, AttributeError):
        pass  # 구버전 Windows 등 — 아이콘이 기본값으로 떨어지더라도 앱은 정상 동작


APP_VERSION = "1.4.1"
_GITHUB_REPO = "yujeong0411/slide-memo"


def _ver_tuple(v: str) -> tuple[int, ...]:
    """'v1.2.0' → (1, 2, 0). 형식이 깨졌으면 빈 튜플(= 가장 낮은 버전)."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except ValueError:
        return ()


class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str)  # current, latest

    def run(self) -> None:
        import json
        import urllib.request

        try:
            url = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "SlideMemo"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                return
            if _ver_tuple(tag) > _ver_tuple(APP_VERSION):
                self.update_available.emit(APP_VERSION, tag)
        except Exception:
            pass


class UpdateDialog(AppDialog):
    def __init__(self, current: str, latest: str, parent: QWidget | None = None) -> None:
        super().__init__("새 버전이 나왔어요", parent)
        self.body.addWidget(role_label(f"v{latest}", "badge"), 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(role_label(f"지금 쓰는 버전은 v{current}이에요.", "description"))
        self.add_actions("업데이트하기", "나중에").clicked.connect(self._open_download)

    def _open_download(self) -> None:
        QDesktopServices.openUrl(
            QUrl(f"https://github.com/{_GITHUB_REPO}/releases/latest/download/SlideMemo-Setup.exe")
        )


WHATS_NEW_KEY = "seen_whatsnew_version"
# 업데이트 후 첫 실행에 보여줄 변경사항. 새 버전마다 맨 위에 한 덩어리씩 쌓는다.
# (팝업으로 따로 안내한 색 팔레트 개편(1.1.1)은 _show_palette_notice가 담당)
WHATS_NEW: list[tuple[str, list[str]]] = [
    ("1.4.1", [
        "<b>메모 색을 단색으로도</b> 지정할 수 있습니다 — 색 점 옆 <b>＋</b>에서"
        " 색을 1개만 고르면 단색, 2개 이상이면 그라데이션입니다.",
        "<b>사용법 가이드</b>를 이 창에서 바로 열 수 있습니다 —"
        " 아래 <b>[사용법 가이드 보기]</b>.",
    ]),
    ("1.4.0", [
        "<b>사용법 가이드 추가</b> — 바와 메모 쓰는 법을 말풍선으로 안내합니다."
        " (설정 → 사용법 가이드 다시 보기)",
        "<b>삭제 되돌리기 · Delete 키</b> — 확인 창 없이 휴지통으로 가고,"
        " 잘못 지웠으면 <b>‘되돌리기’</b>로 복구합니다. 탭을 고른 뒤 Delete로도 삭제.",
        "<b>바 하단 정리</b> — 설정은 트레이·바 우클릭 메뉴로 옮겼고,"
        " 휴지통 아이콘은 휴지통에 메모가 있을 때만 나타납니다.",
    ]),
    ("1.3.0", [
        "<b>바 크기를 마우스로 조절</b> — 안쪽 가장자리를 끌면 가로 폭,"
        " 위·아래 끝을 끌면 세로 길이가 바뀝니다.",
    ]),
    ("1.2.0", [
        "<b>바 잠깐 숨기기 추가</b> — 탭 열 하단 <b>»</b> 또는 <b>Ctrl+Shift+Z</b>로"
        " 감췄다가, 같은 단축키나 트레이 아이콘 클릭으로 되돌립니다.",
    ]),
    ("1.1.0", [
        "<b>버전 기록</b> — 메모를 우클릭해 이전 내용으로 되돌릴 수 있습니다.",
        "<b>파일 내보내기</b> — 메모를 파일로 저장합니다.",
    ]),
]


def _whats_new_since(seen: str) -> list[tuple[str, list[str]]]:
    """seen 버전 이후의 변경사항만. seen이 비었거나 깨졌으면 전부."""
    seen_t = _ver_tuple(seen)
    return [(v, lines) for v, lines in WHATS_NEW if _ver_tuple(v) > seen_t]


def _show_welcome(window: "SlideMemoWindow", db: MemoDatabase) -> None:
    """신규 설치 첫 실행 안내. 튜토리얼을 예고 없이 시작하지 않고 먼저 물어본다.
    (업그레이드 사용자는 이 팝업 대신 '새로운 기능'을 본다)"""
    box = message_box(
        window,
        "화면 가장자리에 붙어 있는 메모장이에요",
        "· 탭을 누르면 메모가 펼쳐지고, <b>Esc</b>로 접혀요.<br>"
        "· 나머지 사용법을 <b>말풍선으로 짧게</b> 안내해 드릴까요?"
        " (바 4단계 · 메모 4단계, 언제든 건너뛸 수 있어요)<br>"
        "· 나중에 보려면 <b>설정 → 사용법 다시 보기</b>를 누르세요.",
    )
    add_box_button(box, "나중에", QMessageBox.ButtonRole.RejectRole)
    start_btn = add_box_button(box, "가이드 보기", QMessageBox.ButtonRole.AcceptRole, "primary")
    box.setDefaultButton(start_btn)
    box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    box.exec()
    window._force_topmost()
    if box.clickedButton() is start_btn:
        window.start_guide("bar")
    else:  # 거절했는데 계속 들이밀지 않는다 (설정에서 언제든 다시 볼 수 있음)
        db.set_setting_int(GUIDE_BAR_KEY, 1)
        db.set_setting_int(GUIDE_BODY_KEY, 1)


def _show_whats_new(window: "SlideMemoWindow", db: MemoDatabase, is_upgrade: bool) -> None:
    """업데이트 후 첫 실행에 '새로운 기능'을 한 번 띄운다.
    마지막으로 안내한 버전을 DB에 남겨, 그 사이에 건너뛴 릴리즈 내용까지 함께
    보여준다 (기록이 없으면 = 안내 기능 이전 사용자라 전부 보여준다)."""
    if not is_upgrade:  # 신규 설치는 전부 처음 보는 기능이라 안내할 게 없다
        db.set_setting_str(WHATS_NEW_KEY, APP_VERSION)
        return
    items = _whats_new_since(db.get_setting_str(WHATS_NEW_KEY, ""))
    if not items:
        return
    db.set_setting_str(WHATS_NEW_KEY, APP_VERSION)  # 먼저 저장 — 다시 뜨지 않게
    box = message_box(
        window,
        f"v{APP_VERSION}로 업데이트했어요",
        "<br>".join(
            f"<b>v{v}</b><br>" + "".join(f"&nbsp;· {ln}<br>" for ln in lines)
            for v, lines in items
        ),
    )
    # 기존 사용자는 가이드가 생긴 줄 모른다 → 여기서 바로 볼 수 있게 한다
    guide_btn = add_box_button(box, "사용법 가이드 보기", QMessageBox.ButtonRole.ActionRole)
    ok_btn = add_box_button(box, "확인", QMessageBox.ButtonRole.AcceptRole, "primary")
    box.setDefaultButton(ok_btn)
    box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    box.exec()
    window._force_topmost()
    if box.clickedButton() is guide_btn:
        window.restart_guide()  # 1단계부터, 2단계는 다음 펼침 때 이어진다


def _show_palette_notice(window: "SlideMemoWindow", db: MemoDatabase, is_upgrade: bool) -> None:
    """메모 색을 옮긴 사용자에게 처음 켤 때 한 번 알린다 (3.0.2)."""
    if not db.get_setting_int(PAPER_NOTICE_KEY, 0):
        return
    db.set_setting_int(PAPER_NOTICE_KEY, 0)  # 먼저 저장 — 다시 뜨지 않게
    box = message_box(
        window,
        "메모 색이 차분한 종이 톤으로 바뀌었어요.",
        "색은 제목 옆 색 단추에서 언제든 바꿀 수 있어요.",
    )
    add_box_button(box, "확인", QMessageBox.ButtonRole.AcceptRole, "primary")
    box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    box.exec()
    window._force_topmost()


def _splash_pixmap() -> QPixmap:
    """새 로고를 얹은 시작 화면. 화면 모드를 따른다."""
    t = theme_apply.current()
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    width, height, logo = 320, 200, 96
    pixmap = QPixmap(int(width * dpr), int(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(t["line"]), 1))
    painter.setBrush(QColor(t["bg_canvas"]))
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), T.RADIUS["surface"], T.RADIUS["surface"])
    QIcon(str(_asset("icons/slidememo.svg"))).paint(painter, QRect((width - logo) // 2, 32, logo, logo))
    painter.end()
    return pixmap


def _install_translator(app: QApplication) -> None:
    """OK·Cancel·Undo 같은 Qt 기본 문구를 한국어로. 번역 파일이 없어도 앱은 동작한다."""
    translator = QTranslator(app)
    for folder in (
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
        str(_resource_path("PyQt6/Qt6/translations")),
    ):
        if translator.load("qtbase_ko", folder):
            app.installTranslator(translator)
            return


def _register_fonts() -> None:
    fonts_dir = _resource_path("assets/fonts")
    if fonts_dir.exists():
        for font_file in fonts_dir.glob("*.otf"):
            QFontDatabase.addApplicationFont(str(font_file))


def main() -> int:
    # HiDPI 환경에서 좌표/스케일 어긋남 방지 (QApplication 생성 전에 호출)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    _set_windows_app_user_model_id()
    if sys.platform == "win32":
        # DirectWrite는 NoSubpixelAntialias를 무시해 글자에 색 번짐이 남는다 (2.1)
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
    app = QApplication(sys.argv)
    install_tooltips(app)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Slide Memo")
    _install_translator(app)
    _register_fonts()
    db = MemoDatabase()  # 시작 화면부터 화면 모드를 따르도록 먼저 연다
    theme_setting = db.get_setting_str(theme_apply.THEME_MODE_KEY, "system")
    theme_apply.request_color_scheme(theme_setting)
    theme_apply.apply_theme(app, theme_apply.resolve_mode(theme_setting))

    # 로딩 splash — 마퀴 progress bar로 'import + 초기화 진행 중' 신호.
    # QApplication 이후에야 뜨므로 그 이전 부트로더/import 구간은 가리지 못함.
    splash_pix = _splash_pixmap()
    splash = QSplashScreen(
        splash_pix,
        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint,
    )
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    logical = splash_pix.deviceIndependentSize().toSize()
    _bar = QProgressBar(splash)
    _bar.setObjectName("splashBar")
    _bar.setGeometry(40, logical.height() - 40, logical.width() - 80, 4)
    _bar.setRange(0, 0)  # 끝을 모르는 진행
    _bar.setTextVisible(False)
    splash.show()
    app.processEvents()
    app_icon = load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    # 30일 지난 휴지통 항목 자동 영구삭제 (+ 첨부 이미지 정리)
    for removed in db.cleanup_old_trash(days=30):
        _delete_memo_images(removed.content)
    _cleanup_old_recordings(days=30)
    # 활성 메모가 하나도 없으면 빈 메모 1개를 자동 생성 (첫 실행 / 모두 삭제 직후 모두 포함)
    # 메모 개수만 보면 "다 지운 사용자"가 신규 설치로 오인돼 업데이트 안내를
    # 못 받는다 → 이 DB를 방금 만든 경우만 신규 설치로 본다.
    is_upgrade = not db.is_fresh_install()
    if not is_upgrade:
        db.create()

    window = SlideMemoWindow(db)
    QGuiApplication.styleHints().colorSchemeChanged.connect(window.on_system_scheme_changed)
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()

    tray = make_tray_icon(window)
    tray.show()
    window._tray = tray  # 참조 유지

    splash.finish(window)
    _show_palette_notice(window, db, is_upgrade)
    # 가이드 자동 시작 여부를 안내 팝업보다 먼저 정한다. 순서가 반대면, 팝업의
    # '사용법 가이드 보기'가 방금 0으로 되돌린 플래그를 이 블록이 다시 1로 덮어
    # 2단계(본문 가이드)가 영영 안 뜬다.
    if not db.get_setting_int(GUIDE_BAR_KEY, 0):
        if is_upgrade:
            # 이미 쓰고 있는 사람에게 갑자기 튜토리얼을 띄우지 않는다.
            # (필요하면 설정 → 가이드 다시 보기)
            db.set_setting_int(GUIDE_BAR_KEY, 1)
            db.set_setting_int(GUIDE_BODY_KEY, 1)
        else:
            QTimer.singleShot(700, lambda: _show_welcome(window, db))
    _show_whats_new(window, db, is_upgrade)

    _checker = UpdateChecker()
    _checker.update_available.connect(
        lambda cur, lat: UpdateDialog(cur, lat, window).exec()
    )
    _checker.start()
    window._update_checker = _checker  # GC 방지

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
