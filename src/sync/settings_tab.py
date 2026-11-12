"""설정 창의 "동기화" 탭 (설계 6장, 디자인 md 4.6). 네트워크가 필요한 일은 SyncController의 작업 줄에 맡긴다."""
from __future__ import annotations

import time
from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import links
from sync import oauth
from sync import runner
from sync.runner import STATUS_TEXT
from theme import apply as A
from theme.widgets import AppDialog, make_button, role_label

GOOGLE_CONNECTIONS_URL = "https://myaccount.google.com/connections"
_LABEL_WIDTH = 112


def relative_time(ms: int, now: float | None = None) -> str:
    if not ms:
        return "아직 없어요"
    sec = max(0, int((now or time.time()) - ms / 1000))
    if sec < 60:
        return "방금"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    return f"{sec // 86400}일 전"


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _row(form: QFormLayout, text: str, field) -> None:
    label = QLabel(text)
    label.setFixedWidth(_LABEL_WIDTH)
    form.addRow(label, field)


class _Ask(AppDialog):
    """확인 창 (4.7): 제목 + 설명 + 주된 동작."""

    def __init__(self, head: str, body: str, action: str, cancel: str, parent=None, check: str = "") -> None:
        super().__init__(head, parent)
        text = role_label(body, "description")
        text.setWordWrap(True)
        self.body.addWidget(text)
        self.check = QCheckBox(check) if check else None
        if self.check is not None:
            self.body.addSpacing(4)
            self.body.addWidget(self.check)
        # 오른쪽 끝이 주된 동작, 바로 왼쪽이 취소 (4.7)
        self.cancel_btn = self.add_button(cancel)
        self.cancel_btn.clicked.connect(self.reject)
        self.action_btn = self.add_button(action, "primary")
        self.action_btn.clicked.connect(self.accept)
        self.action_btn.setDefault(True)

    def set_danger(self, danger: bool) -> None:
        """되돌릴 수 없게 되면 빨간 위험 단추로 바꾸고 기본 포커스를 취소에 둔다 (4.7)."""
        self.action_btn.setProperty("variant", "danger" if danger else "primary")
        A.repolish(self.action_btn)
        self.action_btn.setDefault(not danger)
        self.cancel_btn.setDefault(danger)
        (self.cancel_btn if danger else self.action_btn).setFocus()


