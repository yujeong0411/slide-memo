"""동기화를 앱에 잇는다 (설계 5장 시점, 6장 화면, 7장 실패).

- 네트워크와 비교(reconcile)는 작업 줄(_Worker, QThread) 하나에서만 한다. 작업 줄은 자기 DB 연결을 쓴다.
- 화면 쪽(SyncController)은 시점만 정한다:
  고친 뒤 5초 조용하면(계속 고쳐도 30초에 한 번) 올리기, 1분마다 받기(창이 숨어 있으면 5분),
  펼칠 때 확인(10초 안에 했으면 건너뜀), "지금 동기화"나 올린 직후 12초 뒤 한 번 더(상대 변경이 몇 초 늦게 보인다).
- 고쳤는지는 DB의 data_version으로 안다 (다른 연결이 고치면 바뀐다). 화면 코드 곳곳에 신호를 끼우지 않는다.
"""
from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

PC_NAME_KEY = "sync_pc_name"
LAST_OK_KEY = "sync_last_ok"          # 마지막으로 성공한 동기화 (UTC ms, 이 PC 설정)
PUSH_QUIET_S = 5
PUSH_MAX_S = 30
PULL_S = 60
PULL_HIDDEN_S = 300
FOLLOW_UP_S = 12
EXPAND_GAP_S = 10
BACKOFF_MAX_S = 300
OFFLINE_WARN_S = 3600                 # 이보다 오래 연결이 안 될 때만 바에 경고를 띄운다

STATUS_TEXT = {
    "quota_full": "Google Drive 저장 공간이 가득 차서 동기화를 멈췄어요",
    "reconnect": "Google 연결이 끊어졌어요. 다시 연결해 주세요.",
    "network": "지금은 동기화할 수 없어요. 인터넷이 돌아오면 이어서 맞출게요.",
    "busy": "Google Drive가 잠시 바빠요. 조금 뒤에 이어서 맞출게요.",
    "failed": "동기화하지 못했어요. 조금 뒤에 다시 맞출게요.",
}


def default_pc_name() -> str:
    return os.environ.get("COMPUTERNAME", "").strip() or "이 PC"


def is_connected(conn) -> bool:
    try:
        row = conn.execute("SELECT value FROM sync_state WHERE key = 'connected'").fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == "1"


def drive_transport(store):
    """실제 Drive 전송. 갱신 열쇠는 keyring에서 읽는다."""
    from sync.drive import DriveError, DriveTransport, TokenSource
    from sync.oauth import load_client, load_refresh_token

    client, token = load_client(), load_refresh_token()
    if client is None or not token:
        raise DriveError("reconnect")
    return DriveTransport(TokenSource(client, token), own_device=store.device)


def _error_code(e: Exception) -> str:
    code = getattr(e, "code", "")
    if code in STATUS_TEXT:
        return code
    if code == "invalid_grant":
        return "reconnect"
    return "failed"


