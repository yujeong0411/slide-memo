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

# ----- 신규 설치 판정 -----
# 메모 개수로만 판단하면 "메모를 전부 지운 사용자"가 신규 설치로 오인되고,
# 그러면 업데이트 안내가 조용히 '본 것'으로 처리돼 영영 안 뜬다 (v1.4.0 실제 사고).
import tempfile
from pathlib import Path

from database import MemoDatabase

_db = MemoDatabase(Path(tempfile.mkdtemp()) / "fresh.db")
assert _db.is_fresh_install(), "방금 만든 DB는 신규 설치다"
_memo = _db.create(title="a")
assert not _db.is_fresh_install()
_db.soft_delete(_memo.id)
assert not _db.is_fresh_install(), "휴지통에 있어도 쓰던 사람이다"
_db.set_setting_int("window_width", 400)
assert not _db.is_fresh_install(), "설정이 남아 있으면 쓰던 사람이다"

print("whatsnew OK")