class SyncTab(QWidget):
    def __init__(self, db, controller, parent=None) -> None:
        super().__init__(parent)
        self.db, self.ctl = db, controller
        self._grant: oauth.Grant | None = None
        self._dlg = None
        self._connecting = False
        self._cancel_after_connect = False
        self._pending_email = ""
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(24, 20, 24, 20)
        self.outer.setSpacing(12)
        if self.ctl is not None:
            self.ctl.job_finished.connect(self._on_job)
            self.ctl.cycle_finished.connect(lambda _r: self._refresh_status())
        self.render()

    # ----- 그리기 -----
    def render(self) -> None:
        _clear(self.outer)
        self.status_lbl = role_label("", "hint")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.hide()
        if self.ctl is None or not self.ctl.available:
            self.outer.addWidget(role_label(oauth.MESSAGES["no_client"], "hint"))
        elif not self.ctl.connected:
            self._render_disconnected()
        else:
            self._render_connected()
        self.outer.addStretch(1)

    def _render_disconnected(self) -> None:
        text = role_label("메모를 내 Google Drive에 보관하고 다른 PC와 맞춰요. "
                          "메모는 내 Drive의 앱 전용 공간에만 저장돼요.", "description")
        text.setWordWrap(True)
        self.outer.addWidget(text)
        row = QHBoxLayout()
        self.connect_btn = make_button("Google 계정 연결", "primary")
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(self.connect_btn)
        privacy = make_button("개인정보처리방침", "text")
        privacy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(links.PRIVACY_URL)))
        row.addWidget(privacy)
        row.addStretch(1)
        self.outer.addLayout(row)
        self.outer.addWidget(self.status_lbl)

    def _render_connected(self) -> None:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        _row(form, "계정", QLabel(self.db.get_setting_str(oauth.ACCOUNT_EMAIL_KEY, "")))
        last = QHBoxLayout()
        self.last_lbl = QLabel(relative_time(self.ctl.last_ok_ms()))
        A.set_tabular(self.last_lbl)
        last.addWidget(self.last_lbl)
        last.addStretch(1)
        self.sync_now_btn = make_button("지금 동기화")
        self.sync_now_btn.clicked.connect(self._sync_now)
        last.addWidget(self.sync_now_btn)
        holder = QWidget()
        holder.setLayout(last)
        last.setContentsMargins(0, 0, 0, 0)
        _row(form, "마지막 동기화", holder)
        # PC 이름은 Windows 컴퓨터 이름을 그대로 쓴다 (바꾸지 않는다, 9장 39)
        self.pc_name_lbl = QLabel(runner.default_pc_name())
        _row(form, "PC 이름", self.pc_name_lbl)
        self.outer.addLayout(form)
        self.outer.addWidget(self.status_lbl)
        self.reconnect_btn = make_button("다시 연결하기", "primary")
        self.reconnect_btn.clicked.connect(self._connect)
        self.reconnect_btn.hide()
        self.outer.addWidget(self.reconnect_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.outer.addSpacing(12)
        self.outer.addWidget(role_label("연결된 PC", "group"))
        self.devices_box = QVBoxLayout()
        self.devices_box.setSpacing(8)
        self.devices_box.addWidget(role_label("PC 목록을 읽는 중이에요", "hint"))
        self.outer.addLayout(self.devices_box)
        self.outer.addSpacing(12)
        off = make_button("연결 끊기")
        off.clicked.connect(self._disconnect)
        self.outer.addWidget(off, 0, Qt.AlignmentFlag.AlignLeft)
        self._refresh_status()
        self.ctl.run_job("devices")

    def _refresh_status(self) -> None:
        if not hasattr(self, "status_lbl"):
            return
        if self.ctl is not None and self.ctl.connected and hasattr(self, "last_lbl"):
            try:
                self.last_lbl.setText(relative_time(self.ctl.last_ok_ms()))
            except RuntimeError:  # 다시 그리는 중 지워진 라벨
                return
            self.sync_now_btn.setEnabled(not self.ctl.running)
            bad = self.ctl.status not in ("ok", "syncing")
            self._status(STATUS_TEXT.get(self.ctl.status, "") if bad else "", error=bad)
            self.reconnect_btn.setVisible(self.ctl.status == "reconnect")

    def _status(self, text: str, error: bool = False) -> None:
        try:
            self.status_lbl.setProperty("state", "error" if error else "")
            A.repolish(self.status_lbl)
            self.status_lbl.setText(text)
            self.status_lbl.setVisible(bool(text))
        except RuntimeError:
            pass

    def _fill_devices(self, devices: list[dict]) -> None:
        _clear(self.devices_box)
        for d in devices:
            row = QHBoxLayout()
            name = QLabel(d["name"] or "이름 없는 PC")
            row.addWidget(name)
            if d["is_self"]:
                row.addWidget(role_label("이 PC", "badge"))
            when = role_label(relative_time(d["last_sync"]), "hint")
            A.set_tabular(when)
            row.addWidget(when)
            row.addStretch(1)
            if not d["is_self"]:
                out = make_button("목록에서 빼기", "ghost")
                out.clicked.connect(lambda _c=False, dev=d: self._remove(dev))
                row.addWidget(out)
            self.devices_box.addLayout(row)
        if not devices:
            self.devices_box.addWidget(role_label("아직 연결된 PC가 없어요", "hint"))

    # ----- 동작 -----
    def _sync_now(self) -> None:
        self.sync_now_btn.setEnabled(False)
        self.ctl.sync_now()

    # ----- 연결 (연결 창을 첫 동기화가 끝날 때까지 열어 둔다, 9장 40) -----
    def _connect(self) -> None:
        from sync.login_dialog import LoginDialog

        client = oauth.load_client()
        if client is None:
            self._status(oauth.MESSAGES["no_client"], error=True)
            return
        dlg = LoginDialog(client, self, working=True)
        self._dlg, self._grant, self._connecting = dlg, None, False
        dlg.granted.connect(self._on_granted)
        dlg.cancel_requested.connect(self._cancel_connect)
        self.ctl.progress.connect(dlg.set_progress)
        dlg.exec()
        self.ctl.progress.disconnect(dlg.set_progress)
        self._dlg = None
        if dlg.result():
            self.render()
            self._status(f"{self._pending_email} 계정으로 연결됐어요.")
        elif dlg.error is not None:
            self._status(dlg.error.message, error=True)

    def _on_granted(self, g: oauth.Grant) -> None:
        """브라우저에서 허용했다. 1) Google 계정 확인 → 2) Drive 확인 → 3) 메모 맞추기."""
        previous = self.db.get_setting_str(oauth.ACCOUNT_EMAIL_KEY, "")
        if oauth.is_other_account(previous, g.email):
            ask = _Ask("다른 계정이에요",
                       f"전에 연결한 계정: {previous}\n지금 고른 계정: {g.email}\n\n"
                       "다른 계정으로 연결하면 다른 PC의 메모와 따로 보관돼요.",
                       "이 계정으로 연결", "취소", self._dlg)
            if not ask.exec():
                self._give_up(g)
                return
        self._grant = g
        self._dlg.set_stage("Drive를 확인하고 있어요")
        self.ctl.run_job("probe", g.access_token)

    def _after_probe(self, result: dict) -> None:
        g, self._grant = self._grant, None
        if g is None or self._dlg is None:
            return  # 그 사이 취소했다 (토큰은 _cancel_connect가 철회)
        if "error" in result:
            self._give_up(g, oauth.OAuthError("network" if result["error"] == "network" else "failed"))
            return
        mine = self.db.conn.execute(
            "SELECT COUNT(*) FROM memos WHERE title != '' OR content NOT IN ('', '<p></p>')").fetchone()[0]
        if result.get("others") and mine:
            ask = _Ask("합칠까요?",
                       f"Drive에 다른 PC의 메모가 있어요. 이 PC의 메모 {mine}개와 합칠게요. "
                       "다른 PC의 메모와 이 PC의 메모를 함께 보여 줘요. 합치기 전에 이 PC의 메모를 백업해 둘게요.",
                       "합치기", "나중에", self._dlg)
            if not ask.exec():
                self._give_up(g)  # 연결을 끝내지 않고 토큰도 남기지 않는다
                return
        self.db._backup_db(f".bak-sync-{datetime.now():%Y%m%d}")
        self._dlg.set_stage("메모를 맞추고 있어요")
        self._pending_email = g.email
        self._connecting = True
        self.ctl.run_job("connect", g.email, g.refresh_token)

    def _give_up(self, g: oauth.Grant, error: oauth.OAuthError | None = None) -> None:
        """연결하지 않기로 했다: 받은 토큰을 바로 철회하고 창을 닫는다."""
        self.ctl.run_job("revoke", g.refresh_token)
        if self._dlg is not None:
            self._dlg.fail(error)

    def _cancel_connect(self) -> None:
        """단계 중 [취소]. 아직 연결 전이면 토큰을 철회하고, 첫 동기화 중이면 끝난 뒤 연결을 끊는다."""
        if self._connecting:
            self._cancel_after_connect = True
            return
        g = self._grant or (self._dlg.grant if self._dlg is not None else None)
        self._grant = None
        if g is not None:
            self._give_up(g)

    def _remove(self, dev: dict) -> None:
        ask = _Ask("이 PC를 목록에서 뺄까요?",
                   f"{dev['name'] or '이름 없는 PC'}의 기록을 이 PC가 넘겨받은 뒤 Drive에서 지워요. "
                   "그 PC를 다시 켜면 새로 연결돼요.", "빼기", "취소", self)
        if ask.exec():
            self._status("목록에서 빼는 중이에요")
            self.ctl.run_job("remove", dev["device"])

    def _disconnect(self) -> None:
        ask = _Ask("동기화를 끊을까요?", "이 PC의 메모는 그대로 남아요. Drive에 올린 메모는 남겨 둬요.",
                   "끊기", "취소", self, check="Drive에 올린 메모도 지우기 (다른 PC도 더 이상 받을 수 없어요)")
        ask.check.toggled.connect(ask.set_danger)  # Drive 메모까지 지우면 되돌릴 수 없다
        if ask.exec():
            self._status("연결을 끊는 중이에요")
            self.ctl.run_job("disconnect", bool(ask.check.isChecked()))

    def _on_job(self, kind: str, result: dict) -> None:
        try:
            self.isVisible()
        except RuntimeError:  # 설정 창이 이미 닫혔다
            return
        if kind == "probe":
            self._after_probe(result)
        elif kind == "connect":
            self._connecting = False
            dlg = getattr(self, "_dlg", None)
            if getattr(self, "_cancel_after_connect", False):
                self._cancel_after_connect = False
                self.ctl.run_job("disconnect", False)  # 첫 동기화 중에 취소했다: 끊고 토큰도 철회
                if dlg is not None:
                    dlg.fail(None)
            elif "error" in result:
                if dlg is not None:
                    dlg.fail(None)
                self._status(STATUS_TEXT.get(result["error"], STATUS_TEXT["failed"]), error=True)
            elif dlg is not None:
                dlg.finish_ok()  # "연결됐어요"를 1초 보여 준 뒤 닫힌다
        elif kind == "devices" and hasattr(self, "devices_box"):
            if "error" in result:
                _clear(self.devices_box)
                self.devices_box.addWidget(role_label(STATUS_TEXT.get(result["error"], STATUS_TEXT["failed"]), "hint"))
            else:
                self._fill_devices(result["devices"])
        elif kind == "remove":
            if "error" in result or not result.get("removed"):
                self._status("그 PC의 기록을 아직 다 받지 못했어요. 잠시 뒤 다시 해 주세요.", error=True)
            else:
                self._status("목록에서 뺐어요.")
            self.ctl.run_job("devices")
        elif kind == "disconnect":
            if "error" in result:
                self._status(STATUS_TEXT.get(result["error"], STATUS_TEXT["failed"]), error=True)
                return
            self.render()
            if not result.get("revoked"):
                ask = _Ask("Google에 알리지 못했어요",
                           "Google에 연결을 끊었다고 알리지 못했어요. Google 계정 → 보안 → 타사 앱 연결에서 "
                           "직접 지울 수 있어요.", "열기", "닫기", self)
                if ask.exec():
                    QDesktopServices.openUrl(QUrl(GOOGLE_CONNECTIONS_URL))
