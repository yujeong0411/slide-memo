"""올리기·받기 (설계 2장). 전송 방식(LocalFolderTransport, 이후 DriveTransport)만 알고 Drive는 모른다.

파일 (모두 이 PC만 쓴다):
  dev_<device>.json         PC 이름, 로그 조각 목록 [{"n", "first", "last"}]
  log_<device>_<n>.jsonl    op 한 줄씩. 현재 조각을 통째로 다시 올리고, 크면 다음 조각을 연다
쓰는 순서: 조각 → dev 파일 → 로컬에 '올림' 표시. 중간에 꺼지면 다음에 같은 op를 다시 올린다
(받는 쪽은 PC별 순번 커서로 거르므로 두 번 받아도 같다).
"""
from __future__ import annotations

import json

from sync.core import Op
from sync.store import SyncStore

SEG_MAX_LINES = 500
SEG_MAX_BYTES = 1_000_000


class Syncer:
    def __init__(self, store: SyncStore, transport, name: str = "PC") -> None:
        self.store, self.transport, self.name = store, transport, name

    def sync(self) -> list[tuple[str, bool]]:
        """차이 맞추기 → 받기 → 올리기. 충돌 목록(uid, 진 쪽이 이 PC의 내용인가)을 돌려준다."""
        self.store.reconcile()
        conflicts = self.pull()
        self.push()
        return conflicts

    # ----- 올리기 -----
    def push(self) -> int:
        st = self.store
        if not st.connected:
            return 0
        st.reconcile()
        if not st.pending():
            return 0
        dev = st.device
        segs = st.get_json("segments", [])
        start = segs[-1]["first"] if segs and not segs[-1].get("closed") else None
        if start is None:
            start = st.conn.execute("SELECT MIN(seq) FROM sync_outbox WHERE uploaded = 0").fetchone()[0]
            segs.append({"n": (segs[-1]["n"] + 1) if segs else 1, "first": start})
        lines = [r[0] for r in st.conn.execute(
            "SELECT op FROM sync_outbox WHERE seq >= ? ORDER BY seq", (start,))]
        data = ("\n".join(lines) + "\n").encode("utf-8")
        last = Op.from_json(lines[-1]).seq
        seg = segs[-1]
        seg["last"] = last
        self.transport.write(f"log_{dev}_{seg['n']}.jsonl", data)
        info = {"device": dev, "name": self.name,
                "segments": [{k: s[k] for k in ("n", "first", "last")} for s in segs]}
        self.transport.write(f"dev_{dev}.json", json.dumps(info).encode("utf-8"))
        with st.conn:
            st.conn.execute("UPDATE sync_outbox SET uploaded = 1 WHERE seq <= ?", (last,))
            if len(lines) >= SEG_MAX_LINES or len(data) >= SEG_MAX_BYTES:
                seg["closed"] = True  # 다음 올리기는 새 조각에
            st.set_json("segments", segs)
        return len(lines)

    # ----- 받기 -----
    def pull(self) -> list[tuple[str, bool]]:
        """다른 PC의 새 op를 모두 모아 한 트랜잭션으로 적용한다 (커서도 함께)."""
        st = self.store
        if not st.connected:
            return []
        files = self.transport.list()
        new_ops: list[Op] = []
        cursors: dict[str, tuple[int, str]] = {}
        for name, version in files.items():
            if not (name.startswith("dev_") and name.endswith(".json")):
                continue
            dev = name[4:-5]
            applied, seen_version = st.cursor(dev)
            if dev == st.device or version == seen_version:
                continue
            try:
                info = json.loads(self.transport.read(name))
                segments = [s for s in info["segments"] if int(s["last"]) > applied]
            except (ValueError, KeyError, TypeError):
                continue  # 망가진 dev 파일은 건너뛴다 (다음에 고쳐 올라오면 받는다)
            top, complete = applied, True
            for s in segments:
                log = f"log_{dev}_{int(s['n'])}.jsonl"
                if log not in files:
                    complete = False
                    break  # 조각이 아직 안 보이면 여기까지만 (순번 구멍을 만들지 않는다)
                for line in self.transport.read(log).decode("utf-8", "replace").splitlines():
                    try:
                        op = Op.from_json(line)
                    except (ValueError, KeyError, TypeError):
                        continue  # ponytail: 망가진 줄은 버린다. 같은 PC가 다시 쓰지 않으므로 영영 빠진다.
                    if op.device == dev and op.seq > applied:
                        new_ops.append(op)
                        top = max(top, op.seq)
            cursors[dev] = (top, version if complete else None)  # 덜 읽었으면 다음에 다시 읽는다
        if not new_ops and not cursors:
            return []
        with st.conn:
            conflicts = st.apply_remote(new_ops)
            for dev, (top, version) in cursors.items():
                st.set_cursor(dev, top, version)
            st.refresh_pending_purges()
        return conflicts
