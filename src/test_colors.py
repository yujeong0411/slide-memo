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

print("colors OK")
