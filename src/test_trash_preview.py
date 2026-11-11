# ponytail: 휴지통 미리 보기가 현재 메모를 덮어쓰지 않는지 self-check. run: python src/test_trash_preview.py
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
active = db.create("지금 메모", "<p>지키고 싶은 본문</p>", "blue")
trashed = db.create("지운 메모", "<p>휴지통 본문</p>", "pink")
db.soft_delete(trashed.id)
win = m.SlideMemoWindow(db)
win._load_memo(db.get(active.id))
win.expand()
before = db.get(active.id)


def unchanged(where: str) -> None:
    now = db.get(active.id)
    assert (now.title, now.content, now.updated_at) == (before.title, before.content, before.updated_at), f"{where}: 덮어써짐"
    assert db.list_versions(active.id) == [], f"{where}: 이전 버전이 생김"


win._enter_trash_mode()
win._preview_trashed(trashed.id)

win.save_now()
unchanged("저장 호출")
win.collapse(exit_trash=False)
unchanged("접기")
win._preview_trashed(trashed.id)

# 미리 보기는 편집할 수 없다
assert win.editor.isReadOnly() and win.title_input.isReadOnly()
assert not win.format_toolbar.isEnabled() and not win.color_btn.isEnabled() and not win._ai_bar.isEnabled()
assert not any(s.isEnabled() for s in win._edit_shortcuts)

# 미리 보던 상태에서 트레이 종료와 같은 경로
win._on_color_changed("green")
unchanged("색 바꾸기")
assert db.get(active.id).color == before.color, "미리 보는 중에 지금 메모 색이 바뀜"

# 나오면 원래 메모로 돌아와 다시 편집된다
win._exit_trash_mode()
assert win.editor.toPlainText() == "지키고 싶은 본문" and win.title_input.text() == "지금 메모"
assert not win.editor.isReadOnly() and win.format_toolbar.isEnabled() and win.color_btn.isEnabled() and win._ai_bar.isEnabled()
assert all(s.isEnabled() for s in win._edit_shortcuts)

win._quitting = True
win._enter_trash_mode()
win._preview_trashed(trashed.id)
win.close()  # closeEvent → save_now → db.close
check = MemoDatabase(Path(db.db_path))
now = check.get(active.id)
assert (now.title, now.content, now.updated_at) == (before.title, before.content, before.updated_at), "종료: 덮어써짐"
print("trash preview OK", flush=True)
os._exit(0)
