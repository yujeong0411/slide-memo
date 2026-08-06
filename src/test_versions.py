# ponytail: minimal self-check for version history. run: python src/test_versions.py
import tempfile
from pathlib import Path

import database as db_mod
from database import MemoDatabase

tmp = Path(tempfile.mkdtemp()) / "t.db"
db = MemoDatabase(tmp)
m = db.create(title="제목", content="원본 내용")

# 첫 스냅샷은 항상 남는다 (메모의 원래 상태 = 가장 값진 버전)
assert db.snapshot(m.id) is True
db.update(m.id, content="지워진 내용")
assert [v.content for v in db.list_versions(m.id)] == ["원본 내용"]

# 간격 제한: 방금 떴으므로 내용이 달라도 건너뛴다
assert db.snapshot(m.id) is False
# force는 간격을 무시한다
assert db.snapshot(m.id, force=True) is True
assert len(db.list_versions(m.id)) == 2
# 직전 버전과 내용이 같으면 force여도 남기지 않는다
assert db.snapshot(m.id, force=True) is False

# 복원: 지금 내용도 버전으로 남아 되돌리기를 다시 취소할 수 있다
db.update(m.id, content="최신 내용")  # 아직 버전에 없는 상태
before = len(db.list_versions(m.id))
restored = db.restore_version(db.list_versions(m.id)[-1].id)  # 가장 오래된 = 원본
assert restored.content == "원본 내용"
assert len(db.list_versions(m.id)) == before + 1
assert db.list_versions(m.id)[0].content == "최신 내용"  # 되돌리기 직전 상태가 보존됨

# 보관 개수 제한 (간격 0으로 두면 매번 저장되므로 프루닝만 검증)
db_mod.VERSION_INTERVAL_MIN = 0
for i in range(db_mod.VERSION_KEEP + 10):
    db.update(m.id, content=f"내용 {i}")
    db.snapshot(m.id)
versions = db.list_versions(m.id)
assert len(versions) == db_mod.VERSION_KEEP, len(versions)
assert versions[0].content == f"내용 {db_mod.VERSION_KEEP + 9}"  # 최신순 정렬

# 메모 하드 삭제 시 버전도 CASCADE로 정리된다 (고아 행 방지)
db.delete(m.id)
assert db.list_versions(m.id) == []

# 소프트 삭제(휴지통)는 버전을 건드리지 않는다 — 복원하면 이력도 살아있어야 한다
m2 = db.create(content="A")
db.snapshot(m2.id)
db.soft_delete(m2.id)
assert len(db.list_versions(m2.id)) == 1

db.close()
print("versions OK")
