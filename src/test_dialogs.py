# ponytail: 입력 대화창 첫 포커스 self-check. run: python src/test_dialogs.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoVersion

app = QApplication([])


def focused(dialog):
    """보이기 전이라도 대화창이 포커스를 줄 위젯."""
    return dialog.focusWidget()


blank = m.LinkDialog(parent=None)
assert focused(blank) is blank.text_edit, "선택 없으면 보이는 글자부터"

selected = m.LinkDialog("고른 글자", None, show_text=False)
assert focused(selected) is selected.url_edit, "선택 있으면 주소부터"

table = m.TableDialog(None)
assert focused(table) is table.rows_spin

versions = m.VersionDialog(
    [MemoVersion(id=1, memo_id=1, title="t", content="c", created_at="2026-11-10T10:00:00")]
)
assert focused(versions) is versions.list

# 좁은 배너: 알아볼 수 없으면 미리보기를 비운다
from memo_popups import ElideLabel  # noqa: E402

label = ElideLabel()
label.setText("복사한 글 “3분기 실적 보고서 초안 공유드립니다”")
label.resize(20, 20)
label._elide()  # 화면에 없으면 resizeEvent가 오지 않는다
assert label.text() == "", label.text()
label.resize(600, 20)
label._elide()
assert label.text() == label.full_text()

print("dialogs OK")
