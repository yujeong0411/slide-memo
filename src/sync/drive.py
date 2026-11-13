"""Google Drive appDataFolder 전송 (설계 8장). LocalFolderTransport와 같은 다섯 가지를 갖춘다.
  list() → {이름: 버전}, read(name), write(name, data), write_large(name, data), delete(name)

- 바뀐 것만 알아낸다: changes.list(spaces=appDataFolder). 시작 표시가 무효가 되면 전체 목록을 다시 읽는다.
- 다시 시도: 429·5xx·403(요청 한도)는 기다리는 시간을 늘리고 흔들어서(지터) 다시. 401은 토큰을 새로
  받아 한 번만 다시. 403 저장 공간 가득(storageQuotaExceeded)과 권한 오류는 다시 시도하지 않는다.
- 5MB 넘는 그림은 이어 올리기(resumable). 도중에 꺼지면 Drive는 파일을 만들지 않으므로 처음부터 다시 올린다.
- 이름이 같은 파일이 둘 생기면(만들기 응답을 못 받고 다시 만든 경우 등) 가장 최근 것을 쓴다.
  그림과 이 PC 파일의 중복은 지운다.
- 표준 라이브러리(urllib)만 쓴다. 오류 메시지에 토큰·응답 원문을 넣지 않는다.
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FILE_FIELDS = "id,name,version,modifiedTime"
CHUNK = 8 * 256 * 1024          # 이어 올리기 조각 (256KiB의 배수여야 한다)
MAX_TRIES = 6
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 32.0
HTTP_TIMEOUT_S = 60
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}

MESSAGES = {
    "quota_full": "Google Drive 저장 공간이 가득 차서 동기화를 멈췄어요",
    "reconnect": "Google 연결이 끊어졌어요. 다시 연결해 주세요.",
    "network": "지금은 동기화할 수 없어요. 인터넷이 돌아오면 이어서 맞출게요.",
    "busy": "Google Drive가 잠시 바빠요. 조금 뒤에 이어서 맞출게요.",
    "failed": "동기화하지 못했어요. 조금 뒤에 다시 맞출게요.",
}


class DriveError(Exception):
    """code는 MESSAGES의 키. 동기화만 멈추고 메모는 평소처럼 쓴다 (쌓인 op는 다음 동기화에서 올라간다)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["failed"])


def _reasons(body: bytes) -> set[str]:
    try:
        err = json.loads(body or b"{}").get("error", {})
        out = {e.get("reason", "") for e in err.get("errors", []) if isinstance(e, dict)}
        if err.get("status"):
            out.add(str(err["status"]))
        return out
    except (ValueError, AttributeError):
        return set()


