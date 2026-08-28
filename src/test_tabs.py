# ponytail: minimal self-check for tab column rounding. run: python src/test_tabs.py
# 방향을 뒤집기 쉬운 로직이라 상태별로 못박아 둔다.
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main as m

R = m.COLUMN_RADIUS
Tab = m.MemoTabButton


def radius(side, *, top=True, bottom=True):
    return m._outer_radius_qss(side, top=top, bottom=bottom)


# ----- 바깥면 = 본문이 있는(있던) 쪽. 접힘 여부와 무관하게 항상 둥글다 -----
# 탭이 화면 오른쪽 → 본문은 왼쪽 → 바깥면은 왼쪽
qss = radius("right")
assert f"border-top-left-radius: {R}px" in qss, qss
assert f"border-bottom-left-radius: {R}px" in qss, qss
assert "right-radius" not in qss, qss

# 탭이 화면 왼쪽 → 본문은 오른쪽 → 바깥면은 오른쪽
qss = radius("left")
assert f"border-top-right-radius: {R}px" in qss, qss
assert f"border-bottom-right-radius: {R}px" in qss, qss
assert "left-radius" not in qss, qss

# ----- 그룹 끝만 둥글게 (설정/휴지통/추가를 한 덩어리로) -----
top_only = radius("left", top=True, bottom=False)
assert f"border-top-right-radius: {R}px" in top_only, top_only
assert "bottom" not in top_only.replace("border-radius: 0;", ""), top_only

bottom_only = radius("left", top=False, bottom=True)
assert f"border-bottom-right-radius: {R}px" in bottom_only, bottom_only
assert "top" not in bottom_only.replace("border-radius: 0;", ""), bottom_only

middle = radius("left", top=False, bottom=False)  # 휴지통 = 가운데
assert middle.strip() == "border-radius: 0;", middle

# 전부 0으로 깔고 덮어쓰는 구조라 순서가 뒤집히면 라운드가 죽는다
assert top_only.startswith("border-radius: 0;"), top_only

# 메모 탭은 낱개로 둥글다 (위·아래 모두)
Tab.side = "left"
assert Tab._radius_qss() == radius("left", top=True, bottom=True)
Tab.side = "right"
assert Tab._radius_qss() == radius("right", top=True, bottom=True)

# 인덱스 탭은 본문과 같은 선명도 (비치면 안 됨)
assert Tab.BG_ALPHA == 1.0

# ----- 선택 표시 테두리: 실제로 그려보고 모서리가 둥근지 픽셀로 확인 -----
# 직접 QPainter로 그리면 호를 손으로 계산해야 해서 모서리가 각지게 나오기 쉽다.
# stylesheet border가 border-radius를 따라가는지를 렌더링 결과로 못박는다.
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPixmap, QRegion
from PyQt6.QtWidgets import QApplication, QWidget

from database import Memo

_app = QApplication.instance() or QApplication([])
W, H = 30, 120
_memo = Memo(id=1, title="t", content="", color="mint", created_at="", updated_at="")


def alpha_at(img, x, y):
    return img.pixelColor(x, y).alpha()


