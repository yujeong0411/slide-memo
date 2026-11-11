"""로컬 DB의 동기화 기록 (docs/sync-design.md 3장, 11장).

변경 기록(op)은 메모를 고칠 때마다 남기지 않는다. 대신 reconcile()이 "마지막으로 기록한 상태"
(sync_head: 필드마다 이긴 op)와 지금 memos 표를 비교해서, 다른 필드만 op로 만든다.
이렇게 하면 기록을 놓칠 길이 하나도 없다.
  - 처음 연결: head가 없으니 모든 메모가 "다름" → 전부 한 번 올라간다
  - 끊었다 다시 연결: head는 남아 있으니 끊긴 동안 고친 것만 "다름"
  - 2.0.x로 되돌려 고침: 2.0.x는 head를 모르지만 memos 표가 달라져 있으니 켤 때 잡힌다
  - 고치다가 앱이 꺼짐: 다음 reconcile에서 다시 비교하므로 잃지 않는다
reconcile은 한 트랜잭션이다. 중간에 실패하면 op·head·시계가 전부 취소된다.

다른 PC의 op는 apply_remote()가 받는다. head를 바꾸고 memos 표를 head로 다시 계산해 쓰므로,
적용 뒤 reconcile은 아무것도 만들지 않는다 (주고받기가 되풀이되지 않는다).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import database
from database import DEFAULT_COLOR, VERSION_KEEP
from sync import images
from sync.core import (
    AUTOPURGE_HIDE_DAYS, DAY_MS, HLC, PURGE_KEEP_DAYS, MemoState, Op, SETTING_PREFIX, SYNCED_SETTINGS,
    decide, hlc_wall, materialize, wall_ms,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- 필드마다 지금 이긴 op (op는 JSON 한 줄). 메모의 '마지막으로 기록한 상태'다.
CREATE TABLE IF NOT EXISTS sync_head (uid TEXT NOT NULL, f TEXT NOT NULL, op TEXT NOT NULL, PRIMARY KEY (uid, f));
-- 이 PC가 만든 op. uploaded=0이면 아직 Drive에 안 올라갔다.
CREATE TABLE IF NOT EXISTS sync_outbox (seq INTEGER PRIMARY KEY, op TEXT NOT NULL, uploaded INTEGER NOT NULL DEFAULT 0);
-- body op의 base 사슬 (동시 수정 판정용, core.is_ancestor)
CREATE TABLE IF NOT EXISTS sync_body_chain (op_id TEXT PRIMARY KEY, base TEXT);
-- 다른 PC마다 어디까지 적용했는지. 한 PC의 op는 순번대로 오므로 이것만으로 중복을 거른다.
CREATE TABLE IF NOT EXISTS sync_cursor (device TEXT PRIMARY KEY, applied_seq INTEGER NOT NULL, version TEXT);
-- 이 PC 그림 파일의 해시 (크기·수정 시각이 같으면 다시 읽지 않는다)
CREATE TABLE IF NOT EXISTS sync_image (path TEXT PRIMARY KEY, sha TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_sync_image_sha ON sync_image(sha);
"""


_EMPTY_BODY = {"title": "", "content": ""}


def local_iso_to_ms(text: str | None) -> int:
    """DB의 로컬 시각 문자열(시간대 없음) → UTC ms. 읽을 수 없으면 지금."""
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except (TypeError, ValueError):
        return wall_ms()


def ms_to_local_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")


