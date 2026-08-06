# ponytail: minimal self-check for gradient color logic. run: python src/test_colors.py
import main as m
from database import normalize_color

# 커스텀 그라데이션이 DB 정규화를 통과/거부하는지 (trust boundary)
assert normalize_color("grad:#aabbcc") == "grad:#aabbcc"
assert normalize_color("grad:#fff") == "grad:#fff"
assert normalize_color("grad:nothex") == "sunrise"   # 잘못된 형식 → 기본색
assert normalize_color("garbage") == "sunrise"
assert normalize_color("#ff0000") == "#ff0000"        # 일반 hex 유지
assert normalize_color("ivory") == "ivory"            # 이름 프리셋 유지

# 다색(N) 커스텀
assert normalize_color("grad:#aabbcc,#112233") == "grad:#aabbcc,#112233"
assert normalize_color("grad:#abc,#def,#123") == "grad:#abc,#def,#123"
assert normalize_color("grad:#abc,nothex") == "sunrise"   # 한 색이라도 잘못되면 거부

# is_gradient: 이름 + 커스텀 인식, 일반 hex/솔리드는 제외
assert m.is_gradient("ivory") and m.is_gradient("grad:#aabbcc")
assert not m.is_gradient("#aabbcc") and not m.is_gradient("peach")

# _gradient_def: 단색→2-stop 파생, 다색→균등 stop(0.0~1.0)
d = m._gradient_def("grad:#80c0ff")
assert d["representative"] == "#80c0ff" and len(d["stops"]) == 2
d3 = m._gradient_def("grad:#000000,#ffffff,#ff0000")
assert len(d3["stops"]) == 3 and d3["stops"][0][0] == 0.0 and d3["stops"][-1][0] == 1.0


# ----- 스크롤바 대비 -----
# 원래 버그: 전역 STYLE이 흰색 18%라 밝은 파스텔 메모색 위에서 안 보였다.
# 색을 다시 만질 때 같은 실수를 하면 여기서 걸린다.
from database import COLOR_SEQUENCE


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


for _name in COLOR_SEQUENCE:
    t = m.theme_for(_name)
    assert "scroll" in t and "scroll_hover" in t, _name
    # 프리셋은 전부 그라데이션이라 bg는 qlineargradient 문자열 → 대표색과 비교한다
    bg = m.resolve_color(_name)
    gap = abs(_lum(t["scroll"]) - _lum(bg))
    assert gap > 0.25, (_name, bg, t["scroll"], round(gap, 3))
    # hover는 더 진해져 반응이 보여야 한다
    assert _lum(t["scroll_hover"]) < _lum(t["scroll"]), _name

# 어두운 커스텀 색에선 진하게 하면 묻히므로 밝은 쪽으로 가야 한다
assert m.theme_for("#101020")["scroll"].startswith("rgba(245"), m.theme_for("#101020")
# 그라데이션도 대표색 기준 hex를 돌려준다
assert m.theme_for("grad:#ffd9a0,#ffb3c1")["scroll"].startswith("#")

print("colors OK")
