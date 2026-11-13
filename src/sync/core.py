"""동기화의 규칙만 담는다. Qt·네트워크·DB를 모른다 (docs/sync-design.md 2~3장).

- HLC: PC 시계가 틀려도 원인→결과 순서가 뒤집히지 않는 시계
- Op: 변경 기록 한 줄. 필드 묶음(f)마다 "나중에 쓴 쪽이 이긴다"(LWW)
- decide(): 받은 op를 적용할지, 충돌로 진 내용을 이전 버전에 남겨야 하는지
- materialize(): 필드별 이긴 op(heads)만 보고 메모의 지금 모습을 계산한다.
  op가 어떤 순서로 도착해도 heads가 같으면 결과가 같다 (PC끼리 갈라지지 않음).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

DAY_MS = 86_400_000
TRASH_DAYS = 30           # 휴지통 자동 비우기
PURGE_KEEP_DAYS = 180     # 영구 삭제 기록 보관 (지나면 기록에서 그 메모를 잊는다)
AUTOPURGE_HIDE_DAYS = 7   # 자동 비우기한 메모 내용을 되살림에 대비해 남겨 두는 기간
CLOCK_SLACK_DAYS = 1      # 받는 PC가 봐주는 시계 차이 (자동 비우기를 29일째부터 받아들임)
FAR_AHEAD_MS = DAY_MS     # 이보다 앞선 시계를 받으면 경고만 남긴다

# 메모 필드 묶음. body는 제목+본문을 함께 묶는다.
# purge = 직접 영구 삭제, autopurge = 30일 자동 비우기. 따로 둬야 무효가 된 자동 비우기가
# 직접 삭제를 덮거나, 다음 자동 비우기를 막지 않는다.
MEMO_FIELDS = ("created", "body", "color", "font", "pin", "trash", "purge", "autopurge")
_DELETE_FIELDS = ("purge", "autopurge")
EDIT_FIELDS = ("body", "color", "font", "pin")  # 휴지통에 있는 동안 고쳤는지 볼 때
SETTING_PREFIX = "settings:"                     # 전역 설정 uid (예: settings:user_slots)
SYNCED_SETTINGS = ("user_slots",)               # 허용 목록. 여기 없는 설정은 올리지 않는다


def wall_ms() -> int:
    return int(time.time() * 1000)


# ----- HLC -----
def parse_hlc(stamp: str) -> tuple[int, int, str]:
    l, c, device = stamp.split(".", 2)
    return int(l), int(c), device


def format_hlc(l: int, c: int, device: str) -> str:
    return f"{l:015d}.{c:06d}.{device}"


class HLC:
    """(벽시계 ms, 카운터, device). 비교는 이 순서의 사전순."""

    def __init__(self, device: str, wall: Callable[[], int] = wall_ms, l: int = 0, c: int = 0) -> None:
        self.device, self.wall, self.l, self.c = device, wall, l, c

    def now(self) -> str:
        """이 PC에서 op를 만들 때."""
        w = self.wall()
        if w > self.l:
            self.l, self.c = w, 0
        else:
            self.c += 1
        return format_hlc(self.l, self.c, self.device)

    def observe(self, stamp: str) -> bool:
        """다른 PC의 op를 받을 때. 받은 시계가 지금보다 하루 넘게 앞서면 True(경고용).
        ponytail: 앞선 시계를 막지는 않는다. 막으면 순서 보장이 깨진다 (설계 3.1)."""
        rl, rc, _ = parse_hlc(stamp)
        w = self.wall()
        nl = max(self.l, rl, w)
        if nl == self.l == rl:
            self.c = max(self.c, rc) + 1
        elif nl == self.l:
            self.c += 1
        elif nl == rl:
            self.c = rc + 1
        else:
            self.c = 0
        self.l = nl
        return rl > w + FAR_AHEAD_MS


def hlc_key(stamp: str) -> tuple[int, int, str]:
    return parse_hlc(stamp)


def hlc_wall(stamp: str) -> int:
    return parse_hlc(stamp)[0]


# ----- Op -----
@dataclass(frozen=True)
class Op:
    id: str              # "<device>:<순번>"
    hlc: str
    uid: str             # 메모 uid 또는 "settings:<key>"
    f: str
    v: object = None
    base: str | None = None  # 덮어쓸 때 알고 있던 직전 op id. autopurge는 근거가 된 trash op id

    @property
    def device(self) -> str:
        return self.id.rsplit(":", 1)[0]

    @property
    def seq(self) -> int:
        return int(self.id.rsplit(":", 1)[1])

    @property
    def hlc_key(self) -> tuple[int, int, str]:
        return parse_hlc(self.hlc)

    def to_json(self) -> str:
        d = {"id": self.id, "hlc": self.hlc, "uid": self.uid, "f": self.f, "v": self.v}
        if self.base:
            d["base"] = self.base
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "Op":
        """Drive에서 읽은 줄. 모양이 틀리면 ValueError (그 줄만 건너뛴다)."""
        d = json.loads(line)
        if not isinstance(d, dict):
            raise ValueError("op is not an object")
        op = cls(d.get("id"), d.get("hlc"), d.get("uid"), d.get("f"), d.get("v"), d.get("base"))
        for name in ("id", "hlc", "uid", "f"):
            if not isinstance(getattr(op, name), str) or not getattr(op, name):
                raise ValueError(f"op.{name}")
        if op.base is not None and not isinstance(op.base, str):
            raise ValueError("op.base")
        op.seq, parse_hlc(op.hlc)  # 형식 확인 (틀리면 ValueError)
        if op.uid.startswith(SETTING_PREFIX):
            if op.uid[len(SETTING_PREFIX):] not in SYNCED_SETTINGS or op.f != "value" or not isinstance(op.v, str):
                raise ValueError("unsynced setting")
        elif op.f not in MEMO_FIELDS or not _VALUE_OK[op.f](op.v):
            raise ValueError(f"op.{op.f} value")
        return op


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _at(v) -> bool:
    return isinstance(v, dict) and _is_int(v.get("at"))


# 받은 op 값의 모양. 틀린 줄은 버린다 (손상된 파일 하나로 앱이 죽지 않게).
_VALUE_OK: dict[str, Callable[[object], bool]] = {
    "created": _at,
    "body": lambda v: isinstance(v, dict) and isinstance(v.get("title"), str) and isinstance(v.get("content"), str),
    "color": lambda v: isinstance(v, str),
    "font": lambda v: isinstance(v, dict) and isinstance(v.get("family"), str) and _is_int(v.get("size")),
    "pin": lambda v: isinstance(v, bool),
    "trash": lambda v: v is None or _at(v),
    "purge": lambda v: v is None,
    "autopurge": lambda v: v is None,
}


def newer(a: Op, b: Op | None) -> bool:
    return b is None or hlc_key(a.hlc) > hlc_key(b.hlc)


# ----- 합치기 -----
@dataclass(frozen=True)
class Decision:
    apply: bool                  # r을 새 head로 삼는가
    loser: Op | None = None      # 충돌로 진 body op — 그 내용을 이전 버전에 남긴다


def is_ancestor(op_id: str, start_base: str | None, chain: dict[str, str | None]) -> bool:
    """op_id가 start_base에서 base를 따라 올라간 길 위에 있는가.
    기록이 끊기면 모르는 것이므로 False(동시 수정으로 본다, 설계 3.2)."""
    cur, seen = start_base, set()
    while cur is not None and cur not in seen:
        if cur == op_id:
            return True
        seen.add(cur)
        if cur not in chain:
            return False
        cur = chain[cur]
    return False


def decide(head: Op | None, r: Op, chain: dict[str, str | None]) -> Decision:
    """받은 op r과 지금 head를 비교한다. chain은 body op의 {id: base} 기록."""
    if head is not None and head.id == r.id:
        return Decision(False)
    if newer(r, head):
        if head is None or r.f != "body" or is_ancestor(head.id, r.base, chain):
            return Decision(True)
        return Decision(True, None if head.v == r.v else head)  # 동시 수정: 지금 내용이 졌다
    if r.f != "body" or is_ancestor(r.id, head.base, chain):
        return Decision(False)
    return Decision(False, None if head.v == r.v else r)  # 동시 수정: 받은 내용이 졌다


# ----- 메모의 지금 모습 -----
@dataclass
class MemoState:
    uid: str
    title: str = ""
    content: str = ""
    color: str | None = None        # None이면 DB 기본값
    font_family: str = ""
    font_size: int = 0
    pinned: bool = False
    trashed_at: int | None = None   # UTC ms. None이면 휴지통 아님
    created_at: int | None = None   # UTC ms


def _auto_purge_valid(purge: Op, heads: dict[str, Op], now_ms: int) -> bool:
    trash = heads.get("trash")
    if trash is None or trash.id != purge.base or not trash.v:
        return False  # 그 사이 되살렸거나 다시 넣었다
    if any(newer(heads[f], trash) for f in EDIT_FIELDS if f in heads):
        return False  # 휴지통에 있는 동안 고쳤다
    trashed_at = int(trash.v["at"])
    return now_ms >= trashed_at + (TRASH_DAYS - CLOCK_SLACK_DAYS) * DAY_MS


def materialize(uid: str, heads: dict[str, Op], now_ms: int) -> MemoState | None:
    """None이면 이 PC에 메모가 없어야 한다(영구 삭제됨)."""
    auto = heads.get("autopurge")
    if auto is not None and _auto_purge_valid(auto, heads, now_ms):
        return None  # 무효(되살림·수정)이거나 이 PC 시계로 아직 이르면 아래로 — 휴지통에 그대로
    purge = heads.get("purge")
    if purge is not None and not ("body" in heads and newer(heads["body"], purge)):
        return None
    if not any(f in heads for f in MEMO_FIELDS if f not in _DELETE_FIELDS):
        return None
    m = MemoState(uid)
    if "body" in heads:
        v = heads["body"].v or {}
        m.title, m.content = str(v.get("title", "")), str(v.get("content", ""))
    if "color" in heads:
        m.color = heads["color"].v
    if "font" in heads:
        v = heads["font"].v or {}
        m.font_family, m.font_size = str(v.get("family", "")), int(v.get("size", 0))
    if "pin" in heads:
        m.pinned = bool(heads["pin"].v)
    if "created" in heads:
        m.created_at = int((heads["created"].v or {}).get("at", 0)) or None
    trash = heads.get("trash")
    if trash is not None and trash.v:
        m.trashed_at = int(trash.v["at"])
    if purge is not None and m.trashed_at is None and not ("trash" in heads and newer(heads["trash"], purge)):
        # 직접 영구 삭제했는데 다른 PC가 모르고 고쳤다 → 휴지통에 둔다. 그 뒤에 되살렸으면 그대로.
        # ponytail: 이 경우 trash op가 없어 30일 자동 비우기 대상이 아니다. 사용자가 직접 지우면 된다.
        m.trashed_at = hlc_wall(purge.hlc)
    return m


def auto_purge_due(heads: dict[str, Op], now_ms: int) -> Op | None:
    """이 PC가 autopurge op(base=trash op id)를 만들어야 하면 그 근거 trash op를 돌려준다.
    조건: 휴지통에 들어간 지(동기화된 시각) 30일, 그 사이 되살림·수정 없음 (설계 3.4)."""
    trash = heads.get("trash")
    if trash is None or not trash.v:
        return None
    if "autopurge" in heads and heads["autopurge"].base == trash.id:
        return None  # 이미 이 휴지통 기간에 대해 만들었다
    if any(newer(heads[f], trash) for f in EDIT_FIELDS if f in heads):
        return None
    if now_ms < int(trash.v["at"]) + TRASH_DAYS * DAY_MS:
        return None
    return trash
