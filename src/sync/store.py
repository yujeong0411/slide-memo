"""로컬 DB의 동기화 기록 (docs/sync-design.md 3장, 11장).

변경 기록(op)은 메모를 고칠 때마다 남기지 않는다. 대신 reconcile()이 "마지막으로 기록한 상태"
(sync_head: 필드마다 이긴 op)와 지금 memos 표를 비교해서, 다른 필드만 op로 만든다.
이렇게 하면 기록을 놓칠 길이 하나도 없다.
  - 처음 연결: head가 없으니 모든 메모가 "다름" → 전부 한 번 올라간다
  - 끊었다 다시 연결: head는 남아 있으니 끊긴 동안 고친 것만 "다름"
  - 2.0.x로 되돌려 고침: 2.0.x는 head를 모르지만 memos 표가 달라져 있으니 켤 때 잡힌다
  - 고치다가 앱이 꺼짐: 다음 reconcile에서 다시 비교하므로 잃지 않는다
reconcile은 한 트랜잭션이다. 중간에 실패하면 op·head·시계가 전부 취소된다.
ponytail: 매번 모든 메모를 훑는다(메모 수천 개, 본문 수 MB까지는 수 ms~수십 ms). 느려지면 updated_at·dirty 표시로 범위를 줄인다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sync.core import (
    HLC, MemoState, Op, SETTING_PREFIX, SYNCED_SETTINGS, materialize, wall_ms,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- 필드마다 지금 이긴 op (op는 JSON 한 줄). 메모의 '마지막으로 기록한 상태'다.
CREATE TABLE IF NOT EXISTS sync_head (uid TEXT NOT NULL, f TEXT NOT NULL, op TEXT NOT NULL, PRIMARY KEY (uid, f));
-- 이 PC가 만든 op. uploaded=0이면 아직 Drive에 안 올라갔다.
CREATE TABLE IF NOT EXISTS sync_outbox (seq INTEGER PRIMARY KEY, op TEXT NOT NULL, uploaded INTEGER NOT NULL DEFAULT 0);
-- body op의 base 사슬 (동시 수정 판정용, core.is_ancestor)
CREATE TABLE IF NOT EXISTS sync_body_chain (op_id TEXT PRIMARY KEY, base TEXT);
"""


def local_iso_to_ms(text: str | None) -> int:
    """DB의 로컬 시각 문자열(시간대 없음) → UTC ms. 읽을 수 없으면 지금."""
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except (TypeError, ValueError):
        return wall_ms()


def memo_fields(row) -> dict[str, object]:
    """memos 한 줄 → 동기화 필드 값. created·trash는 아래에서 따로 다룬다."""
    return {
        "body": {"title": row["title"], "content": row["content"]},
        "color": row["color"],
        "font": {"family": row["font_family"] or "", "size": int(row["font_size"] or 0)},
        "pin": bool(row["is_pinned"]),
    }


def _effective(state: MemoState | None) -> dict[str, object]:
    """head에서 계산한 값. head가 없는 필드는 materialize의 기본값과 같다."""
    s = state or MemoState("")
    return {
        "body": {"title": s.title, "content": s.content},
        "color": s.color,
        "font": {"family": s.font_family, "size": s.font_size},
        "pin": s.pinned,
    }