for _side in ("left", "right"):
    Tab.side = _side
    tab = Tab(_memo)
    tab.resize(W, H)
    tab.update_style(selected=True)
    pm = QPixmap(tab.size())
    pm.fill(QColor(0, 0, 0, 0))
    # 기본 render()는 DrawWindowBackground로 사각 배경을 먼저 칠해 모서리를 덮는다
    # → 라운드가 안 보인다. 위젯 자기 그리기만 남긴다.
    tab.render(pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    img = pm.toImage()

    # 바깥면(라운드) 쪽 x좌표와 반대(각진) 쪽 x좌표
    round_x, square_x = (W - 1, 0) if _side == "left" else (0, W - 1)
    # 둥근 모서리는 깎여 나가 비어 있어야 한다
    assert alpha_at(img, round_x, 1) < 40, (_side, alpha_at(img, round_x, 1))
    # 같은 변의 중간은 테두리가 그려져 있어야 한다 (선이 통째로 빠지면 안 됨)
    assert alpha_at(img, round_x, H // 2) > 200, (_side, alpha_at(img, round_x, H // 2))
    # 각진 쪽 모서리는 꽉 차 있어야 한다
    assert alpha_at(img, square_x, 1) > 200, (_side, alpha_at(img, square_x, 1))

# ----- 탭 테두리 -----
# 접힘 상태에서 색이 비슷한 탭끼리 경계가 뭉개져서 낱개로 윤곽을 준다 (4면 전부).
Tab.side = "right"
_tab = Tab(_memo)
_tab.update_style(selected=False)
_qss = _tab.styleSheet()
# 선 색은 그 탭 색을 어둡게 한 것에서 파생된다 (탭마다 달라지는 게 의도)
_outline = m._hex_to_rgba(_tab._sel_color, Tab.OUTLINE_ALPHA)
assert f"border: 1px solid {_outline}" in _qss, _qss
assert "border: none" not in _qss, _qss  # 어느 면도 빠지면 안 된다
# 색이 다른 탭은 선 색도 달라야 한다 (무채색으로 굳으면 여기서 걸린다)
_other = Tab(Memo(id=2, title="t", content="", color="blossom", created_at="", updated_at=""))
_other.update_style(selected=False)
assert _other._sel_color != _tab._sel_color
assert m._hex_to_rgba(_other._sel_color, Tab.OUTLINE_ALPHA) in _other.styleSheet()
# 선택 시엔 선택 테두리(3px)가 이긴다
_tab.update_style(selected=True)
assert f"{Tab.SEL_BORDER_WIDTH}px solid" in _tab.styleSheet(), _tab.styleSheet()


def _lum_rgb(c):
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


# 실제로 4면에 그려지는지 픽셀로 확인 — 각 변의 1px이 안쪽보다 뚜렷하게 어두워야 한다
_t = Tab(_memo)
_t.resize(W, H)
_t.update_style(selected=False)
_pm = QPixmap(_t.size())
_pm.fill(QColor(255, 255, 255))
_t.render(_pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
_im = _pm.toImage()
# 높이는 setFixedHeight로 고정돼 resize가 안 먹는다 → 실제 위젯 크기로 읽어야 한다
_w, _h = _t.width(), _t.height()
_mx, _my = _w // 2, _h // 2  # 라운드 모서리를 피해 각 변의 가운데에서 읽는다
for _tag, _edge, _inner in (
    ("위", (_mx, 0), (_mx, 4)),
    ("아래", (_mx, _h - 1), (_mx, _h - 5)),
    ("왼쪽", (0, _my), (4, _my)),
    ("오른쪽", (_w - 1, _my), (_w - 5, _my)),
):
    _gap = _lum_rgb(_im.pixelColor(*_edge)) - _lum_rgb(_im.pixelColor(*_inner))
    assert _gap < -12, (f"{_tag} 테두리가 안 보인다", _gap)


# ----- 본문과 인덱스 컬럼의 이음매 -----
# 펼치면 컬럼 뒤를 본문 배경으로 채운다. 둘이 좌우로 붙으므로 그라데이션이 세로가
# 아니면(예: 대각선) 폭이 다른 만큼 진행도가 어긋나 경계가 드러난다.
import re

VERTICAL = ("0", "0", "0", "1")


def coords(qss):
    return re.search(r"x1:(\S+), y1:(\S+), x2:(\S+), y2:(\S+),", qss).groups()


body_bg = m.theme_for("sunrise")["bg"]
assert coords(body_bg) == VERTICAL, coords(body_bg)
# 탭도 같은 좌표·같은 stop이어야 한 덩어리로 이어진다
tab_bg = m.gradient_qss("sunrise", coords=(0, 0, 0, 1))
assert coords(tab_bg) == VERTICAL
assert body_bg.split(",", 4)[4] == tab_bg.split(",", 4)[4]

# 맞닿는 면의 1px 테두리가 남으면 그게 경계선으로 읽힌다
for _side, _edge in (("right", "border-right: none;"), ("left", "border-left: none;")):
    panel = m.body_stylesheet(m.theme_for("sunrise"), _side).split("#bodyPanel {")[1]
    assert _edge in panel.split("}")[0], (_side, panel[:200])


# ----- 고정 핀 아이콘 -----
# SVG는 fill이 고정이라 그대로 쓰면 어두운 메모색에서 안 보인다 → 글자색으로 틴트한다.
# 틴트 로직을 직접 본다 — 탭 렌더는 폰트/제목 길이에 좌우돼 픽셀 수가 불안정하다.
_light = Tab._pin_pixmap("#1e1e2e", Tab.PIN_ICON_SIZE).toImage()  # 밝은 배경용 어두운 핀
_dark = Tab._pin_pixmap("#f5f5f5", Tab.PIN_ICON_SIZE).toImage()   # 어두운 배경용 밝은 핀
_solid = [(x, y)
          for y in range(_light.height())
          for x in range(_light.width())
          if _light.pixelColor(x, y).alpha() > 200]
assert _solid, "핀 아이콘이 렌더되지 않음 (SVG 경로/플러그인 확인)"
# 같은 자리에서 색만 뒤집혀야 한다 — 틴트가 빠지면 둘이 같아진다
assert all(_light.pixelColor(x, y).red() < 100 for x, y in _solid)
assert all(_dark.pixelColor(x, y).red() > 150 for x, y in _solid)

# 고정한 탭은 고정 안 한 탭과 그림이 달라야 한다 (핀을 실제로 그리는지)
def render_tab(pinned):
    memo = Memo(id=1, title="t", content="", color="mint", is_pinned=pinned,
                created_at="", updated_at="")
    tab = Tab(memo)
    tab.resize(36, 110)
    pm = QPixmap(tab.size())
    pm.fill(QColor(0, 0, 0, 0))
    tab.render(pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return pm.toImage()


# 탭 폭은 레이아웃이 정해야 한다. QPushButton 기본 정책(Minimum)이면 크기 힌트가
# 하한이 되어 (a) 컬럼보다 넓어 잘리고 (b) 선택 테두리가 붙을 때 힌트가 커져 밀린다.
from PyQt6.QtWidgets import QSizePolicy

_probe = Tab(Memo(id=1, title="t", content="", color="mint",
                  created_at="", updated_at=""))
assert _probe.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
assert _probe.minimumWidth() == 0
# 힌트 자체는 선택 여부에 따라 여전히 변한다 — 정책이 Ignored라 레이아웃에 안 먹을 뿐
_probe.update_style(selected=False)
_off = _probe.minimumSizeHint().width()
_probe.update_style(selected=True)
assert _probe.minimumSizeHint().width() > _off  # 정책이 풀리면 이 차이가 밀림이 된다

_on, _off = render_tab(True), render_tab(False)
_diff = sum(1
            for y in range(_on.height())
            for x in range(_on.width())
            if _on.pixelColor(x, y) != _off.pixelColor(x, y))
assert _diff > 20, _diff


# ----- 휴지통 배지 -----
# 레이아웃 전에는 trash_btn.width()가 Qt 기본값(640)이라, 그걸 쓰면 배지가 버튼
# 밖으로 나가 처음엔 안 보인다. 창을 띄우기 전부터 버튼 안에 있어야 한다.
import tempfile
from pathlib import Path

from database import MemoDatabase

_db = MemoDatabase(Path(tempfile.mkdtemp()) / "t.db")
for _i in range(3):
    _db.create(title=f"m{_i}", content="x", color="mint")
_db.soft_delete(_db.list_all()[0].id)

_win = m.SlideMemoWindow(_db)
_badge = _win._trash_badge
assert _badge.text() == "1", _badge.text()
assert not _badge.isHidden(), "휴지통에 메모가 있는데 배지가 숨겨짐"
# 배지가 버튼 영역(폭 = tab_width) 안에 들어와야 한다
assert 0 <= _badge.x() <= _win.tab_width - _badge.width(), (
    _badge.x(), _badge.width(), _win.tab_width
)

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
# 위/아래 핸들이 마스크(=컬럼) 안에 있어야 접힌 채로도 잡힌다
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

# ----- 넓은 컬럼에서 제목 두 줄 -----
# 회전 텍스트라 "줄 수"는 탭의 가로축 잉크 폭으로 드러난다. 좁으면 한 줄(자름),
# 넓으면 두 줄이어야 한다 — 조건이 뒤집히면 이 폭이 그대로 같아진다.
# 번들 폰트를 등록해야 글자 폭·줄간격이 실제 앱과 같다 (없으면 두부 글리프).
from PyQt6.QtGui import QFontDatabase

for _f in m._resource_path("assets/fonts").glob("*.otf"):
    QFontDatabase.addApplicationFont(str(_f))
Tab.app_font_family = "Pretendard"


def ink_width(w):
    tab = Tab(Memo(id=1, title="아주아주긴메모제목입니다", content="", color="mint",
                   created_at="", updated_at=""))
    tab.resize(w, 110)
    pm = QPixmap(tab.size())
    pm.fill(QColor(0, 0, 0, 0))
    tab.render(pm, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    img = pm.toImage()
    cols = [x for x in range(w)
            if any(img.pixelColor(x, y).lightness() < 120
                   for y in range(20, img.height() - 20))]
    return (max(cols) - min(cols) + 1) if cols else 0


_narrow, _wide = ink_width(m.TAB_WIDTH), ink_width(m.TAB_WIDTH_MAX)
assert _narrow > 0 and _wide > _narrow * 1.5, (_narrow, _wide)

print("tabs OK")
