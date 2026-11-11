# ponytail: 폴더 하나를 Drive처럼 써서 PC 2~3대를 흉내 내는 self-check. Google·실제 메모 DB 없음.
# run: python src/test_sync_pcs.py
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
from sync.engine import Syncer  # noqa: E402
from sync.local_folder import LocalFolderTransport  # noqa: E402
from sync.store import SyncStore  # noqa: E402

H = 3_600_000
T0 = 1_762_000_000_000


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        self.ms += 1
        return self.ms


class PC:
    def __init__(self, name, drive, clock_ms):
        self.name, self.drive = name, drive
        self.clock = Clock(clock_ms)
        self.path = tmp / f"{name}.db"
        self.open()
        self.store.connect("me@example.com")

    def open(self):
        """앱을 켠다 (DB를 다시 연다)."""
        self.db = MemoDatabase(self.path)
        self.store = SyncStore(self.db.conn, self.clock)
        self.syncer = Syncer(self.store, LocalFolderTransport(self.drive), self.name)

    def restart(self):
        self.db.close()
        self.open()

    def sync(self):
        return self.syncer.sync()

    def memo(self, uid):
        return next(m for m in self.db.list_all() + self.db.list_trashed_memos() if m.uid == uid)

    def view(self):
        rows = self.db.conn.execute(
            "SELECT uid, title, content, color, is_pinned, deleted_at IS NOT NULL, font_family, font_size"
            " FROM memos ORDER BY uid").fetchall()
        slots = self.db.get_setting_str("user_slots")
        return [tuple(r) for r in rows], slots

    def versions(self, uid):
        return [v.content for v in self.db.list_versions(self.memo(uid).id)]


def same(*pcs):
    first = pcs[0].view()
    for pc in pcs[1:]:
        assert pc.view() == first, f"{pcs[0].name}와 {pc.name}의 메모가 다름"


def settle(*pcs):
    for _ in range(2):
        for pc in pcs:
            pc.sync()


drive = tmp / "drive"
A = PC("A", drive, T0)
B = PC("B", drive, T0 - 6 * H)  # B의 시계는 6시간 늦다

# ----- 처음 연결: A의 메모가 B로, B의 메모가 A로 (합치기) -----
m1 = A.db.create("장보기", "<p>우유</p>", "blue")
m2 = A.db.create("할 일", "<p>세탁</p>")
B.db.create("B에서 만든 메모", "<p>b</p>")
A.db.set_setting_str("user_slots", '["#123456"]')
settle(A, B)
same(A, B)
assert len(A.db.list_all()) == 3
assert B.db.get_setting_str("user_slots") == '["#123456"]'

# 다 맞춘 뒤에는 더 주고받을 것이 없다 (되풀이 없음)
for pc in (A, B):
    pc.sync()
    assert pc.store.pending() == [] and pc.store.reconcile() == []

# ----- 이어 쓰기: 충돌 아님 (B 시계가 늦어도) -----
B.db.update(B.memo(m1.uid).id, content="<p>우유 빵</p>")
assert B.sync() == []
assert A.sync() == []
assert A.memo(m1.uid).content == "<p>우유 빵</p>" and A.versions(m1.uid) == []

# ----- 동시 수정: 나중에 쓴 쪽(시계 기준) 승리, 진 내용은 두 PC 이전 버전에 -----
A.db.update(A.memo(m1.uid).id, content="<p>A가 고침</p>")
B.clock.ms = A.clock.ms + 1000  # B가 실제로 나중에 고침
B.db.update(B.memo(m1.uid).id, content="<p>B가 고침</p>")
c_a = A.sync()
c_b = B.sync()
c_a2 = A.sync()
same(A, B)
assert c_a == [] and c_a2 == [(m1.uid, True)], (c_a, c_a2)  # A가 받은 뒤 '이 PC 내용이 짐'을 알림
assert A.memo(m1.uid).content == "<p>B가 고침</p>"
assert "<p>A가 고침</p>" in A.versions(m1.uid) and "<p>A가 고침</p>" in B.versions(m1.uid)
assert c_b == [(m1.uid, False)], c_b    # B가 받은 A의 내용이 짐
B.clock.ms = A.clock.ms - 6 * H

# ----- 고정과 편집이 겹치면 둘 다 반영 -----
A.db.set_pinned(A.memo(m2.uid).id, True)
B.db.update(B.memo(m2.uid).id, title="할 일(고침)", color="#112233")
settle(A, B)
same(A, B)
mm = A.memo(m2.uid)
assert mm.is_pinned and mm.title == "할 일(고침)" and mm.color == "#112233"

# ----- 휴지통·되살림·영구 삭제 전파 -----
A.db.soft_delete(A.memo(m2.uid).id)
settle(A, B)
assert B.memo(m2.uid).deleted_at is not None
B.db.restore(B.memo(m2.uid).id)
settle(A, B)
assert A.memo(m2.uid).deleted_at is None
gone = A.db.create("곧 지울 메모")
settle(A, B)
A.db.soft_delete(A.memo(gone.uid).id)
A.db.delete(A.memo(gone.uid).id)
settle(A, B)
same(A, B)
assert all(m.uid != gone.uid for m in B.db.list_all() + B.db.list_trashed_memos())

