"""메모 본문의 그림 경로 ↔ PC와 무관한 표지 (설계 3.5).

본문에는 그림이 이 PC의 절대 경로(<img src="C:/Users/<이름>/.memo_slide/images/img_….png">)로
들어간다. 사용자 이름이 다른 PC에서는 깨지므로, 올릴 때는 smimg:<sha256>.png로 바꾸고 받을 때는
그 PC의 경로로 되돌린다. 같은 그림은 해시가 같아 한 번만 올라간다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable

TOKEN = "smimg:"
MAX_IMAGE_BYTES = 20 * 1024 * 1024    # 넘으면 올리지 않는다 (설계 13장 10)
LARGE_UPLOAD_BYTES = 5 * 1024 * 1024  # 넘으면 이어 올리기(resumable)로 (6단계, Drive)

_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def src_to_path(src: str) -> Path:
    for prefix in ("file:///", "file://"):
        if src.startswith(prefix):
            return Path(src[len(prefix):])
    return Path(src)


def named_sha(path: Path) -> str | None:
    """받은 그림은 <sha256>.png로 저장한다. 이름이 곧 해시라 다시 읽지 않는다."""
    return path.stem if _HEX64.match(path.stem) else None


def local_image(src: str, images_dir: Path) -> Path | None:
    """이 PC의 그림 폴더 안 그림이면 그 경로. 아니면(바깥 파일, 웹 주소 등) None — 그대로 둔다."""
    if src.startswith(TOKEN):
        return None
    try:
        p = src_to_path(src)
        return p if p.parent.resolve() == images_dir.resolve() else None
    except (OSError, ValueError):
        return None


def to_portable(html: str, images_dir: Path, sha_of: Callable[[Path], str | None]) -> str:
    """이 PC의 그림 경로 → smimg:<sha>.png. 해시를 알 수 없는 그림(파일 없음)은 그대로 둔다."""
    def swap(m: re.Match) -> str:
        p = local_image(m.group(2), images_dir)
        sha = sha_of(p) if p is not None else None
        return f"{m.group(1)}{TOKEN}{sha}.png{m.group(3)}" if sha else m.group(0)
    return _SRC_RE.sub(swap, html or "")


def to_local(html: str, path_for: Callable[[str], Path]) -> str:
    """smimg:<sha>.png → 이 PC의 경로 (없는 그림이면 받을 자리 <images>/<sha>.png)."""
    def swap(m: re.Match) -> str:
        src = m.group(2)
        if not src.startswith(TOKEN):
            return m.group(0)
        sha = src[len(TOKEN):].split(".", 1)[0]
        if not _HEX64.match(sha):
            return m.group(0)
        return f"{m.group(1)}{path_for(sha).as_posix()}{m.group(3)}"
    return _SRC_RE.sub(swap, html or "")


def shas_in(html: str) -> set[str]:
    """smimg 표지로 쓰인 그림 해시들."""
    out = set()
    for m in _SRC_RE.finditer(html or ""):
        src = m.group(2)
        if src.startswith(TOKEN):
            sha = src[len(TOKEN):].split(".", 1)[0]
            if _HEX64.match(sha):
                out.add(sha)
    return out


def local_paths_in(html: str, images_dir: Path) -> set[Path]:
    out = set()
    for m in _SRC_RE.finditer(html or ""):
        p = local_image(m.group(2), images_dir)
        if p is not None:
            out.add(p)
    return out