class _Worker(QObject):
    """작업 줄. daemon 스레드라 앱을 끌 때 네트워크를 기다리다 멈추지 않는다
    (QThread는 도는 중에 지워지면 앱이 비정상 종료된다). 끊겨도 DB 트랜잭션은 되돌려진다."""

    done = pyqtSignal(str, object)  # (일 종류, 결과 dict) — 화면 줄에서 받는다

    def __init__(self, db_path: Path, make_transport: Callable) -> None:
        super().__init__()
        self.db_path, self.make_transport = db_path, make_transport
        self.jobs: queue.Queue = queue.Queue()
        self._syncer = None
        self._thread = threading.Thread(target=self.run, name="sync", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, kind: str, *args) -> None:
        self.jobs.put((kind, args))

    def stop(self, timeout: float = 3.0) -> None:
        self.jobs.put(None)
        self._thread.join(timeout)

    def run(self) -> None:
        from database import MemoDatabase
        from sync.store import SyncStore

        self.db = MemoDatabase(self.db_path)
        self.store = SyncStore(self.db.conn)
        while True:
            job = self.jobs.get()
            if job is None:
                break
            kind, args = job
            try:
                result = getattr(self, f"_job_{kind}")(*args)
            except Exception as e:  # noqa: BLE001 — 상세는 화면에 보이지 않는다 (코드만)
                result = {"error": _error_code(e)}
                if result["error"] == "failed":
                    print(f"[sync] {kind} 실패: {type(e).__name__}")  # 원문(토큰·응답)은 남기지 않는다
            self.done.emit(kind, result)
        self.db.close()

    def _syncer_for(self):
        from sync.engine import Syncer

        if self._syncer is None or self._syncer.store.device != self._device:
            self._syncer = Syncer(self.store, self.make_transport(self.store))
        self._syncer.name = self.db.get_setting_str(PC_NAME_KEY, "") or default_pc_name()
        return self._syncer

    @property
    def _device(self):
        return self.store.device

    # ----- 일 -----
    def _job_cycle(self) -> dict:
        if not self.store.connected:
            return {"skipped": True}
        syncer = self._syncer_for()
        self.store.touched = set()
        self.store.reconcile()
        pushed = bool(self.store.pending())  # 이번에 올릴 것이 있었다 → 12초 뒤 한 번 더 확인
        conflicts = syncer.sync()
        too_big_local = self.store.get_json("too_big_local", [])
        return {
            "conflicts": conflicts,
            "touched": sorted(self.store.touched),
            "arrived": [str(p) for p in syncer.arrived],
            "notice": syncer.take_return_notice(),
            "too_big_remote": sorted(syncer.too_big_remote()),
            "too_big_local_paths": [str(self.store.image_path_for(sha)) for sha in too_big_local],
            "at": int(time.time() * 1000),
            "pending": len(self.store.pending()),
            "pushed": pushed,
        }

    def _job_devices(self) -> dict:
        return {"devices": self._syncer_for().devices()}

    def _job_remove(self, dev: str) -> dict:
        return {"removed": self._syncer_for().remove_device(dev), "device": dev}

    def _job_probe(self, access_token: str) -> dict:
        """연결하기 전에 Drive에 다른 PC의 메모가 있는지 본다 ('합칠까요?')."""
        from sync.drive import DriveTransport

        names = DriveTransport(lambda force: access_token).list()
        return {"others": any(n.startswith("dev_") for n in names)}

    def _job_revoke(self, refresh_token: str) -> dict:
        """연결하지 않기로 한 토큰(다른 계정 취소, 합치기 나중에)을 바로 철회한다."""
        from sync import oauth

        return {"revoked": oauth.revoke(refresh_token)}

    def _job_connect(self, email: str, refresh_token: str) -> dict:
        from sync import oauth

        oauth.save_refresh_token(refresh_token)
        self.store.connect(email)
        self.db.set_setting_str(oauth.ACCOUNT_EMAIL_KEY, email)
        self._syncer = None
        return self._job_cycle()

    def _job_disconnect(self, wipe: bool) -> dict:
        from sync import oauth

        token = oauth.load_refresh_token()
        if wipe:  # Drive의 메모도 지운다 (다른 PC도 더 이상 받을 수 없다)
            transport = self._syncer_for().transport
            for name in list(transport.list()):
                transport.delete(name)
        revoked = oauth.revoke(token) if token else True
        oauth.delete_refresh_token()
        self.store.disconnect(drive_wiped=wipe)
        self._syncer = None
        return {"revoked": revoked}