# ----- PC 세 대: C는 고쳐 둔 채 꺼져 있다가 나중에 한꺼번에 받는다 -----
C = PC("C", drive, A.clock.ms)
settle(A, B, C)
same(A, B, C)
x = A.db.create("같이 고치는 메모", "<p>처음</p>")
settle(A, B, C)
C.db.update(C.memo(x.uid).id, content="<p>C가 꺼지기 전에 고침</p>")
C.store.reconcile()        # C는 기록만 하고
C.db.close()               # 올리기 전에 꺼진다
c_round = []
for i in range(5):         # 그동안 A와 B가 여러 번 주고받는다
    A.clock.ms += 60_000
    B.clock.ms = A.clock.ms - 6 * H + 30_000
    c_round += A.sync()    # 받은 뒤에 고친다 (서로 주고받기 — 동시 수정이 아님)
    A.db.update(A.memo(x.uid).id, content=f"<p>A {i}</p>")
    A.db.create(f"A가 {i}번째에 만든 메모")
    c_round += A.sync()
    c_round += B.sync()
    B.db.update(B.memo(x.uid).id, title=f"제목 B {i}", content=f"<p>B {i}</p>")
    c_round += B.sync()
assert c_round == [], f"주고받기만 했는데 충돌: {c_round}"
C.open()                   # 나중에 켠다
C.clock.ms = A.clock.ms + 120_000
got = C.sync()
settle(A, B, C)
same(A, B, C)
assert C.memo(x.uid).content == "<p>B 4</p>", "가장 나중 내용이 이긴다"
for pc in (A, B, C):
    assert "<p>C가 꺼지기 전에 고침</p>" in pc.versions(x.uid), f"{pc.name}에 C의 진 내용이 없다"
assert [u for u, _ in got] == [x.uid], f"C가 받으며 거짓 충돌: {got}"
assert len(A.db.list_all()) == len(C.db.list_all())

# ----- 중간에 꺼져도 깨지지 않는다 -----
# 1) 올리기: 조각은 올렸는데 dev 파일을 쓰기 전에 꺼짐
A.db.update(A.memo(m1.uid).id, content="<p>올리다 꺼짐</p>")
real_write = A.syncer.transport.write


def fail_on_dev(name, data):
    if name.startswith("dev_"):
        raise OSError("시험: 올리는 중 꺼짐")
    real_write(name, data)


A.syncer.transport.write = fail_on_dev
try:
    A.sync()
    raise AssertionError("실패해야 함")
except OSError:
    pass
A.syncer.transport.write = real_write
A.restart()
settle(A, B, C)
same(A, B, C)
assert B.memo(m1.uid).content == "<p>올리다 꺼짐</p>"

# 2) 올리기: 다 올렸는데 '올림' 표시 전에 꺼짐 → 다시 올려도 두 번 적용되지 않는다
A.db.update(A.memo(m1.uid).id, content="<p>표시 전에 꺼짐</p>")
real_set = A.store.set_json
def fail_on_mark(key, value):
    if key == "segments":  # '올림' 표시와 같은 트랜잭션
        raise OSError("시험: 표시 전에 꺼짐")
    real_set(key, value)


A.store.set_json = fail_on_mark
try:
    A.syncer.push()
    raise AssertionError("실패해야 함")
except OSError:
    pass
A.store.set_json = real_set
assert A.store.pending(), "표시가 취소돼 다시 올릴 것으로 남아야 한다"
before = len(B.versions(m1.uid))
settle(A, B, C)
same(A, B, C)
assert len(B.versions(m1.uid)) == before, "같은 op를 두 번 받아 이전 버전이 늘었다"

# 3) 받기: 적용 도중 꺼짐 → 메모·커서 모두 그대로, 다시 받으면 맞는다
A.db.update(A.memo(m1.uid).id, content="<p>받다 꺼짐</p>")
A.db.create("받다 꺼짐 새 메모")
A.sync()
real_write_memo, calls = B.store.write_memo, []


def fail_second(uid):
    calls.append(uid)
    if len(calls) == 2:
        raise RuntimeError("시험: 받는 중 꺼짐")
    real_write_memo(uid)


B.store.write_memo = fail_second
view_before, cursor_before = B.view(), B.store.cursor(A.store.device)
try:
    B.sync()
    raise AssertionError("실패해야 함")
except RuntimeError:
    pass
B.store.write_memo = real_write_memo
assert B.view() == view_before and B.store.cursor(A.store.device) == cursor_before, "반쯤 적용됨"
B.restart()
settle(A, B, C)
same(A, B, C)
assert B.memo(m1.uid).content == "<p>받다 꺼짐</p>"

# 4) 망가진 줄이 섞여도 나머지는 받는다
A.db.update(A.memo(m2.uid).id, title="망가진 줄 뒤")
A.sync()
seg = sorted(p for p in drive.iterdir() if p.name.startswith(f"log_{A.store.device}_"))[-1]
seg.write_bytes(b"{not json\n" + seg.read_bytes())
settle(A, B, C)
assert C.memo(m2.uid).title == "망가진 줄 뒤"

# 마지막: 세 PC 모두 더 주고받을 것이 없다
for pc in (A, B, C):
    pc.sync()
    assert pc.store.pending() == []
same(A, B, C)
for pc in (A, B, C):
    pc.db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("sync pcs OK", flush=True)