class SyncStore:
    def __init__(self, conn, wall=wall_ms) -> None:
        self.conn, self.wall = conn, wall
        self.conn.executescript(_SCHEMA)

    # ----- 상태 -----
    def _get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def _set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)),
        )

    @property
    def device(self) -> str | None:
        return self._get("device")

    @property
    def connected(self) -> bool:
        return self._get("connected") == "1"

    def connect(self, account: str) -> None:
        """연결(처음·다시). 다른 계정이면 기록을 비워 그 계정 Drive에 전부 새로 올린다.
        같은 계정이면 head를 그대로 두므로 끊긴 동안 고친 것만 reconcile에 잡힌다."""
        with self.conn:
            if self._get("account") not in (None, account):
                self._reset()
            if self.device is None:
                self._set("device", uuid.uuid4().hex[:12])
            self._set("account", account)
            self._set("connected", "1")

    def disconnect(self, *, drive_wiped: bool = False) -> None:
        """끊기. head는 남긴다(다시 연결 때 비교 기준). Drive를 지웠으면 기준도 없어진다."""
        with self.conn:
            self._set("connected", "0")
            if drive_wiped:
                self._reset()

    def _reset(self) -> None:
        for table in ("sync_head", "sync_outbox", "sync_body_chain"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM sync_state WHERE key IN ('seq', 'hlc_l', 'hlc_c')")

    # ----- head -----
    def heads(self) -> dict[str, dict[str, Op]]:
        out: dict[str, dict[str, Op]] = {}
        for uid, f, op in self.conn.execute("SELECT uid, f, op FROM sync_head"):
            out.setdefault(uid, {})[f] = Op.from_json(op)
        return out

    def pending(self) -> list[Op]:
        return [Op.from_json(r[0]) for r in self.conn.execute(
            "SELECT op FROM sync_outbox WHERE uploaded = 0 ORDER BY seq")]

    # ----- 차이 맞추기 -----
    def reconcile(self) -> list[Op]:
        """지금 DB와 마지막 기록의 차이를 op로 만든다. 연결 안 했으면 아무것도 안 한다."""
        if not self.connected:
            return []
        with self.conn:  # 한 트랜잭션: 중간에 실패하면 전부 취소
            clock = HLC(self.device, self.wall, int(self._get("hlc_l", "0")), int(self._get("hlc_c", "0")))
            seq = int(self._get("seq", "0"))
            heads = self.heads()
            made: list[Op] = []

            def emit(uid: str, f: str, v) -> None:
                nonlocal seq
                head = heads.get(uid, {}).get(f)
                seq += 1
                op = Op(f"{self.device}:{seq}", clock.now(), uid, f, v, head.id if head else None)
                self._record(op)
                heads.setdefault(uid, {})[f] = op
                made.append(op)

            now = self.wall()
            seen: set[str] = set()
            for row in self.conn.execute("SELECT * FROM memos").fetchall():
                uid = row["uid"]
                seen.add(uid)
                h = heads.get(uid, {})
                state = materialize(uid, h, now) if h else None
                if "created" not in h:
                    emit(uid, "created", {"at": local_iso_to_ms(row["created_at"])})
                current, recorded = memo_fields(row), _effective(state)
                for f, v in current.items():
                    if v != recorded[f]:
                        emit(uid, f, v)
                in_trash = row["deleted_at"] is not None
                if in_trash != (state is not None and state.trashed_at is not None):
                    emit(uid, "trash", {"at": local_iso_to_ms(row["deleted_at"])} if in_trash else None)
            for uid, h in heads.items():  # 기록엔 살아 있는데 DB에 없다 → 영구 삭제됨
                if uid in seen or uid.startswith(SETTING_PREFIX):
                    continue
                if materialize(uid, h, now) is not None:
                    emit(uid, "purge", None)
            for key in SYNCED_SETTINGS:
                row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                uid = SETTING_PREFIX + key
                head = heads.get(uid, {}).get("value")
                if row is not None and (head is None or head.v != row[0]):
                    emit(uid, "value", row[0])
            self._set("seq", seq)
            self._set("hlc_l", clock.l)
            self._set("hlc_c", clock.c)
            return made

    def _record(self, op: Op) -> None:
        line = op.to_json()
        self.conn.execute("INSERT INTO sync_outbox (seq, op) VALUES (?, ?)", (op.seq, line))
        self.conn.execute(
            "INSERT INTO sync_head (uid, f, op) VALUES (?, ?, ?) "
            "ON CONFLICT(uid, f) DO UPDATE SET op = excluded.op", (op.uid, op.f, line),
        )
        if op.f == "body":
            self.conn.execute("INSERT OR REPLACE INTO sync_body_chain (op_id, base) VALUES (?, ?)",
                              (op.id, op.base))
