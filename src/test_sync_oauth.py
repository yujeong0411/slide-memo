# ponytail: Google 로그인 self-check — 가짜 토큰 서버로 PKCE·state·권한 빠짐·취소·시간 초과·갱신 만료·철회.
# 실제 Google·실제 keyring(Windows 자격 증명)을 쓰지 않는다. run: python src/test_sync_oauth.py
import base64
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import keyring  # noqa: E402
import keyring.backend  # noqa: E402
import keyring.errors  # noqa: E402


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1
    store: dict = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        if (service, user) not in self.store:
            raise keyring.errors.PasswordDeleteError("none")
        del self.store[(service, user)]


keyring.set_keyring(MemoryKeyring())  # 실제 Windows 자격 증명에 쓰지 않는다

from sync import oauth  # noqa: E402
from sync.oauth import SCOPE_DRIVE, SCOPE_EMAIL, LoginFlow, OAuthError  # noqa: E402


# ----- 가짜 Google 토큰 서버 -----
class Fake:
    codes: dict = {}        # code → (challenge, redirect_uri)
    scope = f"openid {SCOPE_EMAIL} {SCOPE_DRIVE}"
    issued: list = []
    revoked: set = set()
    email = "me@example.com"


class GoogleHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        if self.path == "/revoke":
            Fake.revoked.add(form.get("token"))
            return self._json(200, {})
        if form.get("grant_type") == "authorization_code":
            challenge, redirect = Fake.codes.pop(form.get("code"), (None, None))
            verifier = form.get("code_verifier", "")
            got = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if challenge is None or got != challenge or redirect != form.get("redirect_uri"):
                return self._json(400, {"error": "invalid_grant"})
            rt, at = f"RT-{os.urandom(4).hex()}", f"AT-{os.urandom(4).hex()}"
            Fake.issued.append(rt)
            idt = "h." + base64.urlsafe_b64encode(json.dumps({"email": Fake.email}).encode()).rstrip(b"=").decode() + ".s"
            return self._json(200, {"access_token": at, "refresh_token": rt, "expires_in": 3599,
                                    "scope": Fake.scope, "id_token": idt})
        if form.get("grant_type") == "refresh_token":
            if form.get("refresh_token") in Fake.revoked or form.get("refresh_token") not in Fake.issued:
                return self._json(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            return self._json(200, {"access_token": "AT-new", "expires_in": 3599})
        return self._json(400, {"error": "unsupported"})

    def _json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):
        pass


google = HTTPServer(("127.0.0.1", 0), GoogleHandler)
threading.Thread(target=google.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{google.server_address[1]}"
client = {"client_id": "test.apps.googleusercontent.com", "client_secret": "not-secret",
          "auth_uri": base + "/auth", "token_uri": base + "/token"}
oauth.REVOKE_URI = base + "/revoke"


def params(flow):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(flow.url).query).items()}


def browser(flow, *, state=None, error=None, scope=None):
    """사용자가 Google 화면에서 허용(또는 취소)하면 브라우저가 redirect_uri로 돌아온다."""
    p = params(flow)
    q = {"state": state or p["state"]}
    if error:
        q["error"] = error
    else:
        code = os.urandom(6).hex()
        Fake.codes[code] = (p["code_challenge"], p["redirect_uri"])
        q["code"] = code
        q["scope"] = scope or Fake.scope
    try:
        with urllib.request.urlopen(p["redirect_uri"] + "?" + urllib.parse.urlencode(q), timeout=5) as r:
            return r.status, r.headers.get("Server", ""), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Server", ""), e.read().decode()


def run(flow, act):
    out = {}

    def wait():
        try:
            out["grant"] = flow.wait()
        except OAuthError as e:
            out["error"] = e
    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.1)
    act()
    t.join(10)
    assert not t.is_alive(), "기다림이 끝나지 않음"
    return out


def port_closed(flow):
    try:
        urllib.request.urlopen(flow.redirect_uri, timeout=1)
        return False
    except (urllib.error.URLError, ConnectionError, OSError):
        return True


# ----- 로그인 주소: PKCE(S256), state, 필요한 권한, 127.0.0.1 -----
flow = LoginFlow(client)
p = params(flow)
assert flow.server.server_address[0] == "127.0.0.1", "창구는 127.0.0.1에만"
assert p["redirect_uri"].startswith("http://127.0.0.1:") and p["code_challenge_method"] == "S256"
assert set(p["scope"].split()) == {"openid", SCOPE_EMAIL, SCOPE_DRIVE}
assert p["access_type"] == "offline" and len(p["state"]) >= 32 and len(flow.verifier) >= 43
assert "client_secret" not in flow.url, "비밀값은 주소에 넣지 않는다"

# 성공. 엉뚱한 state로 온 요청은 무시하고 계속 기다린다
answers = []
out = run(flow, lambda: (answers.append(browser(flow, state="wrong")), answers.append(browser(flow))))
g = out["grant"]
assert answers[0][0] == 400 and answers[1][0] == 200 and "연결됐어요" in answers[1][2]
assert answers[1][1] == "SlideMemo", f"응답 헤더에 서버 버전이 보임: {answers[1][1]}"
assert g.email == "me@example.com" and g.refresh_token in Fake.issued and SCOPE_DRIVE in g.scopes
assert port_closed(flow), "끝나면 창구를 닫는다"

