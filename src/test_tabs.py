# ponytail: 세로 탭·바 self-check. run: python src/test_tabs.py
# 좌우를 뒤집기 쉬운 그리기라 픽셀로 못박아 둔다.
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QFontDatabase, QPixmap, QRegion
from PyQt6.QtWidgets import QApplication, QSizePolicy, QWidget

import main as m
from database import Memo, MemoDatabase
from theme.memo_tokens import memo_tokens

_app = QApplication.instance() or QApplication([])
for _f in m._resource_path("assets/fonts").glob("*.otf"):
    QFontDatabase.addApplicationFont(str(_f))
Tab = m.MemoTabButton
W, H = 40, 112


def memo(title="t", color="blue", pinned=False):
    return Memo(id=1, title=title, content="", color=color, is_pinned=pinned, created_at="", updated_at="")


def render(tab):
    tab.resize(W, H)
    pm = QPixmap(tab.size())
    pm.fill(QColor(0, 0, 0, 0))
    tab.render(pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return pm.toImage()


tokens = memo_tokens("blue", "light")
for side, outer_x, inner_x in (("right", W - 2, 0), ("left", 1, W - 1)):
    Tab.side = side
    img = render(Tab(memo()))
    # 모니터 쪽 4px은 띠 색
    assert img.pixelColor(outer_x, H // 2).name().upper() == tokens["memo_band"], (side, "띠")
    # 안쪽 모서리는 둥글어 비어 있고, 모니터 쪽 모서리는 각져서 차 있다
    assert img.pixelColor(inner_x, 0).alpha() < 40, (side, "안쪽 모서리")
    assert img.pixelColor(outer_x, 0).alpha() > 200, (side, "모니터 쪽 모서리")

    # 열린 탭은 창과 이어진다: 안쪽 모서리도 안쪽 선도 없다
    opened = Tab(memo())
    opened.update_style(selected=True)
    img = render(opened)
    assert img.pixelColor(inner_x, 0).alpha() > 200, (side, "열린 탭 모서리")
    assert img.pixelColor(inner_x, H // 2).name().upper() == tokens["memo_face"], (side, "열린 탭 안쪽 선")
Tab.side = "right"

# 탭 폭은 컬럼이 정한다 (기본 정책이면 크기 힌트가 하한이 되어 밀린다)
_probe = Tab(memo())
assert _probe.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
assert _probe.minimumWidth() == 0
assert _probe.toolTip() == "t"

# 세워 쌓기: 다 안 들어가면 끝을 말줄임, 툴팁엔 전체 제목 (9장 2)
assert Tab.stacked_chars("주간", 4) == ["주", "간"]
assert Tab.stacked_chars("가나다라", 4) == list("가나다라")
assert Tab.stacked_chars("가나다라마바", 4) == ["가", "나", "다", "…"]
assert Tab(memo("가나다라마바")).toolTip() == "가나다라마바"
assert Tab(memo("  ")).memo_title == "(제목 없음)"

# 깨진 색이 DB에 있어도 탭은 그려져야 앱이 켜진다
render(Tab(memo(color="sunrise")))

# 고정 핀은 글자 색으로 칠한다
_light = Tab._pin_pixmap("#1B1D22", 16).toImage()
_solid = [(x, y) for y in range(_light.height()) for x in range(_light.width())
          if _light.pixelColor(x, y).alpha() > 200]
assert _solid, "핀 아이콘이 렌더되지 않음 (SVG 경로/플러그인 확인)"
assert all(_light.pixelColor(x, y).red() < 100 for x, y in _solid)

_on, _off = render(Tab(memo(pinned=True))), render(Tab(memo(pinned=False)))
assert sum(_on.pixelColor(x, y) != _off.pixelColor(x, y) for y in range(H) for x in range(W)) > 5

# ----- 휴지통 배지 -----
# 레이아웃 전에는 버튼 폭이 Qt 기본값이라, 그걸 쓰면 배지가 버튼 밖으로 나간다.
_db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
for _i in range(3):
    _db.create(title=f"m{_i}", content="x")
_db.soft_delete(_db.list_all()[0].id)

_win = m.SlideMemoWindow(_db)
_badge = _win._trash_badge
assert _badge.text() == "1", _badge.text()
assert not _badge.isHidden(), "휴지통에 메모가 있는데 배지가 숨겨짐"
assert 0 <= _badge.x() <= _win.tab_width - _badge.width(), (_badge.x(), _badge.width(), _win.tab_width)
assert _win.trash_btn.height() == m.BAR_BUTTON_HEIGHT or not _win.trash_btn.isVisible()
assert _win.drag_grip.height() == m.GRIP_HEIGHT

# ----- 좁은 창: 정렬 콤보가 아이콘이 된다 -----
_win.resize(520, 500)
_win._fit_top_row()
assert not _win.sort_combo._compact, "넓은데 아이콘이 됐다"
assert _win.sort_combo._btn.text() == "수정일순"
assert "▾" not in _win.sort_combo._btn.text()
_win.resize(m.MIN_W, 500)
_win._fit_top_row()
assert _win.sort_combo._compact, "좁은데 글자로 남았다"
assert "수정일순" in _win.sort_combo._btn.toolTip(), "툴팁에 지금 정렬을 보여 준다"
_win.resize(520, 500)
_win._fit_top_row()

# ----- 접힘 상태 바 폭 드래그 -----
# 핸들은 컬럼의 "안쪽" 가장자리에 있어야 한다 (마스크 밖에 놓이면 잡을 수 없다)
_win._position_collapsed()
_win._update_handles()
_mask = _win._collapsed_mask_region().boundingRect()
_hg = _win.handle_tab.geometry()
assert _win.handle_tab.isVisibleTo(_win), "접힘인데 폭 핸들이 숨김"
assert _mask.x() <= _hg.x() and _hg.right() <= _mask.right(), (_hg, _mask)

_before = _win.tab_width
_win._apply_tab_width(_before + 20)
assert _win.tab_width == _before + 20, _win.tab_width
assert _win.tab_column.width() == _win.tab_width
assert _win._collapsed_mask_region().boundingRect().width() == _win.tab_width

_win._apply_tab_width(9999)  # clamp
assert _win.tab_width == m.TAB_WIDTH_MAX, _win.tab_width
_win._apply_tab_width(0)
assert _win.tab_width == m.TAB_WIDTH_MIN, _win.tab_width

# 펼치면 폭 핸들은 물러나고 본문 가장자리 핸들이 나온다
_win.is_expanded = True
_win._update_handles()
assert not _win.handle_tab.isVisibleTo(_win), "펼침인데 폭 핸들이 살아있음"

# ----- 접힘 상태 세로 길이 -----
_win.is_expanded = False
_win._position_collapsed()
_win._update_handles()
_mask = _win._collapsed_mask_region().boundingRect()
for _h in (_win.handle_top, _win.handle_bottom):
    _g = _h.geometry()
    assert _h.isVisibleTo(_win), "접힘인데 세로 핸들이 숨김"
    assert _mask.x() <= _g.x() and _g.right() <= _mask.right(), (_g, _mask)

# 마스크 높이는 저장값이 아니라 현재 창 높이를 따라간다 (드래그 중 실시간)
_g = _win.geometry()
_win.setGeometry(_g.x(), _g.y(), _g.width(), _g.height() - 80)
assert _win._collapsed_mask_region().boundingRect().height() == _g.height() - 80

print("tabs OK")
