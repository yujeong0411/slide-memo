"""시험 도우미. 창을 만든 시험은 마지막에 finish()를 부른다.

창을 닫지 않고 끝나면 파이썬이 창과 Qt 앱을 정해지지 않은 순서로 지우다 가끔 꺼진다
(test_versions.py가 가끔 종료 코드 139로 끝나던 원인).
"""
from __future__ import annotations


def finish() -> None:
    """열린 창을 모두 닫고, 도는 스레드를 기다린 뒤, 창을 Qt 앱보다 먼저 지운다."""
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication

    import workers

    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if hasattr(w, "_quitting"):
            w._quitting = True  # SlideMemoWindow는 평소에 닫기를 접기로 바꾼다
        w.close()
    workers.wait_all(10000)
    app.processEvents()
    # 부모가 없는 창만 지운다. 자식 창(안내 말풍선 등)은 부모를 지울 때 Qt가 함께 지우므로,
    # 미리 받아 둔 목록으로 다시 지우면 이미 지워진 것을 지우다 꺼진다 → 지울 때마다 목록을 새로 받는다
    while True:
        orphans = [w for w in app.topLevelWidgets() if w.parent() is None and not sip.isdeleted(w)]
        if not orphans:
            break
        sip.delete(orphans[0])
    app.processEvents()