def memo_fields(row) -> dict[str, object]:
    """memos 한 줄 → 동기화 필드 값. created·trash는 따로 다룬다."""
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
        "color": s.color or DEFAULT_COLOR,
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

    def get_json(self, key: str, default):
        raw = self._get(key)
        return json.loads(raw) if raw else default

    def set_json(self, key: str, value) -> None:
        self._set(key, json.dumps(value))

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
        """기록을 비운다. device도 새로 만든다 — 같은 device로 순번을 1부터 다시 쓰면, 옛 계정 Drive에
        남은 같은 순번의 파일 때문에 다른 PC가 새 op를 '이미 받음'으로 걸러 버린다."""
        for table in ("sync_head", "sync_outbox", "sync_body_chain", "sync_cursor"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM sync_state WHERE key NOT IN ('account', 'connected')")

    def _clock(self) -> HLC:
        return HLC(self.device, self.wall, int(self._get("hlc_l", "0")), int(self._get("hlc_c", "0")))

    def _save_clock(self, clock: HLC) -> None:
        self._set("hlc_l", clock.l)
        self._set("hlc_c", clock.c)

    # ----- head -----
    def heads(self) -> dict[str, dict[str, Op]]:
        out: dict[str, dict[str, Op]] = {}
        for uid, f, op in self.conn.execute("SELECT uid, f, op FROM sync_head"):
            out.setdefault(uid, {})[f] = Op.from_json(op)
        return out

    def heads_of(self, uid: str) -> dict[str, Op]:
        return {f: Op.from_json(op) for f, op in self.conn.execute(
            "SELECT f, op FROM sync_head WHERE uid = ?", (uid,))}

    def _put_head(self, op: Op, line: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO sync_head (uid, f, op) VALUES (?, ?, ?) "
            "ON CONFLICT(uid, f) DO UPDATE SET op = excluded.op", (op.uid, op.f, line or op.to_json()),
        )

    def pending(self) -> list[Op]:
        return [Op.from_json(r[0]) for r in self.conn.execute(
            "SELECT op FROM sync_outbox WHERE uploaded = 0 ORDER BY seq")]

    # ----- 차이 맞추기 -----
    def reconcile(self) -> list[Op]:
        """지금 DB와 마지막 기록의 차이를 op로 만든다. 연결 안 했으면 아무것도 안 한다."""
        if not self.connected:
            return []
        with self.conn:  # 한 트랜잭션: 중간에 실패하면 전부 취소
            clock = self._clock()
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
            local_only = set(self.get_json("local_only", []))
            for row in self.conn.execute("SELECT * FROM memos").fetchall():
                uid = row["uid"]
                if uid in local_only:
                    if row["deleted_at"] is not None:
                        continue  # 오래 꺼져 있던 PC에만 남은 메모: 휴지통에 있는 동안은 올리지 않는다
                    local_only.discard(uid)  # 되살렸다 → 새 메모처럼 전부 올린다 (기록이 없으므로)
                seen.add(uid)
                h = heads.get(uid, {})
                state = materialize(uid, h, now) if h else None
                if "created" not in h:
                    emit(uid, "created", {"at": local_iso_to_ms(row["created_at"])})
                current, recorded = memo_fields(row), _effective(state)
                current["body"]["content"] = self.portable(row["content"])
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
            self._save_clock(clock)
            alive = {r[0] for r in self.conn.execute("SELECT uid FROM memos")}
            self.set_json("local_only", sorted(local_only & alive))
            return made

    def _record(self, op: Op) -> None:
        line = op.to_json()
        self.conn.execute("INSERT INTO sync_outbox (seq, op) VALUES (?, ?)", (op.seq, line))
        self._put_head(op, line)
        if op.f == "body":
            self.conn.execute("INSERT OR REPLACE INTO sync_body_chain (op_id, base) VALUES (?, ?)",
                              (op.id, op.base))

    # ----- 다른 PC의 op 받기 -----
    def cursor(self, device: str) -> tuple[int, str | None]:
        row = self.conn.execute(
            "SELECT applied_seq, version FROM sync_cursor WHERE device = ?", (device,)).fetchone()
        return (row[0], row[1]) if row else (0, None)

    def set_cursor(self, device: str, applied_seq: int, version: str | None) -> None:
        self.conn.execute(
            "INSERT INTO sync_cursor (device, applied_seq, version) VALUES (?, ?, ?) "
            "ON CONFLICT(device) DO UPDATE SET applied_seq = excluded.applied_seq, version = excluded.version",
            (device, applied_seq, version),
        )

    def apply_remote(self, ops: list[Op]) -> list[tuple[str, bool]]:
        """다른 PC의 op들을 적용한다. 호출하는 쪽이 트랜잭션을 연다(커서와 함께 커밋).
        HLC 순으로 적용하고 body 사슬을 먼저 모두 넣는다 — 오래 꺼져 있던 PC가 여러 PC의 op를
        한꺼번에 받을 때, 아직 안 넣은 다른 PC의 op를 거쳐 이어 쓴 것을 동시 수정으로 오판하지 않게.
        충돌로 진 내용은 이 PC의 이전 버전에 넣고, (uid, 진 쪽이 이 PC의 내용인가)를 돌려준다."""
        ops = sorted(ops, key=lambda o: o.hlc_key)
        for op in ops:
            if op.f == "body":
                self.conn.execute("INSERT OR IGNORE INTO sync_body_chain (op_id, base) VALUES (?, ?)",
                                  (op.id, op.base))
        chain = dict(self.conn.execute("SELECT op_id, base FROM sync_body_chain").fetchall())
        clock = self._clock()
        conflicts: list[tuple[str, bool]] = []
        touched: list[str] = []
        losers: dict[str, list[Op]] = {}
        for op in ops:
            clock.observe(op.hlc)
            d = decide(self.heads_of(op.uid).get(op.f), op, chain)
            if d.apply:
                self._put_head(op)
            if d.loser is not None:
                losers.setdefault(op.uid, []).append(d.loser)
                conflicts.append((op.uid, d.loser.device == self.device))
            if op.uid not in touched:
                touched.append(op.uid)
        self._save_clock(clock)
        for uid in touched:
            self.write_memo(uid)
        for uid, lost in losers.items():
            row = self.conn.execute("SELECT id FROM memos WHERE uid = ?", (uid,)).fetchone()
            if row is not None:
                for op in lost:
                    self._add_version(row[0], op.v)
        return conflicts

    def refresh_pending_purges(self) -> None:
        """자동 비우기는 이 PC 시계로 날짜가 차야 적용된다. 시간이 지나면 다시 계산한다."""
        for (uid,) in self.conn.execute("SELECT uid FROM sync_head WHERE f = 'autopurge'").fetchall():
            self.write_memo(uid)

    def write_memo(self, uid: str) -> None:
        """head로 계산한 모습을 memos 표에 쓴다 (없으면 만들고, 지워졌으면 지운다)."""
        heads = self.heads_of(uid)
        row = self.conn.execute("SELECT id FROM memos WHERE uid = ?", (uid,)).fetchone()
        if uid.startswith(SETTING_PREFIX):
            if "value" in heads:
                self.conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (uid[len(SETTING_PREFIX):], heads["value"].v),
                )
            return
        st = materialize(uid, heads, self.wall())
        if st is None:
            if row is not None:
                self.conn.execute("DELETE FROM memos WHERE id = ?", (row[0],))  # 이전 버전은 CASCADE
            return
        now = self.wall()
        edited = [hlc_wall(heads[f].hlc) for f in ("body", "color", "font") if f in heads]
        values = (
            st.title, images.to_local(st.content, self.image_path_for), st.color or DEFAULT_COLOR, int(st.pinned),
            ms_to_local_iso(st.trashed_at) if st.trashed_at is not None else None,
            st.font_family, st.font_size,
            ms_to_local_iso(st.created_at or now), ms_to_local_iso(max(edited) if edited else now),
        )
        if row is None:
            self.conn.execute(
                "INSERT INTO memos (title, content, color, is_pinned, deleted_at, font_family, font_size,"
                " created_at, updated_at, uid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values + (uid,))
        else:
            self.conn.execute(
                "UPDATE memos SET title = ?, content = ?, color = ?, is_pinned = ?, deleted_at = ?,"
                " font_family = ?, font_size = ?, created_at = ?, updated_at = ? WHERE id = ?",
                values + (row[0],))

    def _add_version(self, memo_id: int, v) -> None:
        """충돌로 진 내용을 이전 버전에 남긴다 (database.snapshot과 같은 보관 개수)."""
        self.conn.execute(
            "INSERT INTO memo_versions (memo_id, title, content, created_at) VALUES (?, ?, ?, ?)",
            (memo_id, v["title"], v["content"], ms_to_local_iso(self.wall())),
        )
        self.conn.execute(
            "DELETE FROM memo_versions WHERE memo_id = ? AND id NOT IN"
            " (SELECT id FROM memo_versions WHERE memo_id = ? ORDER BY id DESC LIMIT ?)",
            (memo_id, memo_id, VERSION_KEEP),
        )

    # ----- 그림 (설계 3.5) -----
    def portable(self, html: str) -> str:
        return images.to_portable(html, database.IMAGES_DIR, self.image_sha)

    def image_sha(self, path: Path) -> str | None:
        """그림 파일의 해시. 받은 그림(<sha>.png)은 이름이 해시라 파일이 아직 없어도 안다."""
        named = images.named_sha(path)
        if named:
            return named
        try:
            st = path.stat()
        except OSError:
            return None
        key = str(path.resolve())
        row = self.conn.execute("SELECT sha, size, mtime_ns FROM sync_image WHERE path = ?", (key,)).fetchone()
        if row and row[1] == st.st_size and row[2] == st.st_mtime_ns:
            return row[0]
        sha = images.sha256_file(path)
        self.remember_image(path, sha)
        return sha

    def remember_image(self, path: Path, sha: str) -> None:
        st = path.stat()
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_image (path, sha, size, mtime_ns) VALUES (?, ?, ?, ?)",
            (str(path.resolve()), sha, st.st_size, st.st_mtime_ns))

    def image_path_for(self, sha: str) -> Path:
        """이 PC에 같은 그림이 이미 있으면 그 파일(원래 붙여 넣은 img_….png 포함), 없으면 받을 자리."""
        for (path,) in self.conn.execute("SELECT path FROM sync_image WHERE sha = ?", (sha,)):
            if Path(path).exists():
                return Path(path)
        return database.IMAGES_DIR / f"{sha}.png"

    def local_image_refs(self, *, versions: bool = False) -> dict[str, Path]:
        """이 PC의 메모(휴지통 포함, versions=True면 이전 버전도)가 쓰는 그림 {sha: 경로}."""
        out: dict[str, Path] = {}
        tables = ["SELECT content FROM memos"] + (["SELECT content FROM memo_versions"] if versions else [])
        for sql in tables:
            for (html,) in self.conn.execute(sql):
                for p in images.local_paths_in(html, database.IMAGES_DIR):
                    sha = self.image_sha(p)
                    if sha:
                        out.setdefault(sha, p)
        return out

    def head_image_refs(self) -> set[str]:
        """기록상 지금 있는 메모(휴지통 포함, 모든 PC)의 본문이 쓰는 그림."""
        now = self.wall()
        out: set[str] = set()
        for uid, h in self.heads().items():
            if uid.startswith(SETTING_PREFIX) or "body" not in h:
                continue
            if materialize(uid, h, now) is not None:
                out |= images.shas_in(h["body"].v["content"])
        return out

    # ----- 지운 메모 잊기 (설계 2.3) -----
    def forget_deleted(self) -> bool:
        """영구 삭제된 메모의 내용을 기록에서 지운다.
        - 직접 영구 삭제: 바로 본문을 비운다 (id·시계는 남겨 판정에 쓴다)
        - 자동 비우기: 되살림에 대비해 AUTOPURGE_HIDE_DAYS 뒤에 비운다
        - 둘 다 PURGE_KEEP_DAYS가 지나면 그 메모의 기록을 통째로 잊는다 (이 PC가 쓴 기록도)
        이 PC가 올린 기록이 바뀌었으면 True (Drive의 기록도 압축으로 바꿔야 한다)."""
        now = self.wall()
        changed = False
        with self.conn:
            for uid, h in self.heads().items():
                if uid.startswith(SETTING_PREFIX) or materialize(uid, h, now) is not None:
                    continue
                dels = [h[f] for f in ("purge", "autopurge") if f in h]
                if not dels:
                    continue
                age = now - max(hlc_wall(o.hlc) for o in dels)
                if age >= PURGE_KEEP_DAYS * DAY_MS:
                    self.conn.execute("DELETE FROM sync_head WHERE uid = ?", (uid,))
                    changed |= self._drop_outbox(uid)
                    continue
                if "purge" not in h and age < AUTOPURGE_HIDE_DAYS * DAY_MS:
                    continue
                body = h.get("body")
                if body is not None and body.v != _EMPTY_BODY:
                    self._put_head(Op(body.id, body.hlc, uid, "body", dict(_EMPTY_BODY), body.base))
                changed |= self._strip_outbox_body(uid)
        return changed

    def _outbox_rows(self, uid: str | None = None):
        for seq, line, uploaded in self.conn.execute("SELECT seq, op, uploaded FROM sync_outbox").fetchall():
            op = Op.from_json(line)
            if uid is None or op.uid == uid:
                yield seq, op, uploaded

    def _drop_outbox(self, uid: str) -> bool:
        rows = [seq for seq, op, uploaded in self._outbox_rows(uid) if uploaded]
        for seq in rows:
            self.conn.execute("DELETE FROM sync_outbox WHERE seq = ?", (seq,))
        return bool(rows)

    def _strip_outbox_body(self, uid: str) -> bool:
        changed = False
        for seq, op, _ in list(self._outbox_rows(uid)):
            if op.f == "body" and op.v != _EMPTY_BODY:
                bare = Op(op.id, op.hlc, uid, "body", dict(_EMPTY_BODY), op.base)
                self.conn.execute("UPDATE sync_outbox SET op = ? WHERE seq = ?", (bare.to_json(), seq))
                changed = True
        return changed

    def prune_outbox(self) -> None:
        """올린 op는 (메모, 필드)마다 최신 하나만 남긴다 (압축본에 들어갈 것만)."""
        latest: dict[tuple[str, str], int] = {}
        rows = list(self._outbox_rows())
        for seq, op, uploaded in rows:
            key = (op.uid, op.f)
            if key not in latest or seq > latest[key]:
                latest[key] = seq
        for seq, op, uploaded in rows:
            if uploaded and latest[(op.uid, op.f)] != seq:
                self.conn.execute("DELETE FROM sync_outbox WHERE seq = ?", (seq,))

    # ----- 오래 꺼져 있던 PC (설계 3.6) -----
    def alive_uids(self) -> set[str]:
        """이 PC에 있는 메모(휴지통 포함). 이 PC에만 남겨 둔 메모(local_only)는 빼고."""
        local_only = set(self.get_json("local_only", []))
        return {r[0] for r in self.conn.execute("SELECT uid FROM memos")} - local_only

    def set_aside(self, uids: set[str]) -> None:
        """다른 PC에 없는 메모를 이 PC 휴지통으로 옮기고 동기화에서 뺀다. 지우지는 않는다.
        되살리면 새 메모처럼 다시 올라간다 (reconcile)."""
        if not uids:
            return
        now_iso = ms_to_local_iso(self.wall())
        with self.conn:
            for uid in uids:
                self.conn.execute(
                    "UPDATE memos SET deleted_at = COALESCE(deleted_at, ?) WHERE uid = ?", (now_iso, uid))
                self.conn.execute("DELETE FROM sync_head WHERE uid = ?", (uid,))
                for seq, op, uploaded in list(self._outbox_rows(uid)):
                    if not uploaded:
                        self.conn.execute("DELETE FROM sync_outbox WHERE seq = ?", (seq,))
            self.set_json("local_only", sorted(set(self.get_json("local_only", [])) | uids))

    def rebase_device(self) -> None:
        """다른 PC가 이 PC를 목록에서 뺐다 (Drive에 이 PC 파일이 없다). 새 device ID로 바꾸고,
        아직 못 올린 op만 새 ID·새 순번으로 다시 매겨 올린다. 이미 올렸던 op는 뺀 PC가 넘겨받았다."""
        old = self.device
        new = uuid.uuid4().hex[:12]
        with self.conn:
            pending = [(seq, op) for seq, op, uploaded in self._outbox_rows() if not uploaded]
            pending.sort()
            renamed: dict[str, str] = {}
            self.conn.execute("DELETE FROM sync_outbox")
            for i, (_, op) in enumerate(pending, 1):
                nid = f"{new}:{i}"
                renamed[op.id] = nid
                nop = Op(nid, op.hlc, op.uid, op.f, op.v, renamed.get(op.base, op.base))
                self.conn.execute("INSERT INTO sync_outbox (seq, op) VALUES (?, ?)", (i, nop.to_json()))
                head = self.heads_of(op.uid).get(op.f)
                if head is not None and head.id == op.id:
                    self._put_head(nop)
                if op.f == "body":
                    self.conn.execute("INSERT OR REPLACE INTO sync_body_chain (op_id, base) VALUES (?, ?)",
                                      (nid, nop.base))
            for key in ("segments", "snap", "alive_sent", "dev_written_at"):
                self.conn.execute("DELETE FROM sync_state WHERE key = ?", (key,))
            self._set("device", new)
            self._set("seq", len(pending))
            self._set("former_device", old)

    def adopt(self, dev: str) -> int:
        """목록에서 빼는 PC가 쓴 최신 값(head)을 이 PC 기록으로 넘겨받는다. 시계(HLC)와 base는 원래 op
        그대로라, 원래 op를 이미 받은 PC에는 같은 값이라 아무 일도 없고, 못 받은 PC에는 이어 쓰기가 된다."""
        with self.conn:
            seq = int(self._get("seq", "0"))
            n = 0
            for uid, h in self.heads().items():
                for f, op in h.items():
                    if op.device != dev:
                        continue
                    seq += 1
                    self._record(Op(f"{self.device}:{seq}", op.hlc, uid, f, op.v, op.base))
                    n += 1
            self._set("seq", seq)
        return n
