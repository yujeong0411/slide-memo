# ponytail: 동기화 규칙(HLC, LWW, 충돌, 삭제) self-check. Qt·네트워크 없음. run: python src/test_sync_core.py
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync.core import (  # noqa: E402
    DAY_MS, HLC, Op, auto_purge_due, decide, hlc_key, materialize,
)

H = 3_600_000
T0 = 1_762_000_000_000


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        return self.ms


class PC:
    """테스트용 PC 한 대: heads·chain·이전 버전을 메모리에 둔다 (3단계에서 SQLite로 옮긴다)."""

    def __init__(self, dev, clock):
        self.dev, self.wall = dev, clock
        self.hlc, self.seq = HLC(dev, clock), 0
        self.heads, self.chain, self.versions, self.log, self.seen = {}, {}, [], [], set()

    def write(self, uid, f, v, base=...):
        head = self.heads.get((uid, f))
        self.seq += 1
        op = Op(f"{self.dev}:{self.seq}", self.hlc.now(), uid, f, v,
                (head.id if head else None) if base is ... else base)
        self._take(op)
        self.log.append(op)
        return op

    def receive(self, op):
        if op.id in self.seen:  # 이미 받은 op는 다시 판정하지 않는다 (store의 sync_seen_op)
            return
        op = Op.from_json(op.to_json())  # Drive를 거친 것처럼
        self.hlc.observe(op.hlc)
        self._take(op)

    def _take(self, op):
        self.seen.add(op.id)
        if op.f == "body":
            self.chain[op.id] = op.base
        d = decide(self.heads.get((op.uid, op.f)), op, self.chain)
        if d.loser is not None:
            self.versions.append(d.loser.v)
        if d.apply:
            self.heads[(op.uid, op.f)] = op

    def heads_of(self, uid):
        return {f: o for (u, f), o in self.heads.items() if u == uid}

    def state(self, uid):
        return materialize(uid, self.heads_of(uid), self.wall())

    def auto_purge(self, uid):
        trash = auto_purge_due(self.heads_of(uid), self.wall())
        assert trash is not None
        return self.write(uid, "autopurge", None, base=trash.id)


def body(t, c=""):
    return {"title": t, "content": c}


def sync(*pcs):
    for a in pcs:
        for b in pcs:
            if a is not b:
                for op in a.log:
                    b.receive(op)


# ----- HLC -----
w = Clock(T0)
h = HLC("a", w)
s1, s2 = h.now(), h.now()
w.ms -= H  # 시계가 뒤로 감
s3 = h.now()
assert hlc_key(s1) < hlc_key(s2) < hlc_key(s3), "시계가 멈추거나 뒤로 가도 순서는 늘어난다"
late = HLC("b", Clock(T0 - 6 * H))  # 6시간 늦은 PC
late.observe(s3)
assert hlc_key(late.now()) > hlc_key(s3), "받은 뒤에 만든 op는 늦은 시계여도 뒤로 판정"
assert HLC("c", Clock(T0)).observe(HLC("z", Clock(T0 + 2 * DAY_MS)).now()), "하루 넘게 앞선 시계는 경고"
assert not HLC("c", Clock(T0)).observe(s1)

# ----- op 읽기: 틀린 줄은 거부 -----
good = Op("a:1", s1, "u1", "body", body("t", "<p>x</p>"), "b:3")
assert Op.from_json(good.to_json()) == good
for bad in (
    '[]',
    '{"id":"a:1","hlc":"%s","uid":"u","f":"nope","v":1}' % s1,
    '{"id":"a:1","hlc":"%s","uid":"u","f":"body","v":"x"}' % s1,
    '{"id":"a:1","hlc":"%s","uid":"u","f":"trash","v":{"at":"x"}}' % s1,
    '{"id":"a:x","hlc":"%s","uid":"u","f":"pin","v":true}' % s1,
    '{"id":"a:1","hlc":"bad","uid":"u","f":"pin","v":true}',
    '{"id":"a:1","hlc":"%s","uid":"settings:side","f":"value","v":"left"}' % s1,
):
    try:
        Op.from_json(bad)
        raise AssertionError(f"받아들이면 안 됨: {bad}")
    except (ValueError, KeyError, TypeError):
        pass
