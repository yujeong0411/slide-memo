"""동기화 시험용 실행. 배포에 들어가지 않는다 (빌드는 src/main.py와 그것이 불러오는 것만 묶는다).

    python tools/sync_trial.py A          시험 A (오른쪽에 붙음)
    python tools/sync_trial.py B          시험 B (왼쪽에 붙음)
    python tools/sync_trial.py A --reset  시험 A 프로필을 지우고 가짜 메모로 새로 시작
    python tools/sync_trial.py --cleanup  두 프로필을 지운다 (남은 갱신 열쇠는 Google에 철회한 뒤)

- 프로필(DB, 그림, 설정, 화면 캐시)은 %TEMP%\\slidememo_trial\\<A|B> 에만 둔다. 실제 메모 DB(~/.memo_slide)를 열지 않는다.
- 갱신 열쇠는 Windows 자격 증명이 아니라 프로필 안 파일(keyring.json)에 둔다. 시험이 끝나면 --cleanup으로 철회하고 지운다.
- 긴 시간을 줄인다 (시험용 실행에서만):
    인터넷 끊김 경고 1시간 → 1분, 오래 꺼진 PC 판정 170일 → 3분, 지운 메모 기록 보관 180일 → 5분
- 업데이트 확인은 끈다. Ctrl+Shift+Z는 먼저 켠 앱만 받는다 (Windows 단축키는 한 앱만 등록된다).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.gettempdir()) / "slidememo_trial"
SRC = Path(__file__).resolve().parents[1] / "src"
SIDES = {"A": 0, "B": 1}  # 0 = 오른쪽, 1 = 왼쪽
SEED = {
    "A": [("시험 A · 장보기", "<p>우유, 달걀</p>"), ("시험 A · 할 일", "<p>세탁</p>"), ("시험 A · 회의", "<p>3시 회의</p>")],
    "B": [("시험 B · 메모", "<p>B에서 쓴 메모</p>"), ("시험 B · 일정", "<p>금요일 저녁</p>")],
}


def _file_keyring(path: Path):
    import keyring
    import keyring.backend
    import keyring.errors

    class FileKeyring(keyring.backend.KeyringBackend):
        priority = 1

        def _load(self):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}

        def get_password(self, service, user):
            return self._load().get(f"{service}|{user}")

        def set_password(self, service, user, password):
            data = self._load()
            data[f"{service}|{user}"] = password
            path.write_text(json.dumps(data), encoding="utf-8")

        def delete_password(self, service, user):
            data = self._load()
            if f"{service}|{user}" not in data:
                raise keyring.errors.PasswordDeleteError("none")
            del data[f"{service}|{user}"]
            path.write_text(json.dumps(data), encoding="utf-8")

    keyring.set_keyring(FileKeyring())


def cleanup() -> None:
    sys.path.insert(0, str(SRC))
    from sync import oauth

    for name in SIDES:
        folder = ROOT / name
        token = None
        try:
            token = json.loads((folder / "keyring.json").read_text(encoding="utf-8")).get(
                f"{oauth.KEYRING_SERVICE}|{oauth.KEYRING_USER}")
        except (OSError, ValueError):
            pass
        if token:
            print(f"시험 {name}: 남은 갱신 열쇠 철회 =", oauth.revoke(token))
        shutil.rmtree(folder, ignore_errors=True)
        print(f"시험 {name}: 프로필 지움 =", not folder.exists())
    shutil.rmtree(ROOT, ignore_errors=True)


def run(name: str, reset: bool) -> int:
    folder = ROOT / name
    if reset:
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    sys.path.insert(0, str(SRC))
    _file_keyring(folder / "keyring.json")

    import database

    database.APP_DIR, database.DB_PATH, database.IMAGES_DIR = folder, folder / "memos.db", folder / "images"
    fresh = not database.DB_PATH.exists()
    db = database.MemoDatabase(database.DB_PATH)
    if fresh:  # 가짜 메모로 시작. 안내 창·가이드는 이미 본 것으로 둔다
        for title, content in SEED[name]:
            db.create(title, content)
        db.set_setting_int("side", SIDES[name])
        db.set_setting_int("guide_bar_done", 1)
        db.set_setting_int("guide_body_done", 1)
    db.close()

    from sync import core, engine, runner, store

    runner.OFFLINE_WARN_S = 60
    # 두 시험 앱이 같은 컴퓨터라 Windows 이름이 같다. PC 목록에서 구분되게 이름만 바꾼다 (시험용)
    runner.default_pc_name = lambda: f"시험 {name}"
    keep = 5 / 1440                       # 5분
    core.PURGE_KEEP_DAYS = store.PURGE_KEEP_DAYS = keep
    engine.STALE_DAYS = 3 / 1440          # 3분

    import main as M

    M.APP_DIR, M.IMAGES_DIR = database.APP_DIR, database.IMAGES_DIR
    M.UpdateChecker.start = lambda self: None
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel

    seen = database.MemoDatabase(database.DB_PATH)
    seen.set_setting_str(M.WHATS_NEW_KEY, M.APP_VERSION)
    seen.close()
    attach = M.SlideMemoWindow.attach_sync

    def attach_and_mark(self, controller):
        attach(self, controller)
        self.setWindowTitle(f"SlideMemo 시험 {name}")
        mark = QLabel(f"시험\n{name}", self.tab_column)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setToolTip(f"동기화 시험 {name} (프로필: {folder})")
        mark.setStyleSheet("font-weight: 700; font-size: 11px; color: #5055B1; padding: 4px 0;")
        self.tab_column.layout().insertWidget(0, mark)

    M.SlideMemoWindow.attach_sync = attach_and_mark
    make_tray = M.make_tray_icon

    def tray_with_name(window, icon=None):
        tray = make_tray(window, icon)
        tray.setToolTip(f"SlideMemo 시험 {name}")
        return tray

    M.make_tray_icon = tray_with_name
    print(f"시험 {name}: 프로필 {folder}", flush=True)
    return M.main()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--cleanup"]:
        cleanup()
    elif args[:1] and args[0].upper() in SIDES:
        sys.exit(run(args[0].upper(), "--reset" in args))
    else:
        print(__doc__)
