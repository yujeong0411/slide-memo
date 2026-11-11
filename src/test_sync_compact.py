# ponytail: 기록 압축, 영구 삭제한 내용 지우기, 오래(181일) 꺼져 있던 PC, PC 목록·빼기 self-check.
# 폴더 하나를 Drive처럼 쓴다. 임시 폴더만 쓴다. run: python src/test_sync_compact.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from database import MemoDatabase  # noqa: E402
from sync import engine  # noqa: E402
from sync.core import DAY_MS  # noqa: E402
from sync.engine import Syncer  # noqa: E402
from sync.local_folder import LocalFolderTransport  # noqa: E402
from sync.store import SyncStore  # noqa: E402

T0 = 1_762_000_000_000
engine.SEG_MAX_LINES = 3      # 시험용: 조각을 작게
engine.COMPACT_SEGMENTS = 4   # 4조각이면 압축


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        self.ms += 1
        return self.ms


class PC:
    def __init__(self, name, drive, ms=T0):
        self.name, self.drive, self.clock = name, drive, Clock(ms)
        self.db = MemoDatabase(tmp / f"{name}.db")
        self.store = SyncStore(self.db.conn, self.clock)
        self.store.connect("me@example.com")
        self.syncer = Syncer(self.store, LocalFolderTransport(drive), name)

    def sync(self):
        return self.syncer.sync()

    def memo(self, uid):
        for m in self.db.list_all() + self.db.list_trashed_memos():
            if m.uid == uid:
                return m
        return None

    def view(self):
        return [tuple(r) for r in self.db.conn.execute(
            "SELECT uid, title, content, color, is_pinned, deleted_at IS NOT NULL FROM memos ORDER BY uid")]

    def later(self, days):
        self.clock.ms += int(days * DAY_MS)


def same(*pcs):
    for pc in pcs[1:]:
        assert pc.view() == pcs[0].view(), f"{pcs[0].name}와 {pc.name}가 다름"


def settle(*pcs):
    for _ in range(2):
        for pc in pcs:
            pc.sync()


def drive_files(drive, prefix=""):
    return sorted(p.name for p in drive.iterdir() if p.name.startswith(prefix) and not p.name.endswith(".tmp"))


def drive_text(drive):
    return b"".join(p.read_bytes() for p in drive.iterdir() if p.is_file())


def db_text(pc):
    rows = pc.db.conn.execute("SELECT op FROM sync_head UNION ALL SELECT op FROM sync_outbox").fetchall()
    return "".join(r[0] for r in rows)


# ===== 1. 압축: 조각이 쌓이면 줄이고, 늦게 켠 PC도 따라온다 =====
d1 = tmp / "drive1"
A, B = PC("A", d1), PC("B", d1)
m = A.db.create("자주 고치는 메모", "<p>0</p>")
settle(A, B)
for i in range(1, 31):
    A.db.update(A.memo(m.uid).id, content=f"<p>{i}</p>")
    A.sync()
    if i == 10:
        B.sync()                       # B는 중간까지만 받아 둔다
dev_a = A.store.device
assert len(drive_files(d1, f"snap_{dev_a}")) == 1, drive_files(d1)
assert len(drive_files(d1, f"log_{dev_a}")) < engine.COMPACT_SEGMENTS, drive_files(d1, f"log_{dev_a}")
assert A.db.conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] < 10, "이 PC 기록도 줄어든다"
C = PC("C", d1)                        # 압축 뒤에 처음 연결한 PC
settle(A, B, C)
same(A, B, C)
assert C.memo(m.uid).content == "<p>30</p>" and B.memo(m.uid).content == "<p>30</p>"

# 압축 중간에 꺼져도 깨지지 않는다
for i in range(31, 40):
    A.db.update(A.memo(m.uid).id, content=f"<p>{i}</p>")
    A.syncer.push()
real_write = A.syncer.transport.write


def fail_dev(name, data):
    if name.startswith("dev_"):
        raise OSError("시험: 압축본을 올린 뒤 꺼짐")
    real_write(name, data)


