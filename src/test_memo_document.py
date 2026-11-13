# ponytail: 표시용 색이 저장 HTML에 새지 않는지, 색 옮기기가 한 번만 도는지. run: python src/test_memo_document.py
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QTextCursor, QTextDocument, QTextFormat
from PyQt6.QtWidgets import QApplication

import database as D
import memo_document as MD
from theme import apply as A
from theme import tokens as T
from theme.memo_tokens import legible_color, to_oklch

app = QApplication.instance() or QApplication([])
for font in A.resource_path("assets/fonts").glob("*.otf"):
    QFontDatabase.addApplicationFont(str(font))

RED_LIGHT, RED_DARK = "#B01219", "#F28B8B"
YELLOW_LIGHT, YELLOW_DARK = "#FFDD95", "#6B5200"
OLD_BG = "#FEF08A"


def same_hue(want: float, got: float) -> float:
    """hue가 몇 도 안에서 같으면 got을 돌려준다 (hex로 반올림되며 조금 흔들린다)."""
    gap = abs(want - got) % 360
    return got if min(gap, 360 - gap) < 8 else want


def load(html: str, mode: str) -> QTextDocument:
    A._mode = mode
    doc = QTextDocument()
    MD.prepare_document(doc)
    doc.setHtml(html)
    MD.decorate(doc, mode)
    return doc


def formats(doc):
    return {doc.toPlainText()[p:p + n]: f for p, n, f in MD._fragments(doc)}


HTML = (
    "<p><span style='color:#B01219'>red</span> "
    "<span style='background-color:#FFDD95'>mark</span> "
    "<span style='background-color:#FEF08A'>old</span> "
    "<span style='color:#123456'>custom</span> "
    "<a href='https://a.example'>new</a> "
    "<a href='https://b.example'><span style='color:#89b4fa;'>oldlink</span></a></p>"
)

# ----- 어두운 화면 표시 -----
dark = load(HTML, "dark")
f = formats(dark)
assert f["red"].foreground().color().name().upper() == RED_DARK
assert f["mark"].background().color().name().upper() == YELLOW_DARK
assert f["old"].foreground().color().name().upper() == MD.better_ink(OLD_BG)
_shown = f["custom"].foreground().color().name().upper()
assert _shown != "#123456" and MD.contrast(_shown, T.DARK_MEMO_FACE) >= 4.5, "예전 글자색은 읽히게 보정한다"
assert to_oklch(_shown)[2] == same_hue(to_oklch("#123456")[2], to_oklch(_shown)[2]), "색상은 그대로"
assert f["new"].foreground().color().name().upper() == T.MEMO_LINK_ON_DARK
assert f["oldlink"].foreground().color().name().upper() == "#89B4FA", "저장된 링크 색은 그대로"

# ----- 저장: 밝은 화면 값으로 돌아오고 표시용 값은 새지 않는다 -----
saved = MD.saved_html(dark).upper()
for leaked in (RED_DARK, YELLOW_DARK, T.MEMO_LINK_ON_DARK, "LINE-HEIGHT"):
    assert leaked not in saved, leaked
assert RED_LIGHT in saved and YELLOW_LIGHT in saved and "#123456" in saved and "#89B4FA" in saved
assert MD.better_ink(OLD_BG).upper() not in saved, "16번: 칠한 글자색은 저장 때 지운다"

# 원본 문서는 저장으로 바뀌지 않는다
assert formats(dark)["red"].foreground().color().name().upper() == RED_DARK

# ----- 왕복: 어두운 화면에서 저장한 것을 밝은 화면에서 열어도 같다 -----
light = load(MD.saved_html(dark), "light")
f = formats(light)
assert f["red"].foreground().color().name().upper() == RED_LIGHT
assert f["mark"].background().color().name().upper() == YELLOW_LIGHT
assert f["new"].foreground().color().name().upper() == T.MEMO_LINK_ON_LIGHT
assert MD.saved_html(light) == MD.saved_html(load(MD.saved_html(light), "light")), "저장을 반복해도 안 바뀐다"

# ----- 예전 글자색 보정 (9장 21) -----
OLD = "<p><span style='color:#1f2937'>dark</span> <span style='color:#ffffff'>white</span> <span style='color:#ef4444'>red</span></p>"
assert legible_color("#808080", "#FFFFFF", T.INK_DARK) == T.INK_DARK, "회색은 먹색으로"
for mode, ink in (("light", T.INK_DARK), ("dark", T.WHITE)):
    doc = load(OLD, mode)
    f = formats(doc)
    assert f["white"].foreground().color().name().upper() == ink, (mode, "채도 없는 색은 ink")
    saved = MD.saved_html(doc).lower()
    for original in ("#1f2937", "#ffffff", "#ef4444"):
        assert original in saved, (mode, original, "저장은 원래 값")
    faces = [T.DARK_MEMO_FACE] if mode == "dark" else [p[1] for p in T.MEMO_PRESETS.values()]
    for word in ("dark", "red"):
        color = f[word].foreground().color().name().upper()
        for face in faces:
            assert MD.contrast(color, face) >= 4.5, (mode, word, color, face)

