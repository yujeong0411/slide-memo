"""폴더 하나를 Drive appDataFolder처럼 쓰는 전송 방식 (설계 8장).
시험에서 PC 여러 대를 흉내 낼 때 쓴다. DriveTransport(8단계)도 같은 네 가지를 갖춘다.
  list()  → {파일 이름: 버전 문자열}   (바뀌면 버전도 바뀐다)
  read(name) → bytes
  write(name, data)                   (파일을 통째로 바꾼다. 읽는 쪽이 반쯤 쓴 파일을 보지 않는다)
  delete(name)
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


class LocalFolderTransport:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> dict[str, str]:
        out = {}
        for p in self.root.iterdir():
            if p.is_file() and not p.name.endswith(".tmp"):
                # ponytail: 내용 해시를 버전으로 (시험용이라 매번 읽어도 된다). 수정 시각은 빠르게
                # 두 번 쓰면 같을 수 있다. Drive는 파일마다 version 값을 준다.
                out[p.name] = hashlib.sha1(p.read_bytes()).hexdigest()
        return out

    def read(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def write(self, name: str, data: bytes) -> None:
        tmp = self.root / f"{name}.{os.getpid()}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.root / name)

    def delete(self, name: str) -> None:
        (self.root / name).unlink(missing_ok=True)