A.syncer.transport.write = fail_dev
try:
    A.syncer.compact(force=True)
    raise AssertionError("실패해야 함")
except OSError:
    pass
A.syncer.transport.write = real_write
settle(A, B, C)                        # dev 파일은 옛 조각을 그대로 가리키므로 받는 쪽은 문제없다
same(A, B, C)
real_delete = A.syncer.transport.delete
A.syncer.transport.delete = lambda name: (_ for _ in ()).throw(OSError("시험: 옛 파일 지우다 꺼짐"))
A.db.update(A.memo(m.uid).id, content="<p>마지막</p>")
A.syncer.push()
try:
    A.syncer.compact(force=True)
    raise AssertionError("실패해야 함")
except OSError:
    pass
A.syncer.transport.delete = real_delete
settle(A, B, C)
same(A, B, C)
assert C.memo(m.uid).content == "<p>마지막</p>"
A.syncer.compact(force=True)           # 다음 압축이 남은 옛 파일을 치운다
assert len(drive_files(d1, f"snap_{dev_a}")) == 1 and drive_files(d1, f"log_{dev_a}") == []
for pc in (A, B, C):
    pc.db.close()

# ===== 2. 영구 삭제한 메모의 내용은 Drive와 기록에 남지 않는다 =====
d2 = tmp / "drive2"
A, B = PC("A2", d2), PC("B2", d2)
secret = A.db.create("지울 메모", "<p>비밀 XYZZY</p>")
keep = A.db.create("남길 메모", "<p>남김</p>")
settle(A, B)
B.db.update(B.memo(secret.uid).id, content="<p>비밀 XYZZY 덧붙임</p>")  # B의 기록에도 들어간다
settle(A, B)
assert b"XYZZY" in drive_text(d2)
A.db.soft_delete(A.memo(secret.uid).id)
A.db.delete(A.memo(secret.uid).id)
settle(A, B)
assert B.memo(secret.uid) is None
assert b"XYZZY" not in drive_text(d2), "Drive에 지운 메모 내용이 남음"
for pc in (A, B):
    assert "XYZZY" not in db_text(pc), f"{pc.name} 기록에 지운 메모 내용이 남음"
assert B.memo(keep.uid).content == "<p>남김</p>"
# 보관 기간(180일)이 지나면 그 메모의 기록 자체를 잊는다
for pc in (A, B):
    pc.later(181)
settle(A, B)
assert secret.uid.encode() not in drive_text(d2), "180일 뒤에도 지운 메모 기록이 남음"
assert secret.uid not in db_text(A) and secret.uid not in db_text(B)
for pc in (A, B):
    pc.db.close()

# ===== 3. 181일 꺼져 있던 PC가 돌아온다 =====
d3 = tmp / "drive3"
A, B, C = PC("A3", d3), PC("B3", d3), PC("C3", d3)
m1 = A.db.create("다른 PC에서 지울 메모", "<p>1</p>")
m2 = A.db.create("다른 PC에서 고칠 메모", "<p>2</p>")
m3 = A.db.create("C가 꺼진 동안 고칠 메모", "<p>3</p>")
settle(A, B, C)
same(A, B, C)
# C는 꺼지기 전에 고쳐 두고 (기록만 남기고) 꺼진다
C.db.update(C.memo(m3.uid).id, content="<p>3 C가 고침</p>")
m5 = C.db.create("C가 꺼진 동안 쓴 메모", "<p>5</p>")
C.store.reconcile()
# 그동안 A가 m1을 영구 삭제, B가 m2를 고친다
A.db.soft_delete(A.memo(m1.uid).id)
A.db.delete(A.memo(m1.uid).id)
B.db.update(B.memo(m2.uid).id, content="<p>2 B가 고침</p>")
settle(A, B)
for pc in (A, B):                      # 181일 동안 A, B는 계속 쓴다 (지운 기록은 180일 뒤 사라진다)
    pc.later(181)
