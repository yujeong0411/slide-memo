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

print("dialogs OK")