# ----- 어두운 화면에서 칠한 글자색도 밝은 값으로 저장 -----
A._mode = "dark"
doc = QTextDocument()
doc.setPlainText("abc")
cursor = QTextCursor(doc)
cursor.select(QTextCursor.SelectionType.Document)
cursor.mergeCharFormat(MD.text_color_format(RED_LIGHT, "dark"))
assert RED_LIGHT in MD.saved_html(doc).upper() and RED_DARK not in MD.saved_html(doc).upper()
cursor.mergeCharFormat(MD.text_color_format(None, "dark"))
assert "COLOR:#" not in MD.saved_html(doc).upper().replace("COLOR:#000000", ""), "없음은 색을 지운다"

# ----- 표: 표시용 선·머리 칸 색은 저장되지 않는다 -----
table_html = "<table border='1'><tr><td><b>a</b></td><td><b>b</b></td></tr><tr><td>c</td><td>d</td></tr></table>"
doc = load(table_html, "dark")
table = next(MD._tables(doc.rootFrame()))
assert table.format().hasProperty(QTextFormat.Property.FrameBorderBrush)
assert table.cellAt(0, 0).format().background().color().alpha() > 0, "머리 칸이 칠해져야 한다"
assert table.cellAt(1, 0).format().background().style().name == "NoBrush"
assert "BACKGROUND-COLOR" not in MD.saved_html(doc).upper()
_cell = table.cellAt(1, 1).format().toTableCellFormat()
assert (_cell.leftPadding(), _cell.rightPadding(), _cell.topPadding(), _cell.bottomPadding()) == (12, 12, 6, 6)
assert "PADDING-LEFT:12" not in MD.saved_html(doc).upper().replace(" ", ""), "표시용 여백은 저장되지 않는다"

# ----- 색 옮기기 -----
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    path = Path(d) / "old.db"
    db = D.MemoDatabase(path)
    ids = {}
    for name in ("sunrise", "grad:#2f3650,#ffffff", "#e07a5f", "peach", "blue"):
        memo = db.create("t", "x")
        db.conn.execute("UPDATE memos SET color = ? WHERE id = ?", (name, memo.id))
        ids[name] = memo.id
    db.set_setting_str(D.USER_SLOTS_KEY, "#111111|grad:#abc,#def|ivory|#222222")
    db.conn.execute("ALTER TABLE memos DROP COLUMN color_before_v2")
    db.conn.execute("PRAGMA user_version = 2")
    db.conn.commit()
    db.close()

    db = D.MemoDatabase(path)
    color = lambda key: db.get(ids[key]).color  # noqa: E731
    assert color("sunrise") == "green"
    assert color("grad:#2f3650,#ffffff") == "blue"
    assert color("#e07a5f") == "#E07A5F"
    assert color("peach") == "orange"
    assert color("blue") == "blue"
    before = db.conn.execute("SELECT color_before_v2 FROM memos WHERE id = ?", (ids["sunrise"],)).fetchone()[0]
    assert before == "sunrise", "되돌리기 대비로 옛 값을 남긴다"
    assert db.get_setting_str(D.USER_SLOTS_KEY) == "#222222|#111111", "단색만, 최근 것부터"
    assert db.get_setting_int(D.PAPER_NOTICE_KEY, 0) == 1
    assert Path(str(path) + ".bak").exists(), "옮기기 전에 백업한다"

    # 다시 열어도 다시 돌지 않는다
    db.update(ids["sunrise"], color="pink")
    db.set_setting_int(D.PAPER_NOTICE_KEY, 0)
    db.close()
    db = D.MemoDatabase(path)
    assert db.get(ids["sunrise"]).color == "pink"
    assert db.get_setting_int(D.PAPER_NOTICE_KEY, 0) == 0
    db.close()

    # 새 DB는 신규 설치로 판정돼야 하고 안내도 없다
    fresh = D.MemoDatabase(Path(d) / "fresh.db")
    assert fresh.is_fresh_install()
    assert fresh.get_setting_int(D.PAPER_NOTICE_KEY, 0) == 0
    assert fresh.conn.execute("PRAGMA user_version").fetchone()[0] == D._SCHEMA_VERSION
    fresh.close()

A._mode = "light"
print("memo document OK")