settle(A, B)
others = b"".join(p.read_bytes() for p in d3.iterdir() if C.store.device not in p.name)
assert m1.uid.encode() not in others, "A·B의 파일에 지운 기록이 남아 있으면 이 시험의 전제가 아니다"
C.later(181)
C.sync()
assert C.syncer.take_return_notice() == 1, "다른 PC에 없는 메모 1개를 알린다"
assert C.syncer.take_return_notice() == 0, "알림은 한 번만"
gone = C.memo(m1.uid)
assert gone is not None and gone.deleted_at is not None, "지우지 않고 휴지통으로"
assert C.memo(m2.uid).content == "<p>2 B가 고침</p>"
settle(A, B, C)
assert A.memo(m1.uid) is None and B.memo(m1.uid) is None, "휴지통으로 옮긴 메모가 다른 PC로 퍼지면 안 된다"
assert A.memo(m3.uid).content == "<p>3 C가 고침</p>", "C가 꺼지기 전에 고친 내용은 올라간다"
assert A.memo(m5.uid) is not None and B.memo(m5.uid).content == "<p>5</p>", "C가 새로 쓴 메모는 올라간다"
# C에서 되살리면 새 메모처럼 다른 PC로 간다
C.db.restore(C.memo(m1.uid).id)
settle(A, B, C)
same(A, B, C)
assert A.memo(m1.uid).deleted_at is None and A.memo(m1.uid).content == "<p>1</p>"

# 100일 꺼져 있던 PC는 지운 기록이 남아 있어 그대로 지워진다 (알림 없음)
D = PC("D3", d3, A.clock.ms)
settle(A, B, C, D)
m6 = A.db.create("100일 사이에 지울 메모", "<p>6</p>")
settle(A, B, C, D)
A.db.soft_delete(A.memo(m6.uid).id)
A.db.delete(A.memo(m6.uid).id)
settle(A, B, C)
for pc in (A, B, C, D):
    pc.later(100)
settle(A, B, C)
D.sync()
assert D.syncer.take_return_notice() == 0 and D.memo(m6.uid) is None
settle(A, B, C, D)
same(A, B, C, D)

# ===== 4. 연결된 PC 목록과 목록에서 빼기 =====
names = [(d["name"], d["is_self"]) for d in A.syncer.devices()]
assert names[0] == ("A3", True) and {n for n, _ in names} == {"A3", "B3", "C3", "D3"}, names
assert all(d["last_sync"] > 0 for d in A.syncer.devices())
# C가 고쳐서 올렸지만 B는 아직 못 받았다. A가 C를 목록에서 뺀다.
C.db.update(C.memo(m2.uid).id, content="<p>2 C가 마지막으로 고침</p>")
C.sync()
dev_c = C.store.device
assert A.syncer.remove_device(dev_c)
assert not [n for n in drive_files(d3) if dev_c in n], "C의 기록 파일이 남음"
assert "C3" not in {d["name"] for d in A.syncer.devices()}
conflicts = B.sync()
assert conflicts == [], conflicts
assert B.memo(m2.uid).content == "<p>2 C가 마지막으로 고침</p>", "뺀 PC의 기록을 B도 받는다"
settle(A, B, D)
same(A, B, D)
# 빠진 C가 다시 켜진다: 새 ID로 다시 들어오고, 그 사이 C에서 쓴 것도 올라간다
C.later(1)
C.db.update(C.memo(m3.uid).id, content="<p>3 빠진 뒤 C가 고침</p>")
m7 = C.db.create("빠진 뒤 C가 쓴 메모", "<p>7</p>")
C.sync()
assert C.store.device != dev_c and C.syncer.take_return_notice() == 0
settle(A, B, C, D)
same(A, B, C, D)
assert A.memo(m7.uid) is not None and A.memo(m3.uid).content == "<p>3 빠진 뒤 C가 고침</p>"
assert "C3" in {d["name"] for d in A.syncer.devices()}
for pc in (A, B, C, D):
    pc.sync()
    assert pc.store.pending() == []
for pc in (A, B, C, D):
    pc.db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("sync compact OK", flush=True)
