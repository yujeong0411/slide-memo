# ponytail: 처리하지 않은 예외로 앱이 꺼지지 않는지, 알림이 쏟아지지 않는지, 화면이 바뀌면 가장자리에 다시 붙는지 self-check.
# run: python src/test_crash_guard.py   (실제 메모 폴더는 쓰지 않는다)
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 1) 다른 프로세스: 신호 처리 함수 안의 예외에도 앱이 꺼지지 않는다 (예전에는 Qt6Core.dll c0000409로 꺼졌다)
child = textwrap.dedent("""
    import sys
    sys.path.insert(0, %r)
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    import main as M
    app = QApplication([])
    M.install_exception_guard()
    QTimer.singleShot(0, lambda: 1 / 0)
    QTimer.singleShot(300, app.quit)
    app.exec()
    print("살아남음")
""" % HERE)
r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, encoding="utf-8",
                   env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8"), timeout=60)
assert r.returncode == 0 and "살아남음" in r.stdout, (hex(r.returncode & 0xFFFFFFFF), r.stdout, r.stderr[-500:])
assert "ZeroDivisionError" in r.stderr, "개발 실행에서는 콘솔에 오류가 보여야 한다"

# 2) 같은 프로세스: 알림 횟수, 저장 중 오류, 다른 스레드
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.DB_PATH, database.IMAGES_DIR = tmp, tmp / "memos.db", tmp / "images"
import main as M  # noqa: E402

M.APP_DIR, M.IMAGES_DIR = tmp, tmp / "images"
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
db = M.MemoDatabase(tmp / "memos.db")
memo = db.create(title="t", content="<p>a</p>")
win = M.SlideMemoWindow(db)
win._load_memo(memo)
guard = M.ExceptionGuard()
guard.window = win
toasts: list[str] = []
win._show_toast = lambda msg, *a, **k: toasts.append(msg)


def raise_in(fn):
    try:
        fn()
    except Exception:
        return sys.exc_info()
    raise AssertionError("예외가 안 났다")


def boom():
    raise ValueError("메모 내용이 들어 있을 수 있는 값")


# 저장과 상관없는 오류: 평소 저장을 한 번 하고 알림을 띄운다. 같은 오류가 이어져도 알림은 한 번만
win.editor.setPlainText("고친 내용")
guard(*raise_in(boom))
assert db.get(memo.id).content != "<p>a</p>", "오류 뒤에 평소 저장을 해야 한다"
assert toasts == ["문제가 생겨 방금 동작을 멈췄어요. 메모는 저장해 두었어요."], toasts
for _ in range(5):
    guard(*raise_in(boom))
assert len(toasts) == 1, "같은 오류가 반복돼도 알림이 쏟아지면 안 된다"
assert all("메모 내용" not in t and "ValueError" not in t for t in toasts), "오류 내용이 화면에 보이면 안 된다"

# 저장하다 난 오류: 다시 저장하지 않는다 (꼬리 물기 방지)
guard._last_notice = -M.ERROR_NOTICE_GAP_S
calls = []
real_update = db.update


def broken_update(*a, **k):
    calls.append(1)
    raise RuntimeError("디스크 문제")


db.update = broken_update
win.editor.setPlainText("또 고친 내용")
guard(*raise_in(win.save_now))
assert len(calls) == 1, f"저장 중 오류인데 다시 저장했다 ({len(calls)}번)"
assert toasts[-1] == "문제가 생겨 방금 동작을 멈췄어요. 앱은 계속 쓸 수 있어요.", toasts[-1]
db.update = real_update

# 다른 스레드에서 난 오류: 화면을 건드리지 않는다
guard._last_notice = -M.ERROR_NOTICE_GAP_S
before = len(toasts)
t = threading.Thread(target=lambda: guard(*raise_in(boom)))
t.start()
t.join()
assert len(toasts) == before, "다른 스레드에서 화면을 건드리면 안 된다"

# 진단용 빌드가 붙이는 기록 함수는 오류마다 불린다
seen = []
M.EXCEPTION_LISTENERS.append(lambda et, v, tb: seen.append(et.__name__))
guard(*raise_in(boom))
assert seen == ["ValueError"], seen
M.EXCEPTION_LISTENERS.clear()

# 3) 화면이 바뀌면 남은 화면 가장자리에 다시 붙는다 (모니터 하나를 끊은 것처럼 화면 범위를 바꾼다)
win.show()
win._screen_rect = lambda: QRect(100, 0, 800, 500)
win._on_screens_changed()
QTest.qWait(500)  # 신호를 모으는 0.3초 뒤에 한 번
g = win.geometry()
assert g.right() == 899 and g.height() <= 500 and g.top() >= 0, g

import testkit  # noqa: E402

testkit.finish()
print("crash guard OK")
