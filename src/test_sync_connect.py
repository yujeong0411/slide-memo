# ponytail: 동기화 탭의 연결 흐름 self-check — 브라우저 허용 뒤에도 연결 창이 첫 동기화가 끝날 때까지 열려 있고,
# 단계 문구와 진행(12/30)을 보여 주고, "연결됐어요" 뒤 닫히는지. 중간 취소. 가짜 Google·폴더 Drive·메모리 keyring.
# 임시 폴더만 쓴다. run: python src/test_sync_connect.py
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())

import keyring  # noqa: E402
import keyring.backend  # noqa: E402
import keyring.errors  # noqa: E402


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1
    store: dict = {}

    def get_password(self, s, u):
        return self.store.get((s, u))

    def set_password(self, s, u, p):
        self.store[(s, u)] = p

    def delete_password(self, s, u):
        if (s, u) not in self.store:
            raise keyring.errors.PasswordDeleteError("none")
        del self.store[(s, u)]


keyring.set_keyring(MemoryKeyring())  # 실제 Windows 자격 증명에 쓰지 않는다

import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from database import MemoDatabase  # noqa: E402
from sync import login_dialog, oauth, runner  # noqa: E402
from sync.engine import Syncer  # noqa: E402
from sync.local_folder import LocalFolderTransport  # noqa: E402
from sync.oauth import SCOPE_DRIVE, SCOPE_EMAIL  # noqa: E402
from sync.settings_tab import SyncTab  # noqa: E402
from sync.store import SyncStore  # noqa: E402
from theme.widgets import AppDialog  # noqa: E402

# ----- 가짜 Google 토큰 서버 -----
revoked: list = []


class Google(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        if self.path == "/revoke":
            revoked.append(form["token"])
            body = {}
        else:
            idt = "h." + base64.urlsafe_b64encode(json.dumps({"email": "me@example.com"}).encode()).rstrip(b"=").decode() + ".s"
            body = {"access_token": "AT", "refresh_token": f"RT-{len(revoked)}-{time.time()}", "expires_in": 3599,
                    "scope": f"openid {SCOPE_EMAIL} {SCOPE_DRIVE}", "id_token": idt}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):
        pass


server = HTTPServer(("127.0.0.1", 0), Google)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"
client = {"client_id": "x.apps.googleusercontent.com", "client_secret": "not-secret",
          "auth_uri": base + "/auth", "token_uri": base + "/token"}
oauth.REVOKE_URI = base + "/revoke"
oauth.load_client = lambda path=None: client
login_dialog.LoginFlow.open_browser = lambda self: True


def browser(flow):
    """사용자가 브라우저에서 허용 → redirect_uri로 돌아온다."""
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(flow.url).query).items()}
    urllib.request.urlopen(q["redirect_uri"] + "?" + urllib.parse.urlencode({"state": q["state"], "code": "c"}), timeout=5).read()


# ----- Drive 대신 폴더. 다른 PC가 메모와 그림을 먼저 올려 둔다 -----
drive = tmp / "drive"
runner._Worker._job_probe = lambda self, token: {"others": any(n.startswith("dev_") for n in LocalFolderTransport(drive).list())}
other_db = MemoDatabase(tmp / "other.db")
images_other = tmp / "other_images"
images_other.mkdir()
database.IMAGES_DIR = images_other
pics = []
for i in range(3):
    p = images_other / f"img_{i}.png"
    p.write_bytes(os.urandom(3000))
    pics.append(f'<img src="{p.as_posix()}" />')
for i in range(5):
    other_db.create(f"다른 PC 메모 {i}", f"<p>{i}</p>" + (pics[i] if i < 3 else ""))
other = SyncStore(other_db.conn)
other.connect("me@example.com")
Syncer(other, LocalFolderTransport(drive), "다른 PC").sync()
database.IMAGES_DIR = tmp / "images"

app = QApplication([])
db = MemoDatabase(tmp / "me.db")
db.create("이 PC 메모", "<p>내 메모</p>")
ctl = runner.SyncController(db, lambda store: LocalFolderTransport(drive), available=True)
tab = SyncTab(db, ctl)
tab.show()

# 단계 문구와 진행을 기록한다
seen: list[str] = []
real_stage, real_progress, real_finish = (login_dialog.LoginDialog.set_stage, login_dialog.LoginDialog.set_progress,
                                         login_dialog.LoginDialog.finish_ok)


def record_stage(self, text):
    seen.append(text)
    real_stage(self, text)


def record_progress(self, done, total):
    real_progress(self, done, total)
    seen.append(self.info.text())


finish_at = []


def record_finish(self):
    visible = self.isVisible()
    real_finish(self)
    finish_at.append((time.monotonic(), visible, self.cancel_button.isEnabled()))
    seen.append(self.info.text())


