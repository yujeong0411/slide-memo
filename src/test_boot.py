"""main() 부팅 경로가 끝까지 도달하는지 확인.

단위 테스트는 위젯을 직접 만들어 쓰기 때문에 main() 안에서만 지나가는 구간
(스플래시, 폰트 등록, 휴지통·임시파일 정리, 트레이 등록)을 건드리지 않는다.
그 구간의 NameError/AttributeError는 문법 검사로도 안 잡히고 앱이 아예 안 켜지므로,
여기서 실제로 main()을 한 번 태운다.

사용자 데이터는 건드리지 않는다 — DB/APP_DIR을 임시 폴더로 바꿔치기한다.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def demo():
    tmp = Path(tempfile.mkdtemp())
    try:
        # main이 `from database import APP_DIR ...`로 값을 박아 넣으므로
        # database를 먼저 갈아끼운 뒤에 main을 import해야 한다.
        import database
        database.APP_DIR = tmp
        database.DB_PATH = tmp / "memos.db"
        database.IMAGES_DIR = tmp / "images"

        import main as M
        # 이미 있는 이름만 갈아끼운다. 없는 이름을 새로 만들어 주면 import 누락을
        # 이 테스트가 덮어버려서, 정작 잡아야 할 NameError가 안 난다.
        for _name, _value in (("APP_DIR", tmp), ("IMAGES_DIR", tmp / "images")):
            if hasattr(M, _name):
                setattr(M, _name, _value)

        from PyQt6.QtWidgets import QApplication

        # 부팅 확인과 무관한 두 가지는 끈다: 업데이트 체크(네트워크), 팔레트 안내(모달)
        M.UpdateChecker.start = lambda self: None
        M._show_palette_notice = lambda *a, **k: None

        reached = []

        def _fake_exec(*_a):
            # 여기 닿았다 = 부팅 경로를 전부 통과했다는 뜻.
            # 실제 이벤트 루프는 돌리지 않는다 — 트레이 아이콘 때문에 안 끝난다.
            reached.append(True)
            QApplication.instance().processEvents()
            return 0

        QApplication.exec = _fake_exec

        code = M.main()

        assert reached, "main()이 app.exec()에 도달하지 못했다"
        assert code == 0, f"main() 반환 코드 {code}"
        assert (tmp / "memos.db").exists(), "DB가 생성되지 않았다"
        assert M.APP_DIR == tmp, "APP_DIR이 실제 경로로 새어 나갔다"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("boot OK")


if __name__ == "__main__":
    demo()
