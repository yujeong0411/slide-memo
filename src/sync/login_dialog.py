"""Google 계정 연결 창 (설계 6.1, 디자인 md 4.6). 브라우저에서 허용하는 동안 [취소]를 누를 수 있고,
브라우저가 열리지 않으면 로그인 주소를 복사할 수 있게 보여 준다. 5분이 지나면 저절로 멈춘다.

허용한 뒤에도 닫지 않고 첫 동기화가 끝날 때까지 단계와 진행을 보여 준다 (9장 40):
  "Google 계정을 확인하고 있어요" → "Drive를 확인하고 있어요" → "메모를 맞추고 있어요 (12/30)" → "연결됐어요"
단계를 넘기는 일은 이 창을 연 쪽(동기화 탭)이 granted 신호를 받아 한다."""
from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QProgressBar, QWidget

from memo_popups import Spinner
from sync.oauth import LOGIN_TIMEOUT_S, Grant, LoginFlow, OAuthError
from theme.widgets import AppDialog, make_button, role_label

DONE_SHOW_MS = 1000  # "연결됐어요"를 보여 주는 시간


class _Waiter(QThread):
    done = pyqtSignal(object)  # Grant 또는 OAuthError

    def __init__(self, flow: LoginFlow) -> None:
        super().__init__()
        self.flow = flow

    def run(self) -> None:
        try:
            self.done.emit(self.flow.wait())
        except OAuthError as e:
            self.done.emit(e)
        except Exception:  # noqa: BLE001 — 사용자에게는 일반 문구만, 상세는 남기지 않는다
            self.done.emit(OAuthError("failed"))


class LoginDialog(AppDialog):
    """exec()가 끝나면 grant(성공) 또는 error(OAuthError)가 채워진다.
    working=True로 열면 허용 뒤 granted 신호를 보내고 창은 열어 둔다(단계 표시). 끝은 finish_ok()/fail()."""

    granted = pyqtSignal(object)        # Grant
    cancel_requested = pyqtSignal()     # 허용 뒤 단계 중에 [취소]

    def __init__(self, client: dict, parent=None, timeout: float = LOGIN_TIMEOUT_S, *, working: bool = False) -> None:
        super().__init__("Google 계정 연결", parent)
        self.grant: Grant | None = None
        self.error: OAuthError | None = None
        self.working = working
        self._stage_mode = False
        self.flow = LoginFlow(client, timeout)
        status_row = QHBoxLayout()
        self.spinner = Spinner(self)
        self.spinner.hide()
        status_row.addWidget(self.spinner)
        self.info = role_label("브라우저에서 Google 계정을 고르고 허용해 주세요.", "body")
        self.info.setWordWrap(True)
        status_row.addWidget(self.info, 1)
        self.body.addLayout(status_row)
        self.bar = QProgressBar()
        self.bar.setObjectName("syncProgress")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        self.body.addWidget(self.bar)
        self.url_box = QWidget()
        row = QHBoxLayout(self.url_box)
        row.setContentsMargins(0, 0, 0, 0)
        self.url_edit = QLineEdit(self.flow.url)
        self.url_edit.setReadOnly(True)
        self.copy_button = make_button("주소 복사")
        self.copy_button.clicked.connect(self._copy)
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.copy_button)
        self.url_box.hide()
        self.body.addWidget(self.url_box)
        self.cancel_button = self.add_button("취소")
        self.cancel_button.clicked.connect(self._cancel)
        self._waiter = _Waiter(self.flow)
        self._waiter.done.connect(self._finished)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._waiter.isRunning() and self.grant is None and self.error is None:
            self._waiter.start()
            if not self.flow.open_browser():
                self.info.setText("브라우저가 열리지 않았어요. 아래 주소를 복사해 브라우저에 붙여 넣어 주세요.")
                self.url_box.show()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.flow.url)
        self.copy_button.setText("복사했어요")

    # ----- 단계 표시 (허용 뒤) -----
    def set_stage(self, text: str) -> None:
        self._stage_mode = True
        self.url_box.hide()
        self.spinner.show()
        self.bar.show()
        self.bar.setRange(0, 0)  # 끝을 모르는 동안은 흐르는 막대
        self.info.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        if not self._stage_mode or total <= 0:
            return
        self.bar.setRange(0, total)
        self.bar.setValue(min(done, total))
        self.info.setText(f"메모를 맞추고 있어요 ({min(done, total)}/{total})")

    def finish_ok(self) -> None:
        self.spinner.hide()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.info.setText("연결됐어요")
        self.cancel_button.setEnabled(False)
        QTimer.singleShot(DONE_SHOW_MS, self.accept)

    def fail(self, error: OAuthError | None) -> None:
        self.error = error
        self._stage_mode = False
        super().reject()

    # ----- 취소 -----
    def _cancel(self) -> None:
        if self._stage_mode:
            self.cancel_button.setEnabled(False)
            self.info.setText("취소하고 있어요")
            self.cancel_requested.emit()  # 연결한 쪽이 정리한 뒤 fail()로 닫는다
            return
        self.cancel_button.setEnabled(False)
        self.flow.cancel()  # 기다림이 끝나면 _finished가 창을 닫는다

    def _finished(self, result) -> None:
        self._waiter.wait()
        if isinstance(result, Grant):
            self.grant = result
            if self.working:
                self.cancel_button.setEnabled(True)
                self.set_stage("Google 계정을 확인하고 있어요")
                self.granted.emit(result)
            else:
                self.accept()
        else:
            self.error = result
            super().reject()

    def reject(self) -> None:
        if self._waiter.isRunning() or self._stage_mode:  # Esc·창 닫기도 취소와 같다
            if self.cancel_button.isEnabled():
                self._cancel()
            return
        super().reject()
