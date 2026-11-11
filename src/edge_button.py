"""바를 잠깐 숨겼을 때 화면 가장자리에 남는 로고 단추 (4.1)."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from theme import apply as A
from theme import tokens as T
from theme.widgets import _paint_soft_shadow

_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def covers_monitor(window: tuple[int, int, int, int], monitor: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = window
    m_left, m_top, m_right, m_bottom = monitor
    return left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def is_foreign_fullscreen(own_hwnd: int) -> bool:
    """다른 앱이 이 창이 있는 모니터를 전체 화면으로 쓰고 있는가."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
    if pid.value == os.getpid():
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(foreground, name, 64)
    if name.value in _SHELL_CLASSES:
        return False
    monitor = user32.MonitorFromWindow(foreground, 2)
    if monitor != user32.MonitorFromWindow(wintypes.HWND(own_hwnd), 2):
        return False
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    rect = wintypes.RECT()
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)) or not user32.GetWindowRect(foreground, ctypes.byref(rect)):
        return False
    m = info.rcMonitor
    return covers_monitor((rect.left, rect.top, rect.right, rect.bottom), (m.left, m.top, m.right, m.bottom))


class EdgeLogoButton(QWidget):
    """바깥쪽은 직각, 안쪽 두 모서리는 둥근 32×32 단추. 누르면 clicked, 끌면 moved(면의 y)."""

    clicked = pyqtSignal()
    moved = pyqtSignal(int)

    FACE, LOGO, RADIUS = 32, 20, 8
    TOOLTIP = "메모장 펼치기 (Ctrl+Shift+Z)"

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)  # 활성 창이 아니어도 툴팁을 띄운다
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        _y, blur, _alpha = T.SHADOW["sm"]
        self._blur = blur
        self.side = "right"
        self.area = QRect()
        self.hovered = False
        self._press_y: int | None = None
        self._start_top = 0
        self._dragging = False

    def _face(self) -> QRect:
        y, blur, _alpha = T.SHADOW["sm"]
        x = 0 if self.side == "left" else blur
        return QRect(x, blur - y, self.FACE, self.FACE)

    def face_top(self) -> int:
        return self.y() + self._face().y()

    def place(self, area: QRect, side: str, face_top: int) -> None:
        """area는 화면 영역, face_top은 면의 위쪽 y."""
        self.side, self.area = side, area
        y, blur, _alpha = T.SHADOW["sm"]
        self.resize(self.FACE + blur, self.FACE + blur * 2)
        x = area.left() if side == "left" else area.right() + 1 - self.width()
        self.move(x, self._clamped(face_top) - (blur - y))
        self.update()

    def _clamped(self, face_top: int) -> int:
        return max(self.area.top(), min(face_top, self.area.bottom() + 1 - self.FACE))

    def tooltip_request(self) -> tuple[str, str] | None:
        return self.TOOLTIP, "left" if self.side == "right" else "right"

    def _set_hovered(self, hovered: bool) -> None:
        if hovered != self.hovered:
            self.hovered = hovered
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._face().contains(event.position().toPoint()):
            self._press_y = round(event.globalPosition().y())
            self._start_top = self.face_top()
            self._dragging = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_y is None:
            self._set_hovered(self._face().contains(event.position().toPoint()))
            return
        delta = round(event.globalPosition().y()) - self._press_y
        if not self._dragging and abs(delta) < QApplication.startDragDistance():
            return
        self._dragging = True
        self.move(self.x(), self._clamped(self._start_top + delta) - self._face().y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_y is None:
            return
        self._press_y = None
        if self._dragging:
            self._dragging = False
            self.moved.emit(self.face_top())
        elif self._face().contains(event.position().toPoint()):
            self._set_hovered(False)
            self.clicked.emit()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._set_hovered(False)

    def _shape(self, face: QRectF) -> QPainterPath:
        rounded = QPainterPath()
        rounded.addRoundedRect(face, self.RADIUS, self.RADIUS)
        outer = QPainterPath()
        half = face.width() / 2
        outer.addRect(QRectF(face.left() if self.side == "left" else face.left() + half, face.top(), half, face.height()))
        return rounded.united(outer).simplified()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = A.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        face = QRectF(self._face())
        _paint_soft_shadow(painter, face, self.RADIUS, "sm")
        shape = self._shape(face.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.setPen(QPen(A.qcolor(t["line"]), 1))
        painter.setBrush(A.qcolor(t["bg_canvas"]))
        painter.drawPath(shape)
        if self.hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(A.qcolor(t["overlay_hover"]))
            painter.drawPath(shape)
        screen = QGuiApplication.primaryScreen()
        dpr = self.devicePixelRatioF() if screen is not None else 1.0
        logo = QIcon(str(A.asset_path("icons/slidememo-20.svg"))).pixmap(QSize(self.LOGO, self.LOGO), dpr)
        margin = (self.FACE - self.LOGO) // 2
        painter.drawPixmap(QPoint(self._face().x() + margin, self._face().y() + margin), logo)
        painter.end()
