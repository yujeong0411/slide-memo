# ponytail: minimal self-check for 업데이트 후 '새로운 기능' 안내. run: python src/test_whatsnew.py
# 버전 비교를 문자열로 하면 "1.10.0" < "1.9.0"이 되는 종류의 실수라 못박아 둔다.
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main as m

assert m._ver_tuple("v1.2.0") == (1, 2, 0)
assert m._ver_tuple("1.10.0") > m._ver_tuple("1.9.0")
assert m._ver_tuple("") == () and m._ver_tuple("dev") == ()  # 깨진 값도 죽지 않는다

# 안내 기록이 없는 사용자(= 안내 기능 이전 버전에서 올라옴)에게는 전부 보여준다
assert m._whats_new_since("") == m.WHATS_NEW
# 기록이 있으면 그 뒤 것만
assert [v for v, _ in m._whats_new_since("1.2.0")] == [
    v for v, _ in m.WHATS_NEW if m._ver_tuple(v) > (1, 2, 0)
]
# 현재 버전까지 다 본 사용자에겐 안 뜬다 = 목록에 미래 버전이 섞여 있지 않다
assert m._whats_new_since(m.APP_VERSION) == [], "APP_VERSION 미반영 항목이 있음"

# 최신 버전이 위 (표시 순서)
_vers = [m._ver_tuple(v) for v, _ in m.WHATS_NEW]
assert _vers == sorted(_vers, reverse=True), _vers
assert all(lines for _, lines in m.WHATS_NEW), "내용 없는 버전 항목"

print("whatsnew OK")