class DriveTransport:
    def __init__(self, token: Callable[[bool], str], *, api: str = API, upload: str = UPLOAD,
                 sleep: Callable[[float], None] = time.sleep, own_device: str | None = None) -> None:
        """token(force) → access token. force=True면 갱신해서 준다 (OAuthError는 'reconnect'로 바꾼다)."""
        self._token, self.api, self.upload, self.sleep = token, api, upload, sleep
        self.own_device = own_device
        self._files: dict[str, dict] | None = None   # id → {"name", "version", "modifiedTime"}
        self._page_token: str | None = None
        self.full_relists = 0

    # ----- HTTP -----
    def _access(self, force: bool) -> str:
        try:
            return self._token(force)
        except Exception as e:  # noqa: BLE001 — 갱신 실패(만료·철회 등)는 '다시 연결해 주세요'
            code = getattr(e, "code", "")
            raise DriveError("network" if code == "network" else "reconnect") from None

    def _request(self, method: str, url: str, body: bytes | None = None, headers: dict | None = None,
                 *, ok: tuple[int, ...] = (200,), raw: bool = False, tries: int = MAX_TRIES):
        """(상태, 응답 헤더, 본문). 다시 시도 규칙은 모듈 설명대로."""
        refreshed = False
        for attempt in range(tries):
            h = {"Authorization": f"Bearer {self._access(False)}", **(headers or {})}
            req = urllib.request.Request(url, data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                    data = r.read()
                    status, resp_headers = r.status, r.headers
            except urllib.error.HTTPError as e:
                status, resp_headers, data = e.code, e.headers, e.read()
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                raise DriveError("network") from None
            if status in ok:
                return status, resp_headers, (data if raw else (json.loads(data) if data else {}))
            reasons = _reasons(data)
            if status == 401 and not refreshed:
                refreshed = True
                self._access(True)  # 토큰을 새로 받아 한 번만 다시
                continue
            if status == 401:
                raise DriveError("reconnect")
            if status == 403 and "storageQuotaExceeded" in reasons:
                raise DriveError("quota_full")
            if "/changes?" in url and status in (400, 404, 410):
                raise _BadPageToken()
            if status in (404, 410):
                raise FileNotFoundError(url.split("?")[0].rsplit("/", 1)[-1])
            if status == 429 or status >= 500 or (status == 403 and reasons & _RATE_REASONS):
                if attempt == tries - 1:
                    raise DriveError("busy")
                wait = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** attempt)
                try:
                    wait = max(wait, float(resp_headers.get("Retry-After", 0)))
                except (TypeError, ValueError):
                    pass
                self.sleep(wait * random.uniform(0.5, 1.5))  # 지터: 여러 PC가 같은 순간에 몰리지 않게
                continue
            if status == 403:
                raise DriveError("reconnect")  # 권한 오류: 다시 시도하지 않는다
            raise DriveError("failed")
        raise DriveError("busy")

    # ----- 목록 -----
    def _full_list(self) -> None:
        """시작 표시를 먼저 받고 전체 목록을 읽는다 (그 사이 바뀐 것도 다음 changes에 잡힌다)."""
        _, _, start = self._request("GET", f"{self.api}/changes/startPageToken")
        files: dict[str, dict] = {}
        token = None
        while True:
            q = {"spaces": "appDataFolder", "pageSize": 1000, "fields": f"nextPageToken,files({FILE_FIELDS})"}
            if token:
                q["pageToken"] = token
            _, _, page = self._request("GET", f"{self.api}/files?{urllib.parse.urlencode(q)}")
            for f in page.get("files", []):
                files[f["id"]] = f
            token = page.get("nextPageToken")
            if not token:
                break
        self._files, self._page_token = files, start["startPageToken"]
        self.full_relists += 1

    def _changes(self) -> None:
        token = self._page_token
        while token:
            q = {"pageToken": token, "spaces": "appDataFolder", "pageSize": 1000,
                 "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS},trashed))"}
            _, _, page = self._request("GET", f"{self.api}/changes?{urllib.parse.urlencode(q)}")
            for c in page.get("changes", []):
                f = c.get("file")
                if c.get("removed") or not f or f.get("trashed"):
                    self._files.pop(c.get("fileId"), None)
                else:
                    self._files[f["id"]] = f
            if page.get("newStartPageToken"):
                self._page_token = page["newStartPageToken"]
                return
            token = page.get("nextPageToken")

    def list(self) -> dict[str, str]:
        if self._files is None:
            self._full_list()
        else:
            try:
                self._changes()
            except _BadPageToken:
                self._full_list()  # 시작 표시가 무효(오래됨 등): 전체 목록으로 다시 맞춘다
        self._dedupe()
        return {f["name"]: str(f.get("version", "")) for f in self._by_name().values()}

    def _by_name(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for f in sorted(self._files.values(), key=lambda f: (f.get("modifiedTime", ""), f["id"])):
            out[f["name"]] = f  # 같은 이름이면 가장 최근 것
        return out

    def _dedupe(self) -> None:
        """이름이 같은 파일 중 최근 것만 남긴다. 그림(내용이 같다)과 이 PC 파일만 지운다."""
        newest = {f["id"] for f in self._by_name().values()}
        for fid, f in list(self._files.items()):
            if fid in newest:
                continue
            name = f["name"]
            mine = self.own_device and f"_{self.own_device}" in name
            if name.startswith("img_") or mine:
                try:
                    self._request("DELETE", f"{self.api}/files/{fid}", ok=(200, 204))
                except FileNotFoundError:
                    pass
                self._files.pop(fid, None)

    def _id(self, name: str) -> str | None:
        if self._files is None:
            self.list()
        f = self._by_name().get(name)
        return f["id"] if f else None

    # ----- 읽기·쓰기 -----
    def read(self, name: str) -> bytes:
        fid = self._id(name)
        if fid is None:
            raise FileNotFoundError(name)
        _, _, data = self._request("GET", f"{self.api}/files/{fid}?alt=media", raw=True)
        return data

    def _remember(self, f: dict) -> None:
        self._files[f["id"]] = f

    def write(self, name: str, data: bytes) -> None:
        fid = self._id(name)
        if fid:
            _, _, f = self._request("PATCH", f"{self.upload}/files/{fid}?uploadType=media&fields={FILE_FIELDS}",
                                    data, {"Content-Type": "application/octet-stream"})
        else:
            boundary = "slidememo" + os.urandom(8).hex()
            meta = json.dumps({"name": name, "parents": ["appDataFolder"]})
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                    f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + data \
                + f"\r\n--{boundary}--\r\n".encode()
            _, _, f = self._request("POST", f"{self.upload}/files?uploadType=multipart&fields={FILE_FIELDS}",
                                    body, {"Content-Type": f"multipart/related; boundary={boundary}"})
        self._remember(f)

    def write_large(self, name: str, data: bytes) -> None:
        """이어 올리기. 조각마다 다시 시도하고, 끊기면 Drive에 받은 곳을 물어 그 뒤부터 잇는다.
        세션이 사라지면(404·410) 처음부터. 앱이 꺼지면 Drive는 파일을 만들지 않는다."""
        fid = self._id(name)
        meta = json.dumps({} if fid else {"name": name, "parents": ["appDataFolder"]}).encode()
        url = f"{self.upload}/files/{fid}?uploadType=resumable" if fid else f"{self.upload}/files?uploadType=resumable"
        _, h, _ = self._request("PATCH" if fid else "POST", url + f"&fields={FILE_FIELDS}", meta,
                                {"Content-Type": "application/json; charset=UTF-8",
                                 "X-Upload-Content-Length": str(len(data))})
        session = h["Location"]
        total, offset, fails = len(data), 0, 0
        while True:
            chunk = data[offset:offset + CHUNK]
            rng = f"bytes {offset}-{offset + len(chunk) - 1}/{total}"
            try:
                status, h, f = self._request("PUT", session, chunk, {"Content-Range": rng}, ok=(200, 201, 308), tries=1)
            except FileNotFoundError:
                return self.write_large(name, data)  # 세션이 사라졌다: 처음부터
            except DriveError as e:
                if e.code != "busy" or fails >= MAX_TRIES - 1:
                    raise
                fails += 1  # 조각이 끊겼다: 기다렸다가 Drive가 어디까지 받았는지 묻고 그 뒤부터
                self.sleep(min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** fails) * random.uniform(0.5, 1.5))
                status, h, f = self._request("PUT", session, b"", {"Content-Range": f"bytes */{total}"},
                                             ok=(200, 201, 308))
            if status in (200, 201):
                self._remember(f)
                return
            got = h.get("Range")  # 308: 받은 곳까지 ("bytes=0-N"), 없으면 아직 0바이트
            offset = int(got.rsplit("-", 1)[1]) + 1 if got else 0

    def delete(self, name: str) -> None:
        fid = self._id(name)
        if fid is None:
            return
        try:
            self._request("DELETE", f"{self.api}/files/{fid}", ok=(200, 204))
        except FileNotFoundError:
            pass
        self._files.pop(fid, None)


class _BadPageToken(Exception):
    pass


class TokenSource:
    """refresh token으로 access token을 받아 두고 만료 전에 갱신한다. token(force=True)는 바로 갱신."""

    def __init__(self, client: dict, refresh_token: str) -> None:
        self.client, self.refresh_token = client, refresh_token
        self._access, self._expires = "", 0.0

    def __call__(self, force: bool = False) -> str:
        from sync.oauth import refresh_access

        if force or not self._access or time.time() > self._expires - 60:
            self._access, self._expires = refresh_access(self.client, self.refresh_token)
        return self._access