login_dialog.LoginDialog.set_stage = record_stage
login_dialog.LoginDialog.set_progress = record_progress
login_dialog.LoginDialog.finish_ok = record_finish


def press(head, button, delay=200):
    """확인 창(head)이 뜨면 그 단추를 누른다."""
    def go():
        for w in app.topLevelWidgets():
            if isinstance(w, AppDialog) and w.isVisible() and w.head_label.text() == head:
                next(b for b in w.findChildren(QPushButton) if b.text() == button).click()
                return
        QTimer.singleShot(100, go)
    QTimer.singleShot(delay, go)


# ----- 연결: 허용 → 계정 확인 → Drive 확인 → 합칠까요? → 메모 맞추기 (n/m) → 연결됐어요 → 닫힘 -----
QTimer.singleShot(300, lambda: threading.Thread(target=browser, args=(tab._dlg.flow,), daemon=True).start())
press("합칠까요?", "합치기", 600)
t0 = time.monotonic()
tab._connect()   # 연결 창이 닫힐 때까지 여기서 기다린다
closed_at = time.monotonic()
assert seen[0] == "Google 계정을 확인하고 있어요" and "Drive를 확인하고 있어요" in seen, seen
i = seen.index("메모를 맞추고 있어요")
counted = [t for t in seen[i:] if t.startswith("메모를 맞추고 있어요 (")]
assert counted and counted[-1].endswith(")"), seen
done, total = counted[-1].split("(")[1].rstrip(")").split("/")
assert int(done) == int(total) >= 6, f"이 PC 메모 1 + 받은 메모 5 + 그림 3 이상: {counted}"
assert seen[-1] == "연결됐어요" and finish_at and finish_at[0][1], "끝날 때까지 창이 열려 있다"
assert not finish_at[0][2], "끝난 뒤에는 취소할 수 없다"
assert 0.8 <= closed_at - finish_at[0][0] <= 3, "'연결됐어요'를 1초쯤 보여 준 뒤 닫는다"
assert ctl.connected and keyring.get_password(oauth.KEYRING_SERVICE, oauth.KEYRING_USER)
assert len(db.list_all()) == 6, "합쳐졌다"
labels = [w.text() for w in tab.findChildren(QLabel)]
assert "me@example.com" in labels and any("계정으로 연결됐어요" in t for t in labels), labels
print(f"  연결까지 {closed_at - t0:.1f}초, 단계: {' → '.join(dict.fromkeys(s.split(' (')[0] for s in seen))}")

# ----- 연결 끊기: 이 PC의 열쇠만 지우고 Google에 철회는 보내지 않는다 (다른 PC가 끊기지 않게, 9장 45) -----
revoked.clear()
ctl.run_job("disconnect", False)
for _ in range(50):
    app.processEvents()
    time.sleep(0.05)
tab.render()
assert not ctl.connected
assert revoked == [], "연결 끊기는 Google에 철회를 보내지 않는다"
assert keyring.get_password(oauth.KEYRING_SERVICE, oauth.KEYRING_USER) is None, "이 PC의 열쇠는 지운다"
assert any(n.startswith("dev_") for n in LocalFolderTransport(drive).list()), "Drive 메모는 남는다(체크 안 함)"

# ----- 단계 중 [취소]: Drive를 확인하는 동안 누르면 연결하지 않고, 받은 토큰은 저장하지 않고 버린다 -----
seen.clear()
slow_probe = runner._Worker._job_probe
runner._Worker._job_probe = lambda self, token: (time.sleep(1.0), slow_probe(self, token))[1]


def cancel_when_checking_drive():
    if "Drive를 확인하고 있어요" in seen and tab._dlg is not None:
        tab._dlg.cancel_button.click()
    else:
        QTimer.singleShot(50, cancel_when_checking_drive)


QTimer.singleShot(300, lambda: threading.Thread(target=browser, args=(tab._dlg.flow,), daemon=True).start())
QTimer.singleShot(400, cancel_when_checking_drive)
tab._connect()
for _ in range(60):
    app.processEvents()
    time.sleep(0.05)
assert not ctl.connected, "취소하면 연결하지 않는다"
assert revoked == [], "취소해도 철회는 보내지 않는다 (다른 PC가 끊긴다)"
assert keyring.get_password(oauth.KEYRING_SERVICE, oauth.KEYRING_USER) is None, "받은 토큰은 저장하지 않는다"
assert tab._grant is None, "메모리에서도 버린다"
assert "연결됐어요" not in seen

ctl.shutdown()
other_db.close()
server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("sync connect OK", flush=True)
# 앱처럼 정상 종료한다 (os._exit로 끊으면 Qt 객체가 남은 채 접근 오류가 기록된다, test_sync_runner.py와 같음)
app.quit()
from theme import apply as theme_apply  # noqa: E402

theme_apply.release_watchers()
sys.exit(0)
