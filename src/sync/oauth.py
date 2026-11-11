"""Google 로그인 (설계 0장, 6.1, 7장). 데스크톱 방식: 브라우저 + loopback(127.0.0.1) + PKCE(S256) + state.

- 클라이언트 ID·비밀값은 설치본에 들어간다는 전제로 다룬다. 보호는 PKCE가 맡는다.
- refresh token은 keyring(memo_slide_sync)에만 둔다. access token은 메모리에만.
- 토큰·인증 코드는 로그·예외 메시지·브라우저 응답 어디에도 넣지 않는다.
- HTTP는 표준 라이브러리(urllib)만 쓴다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring
import keyring.errors

SCOPE_DRIVE = "https://www.googleapis.com/auth/drive.appdata"
SCOPE_EMAIL = "https://www.googleapis.com/auth/userinfo.email"
SCOPES = ("openid", SCOPE_EMAIL, SCOPE_DRIVE)
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
KEYRING_SERVICE = "memo_slide_sync"
KEYRING_USER = "refresh_token"
LOGIN_TIMEOUT_S = 300
HTTP_TIMEOUT_S = 30
ACCOUNT_EMAIL_KEY = "sync_account_email"  # 이 PC 설정에만. 화면 표시와 '다른 계정이에요' 비교에만 쓴다

# 사용자에게 보이는 문구 (해요체). 상세 원인은 보여 주지 않는다.
MESSAGES = {
    "cancelled": "Google 화면에서 연결을 취소했어요.",
    "scope_missing": "Drive 앱 공간 권한을 허용해야 동기화할 수 있어요. 다시 연결하고 모든 항목을 허용해 주세요.",
    "timeout": "5분 동안 응답이 없어 연결을 멈췄어요. 다시 시도해 주세요.",
    "invalid_grant": "Google 연결이 끊어졌어요. 다시 연결해 주세요.",
    "network": "인터넷에 연결할 수 없어요. 연결을 확인한 뒤 다시 시도해 주세요.",
    "no_client": "이 빌드에서는 동기화를 쓸 수 없어요",
    "failed": "연결하지 못했어요. 다시 시도해 주세요.",
}


class OAuthError(Exception):
    """code는 MESSAGES의 키. 메시지에는 토큰이나 서버 응답 원문을 넣지 않는다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["failed"])


@dataclass
class Grant:
    refresh_token: str
    access_token: str
    expires_at: float
    email: str
    scopes: frozenset[str]


# ----- 클라이언트 JSON (설계 10장) -----
def client_path() -> Path:
    """설치본: 실행 파일 안의 secrets/, 개발 실행: 저장소의 secrets/ (커밋하지 않는다)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "secrets" / "google_oauth_client.json"


def load_client(path: Path | None = None) -> dict | None:
    """데스크톱 앱(installed) 클라이언트. 없거나 모양이 틀리면 None ('이 빌드에서는 동기화를 쓸 수 없어요')."""
    try:
        data = json.loads((path or client_path()).read_text(encoding="utf-8"))
        c = data["installed"]
        if not (c["client_id"] and c["client_secret"] and c["auth_uri"] and c["token_uri"]):
            return None
        return c
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ----- HTTP -----
def _post(url: str, fields: dict) -> dict:
    """폼 POST → JSON. 실패하면 OAuthError (원인 코드만)."""
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error")
        except ValueError:
            err = None
        raise OAuthError("invalid_grant" if err == "invalid_grant" else "failed") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OAuthError("network") from None


def _email_from_id_token(id_token: str) -> str:
    """토큰 응답(TLS로 Google에서 바로 받음)의 id_token에서 email만 꺼낸다. 서명은 검증하지 않는다(설계 6.4)."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("email", ""))
    except (IndexError, ValueError):
        return ""


