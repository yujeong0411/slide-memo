"""올리기·받기 (설계 2장, 3.5). 전송 방식(LocalFolderTransport, 이후 DriveTransport)만 알고 Drive는 모른다.

파일 (dev_·log_는 그 PC만 쓴다):
  dev_<device>.json         PC 이름, 로그 조각 목록 [{"n", "first", "last"}], 너무 커서 못 올린 그림
  log_<device>_<n>.jsonl    op 한 줄씩. 현재 조각을 통째로 다시 올리고, 크면 다음 조각을 연다
  img_<sha256>.png          그림. 이름이 내용 해시라 누가 올려도 같다
쓰는 순서: 그림 → 조각 → dev 파일 → 로컬에 '올림' 표시. 중간에 꺼지면 다음에 같은 op를 다시 올린다
(받는 쪽은 PC별 순번 커서로 거르므로 두 번 받아도 같다). 기록이 그림보다 먼저 보이는 일은 없다.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import database
from sync import images
from sync.core import DAY_MS, Op
from sync.store import SyncStore

SEG_MAX_LINES = 500
SEG_MAX_BYTES = 1_000_000
IMAGE_KEEP_DAYS = 180   # 안 쓰는 그림을 지우기까지 (영구 삭제 기록 보관 기간과 같다, 설계 2.3)
CLEANUP_EVERY_MS = DAY_MS


class Syncer:
    def __init__(self, store: SyncStore, transport, name: str = "PC") -> None:
        self.store, self.transport, self.name = store, transport, name
        self.arrived: list[Path] = []  # 마지막 받기에서 새로 받은 그림 (열린 메모를 다시 그릴 때)

    def sync(self) -> list[tuple[str, bool]]:
        """차이 맞추기 → 받기 → 올리기 → (하루 한 번) 안 쓰는 그림 정리.
        충돌 목록(uid, 진 쪽이 이 PC의 내용인가)을 돌려준다."""
        self.store.reconcile()
        conflicts = self.pull()
        self.push()
        self.cleanup_images()
        return conflicts

    # ----- 올리기 -----
    def push(self) -> int:
        st = self.store
        if not st.connected:
            return 0
        st.reconcile()
        too_big = self._upload_images(self.transport.list())
        too_big_changed = too_big != st.get_json("too_big_local", [])
        if not st.pending() and not too_big_changed:
            return 0
        dev = st.device
        segs = st.get_json("segments", [])
        lines: list[str] = []
        if st.pending():
            start = segs[-1]["first"] if segs and not segs[-1].get("closed") else None
            if start is None:
                start = st.conn.execute("SELECT MIN(seq) FROM sync_outbox WHERE uploaded = 0").fetchone()[0]
                segs.append({"n": (segs[-1]["n"] + 1) if segs else 1, "first": start})
            lines = [r[0] for r in st.conn.execute(
                "SELECT op FROM sync_outbox WHERE seq >= ? ORDER BY seq", (start,))]
            data = ("\n".join(lines) + "\n").encode("utf-8")
            segs[-1]["last"] = Op.from_json(lines[-1]).seq
            self.transport.write(f"log_{dev}_{segs[-1]['n']}.jsonl", data)
        info = {"device": dev, "name": self.name, "too_big": too_big,
                "segments": [{k: s[k] for k in ("n", "first", "last")} for s in segs]}
        self.transport.write(f"dev_{dev}.json", json.dumps(info).encode("utf-8"))
        with st.conn:
            if lines:
                st.conn.execute("UPDATE sync_outbox SET uploaded = 1 WHERE seq <= ?", (segs[-1]["last"],))
                if len(lines) >= SEG_MAX_LINES or len(data) >= SEG_MAX_BYTES:
                    segs[-1]["closed"] = True  # 다음 올리기는 새 조각에
            st.set_json("segments", segs)
            st.set_json("too_big_local", too_big)
        return len(lines)

    def _upload_images(self, files: dict[str, str]) -> list[str]:
        """이 PC 메모가 쓰는 그림 중 Drive에 없는 것을 올린다. 기록에 새로 쓴 그림만이 아니라 전부 본다 —
        다른 PC가 안 쓰는 그림으로 보고 지웠어도 여기서 다시 올라간다. 너무 커서 못 올린 해시 목록을 돌려준다."""
        too_big = []
        with self.store.conn:  # 해시 기억(sync_image)을 저장
            refs = self.store.local_image_refs()
        for sha, path in sorted(refs.items()):
            if f"img_{sha}.png" in files or not path.exists():
                continue
            size = path.stat().st_size
            if size > images.MAX_IMAGE_BYTES:
                too_big.append(sha)
                continue
            write = self.transport.write_large if size > images.LARGE_UPLOAD_BYTES else self.transport.write
            write(f"img_{sha}.png", path.read_bytes())
        return too_big

    # ----- 받기 -----
    def pull(self) -> list[tuple[str, bool]]:
        """다른 PC의 새 op를 모두 모아 한 트랜잭션으로 적용한다 (커서도 함께). 그다음 빠진 그림을 받는다."""
        st = self.store
        self.arrived = []
        if not st.connected:
            return []
        files = self.transport.list()
        new_ops: list[Op] = []
        cursors: dict[str, tuple[int, str]] = {}
        remote_big = st.get_json("too_big_remote", {})
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
                remote_big[dev] = [x for x in info.get("too_big", []) if isinstance(x, str)]
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
                        continue  # ponytail: 망가진 줄은 버린다. 같은 PC가 다시 쓰지 않으므로 그 op는 빠진다.
                    if op.device == dev and op.seq > applied:
                        new_ops.append(op)
                        top = max(top, op.seq)
            cursors[dev] = (top, version if complete else None)  # 덜 읽었으면 다음에 다시 읽는다
        conflicts: list[tuple[str, bool]] = []
        if new_ops or cursors:
            with st.conn:
                conflicts = st.apply_remote(new_ops)
                for dev, (top, version) in cursors.items():
                    st.set_cursor(dev, top, version)
                st.set_json("too_big_remote", remote_big)
                st.refresh_pending_purges()
        self.arrived = self._download_images(files)
        return conflicts

    def too_big_remote(self) -> set[str]:
        """다른 PC가 너무 커서 못 올린 그림 (그 자리에 다른 안내를 띄운다)."""
        return {sha for shas in self.store.get_json("too_big_remote", {}).values() for sha in shas}

    def _download_images(self, files: dict[str, str]) -> list[Path]:
        """메모가 쓰는데 이 PC에 아직 없는 그림을 받는다. Drive에 아직 없으면 다음 받기에서 다시."""
        arrived = []
        for (html,) in self.store.conn.execute("SELECT content FROM memos").fetchall():
            for path in images.local_paths_in(html, database.IMAGES_DIR):
                sha = images.named_sha(path)
                if sha is None or path.exists() or f"img_{sha}.png" not in files:
                    continue
                data = self.transport.read(f"img_{sha}.png")
                if hashlib.sha256(data).hexdigest() != sha:
                    continue  # 손상된 파일은 쓰지 않는다
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".part")
                tmp.write_bytes(data)
                os.replace(tmp, path)  # 열린 메모가 반쯤 쓴 파일을 읽지 않게
                arrived.append(path)
        if arrived:
            with self.store.conn:
                for p in arrived:
                    self.store.remember_image(p, p.stem)
        return arrived

    # ----- 안 쓰는 그림 정리 -----
    def cleanup_images(self, *, force: bool = False) -> tuple[list[str], list[Path]]:
        """어느 메모(모든 PC, 휴지통 포함)의 지금 본문에도 안 쓰이는 그림을 IMAGE_KEEP_DAYS 동안
        지켜본 뒤 지운다. Drive는 기록(모든 PC의 head)과 이 PC 메모 기준, 이 PC 파일은 거기에 이 PC의
        이전 버전까지 더한 기준. 지운 (Drive 그림 해시, 이 PC 파일)을 돌려준다.
        ponytail: '안 쓰임'을 처음 본 시각은 PC마다 따로 센다. 다른 PC가 아직 안 올린 기록이 그림을
        쓰고 있었다면, 그 PC가 올릴 때 _upload_images가 다시 올린다."""
        st = self.store
        if not st.connected:
            return [], []
        now = st.wall()
        if not force and now - int(st._get("img_cleanup_at", "0")) < CLEANUP_EVERY_MS:
            return [], []
        keep_ms = IMAGE_KEEP_DAYS * DAY_MS
        with st.conn:
            local_refs = st.local_image_refs(versions=True)
            used = st.head_image_refs() | set(st.local_image_refs())
        # Drive
        orphans = st.get_json("img_orphans_drive", {})
        gone_drive = []
        drive_shas = {n[4:-4] for n in self.transport.list() if n.startswith("img_") and n.endswith(".png")}
        for sha in drive_shas:
            if sha in used:
                orphans.pop(sha, None)
            elif now - orphans.setdefault(sha, now) >= keep_ms:
                self.transport.delete(f"img_{sha}.png")
                orphans.pop(sha)
                gone_drive.append(sha)
        orphans = {k: v for k, v in orphans.items() if k in drive_shas}
        # 이 PC 파일
        local_used = used | set(local_refs)
        lorphans = st.get_json("img_orphans_local", {})
        gone_local = []
        present = set()
        for path in sorted(database.IMAGES_DIR.glob("*.png")) if database.IMAGES_DIR.exists() else []:
            key = str(path)
            present.add(key)
            sha = st.image_sha(path)
            if sha in local_used:
                lorphans.pop(key, None)
            elif now - lorphans.setdefault(key, now) >= keep_ms:
                path.unlink(missing_ok=True)
                lorphans.pop(key)
                gone_local.append(path)
        lorphans = {k: v for k, v in lorphans.items() if k in present}
        with st.conn:
            for p in gone_local:
                st.conn.execute("DELETE FROM sync_image WHERE path = ?", (str(p.resolve()),))
            st.set_json("img_orphans_drive", orphans)
            st.set_json("img_orphans_local", lorphans)
            st._set("img_cleanup_at", now)
        return gone_drive, gone_local