assert Op.from_json('{"id":"a:2","hlc":"%s","uid":"settings:user_slots","f":"value","v":"[]"}' % s1)
try:
    Op.from_json('{"id":"a:2","hlc":"%s","uid":"settings:user_slots","f":"value","v":1}' % s1)
    raise AssertionError("설정 값은 문자열만")
except ValueError:
    pass

# ----- 이어 쓰기는 충돌이 아니다, 동시 수정은 진 쪽을 양쪽 이전 버전에 -----
wa, wb = Clock(T0), Clock(T0)
A, B = PC("a", wa), PC("b", wb)
A.write("m1", "created", {"at": T0})
A.write("m1", "body", body("장보기", "우유"))
sync(A, B)
wb.ms += 1000
B.write("m1", "body", body("장보기", "우유 빵"))  # 받은 뒤 이어 씀
sync(A, B)
assert A.versions == [] and B.versions == [], "이어 쓰기에 충돌 표시"
assert A.state("m1").content == B.state("m1").content == "우유 빵"

wa.ms += 5000
wb.ms += 6000
A.write("m1", "body", body("장보기", "A가 고침"))
B.write("m1", "body", body("장보기", "B가 고침"))  # 서로 모르고 (B가 나중)
sync(A, B)
assert A.state("m1").content == B.state("m1").content == "B가 고침", "나중에 쓴 쪽이 이긴다"
assert A.versions == [body("장보기", "A가 고침")] == B.versions, "진 내용은 두 PC 모두 이전 버전에"

# 같은 내용으로 동시에 고치면 남길 것이 없다
A.versions.clear()
B.versions.clear()
wa.ms += 5000
wb.ms += 5000
A.write("m1", "body", body("같음"))
B.write("m1", "body", body("같음"))
sync(A, B)
assert A.versions == B.versions == []

# 순서가 뒤바뀌어 도착해도 거짓 충돌이 없다 (C는 A의 두 op를 거꾸로 받는다)
C = PC("c", Clock(T0))
a1 = A.write("m2", "body", body("1"))
a2 = A.write("m2", "body", body("2"))
C.receive(a2)
C.receive(a1)
assert C.versions == [] and C.state("m2").title == "2"

# ----- 필드가 다르면 둘 다 반영 -----
wa.ms += 5000
wb.ms += 5000
A.write("m1", "pin", True)
B.write("m1", "body", body("고정과 동시에 고침"))
B.write("m1", "color", "#112233")
sync(A, B)
for pc in (A, B):
    st = pc.state("m1")
    assert st.pinned and st.title == "고정과 동시에 고침" and st.color == "#112233"

# ----- 시계가 6시간 늦은 PC도 받은 뒤 고치면 이긴다 -----
wb.ms = wa.ms - 6 * H
sync(A, B)
B.write("m1", "body", body("늦은 시계로 나중에 고침"))
sync(A, B)
assert A.state("m1").title == "늦은 시계로 나중에 고침"

# ----- 어떤 순서로 받아도 결과가 같다 -----
ops = [o for o in A.log + B.log if o.uid == "m1"]
expect = A.state("m1")
checked = 0
for perm in itertools.islice(itertools.permutations(ops), 0, None, 997):
    D = PC("d", Clock(wa.ms))
    for o in perm + perm:  # 두 번씩 받아도 같다
        D.receive(o)
    assert D.state("m1") == expect, "도착 순서에 따라 결과가 갈라짐"
    checked += 1
assert checked > 100

# ----- 휴지통·복원 전파 -----
w1, w2 = Clock(T0), Clock(T0)
A, B = PC("a", w1), PC("b", w2)
A.write("t", "created", {"at": T0})
A.write("t", "body", body("버릴 메모"))
A.write("t", "trash", {"at": w1.ms})
sync(A, B)
assert B.state("t").trashed_at == T0
w2.ms += 1000
B.write("t", "trash", None)  # 되살림
sync(A, B)
assert A.state("t").trashed_at is None

# ----- 직접 영구 삭제: 전파, 단 모르고 고친 내용이 있으면 휴지통에 남김 -----
A.write("p", "body", body("지울 메모"))
A.write("p", "trash", {"at": w1.ms})
sync(A, B)
w1.ms += 1000
w2.ms += 2000
A.write("p", "purge", None)
B.write("p", "body", body("지우는 줄 모르고 고침"))
sync(A, B)
for pc in (A, B):
    st = pc.state("p")
    assert st is not None and st.title == "지우는 줄 모르고 고침" and st.trashed_at is not None
