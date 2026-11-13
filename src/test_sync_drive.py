# ponytail: DriveTransport self-check — 가짜 Drive 서버로 두 PC 동기화, 다시 시도 규칙(429·5xx·401·403),
# 저장 공간 가득, 이어 올리기(도중 꺼짐·조각 실패), 시작 표시 무효, 이름 중복. 실제 Google 없음.
# 임시 폴더만 쓴다. run: python src/test_sync_drive.py
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import MemoDatabase  # noqa: E402
from sync import drive as D  # noqa: E402
from sync import images  # noqa: E402
from sync.drive import DriveError, DriveTransport  # noqa: E402
from sync.engine import Syncer  # noqa: E402
from sync.store import SyncStore  # noqa: E402


# ===== 가짜 Drive =====
class Drive:
    lock = threading.Lock()
    files: dict = {}          # id → {"name", "data", "version", "modifiedTime"}
    changes: list = []        # (fileId, removed)
    min_token = 0
    sessions: dict = {}
    tokens = {"good"}
    quota_full = False
    faults: list = []         # [method, 경로 일부, 상태, 이유, 남은 횟수]
    requests: list = []
    page_size = 2             # 목록 페이지 나누기를 시험하려고 작게
    clock = 0

    @classmethod
    def tick(cls):
        cls.clock += 1
        return f"2026-11-11T00:00:{cls.clock:06d}Z"

    @classmethod
    def meta(cls, fid):
        f = cls.files[fid]
        return {"id": fid, "name": f["name"], "version": str(f["version"]), "modifiedTime": f["modifiedTime"]}

    @classmethod
    def put(cls, fid, name, data):
        old = cls.files.get(fid)
        cls.files[fid] = {"name": name, "data": data, "version": (old["version"] + 1) if old else 1,
                          "modifiedTime": cls.tick()}
        cls.changes.append((fid, False))
        return cls.meta(fid)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, obj=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, reason):
        self._send(status, {"error": {"code": status, "message": "x", "errors": [{"reason": reason}]}})

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _handle(self, method):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        body = self._body()
        with Drive.lock:
            Drive.requests.append((method, url.path))
            if self.headers.get("Authorization") not in {f"Bearer {t}" for t in Drive.tokens}:
                return self._error(401, "authError")
            for rule in Drive.faults:
                if rule[4] > 0 and rule[0] == method and rule[1] in self.path:
                    rule[4] -= 1
                    return self._error(rule[2], rule[3])
            path = url.path
            if path == "/drive/v3/changes/startPageToken":
                return self._send(200, {"startPageToken": str(len(Drive.changes))})
            if path == "/drive/v3/changes":
                start = int(q["pageToken"])
                if start < Drive.min_token:
                    return self._error(400, "invalid")
                part = Drive.changes[start:start + Drive.page_size]
                out = {"changes": []}
                for fid, removed in part:
                    c = {"fileId": fid, "removed": removed or fid not in Drive.files}
                    if not c["removed"]:
                        c["file"] = Drive.meta(fid)
                    out["changes"].append(c)
                end = start + len(part)
                if end < len(Drive.changes):
                    out["nextPageToken"] = str(end)
                else:
                    out["newStartPageToken"] = str(end)
                return self._send(200, out)
            if path == "/drive/v3/files" and method == "GET":
                ids = sorted(Drive.files)
                start = int(q.get("pageToken", 0))
                page = ids[start:start + Drive.page_size]
                out = {"files": [Drive.meta(i) for i in page]}
                if start + len(page) < len(ids):
                    out["nextPageToken"] = str(start + len(page))
                return self._send(200, out)
            if path.startswith("/drive/v3/files/"):
                fid = path.rsplit("/", 1)[1]
                if fid not in Drive.files:
                    return self._error(404, "notFound")
                if method == "DELETE":
                    del Drive.files[fid]
                    Drive.changes.append((fid, True))
                    return self._send(204)
                return self._send(200, raw=Drive.files[fid]["data"])
            if path.startswith("/upload/drive/v3/files"):
                if Drive.quota_full:
                    return self._error(403, "storageQuotaExceeded")
                fid = path.rsplit("/", 1)[1] if path.count("/") > 4 else None
                kind = q.get("uploadType")
                if kind == "multipart":
                    boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
                    parts = body.split(b"--" + boundary)
                    meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
                    data = parts[2].split(b"\r\n\r\n", 1)[1][:-2]
                    return self._send(200, Drive.put(os.urandom(6).hex(), meta["name"], data))
                if kind == "media":
                    return self._send(200, Drive.put(fid, Drive.files[fid]["name"], body))
                if kind == "resumable":
                    sid = os.urandom(6).hex()
                    meta = json.loads(body or b"{}")
                    Drive.sessions[sid] = {"fid": fid, "name": meta.get("name") or Drive.files[fid]["name"],
                                           "total": int(self.headers["X-Upload-Content-Length"]), "got": b""}
                    port = self.server.server_address[1]
                    return self._send(200, {}, headers={"Location": f"http://127.0.0.1:{port}/upload/session/{sid}"})
            if path.startswith("/upload/session/"):
                s = Drive.sessions.get(path.rsplit("/", 1)[1])
                if s is None:
                    return self._error(404, "notFound")
                rng = self.headers["Content-Range"].split(" ", 1)[1]
                if not rng.startswith("*"):
                    a = int(rng.split("-")[0])
                    if a != len(s["got"]):
                        return self._error(400, "badRange")
                    s["got"] += body
                if len(s["got"]) == s["total"]:
                    del Drive.sessions[path.rsplit("/", 1)[1]]
                    return self._send(200, Drive.put(s["fid"] or os.urandom(6).hex(), s["name"], s["got"]))
                h = {"Range": f"bytes=0-{len(s['got']) - 1}"} if s["got"] else {}
                return self._send(308, headers=h)
            return self._error(400, "unknown")

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")

    def do_PATCH(self):  # noqa: N802
        self._handle("PATCH")

    def do_PUT(self):  # noqa: N802
        self._handle("PUT")

    def do_DELETE(self):  # noqa: N802
        self._handle("DELETE")

    def log_message(self, *_a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
sleeps: list = []
refreshes: list = []


def token(force):
    if force:
        refreshes.append(1)
        if "refresh-broken" in Drive.tokens:
            raise RuntimeError("invalid_grant")
        Drive.tokens.add("good")
    return "good"


def transport(device=None):
    return DriveTransport(token, api=BASE + "/drive/v3", upload=BASE + "/upload/drive/v3",
                          sleep=sleeps.append, own_device=device)


T0 = 1_762_000_000_000


class Clock:
    def __init__(self):
        self.ms = T0

    def __call__(self):
        self.ms += 1
        return self.ms


class PC:
    def __init__(self, user):
        self.images = tmp / "Users" / user / "images"
        self.images.mkdir(parents=True)
        self.clock = Clock()
        self.user = user
        with self:
            self.db = MemoDatabase(tmp / f"{user}.db")
            self.store = SyncStore(self.db.conn, self.clock)
            self.store.connect("me@example.com")
            self.syncer = Syncer(self.store, transport(self.store.device), user)

    def __enter__(self):
        database.IMAGES_DIR = self.images
        return self

    def __exit__(self, *a):
        return False

    def sync(self):
        with self:
            return self.syncer.sync()

    def restart(self):
        self.syncer = Syncer(self.store, transport(self.store.device), self.user)

    def memo(self, uid):
        return next((m for m in self.db.list_all() + self.db.list_trashed_memos() if m.uid == uid), None)

    def view(self):
        rows = self.db.conn.execute(
            "SELECT uid, title, content, color, is_pinned, deleted_at IS NOT NULL FROM memos ORDER BY uid").fetchall()
        out = []
        for r in rows:
            body = images.to_portable(r[2], self.images, self.store.image_sha)  # 경로는 PC마다 다르다
            out.append((r[0], r[1], body, r[3], r[4], r[5]))
        return out

    def picture(self, name, size):
        p = self.images / name
        p.write_bytes(os.urandom(size))
        return f'<p><img src="{p.as_posix()}" width="40" /></p>'


def same(a, b):
    assert a.view() == b.view(), "두 PC의 메모가 다름"


def settle(a, b):
    for _ in range(2):
        a.sync()
        b.sync()


def drive_names():
    return sorted(f["name"] for f in Drive.files.values())


images.LARGE_UPLOAD_BYTES = 600_000     # 시험용: 600KB 넘으면 이어 올리기
D.CHUNK = 256 * 1024                    # 조각 256KiB

# ===== 두 PC: 만들기, 고치기, 동시 수정, 휴지통·되살림, 그림(큰 것 포함) =====
A, B = PC("alice"), PC("bob")
m1 = A.db.create("장보기", "<p>우유</p>")
small = A.picture("img_small.png", 2_000)
large = A.picture("img_large.png", 900_000)         # 이어 올리기로 (조각 4개)
m2 = A.db.create("그림 메모", small + large)
settle(A, B)
same(A, B)
assert any(r[1] == "/upload/drive/v3/files" and r[0] == "POST" for r in Drive.requests)
assert sum(1 for r in Drive.requests if r[0] == "PUT" and r[1].startswith("/upload/session/")) == 4, "큰 그림은 조각 4개로 이어 올린다"
assert B.memo(m2.uid) and len(list(B.images.iterdir())) == 2
for p in B.images.iterdir():
    assert images.sha256_file(p) == p.stem, "받은 그림 내용이 다름"
B.db.update(B.memo(m1.uid).id, content="<p>우유 빵</p>")
settle(A, B)
A.db.update(A.memo(m1.uid).id, content="<p>A 동시</p>")
B.clock.ms = A.clock.ms + 1000
B.db.update(B.memo(m1.uid).id, content="<p>B 동시</p>")
settle(A, B)
same(A, B)
assert A.memo(m1.uid).content == "<p>B 동시</p>" and "<p>A 동시</p>" in [v.content for v in A.db.list_versions(A.memo(m1.uid).id)]
A.db.soft_delete(A.memo(m2.uid).id)
settle(A, B)
assert B.memo(m2.uid).deleted_at is not None
B.db.restore(B.memo(m2.uid).id)
settle(A, B)
same(A, B)
assert A.memo(m2.uid).deleted_at is None

# 바뀐 게 없으면 목록 확인은 요청 1번(changes)
A.sync()
n = len(Drive.requests)
A.syncer.transport.list()
assert Drive.requests[n:] == [("GET", "/drive/v3/changes")], Drive.requests[n:]

# ===== 시작 표시가 무효가 되면 전체 목록으로 다시 맞춘다 =====
Drive.min_token = len(Drive.changes) + 1
before = B.syncer.transport.full_relists
A.db.update(A.memo(m1.uid).id, title="장보기(무효 표시 뒤)")
A.sync()          # A도 같은 처지: 다시 맞춘다
B.sync()
assert B.syncer.transport.full_relists == before + 1
assert B.memo(m1.uid).title == "장보기(무효 표시 뒤)"
Drive.min_token = 0

# ===== 다시 시도 규칙 =====
t = transport()
t.list()
sleeps.clear()
Drive.faults = [["GET", "/drive/v3/changes", 429, "rateLimitExceeded", 2], ["GET", "/drive/v3/changes", 503, "backendError", 1],
                ["GET", "/drive/v3/changes", 403, "userRateLimitExceeded", 1]]
t.list()
assert len(sleeps) == 4, sleeps
for i, s in enumerate(sleeps):  # 1, 2, 4, 8초 × (0.5~1.5) — 늘어나고 흔들린다
    assert 0.5 * 2 ** i <= s <= 1.5 * 2 ** i, (i, s)
Drive.faults = [["GET", "/drive/v3/changes", 503, "backendError", 99]]
try:
    t.list()
    raise AssertionError("계속 실패하면 멈춰야 함")
except DriveError as e:
    assert e.code == "busy"
Drive.faults = []
# 401: 토큰을 새로 받아 한 번만 다시
Drive.tokens = set()
refreshes.clear()
t.list()
assert refreshes == [1]
Drive.tokens = {"refresh-broken"}  # 새로 받아도 안 됨 → 다시 연결
try:
    t.list()
    raise AssertionError
except DriveError as e:
    assert e.code == "reconnect" and e.message == "Google 연결이 끊어졌어요. 다시 연결해 주세요."
Drive.tokens = {"good"}
# 403 권한 오류: 다시 시도하지 않는다
Drive.faults = [["GET", "/drive/v3/changes", 403, "insufficientPermissions", 5]]
n = len(Drive.requests)
try:
    t.list()
    raise AssertionError
except DriveError as e:
    assert e.code == "reconnect" and len(Drive.requests) - n == 1
Drive.faults = []

# ===== 저장 공간 가득: 멈추고, 메모는 그대로 쓰고, 공간이 생기면 이어서 =====
Drive.quota_full = True
A.db.update(A.memo(m1.uid).id, content="<p>가득 찬 동안 고침</p>")
try:
    A.sync()
    raise AssertionError
except DriveError as e:
    assert e.code == "quota_full" and e.message == "Google Drive 저장 공간이 가득 차서 동기화를 멈췄어요"
n = len(Drive.requests)
assert [r for r in Drive.requests[n - 3:] if r[0] == "POST" or r[0] == "PATCH"].__len__() <= 1, "가득 찼는데 계속 다시 시도"
A.db.update(A.memo(m1.uid).id, content="<p>가득 찬 동안 또 고침</p>")   # 메모는 평소처럼
assert A.store.pending(), "못 올린 기록은 남아 있다"
Drive.quota_full = False
A.sync()
B.sync()
assert B.memo(m1.uid).content == "<p>가득 찬 동안 또 고침</p>"

# ===== 이어 올리기 도중 앱이 꺼짐 → 다시 켜서 처음부터: 반쪽 파일·같은 그림 두 개 없음 =====
huge = A.picture("img_huge.png", 1_300_000)
sha_huge = images.sha256_file(A.images / "img_huge.png")
m3 = A.db.create("큰 그림 하나 더", huge)


class Crash(BaseException):
    pass


real = A.syncer.transport._request
puts = []


def crash_after_first_chunk(method, url, *a, **k):
    if method == "PUT" and "/upload/session/" in url:
        puts.append(1)
        if len(puts) == 2:
            raise Crash()  # 두 번째 조각을 보내는 순간 앱이 꺼진다
    return real(method, url, *a, **k)


A.syncer.transport._request = crash_after_first_chunk
try:
    A.sync()
    raise AssertionError
except Crash:
    pass
assert f"img_{sha_huge}.png" not in drive_names(), "반쪽 파일이 보이면 안 된다"
A.restart()
A.sync()
B.sync()
named = [f for f in Drive.files.values() if f["name"] == f"img_{sha_huge}.png"]
assert len(named) == 1 and len(named[0]["data"]) == 1_300_000
(got,) = [p for p in B.images.iterdir() if p.stem == sha_huge]
assert images.sha256_file(got) == sha_huge

# 조각 하나가 실패하면 Drive에 받은 곳을 묻고 그 뒤부터 잇는다
p4 = A.picture("img_resume.png", 800_000)
sha4 = images.sha256_file(A.images / "img_resume.png")
A.db.create("조각 실패", p4)
Drive.faults = [["PUT", "/upload/session/", 503, "backendError", 1]]
A.sync()
Drive.faults = []
named = [f for f in Drive.files.values() if f["name"] == f"img_{sha4}.png"]
assert len(named) == 1 and len(named[0]["data"]) == 800_000

# 같은 그림을 두 PC가 동시에 올려 이름이 둘이 되면 하나만 남긴다
fid_extra = os.urandom(6).hex()
Drive.put(fid_extra, f"img_{sha4}.png", named[0]["data"])
B.sync()
assert [f["name"] for f in Drive.files.values()].count(f"img_{sha4}.png") == 1, "같은 그림이 두 개 남음"

settle(A, B)
same(A, B)
for pc in (A, B):
    pc.db.close()
server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("sync drive OK", flush=True)
