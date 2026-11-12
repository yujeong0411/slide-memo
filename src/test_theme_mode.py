# ponytail: 화면 모드 전환 self-check. run: python src/test_theme_mode.py
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main as m
import memo_document as MD
import settings_dialog as SD
import database
from database import MemoDatabase
from theme import apply as A
from theme import tokens as T

database.APP_DIR = Path(tempfile.mkdtemp())  # 아이콘 캐시가 실제 데이터 폴더에 생기지 않게 한다
app = QApplication([])
SD.load_api_key = lambda _provider: None
A.apply_theme(app, "light")

RED_LIGHT, RED_DARK = "#B01219", "#F28B8B"
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
memo = db.create("빨강", f"<p><span style='color:{RED_LIGHT}'>글자</span></p>", "blue")
win = m.SlideMemoWindow(db)
win._load_memo(memo)


def shown_color() -> str:
    return next(MD._fragments(win.editor.document()))[2].foreground().color().name().upper()


saved_before = db.get(memo.id).content
assert A.resolve_mode("nonsense") == A.system_mode(), "모르는 값은 시스템을 따른다"

# 어둡게: 팔레트·문서·메모 면이 함께 바뀌고 저장 내용은 그대로다
db.set_setting_str(A.THEME_MODE_KEY, "dark")
win.apply_screen_mode()
assert A.current_mode() == "dark"
assert app.palette().window().color().name().upper() == T.DARK["bg_canvas"]
assert shown_color() == RED_DARK, shown_color()
from theme.memo_tokens import memo_tokens as _memo_tokens  # noqa: E402

assert _memo_tokens(memo.color, "dark")["memo_face"] in win.body.styleSheet(), "어두운 메모 면(띠 색 7%)"
assert RED_LIGHT.lower() in db.get(memo.id).content.lower(), "어두운 화면에서도 저장은 밝은 값"
assert RED_DARK.lower() not in db.get(memo.id).content.lower()

# 시스템 변경은 '시스템 설정 따르기'일 때만 따른다
A.system_mode, original = (lambda: "light"), A.system_mode
win.on_system_scheme_changed()
assert A.current_mode() == "dark", "어둡게로 고정했는데 시스템을 따라갔다"
db.set_setting_str(A.THEME_MODE_KEY, "system")
win.on_system_scheme_changed()
assert A.current_mode() == "light", "시스템 변경을 따라가지 않았다"
A.system_mode = original
assert shown_color() == RED_LIGHT

# 같은 모드로 다시 저장하면 Ctrl+Z 기록을 지우지 않는다
_doc = win.editor.document()
db.set_setting_str(A.THEME_MODE_KEY, "light")
win.apply_screen_mode()
assert win.editor.document() is _doc, "모드가 그대로인데 문서를 다시 만들었다"

# 왕복해도 저장 내용이 바뀌지 않는다
win.save_now()
assert RED_LIGHT.lower() in db.get(memo.id).content.lower()
assert len(saved_before) > 0

# 설정 창 저장
dlg = SD.SettingsDialog(db, win)
assert dlg._theme_combo.currentData() == "light"
dlg._theme_combo.setCurrentIndex(dlg._theme_combo.findData("dark"))
dlg._save_and_accept()
assert db.get_setting_str(A.THEME_MODE_KEY) == "dark"

A.apply_theme(app, "light")
print("theme mode OK")