class SyncController(QObject):
    """화면 쪽. 시점을 정하고, 작업 줄 결과를 신호로 넘긴다."""

    about_to_sync = pyqtSignal()         # 동기화 직전 (창이 편집 중인 내용을 저장한다)
    cycle_finished = pyqtSignal(object)  # 결과 dict
    job_finished = pyqtSignal(str, object)
    status_changed = pyqtSignal()

    def __init__(self, db, make_transport: Callable | None = None, *, available: bool | None = None,
                 is_visible: Callable[[], bool] = lambda: True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from sync.oauth import load_client

        self.db = db
        self.available = (load_client() is not None) if available is None else available
        self.is_visible = is_visible
        self.status = "ok"
        self.running = False
        self._closed = False
        self._again = False
        self._started = time.monotonic()
        self._last_cycle = 0.0
        self._next_pull = time.monotonic() + 2  # 켠 직후 한 번
        self._follow_up: float | None = None
        self._dirty_since: float | None = None
        self._last_change = 0.0
        self._backoff = PULL_S
        self._monitor = sqlite3.connect(str(db.db_path), check_same_thread=False)
        self._data_version = self._dv()
        self.worker = _Worker(db.db_path, make_transport or drive_transport)
        self.worker.done.connect(self._on_done)
        self.worker.start()
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    # ----- 상태 -----
    @property
    def connected(self) -> bool:
        return self.available and is_connected(self.db.conn)

    def last_ok_ms(self) -> int:
        try:
            return int(self.db.get_setting_str(LAST_OK_KEY, "0") or 0)
        except ValueError:
            return 0

    def problem(self) -> tuple[str, str] | None:
        """바에 경고를 띄울 문제. 다시 연결·저장 공간 가득은 바로, 연결 안 됨은 1시간이 넘었을 때만."""
        if not self.connected or self.status in ("ok", "syncing"):
            return None
        if self.status in ("reconnect", "quota_full"):
            return self.status, STATUS_TEXT[self.status]
        since = self.last_ok_ms() / 1000 or (time.time() - (time.monotonic() - self._started))
        if time.time() - since >= OFFLINE_WARN_S:
            return self.status, STATUS_TEXT.get(self.status, STATUS_TEXT["failed"])
        return None

    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.status_changed.emit()

    # ----- 시점 -----
    def _dv(self) -> int:
        try:
            return self._monitor.execute("PRAGMA data_version").fetchone()[0]
        except sqlite3.Error:
            return 0

    def _on_tick(self) -> None:
        if not self.connected or self.status == "reconnect":
            return
        now = time.monotonic()
        dv = self._dv()
        if dv != self._data_version:  # 이 PC에서 무언가 고쳤다
            self._data_version = dv
            self._last_change = now
            self._dirty_since = self._dirty_since or now
        due = False
        if self._dirty_since and (now - self._last_change >= PUSH_QUIET_S or now - self._dirty_since >= PUSH_MAX_S):
            due = True
        if self._follow_up is not None and now >= self._follow_up:
            self._follow_up = None
            due = True
        interval = self._backoff if self.status != "ok" else (PULL_S if self.is_visible() else PULL_HIDDEN_S)
        if now >= max(self._next_pull, self._last_cycle + interval):
            due = True
        if due:
            self.request_cycle()

    def request_cycle(self, *, follow_up: bool = False) -> None:
        if not self.connected:
            return
        if follow_up:
            self._follow_up = time.monotonic() + FOLLOW_UP_S
        if self.running:
            self._again = True
            return
        self.about_to_sync.emit()  # 편집 중인 내용을 먼저 DB에 (그래야 비교에 잡힌다)
        self.running = True
        self._dirty_since = None
        self._last_cycle = time.monotonic()
        self._set_status("syncing" if self.status == "ok" else self.status)
        self.worker.submit("cycle")

    def sync_now(self) -> None:
        self.request_cycle(follow_up=True)

    def on_expand(self) -> None:
        if time.monotonic() - self._last_cycle >= EXPAND_GAP_S:
            self.request_cycle()

    def run_job(self, kind: str, *args) -> None:
        self.worker.submit(kind, *args)

    def _on_done(self, kind: str, result: dict) -> None:
        if self._closed:
            return  # 앱을 끄는 중: 화면 쪽 DB는 이미 닫혔다. 늦게 온 결과로 닫힌 DB를 건드리면 앱이 비정상 종료된다
        if kind == "cycle" or (kind == "connect" and "error" not in result):
            self.running = False
            self._data_version = self._dv()  # 작업 줄이 쓴 것은 이 PC의 수정이 아니다
            err = result.get("error")
            if err:
                self._backoff = min(BACKOFF_MAX_S, max(PULL_S, self._backoff * 2))
                self._set_status(err)
            elif not result.get("skipped"):
                self._backoff = PULL_S
                self.db.set_setting_str(LAST_OK_KEY, str(result["at"]))
                self._set_status("ok")
                if result.get("pending"):  # 다 못 올렸다 → 곧 다시
                    self._dirty_since = time.monotonic()
                if result.get("pushed") and self._follow_up is None:
                    self._follow_up = time.monotonic() + FOLLOW_UP_S
            self._next_pull = self._last_cycle + PULL_S
            self.cycle_finished.emit(result)
            self.status_changed.emit()
            if self._again:
                self._again = False
                QTimer.singleShot(0, self.request_cycle)
        if kind != "cycle":
            if kind == "disconnect" and "error" not in result:
                self._set_status("ok")
            self.job_finished.emit(kind, result)

    def shutdown(self) -> None:
        """앱을 끌 때. 연결돼 있고 못 올린 것이 있으면 최대 3초 동안 올려 본다 (못 하면 다음에 켤 때)."""
        self._tick.stop()
        if self.connected and not self.running and self._dv() != self._data_version:
            self.worker.submit("cycle")
        self._closed = True
        self.worker.stop(3.0)
        self._monitor.close()