w2.ms += 1000
B.write("p", "trash", None)  # 휴지통에 남은 그 메모를 되살리면 되살아난 채로 둔다
sync(A, B)
assert A.state("p").trashed_at is None and B.state("p").trashed_at is None
A.write("q", "body", body("그냥 지움"))
A.write("q", "purge", None)
sync(A, B)
assert A.state("q") is None and B.state("q") is None

# ----- 휴지통 자동 비우기 (설계 3.4) -----
w1, w2 = Clock(T0), Clock(T0)
A, B = PC("a", w1), PC("b", w2)
A.write("x", "body", body("30일 뒤 지워질 메모"))
A.write("x", "trash", {"at": T0})
sync(A, B)
w1.ms = T0 + 29 * DAY_MS
assert auto_purge_due(A.heads_of("x"), w1.ms) is None, "30일 전에는 아직"
w1.ms = T0 + 30 * DAY_MS
A.auto_purge("x")
assert A.state("x") is None
w2.ms = T0 + 28 * DAY_MS  # B의 시계가 2일 늦다
sync(A, B)
assert B.state("x") is not None and B.state("x").trashed_at == T0, "시계가 늦은 PC는 미룬다"
w2.ms = T0 + 29 * DAY_MS
assert B.state("x") is None, "자기 시계로 29일이 되면 지운다"

# 되살림과 겹치면 되살림이 이긴다 (A의 자동 비우기 ↔ B의 되살림)
w1, w2 = Clock(T0), Clock(T0)
A, B = PC("a", w1), PC("b", w2)
A.write("y", "body", body("되살릴 메모"))
A.write("y", "trash", {"at": T0})
sync(A, B)
w1.ms = w2.ms = T0 + 30 * DAY_MS
A.auto_purge("y")
B.write("y", "trash", None)
sync(A, B)
for pc in (A, B):
    st = pc.state("y")
    assert st is not None and st.trashed_at is None and st.title == "되살릴 메모", "되살린 메모를 지움"

# 되살렸다가 다시 휴지통에 넣으면 날짜를 새로 센다
B.write("y", "trash", {"at": w2.ms})
w2.ms += 29 * DAY_MS
assert auto_purge_due(B.heads_of("y"), w2.ms) is None, "다시 넣은 날부터 30일"
w2.ms += DAY_MS
assert auto_purge_due(B.heads_of("y"), w2.ms) is not None

# 휴지통에 있는 동안 고쳤으면 자동 비우기 대상이 아니다
w1 = Clock(T0)
A = PC("a", w1)
A.write("z", "body", body("z"))
A.write("z", "trash", {"at": T0})
w1.ms += 1000
A.write("z", "pin", True)
w1.ms = T0 + 40 * DAY_MS
assert auto_purge_due(A.heads_of("z"), w1.ms) is None

# 자동 비우기가 한 번 무효가 됐어도 다음 휴지통 기간의 자동 비우기는 다시 된다
y_auto = B.auto_purge("y")
assert B.state("y") is None and y_auto.base == B.heads_of("y")["trash"].id
assert auto_purge_due(B.heads_of("y"), w2.ms) is None, "같은 기간에 두 번 만들지 않는다"
sync(A, B)
assert A.state("y") is not None, "A의 시계로는 아직 29일이 안 됐다"
w1.ms = w2.ms
assert A.state("y") is None

# 직접 영구 삭제는 나중에 온 (무효인) 자동 비우기에 덮이지 않는다 (어느 순서로 받아도)
seed = Op("a:0", HLC("a", Clock(T0 - 1)).now(), "k", "body", body("k"))
manual = Op("a:1", HLC("a", Clock(T0)).now(), "k", "purge", None)
auto = Op("b:1", HLC("b", Clock(T0 + DAY_MS)).now(), "k", "autopurge", None, "a:0")
for order in ((manual, auto), (auto, manual)):
    D = PC("d", Clock(T0 + 31 * DAY_MS))
    D.receive(seed)
    for o in order:
        D.receive(o)
    assert D.state("k") is None

print("sync core OK", flush=True)
