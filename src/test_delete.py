# ponytail: minimal self-check for 삭제 → 되돌리기 + 휴지통 조건부 표시.
# run: python src/test_delete.py
# 확인창을 되살리면 이 테스트가 모달에서 멈춘다 = 확인창 제거를 지키는 장치이기도 하다.
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main as m
from database import MemoDatabase

app = QApplication([])
db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
for i in range(2):
    db.create(title=f"m{i}", content="x")

win = m.SlideMemoWindow(db)
win.show()

# 휴지통이 비어 있으면 아이콘 자체가 없다 (평소 하단은 숨기기 + ＋ 둘뿐)
assert not win.trash_btn.isVisibleTo(win), "빈 휴지통인데 아이콘이 보인다"
# 설정 아이콘은 아예 없어졌다 — 우클릭/트레이 메뉴로 이동
assert not hasattr(win, "settings_btn"), "설정 버튼이 아직 컬럼에 남아 있다"

win.expand()
assert win.current_memo is not None
victim = win.current_memo.id

win._delete_current_memo()  # 확인창 없이 바로 휴지통
assert db.count_trashed() == 1, db.count_trashed()
assert win.trash_btn.isVisibleTo(win), "지웠는데 휴지통 아이콘이 안 나타났다"
assert win._trash_badge.text() == "1", win._trash_badge.text()
assert not win._toast_lbl.isHidden(), "되돌리기 토스트가 안 떴다"

win._toast_lbl.clicked.emit()  # 토스트 클릭 = 되돌리기
assert db.count_trashed() == 0, "토스트 클릭이 복구를 안 했다"
assert win.current_memo is not None and win.current_memo.id == victim
assert not win.trash_btn.isVisibleTo(win), "휴지통이 다시 비었는데 아이콘이 남았다"

# 접힘 상태에선 토스트가 뜰 본문이 안 보인다 → 대신 휴지통 아이콘이 복구 경로
win.collapse()
win._delete_current_memo()
assert db.count_trashed() == 1
assert win.trash_btn.isVisibleTo(win)

print("delete/undo OK")
