"""올리기·받기·압축 (설계 2장, 3.5, 3.6). 전송 방식(LocalFolderTransport, 이후 DriveTransport)만 알고 Drive는 모른다.

파일 (img_ 말고는 이름의 그 PC만 쓴다):
  dev_<device>.json           PC 이름, 마지막 동기화, 압축본·로그 조각 목록, 다른 PC를 어디까지 받았는지,
                              너무 커서 못 올린 그림
  log_<device>_<첫 순번>.jsonl  op 한 줄씩. 현재 조각을 통째로 다시 올리고, 크면 다음 조각을 연다
  snap_<device>_<n>.json      압축본: (메모, 필드)마다 최신 op만. 영구 삭제한 메모의 본문은 비운다
  alive_<device>.json         이 PC에 있는 메모 목록. 오래 꺼져 있던 PC가 돌아올 때만 쓴다 (3.6)
  img_<sha256>.png            그림. 이름이 내용 해시라 누가 올려도 같다
쓰는 순서: 그림 → 조각 → 메모 목록 → dev 파일 → 로컬에 '올림' 표시. 중간에 꺼지면 다음에 같은 op를
다시 올린다 (받는 쪽은 PC별 순번 커서로 거르므로 두 번 받아도 같다). 기록이 그림보다 먼저 보이지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import database
from sync import images
from sync.core import DAY_MS, PURGE_KEEP_DAYS, Op
from sync.store import SyncStore

SEG_MAX_LINES = 500
SEG_MAX_BYTES = 1_000_000
COMPACT_SEGMENTS = 20          # 조각이 이만큼 쌓이거나
COMPACT_BYTES = 5_000_000      # 합계가 이만큼이면 압축한다
IMAGE_KEEP_DAYS = 180          # 안 쓰는 그림을 지우기까지 (영구 삭제 기록 보관 기간과 같다)
CLEANUP_EVERY_MS = DAY_MS
STALE_DAYS = PURGE_KEEP_DAYS - 10  # 이보다 오래 못 받았으면 '오래 꺼져 있던 PC' (시계 차이 여유 10일)
HEARTBEAT_MS = 3_600_000       # 바뀐 게 없어도 이 간격으로 dev 파일을 다시 써서 마지막 동기화 시각을 알린다


class Syncer:
    def __init__(self, store: SyncStore, transport, name: str = "PC") -> None:
        self.store, self.transport, self.name = store, transport, name
        self.arrived: list[Path] = []  # 마지막 받기에서 새로 받은 그림 (열린 메모를 다시 그릴 때)

    def sync(self) -> list[tuple[str, bool]]:
        """차이 맞추기 → 받기 → (돌아온 PC면 정리) → 올리기 → 잊기·압축 → (하루 한 번) 그림 정리.
        충돌 목록(uid, 진 쪽이 이 PC의 내용인가)을 돌려준다."""
        st = self.store
        if not st.connected:
            return []
        st.reconcile()
        files = self.transport.list()
        returning = self._returning(files)
        if returning == "wiped":
            with st.conn:  # Drive가 비었다: 처음 연결처럼 전부 올린다
                st._reset()
                st._set("device", os.urandom(6).hex())
            st.reconcile()
        conflicts = self.pull(files)
        if returning in ("stale", "removed"):
            self._handle_return(returning)
        st.auto_purge()
        self.push()
        if st.forget_deleted():
            with st.conn:
                st._set("compact_due", "1")
        self.compact()
        self.cleanup_images()
        return conflicts

    # ----- 올리기 -----
    def _dev_info(self, segs: list[dict], too_big: list[str], now: int) -> bytes:
        st = self.store
        cursors = {d: s for d, s in st.conn.execute("SELECT device, applied_seq FROM sync_cursor")}
        return json.dumps({
            "device": st.device, "name": self.name, "last_sync": now, "too_big": too_big,
            "snap": st.get_json("snap", None), "cursors": cursors,
            "segments": [{k: s[k] for k in ("n", "first", "last")} for s in segs],
        }, ensure_ascii=False).encode("utf-8")

    def push(self) -> int:
        st = self.store
        if not st.connected:
            return 0
        st.reconcile()
        too_big = self._upload_images(self.transport.list())
        alive = sorted(st.alive_uids())
        alive_key = hashlib.sha1("\n".join(alive).encode()).hexdigest()
        now = st.wall()
        changed = (
            bool(st.pending()) or too_big != st.get_json("too_big_local", [])
            or alive_key != st._get("alive_sent") or now - int(st._get("dev_written_at", "0")) >= HEARTBEAT_MS
        )
        if not changed:
            return 0
        dev = st.device
        segs = st.get_json("segments", [])
        lines: list[str] = []
        data = b""
        if st.pending():
            if not segs or segs[-1].get("closed"):
                start = st.conn.execute("SELECT MIN(seq) FROM sync_outbox WHERE uploaded = 0").fetchone()[0]
                segs.append({"n": start, "first": start})
            lines = [r[0] for r in st.conn.execute(
                "SELECT op FROM sync_outbox WHERE seq >= ? ORDER BY seq", (segs[-1]["first"],))]
            data = ("\n".join(lines) + "\n").encode("utf-8")
            segs[-1]["last"] = Op.from_json(lines[-1]).seq
            segs[-1]["size"] = len(data)
            self.transport.write(f"log_{dev}_{segs[-1]['n']}.jsonl", data)
        if alive_key != st._get("alive_sent"):
            self.transport.write(f"alive_{dev}.json", json.dumps(alive).encode("utf-8"))
        self.transport.write(f"dev_{dev}.json", self._dev_info(segs, too_big, now))
        with st.conn:
            if lines:
                st.conn.execute("UPDATE sync_outbox SET uploaded = 1 WHERE seq <= ?", (segs[-1]["last"],))
                if len(lines) >= SEG_MAX_LINES or len(data) >= SEG_MAX_BYTES:
                    segs[-1]["closed"] = True  # 다음 올리기는 새 조각에
            st.set_json("segments", segs)
            st.set_json("too_big_local", too_big)
            st._set("alive_sent", alive_key)
            st._set("dev_written_at", now)
        return len(lines)

    # ----- 압축 (설계 2.3) -----
    def compact(self, *, force: bool = False) -> bool:
        """조각이 많거나 크면, 또는 영구 삭제한 메모의 본문을 Drive에서 지워야 하면,
        이 PC의 기록을 (메모, 필드)마다 최신 하나로 줄인 압축본으로 바꾼다.
        순서: 압축본 올림 → dev 파일이 압축본을 가리킴 → 로컬 상태 → 옛 파일 지움.
        어디서 꺼져도 dev 파일은 늘 있는 파일만 가리킨다."""
        st = self.store
        segs = st.get_json("segments", [])
        due = force or st._get("compact_due") == "1" or len(segs) >= COMPACT_SEGMENTS \
            or sum(s.get("size", 0) for s in segs) >= COMPACT_BYTES
        if not st.connected or not due or st.pending():
            return False
        dev = st.device
        with st.conn:
            st.prune_outbox()
        lines = [r[0] for r in st.conn.execute("SELECT op FROM sync_outbox ORDER BY seq")]
        upto = int(st._get("seq", "0"))
        old = st.get_json("snap", None)
        snap = {"n": (old["n"] + 1) if old else 1, "upto": upto}
        self.transport.write(f"snap_{dev}_{snap['n']}.json",
                             json.dumps({"upto": upto, "ops": lines}, ensure_ascii=False).encode("utf-8"))
        with st.conn:
            st.set_json("snap", snap)
            st.set_json("segments", [])
            self.transport.write(f"dev_{dev}.json", self._dev_info([], st.get_json("too_big_local", []), st.wall()))
            st._set("compact_due", "0")
        keep = f"snap_{dev}_{snap['n']}.json"
        for name in self.transport.list():
            if name.startswith((f"log_{dev}_", f"snap_{dev}_")) and name != keep:
                self.transport.delete(name)
        return True

    # ----- 받기 -----
    def _read_ops(self, name: str, dev: str, applied: int) -> list[Op]:
        raw = self.transport.read(name).decode("utf-8", "replace")
        lines = json.loads(raw)["ops"] if name.startswith("snap_") else raw.splitlines()
        out = []
        for line in lines:
            try:
                op = Op.from_json(line)
            except (ValueError, KeyError, TypeError):
                continue  # ponytail: 망가진 줄은 버린다. 같은 PC가 다시 쓰지 않으므로 그 op는 빠진다.
            if op.device == dev and op.seq > applied:
                out.append(op)
        return out

    def pull(self, files: dict[str, str] | None = None) -> list[tuple[str, bool]]:
        """다른 PC의 새 op를 모두 모아 HLC 순으로 한 트랜잭션에 적용한다 (커서도 함께). 그다음 빠진 그림을 받는다."""
        st = self.store
        self.arrived = []
        if not st.connected:
            return []
        files = self.transport.list() if files is None else files
        new_ops: list[Op] = []
        cursors: dict[str, tuple[int, str]] = {}
        remote_big = st.get_json("too_big_remote", {})
        seen_me = st.get_json("remote_cursors", {})
        for name, version in files.items():
            if not (name.startswith("dev_") and name.endswith(".json")):
                continue
            dev = name[4:-5]
            applied, seen_version = st.cursor(dev)
            if dev == st.device or version == seen_version:
                continue
            try:
                info = json.loads(self.transport.read(name))
                snap = info.get("snap")
                segments = [s for s in info["segments"] if int(s["last"]) > applied]
                remote_big[dev] = [x for x in info.get("too_big", []) if isinstance(x, str)]
                seen_me[dev] = int((info.get("cursors") or {}).get(st.device, 0))
            except (ValueError, KeyError, TypeError, AttributeError, FileNotFoundError):
                continue  # 망가지거나 방금 사라진 dev 파일은 건너뛴다 (다음에 다시 본다)
            top, complete = applied, True
            parts = ([f"snap_{dev}_{int(snap['n'])}.json"] if snap and int(snap["upto"]) > applied else []) \
                + [f"log_{dev}_{int(s['n'])}.jsonl" for s in segments]
            for part in parts:
                try:
                    if part not in files:
                        raise FileNotFoundError(part)
                    ops = self._read_ops(part, dev, applied)
                except FileNotFoundError:  # 아직 안 보이거나 그 PC가 방금 압축했다
                    complete = False
                    break  # 여기까지만 (순번 구멍을 만들지 않는다), 다음에 dev 파일부터 다시
                except ValueError:  # 압축본이 망가졌다
                    complete = False
                    break
                new_ops += ops
                top = max([top] + [o.seq for o in ops])
            cursors[dev] = (top, version if complete else None)  # 덜 읽었으면 다음에 다시 읽는다
        conflicts: list[tuple[str, bool]] = []
        with st.conn:
            if new_ops or cursors:
                conflicts = st.apply_remote(new_ops)
                for dev, (top, version) in cursors.items():
                    st.set_cursor(dev, top, version)
            st.set_json("too_big_remote", remote_big)
            st.set_json("remote_cursors", seen_me)
            st.refresh_pending_purges()
            st._set("last_pull_at", st.wall())
        self.arrived = self._download_images(files)
        return conflicts

    # ----- 오래 꺼져 있던 PC, 목록에서 빠진 PC (설계 3.6) -----
    def _returning(self, files: dict[str, str]) -> str | None:
        st = self.store
        uploaded_before = bool(st.get_json("segments", []) or st.get_json("snap", None))
        if uploaded_before and f"dev_{st.device}.json" not in files:
            others = any(n.startswith("dev_") for n in files)
            return "removed" if others else "wiped"
        last = st._get("last_pull_at")
        if last is not None and st.wall() - int(last) >= STALE_DAYS * DAY_MS:
            return "stale"
        return None

    def _handle_return(self, kind: str) -> None:
        """다른 PC의 메모 목록(alive_)에도 없고, 다른 PC가 이미 받아 본 메모는 그 사이 다른 PC에서
        지워진 것이다 (지운 기록은 보관 기간이 지나 사라졌다). 지우지 않고 이 PC 휴지통으로 옮겨
        동기화에서 뺀다. 되살리면 새 메모로 다시 올라간다."""
        st = self.store
        files = self.transport.list()
        known: set[str] = set()
        for name in files:
            if name.startswith("alive_") and name != f"alive_{st.device}.json":
                try:
                    known |= set(json.loads(self.transport.read(name)))
                except (ValueError, TypeError, FileNotFoundError):
                    pass
        seen_upto = max(st.get_json("remote_cursors", {}).values(), default=0)
        if kind == "removed":  # 빼 준 PC가 올라와 있던 기록은 모두 넘겨받았다
            segs = st.get_json("segments", [])
            snap = st.get_json("snap", None)
            seen_upto = max([seen_upto] + [s["last"] for s in segs] + ([snap["upto"]] if snap else []))
        heads = st.heads()
        aside = set()
        for uid in st.alive_uids():
            created = heads.get(uid, {}).get("created")
            if uid in known or created is None:
                continue
            if created.device == st.device and created.seq > seen_upto:
                continue  # 이 PC가 꺼져 있는 동안 새로 쓴 메모 — 다른 PC가 본 적이 없다
            aside.add(uid)
        st.set_aside(aside)
        with st.conn:
            st._set("return_notice", len(aside))
        if kind == "removed":
            st.rebase_device()

    def take_return_notice(self) -> int:
        """돌아온 PC에서 휴지통으로 옮긴 메모 수. 한 번 읽으면 0 (9단계에서 안내를 한 번 띄운다)."""
        st = self.store
        n = int(st._get("return_notice", "0"))
        if n:
            with st.conn:
                st._set("return_notice", 0)
        return n

    # ----- 연결된 PC 목록 -----
    def devices(self) -> list[dict]:
        """Drive의 PC 정보 파일에서 PC 이름과 마지막 동기화 시각(UTC ms)을 읽는다. 이 PC가 맨 앞."""
        out = []
        for name in self.transport.list():
            if not (name.startswith("dev_") and name.endswith(".json")):
                continue
            try:
                info = json.loads(self.transport.read(name))
                out.append({"device": info["device"], "name": str(info.get("name", "")),
                            "last_sync": int(info.get("last_sync", 0)),
                            "is_self": info["device"] == self.store.device})
            except (ValueError, KeyError, TypeError, FileNotFoundError):
                continue
        return sorted(out, key=lambda d: (not d["is_self"], -d["last_sync"]))

    def remove_device(self, dev: str) -> bool:
        """다른 PC를 목록에서 뺀다. 그 PC 기록을 먼저 전부 받고, 그 PC가 쓴 최신 값을 이 PC 기록으로
        넘겨받아 올린 뒤에 그 PC 파일을 지운다 — 아직 그 PC 기록을 못 받은 PC도 잃지 않는다.
        그 PC 기록을 다 받지 못했으면(파일이 덜 보임) 아무것도 지우지 않고 False."""
        st = self.store
        if dev == st.device:
            raise ValueError("이 PC는 뺄 수 없어요")
        files = self.transport.list()
        self.pull(files)
        if f"dev_{dev}.json" in files and st.cursor(dev)[1] != files[f"dev_{dev}.json"]:
            return False
        st.adopt(dev)
        self.push()
        for name in self.transport.list():
            if name in (f"dev_{dev}.json", f"alive_{dev}.json") or name.startswith((f"log_{dev}_", f"snap_{dev}_")):
                self.transport.delete(name)
        with st.conn:
            st.conn.execute("DELETE FROM sync_cursor WHERE device = ?", (dev,))
        return True

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
                try:
                    data = self.transport.read(f"img_{sha}.png")
                except FileNotFoundError:
                    continue  # 방금 지워졌다 (쓰는 PC가 다시 올린다)
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
