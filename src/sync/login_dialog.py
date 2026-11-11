"""Google 계정 연결을 기다리는 창 (설계 6.1). 브라우저에서 허용하는 동안 [취소]를 누를 수 있고,
브라우저가 열리지 않으면 로그인 주소를 복사할 수 있게 보여 준다. 5분이 지나면 저절로 멈춘다."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QWidget

from sync.oauth import LOGIN_TIMEOUT_S, Grant, LoginFlow, OAuthError
from theme.widgets import AppDialog, make_button, role_label


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
    """exec()가 끝나면 grant(성공) 또는 error(OAuthError)가 채워진다."""

    def __init__(self, client: dict, parent=None, timeout: float = LOGIN_TIMEOUT_S) -> None:
        super().__init__("Google 계정 연결", parent)
        self.grant: Grant | None = None
        self.error: OAuthError | None = None
        self.flow = LoginFlow(client, timeout)
        self.info = role_label("브라우저에서 Google 계정을 고르고 허용해 주세요.", "body")
        self.info.setWordWrap(True)
        self.body.addWidget(self.info)
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

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.flow.cancel()  # 기다림이 끝나면 _finished가 창을 닫는다

    def _finished(self, result) -> None:
        self._waiter.wait()
        if isinstance(result, Grant):
            self.grant = result
            self.accept()
        else:
            self.error = result
            self.reject()

    def reject(self) -> None:
        if self._waiter.isRunning():  # Esc·창 닫기도 취소와 같다
            self._cancel()
            return
        super().reject()