# PKCE: 코드를 가로채도 verifier 없이는 바꿀 수 없다
code = "stolen"
Fake.codes[code] = (params(flow)["code_challenge"], flow.redirect_uri)
try:
    oauth._post(client["token_uri"], {"code": code, "client_id": "x", "client_secret": "x",
                                      "redirect_uri": flow.redirect_uri, "grant_type": "authorization_code",
                                      "code_verifier": "guess"})
    raise AssertionError("verifier 없이 바뀜")
except OAuthError:
    pass

# Google 화면에서 취소
flow = LoginFlow(client)
out = run(flow, lambda: browser(flow, error="access_denied"))
assert out["error"].code == "cancelled" and "취소" in out["error"].message and port_closed(flow)

# 권한을 빼고 허용 → 연결하지 않고, 받은 토큰은 바로 철회
for partial in (f"openid {SCOPE_EMAIL}", f"openid {SCOPE_DRIVE}"):
    Fake.scope = partial
    flow = LoginFlow(client)
    out = run(flow, lambda: browser(flow))
    assert out["error"].code == "scope_missing", out
    assert Fake.issued[-1] not in Fake.revoked, "철회는 보내지 않는다 (계정 권한 전체가 거둬져 다른 PC가 끊긴다)"
    assert "Drive 앱 공간 권한" in out["error"].message
Fake.scope = f"openid {SCOPE_EMAIL} {SCOPE_DRIVE}"

# 앱에서 취소, 5분(시험은 1초) 동안 응답 없음
flow = LoginFlow(client)
out = run(flow, flow.cancel)
assert out["error"].code == "cancelled" and port_closed(flow)
flow = LoginFlow(client, timeout=1)
t0 = time.monotonic()
out = run(flow, lambda: None)
assert out["error"].code == "timeout" and time.monotonic() - t0 < 5 and port_closed(flow)
assert "5분" in out["error"].message

# 갱신: 정상 → access token, 철회·만료 → '다시 연결해 주세요'
access, exp = oauth.refresh_access(client, g.refresh_token)
assert access == "AT-new" and exp > time.time()
assert oauth.revoke(g.refresh_token) and g.refresh_token in Fake.revoked
try:
    oauth.refresh_access(client, g.refresh_token)
    raise AssertionError("철회된 토큰으로 갱신됨")
except OAuthError as e:
    assert e.code == "invalid_grant" and e.message == "Google 연결이 끊어졌어요. 다시 연결해 주세요."
    assert g.refresh_token not in str(e) and "expired" not in str(e), "메시지에 토큰·서버 응답이 섞이면 안 된다"

# 인터넷이 안 되면 철회는 False (연결 끊기는 keyring만 지우고 직접 지우는 방법을 안내)
assert oauth.revoke("x", "http://127.0.0.1:9/revoke") is False
try:
    oauth.refresh_access({**client, "token_uri": "http://127.0.0.1:9/token"}, "x")
    raise AssertionError
except OAuthError as e:
    assert e.code == "network"

# keyring 보관·삭제 (가짜 keyring)
oauth.save_refresh_token("RT-keep")
assert oauth.load_refresh_token() == "RT-keep"
oauth.delete_refresh_token()
oauth.delete_refresh_token()  # 두 번 지워도 괜찮다
assert oauth.load_refresh_token() is None

# 다른 계정 확인
assert oauth.is_other_account("a@gmail.com", "b@gmail.com")
assert not oauth.is_other_account("A@gmail.com", "a@gmail.com ") and not oauth.is_other_account("", "a@gmail.com")

# 클라이언트 JSON이 없으면 None ('이 빌드에서는 동기화를 쓸 수 없어요')
from pathlib import Path  # noqa: E402

assert oauth.load_client(Path("없는 파일.json")) is None
assert oauth.MESSAGES["no_client"] == "이 빌드에서는 동기화를 쓸 수 없어요"

# ----- 기다리는 창: 브라우저가 안 열리면 주소 복사, [취소] -----
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sync import login_dialog  # noqa: E402

app = QApplication([])
login_dialog.LoginFlow.open_browser = lambda self: False
dlg = login_dialog.LoginDialog(client)
QTimer.singleShot(300, lambda: (
    dlg.url_box.isVisible() or print("주소 칸이 안 보임"),
    dlg.copy_button.click(),
    threading.Thread(target=lambda: browser(dlg.flow), daemon=True).start(),
))
assert dlg.exec() == 1 and dlg.grant is not None and dlg.grant.email == "me@example.com"
assert QApplication.clipboard().text() == dlg.flow.url, "주소 복사"
assert "복사했어요" == dlg.copy_button.text()
dlg = login_dialog.LoginDialog(client)
QTimer.singleShot(300, dlg.cancel_button.click)
assert dlg.exec() == 0 and dlg.error is not None and dlg.error.code == "cancelled" and port_closed(dlg.flow)

google.shutdown()
print("sync oauth OK", flush=True)
os._exit(0)
