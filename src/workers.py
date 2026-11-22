"""돌고 있는 QThread를 끝날 때까지 붙잡아 둔다.

돌고 있는 QThread가 지워지면 Qt가 "Destroyed while thread is still running"으로 앱을 끈다(qFatal).
창이 먼저 닫히거나(설정 창의 [키 확인하기]) 앱이 끝날 때(업데이트 확인, AI 요청) 생길 수 있다.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QThread

_running: set[QThread] = set()


def _alive(worker: QThread) -> bool:
    try:
        return worker.isRunning()
    except RuntimeError:  # C++ 쪽이 이미 지워졌다 (끝난 뒤 deleteLater)
        return False


def keep(worker: QThread) -> QThread:
    """worker를 시작하기 전에 맡긴다. 끝난 것은 다음에 맡길 때 정리된다."""
    _running.difference_update({w for w in _running if not _alive(w)})
    _running.add(worker)
    return worker


def any_running() -> bool:
    return any(_alive(w) for w in _running)


def wait_all(timeout_ms: int) -> bool:
    """맡긴 스레드가 모두 끝날 때까지 최대 timeout_ms 기다린다. 다 끝났으면 True."""
    deadline = time.monotonic() + timeout_ms / 1000
    for w in list(_running):
        left = int((deadline - time.monotonic()) * 1000)
        if left <= 0:
            break
        if _alive(w):
            w.wait(left)
    return not any_running()


def detach_running() -> None:
    """아직 도는 스레드를 부모 창에서 떼어, 창이 지워질 때 함께 지워지지 않게 한다."""
    for w in _running:
        if _alive(w) and w.parent() is not None:
            w.setParent(None)