# ----- 로그인 한 번 -----
_PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>SlideMemo</title>
<body style="font-family:sans-serif;max-width:32em;margin:4em auto;line-height:1.6">
<h2>{title}</h2><p>{body}</p></body></html>"""


class LoginFlow:
    """브라우저 로그인 한 번. 127.0.0.1의 임의 포트에만 창구를 연다(0.0.0.0이면 방화벽 창이 뜬다).
    wait()는 결과가 오거나, 시간이 지나거나, cancel()될 때까지 기다린다. 어느 경우든 창구를 닫는다."""

    def __init__(self, client: dict, timeout: float = LOGIN_TIMEOUT_S) -> None:
        self.client, self.timeout = client, timeout
        self.verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        self.state = secrets.token_urlsafe(32)
        self._result: dict | None = None
        self._done = threading.Event()
        flow = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if q.get("state", [""])[0] != flow.state:
                    self._page(400, "연결하지 못했어요", "이 창은 닫아도 돼요.")
                    return  # 다른 곳에서 온 요청은 무시하고 계속 기다린다
                if "code" in q:
                    flow._result = {"code": q["code"][0], "scope": q.get("scope", [""])[0]}
                    self._page(200, "연결됐어요", "SlideMemo로 돌아가세요. 이 창은 닫아도 돼요.")
                else:
                    flow._result = {"error": q.get("error", ["failed"])[0]}
                    self._page(200, "연결하지 않았어요", "SlideMemo로 돌아가 다시 시도할 수 있어요. 이 창은 닫아도 돼요.")
                flow._done.set()

            def _page(self, status, title, body):
                data = _PAGE.format(title=title, body=body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_a):  # 주소(인증 코드 포함)를 콘솔에 남기지 않는다
                pass

            def version_string(self):  # 응답 헤더에 서버·파이썬 버전을 넣지 않는다
                return "SlideMemo"

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.2
        self.redirect_uri = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.url = client["auth_uri"] + "?" + urllib.parse.urlencode({
            "client_id": client["client_id"],
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": self.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",  # 다시 연결할 때도 refresh token을 받는다
        })

    def open_browser(self) -> bool:
        """기본 브라우저를 연다. 실패하면 False — 화면에 주소와 [주소 복사]를 보여 준다."""
        try:
            return bool(webbrowser.open(self.url))
        except Exception:  # noqa: BLE001 — 브라우저 실행 실패는 어떤 종류든 '주소 복사'로 넘어간다
            return False

    def cancel(self) -> None:
        if self._result is None:
            self._result = {"error": "app_cancelled"}
        self._done.set()

    def wait(self) -> Grant:
        deadline = time.monotonic() + self.timeout
        try:
            while not self._done.is_set():
                if time.monotonic() > deadline:
                    raise OAuthError("timeout")
                self.server.handle_request()
        finally:
            self.server.server_close()
        result = self._result or {}
        if "error" in result:
            raise OAuthError("cancelled" if result["error"] in ("access_denied", "app_cancelled") else "failed")
        return self._exchange(result["code"])

    def _exchange(self, code: str) -> Grant:
        c = self.client
        tok = _post(c["token_uri"], {
            "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code", "code_verifier": self.verifier,
        })
        refresh, access = tok.get("refresh_token"), tok.get("access_token")
        if not refresh or not access:
            raise OAuthError("failed")
        granted = frozenset(str(tok.get("scope", "")).split())
        if SCOPE_DRIVE not in granted or SCOPE_EMAIL not in granted:
            revoke(refresh)  # 일부만 허용된 권한은 남겨 두지 않는다
            raise OAuthError("scope_missing")
        return Grant(refresh, access, time.time() + float(tok.get("expires_in", 3600)),
                     _email_from_id_token(tok.get("id_token", "")), granted)


# ----- 갱신·철회·보관 -----
def refresh_access(client: dict, refresh_token: str) -> tuple[str, float]:
    """(access token, 만료 시각). 만료·철회면 OAuthError('invalid_grant') → '다시 연결해 주세요'."""
    tok = _post(client["token_uri"], {
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    if not tok.get("access_token"):
        raise OAuthError("failed")
    return tok["access_token"], time.time() + float(tok.get("expires_in", 3600))


def revoke(token: str, uri: str | None = None) -> bool:
    """Google에 철회를 보낸다. 이미 무효인 토큰도 성공으로 본다. 인터넷이 안 되면 False."""
    try:
        _post(uri or REVOKE_URI, {"token": token})
        return True
    except OAuthError as e:
        return e.code != "network"


def save_refresh_token(token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)


def load_refresh_token() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.KeyringError:
        return None


def delete_refresh_token() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass


def is_other_account(previous_email: str, email: str) -> bool:
    """이 PC가 전에 다른 계정으로 연결했었는가 ('다른 계정이에요' 확인, 설계 6.1)."""
    return bool(previous_email) and previous_email.strip().lower() != email.strip().lower()
