# ponytail: 메모 색 self-check (정규화, 슬롯, 직접 만든 색). run: python src/test_colors.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main as m
from database import DEFAULT_COLOR, normalize_color, paper_color
from memo_color import MemoColorDialog, normalized_hex
from theme import apply as A
from theme import tokens as T
from theme.memo_tokens import nearest_preset

_app = QApplication.instance() or QApplication([])

# 저장값은 신뢰 경계: 프리셋과 hex만 통과한다
assert DEFAULT_COLOR == "yellow"
assert normalize_color("blue") == "blue"
assert normalize_color("#ff0000") == "#FF0000"
assert normalize_color("#abc") == "#AABBCC"
for bad in ("garbage", "grad:#aabbcc", "sunrise", "#12345", "red;}", None, ""):
    assert normalize_color(bad) == DEFAULT_COLOR, bad

# 슬롯 왕복. 깨진 값과 예전 그라데이션은 걸러진다
assert m.parse_color_slots("") == []
assert m.parse_color_slots("#AABBCC|#112233") == ["#AABBCC", "#112233"]
assert m.parse_color_slots("#AABBCC|;background:red|grad:#abc|ivory") == ["#AABBCC"]
assert len(m.parse_color_slots("|".join(["#AABBCC"] * 9))) == T.MAX_CUSTOM_COLORS

# 메모 색 옮기기: 실제 색의 hue 기준 (9장 18)
assert nearest_preset("#808080") == "gray"          # 채도 없음
assert nearest_preset("#FFF2EB") != "gray"          # 복숭아: 옅어도 회색으로 안 간다
assert nearest_preset("#F4EEFF") == "purple"
assert paper_color("sunrise") == "green"
assert paper_color("blossom") == "pink"             # 첫 번째 색 기준
assert paper_color("grad:#FFD27A,#FF8FB1") == nearest_preset("#FFD27A")
assert paper_color("grad:nothex") == DEFAULT_COLOR
assert paper_color("#e07a5f") == "#E07A5F"          # 직접 만든 단색은 그대로
assert paper_color("blue") == "blue"

# 메모 색 만들기: 색 하나만 고른다
dlg = MemoColorDialog("#123456")
assert dlg.value() == "#123456"
assert dlg.focusWidget() is dlg.hex_edit
dlg.hex_edit.setText("abcdef")
assert dlg.value() == "#ABCDEF"
dlg.hex_edit.setText("#12")
assert not dlg._action.isEnabled(), "형식이 틀리면 만들 수 없다"
assert normalized_hex("#12") is None and normalized_hex("e07a5f") == "#E07A5F"

# 어떤 색이든 메모 창 QSS가 만들어져야 앱이 켜진다 (v1.1.1 사고)
from PyQt6.QtWidgets import QWidget  # noqa: E402

_body = QWidget()
for mode in ("light", "dark"):
    A._mode = mode
    for color in list(T.MEMO_PRESETS) + ["#E07A5F", "#000000", "#FFFFFF"]:
        for side in ("right", "left"):
            tokens = A.apply_memo(_body, color, side)
            sheet = _body.styleSheet()
            assert "#bodyPanel" in sheet and "$" not in sheet, (mode, color, side)
            assert f"border-{side}: none;" in sheet, "맞닿는 면에 테두리가 남으면 경계선으로 읽힌다"
            assert tokens["memo_face"] in sheet
A._mode = "light"

print("colors OK")
