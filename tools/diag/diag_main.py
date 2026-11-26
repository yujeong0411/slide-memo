"""진단용 SlideMemo — 개발자 본인만 쓰는 빌드. 배포 설치본에는 들어가지 않는다.
(배포용 SlideMemo.spec은 src/main.py만 쓰고, 이 파일은 tools/diag/SlideMemo-diag.spec만 쓴다. 결과는 dist-diag/)

기록 파일: 바탕화면의 SlideMemo-diag.log (켤 때마다 이어 쓴다)
남기는 것: 처리하지 않은 예외의 종류와 호출 경로(파일·줄·함수 이름), Qt 경고·치명적 메시지,
          faulthandler(프로그램 수준 충돌), 화면 추가·제거·변화와 그때의 창 위치
남기지 않는 것: 예외 메시지(값이 들어갈 수 있다), 지역 변수 값, 메모 제목·본문, API 키
업데이트 안내는 띄우지 않는다.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import time
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):  # 빌드하지 않고 바로 실행할 때
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import main as M  # noqa: E402
from PyQt6.QtCore import QStandardPaths, QtMsgType, qInstallMessageHandler  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

LOG = Path(os.environ.get("SLIDEMEMO_DIAG_LOG") or  # 시험용으로만 바꾼다
           Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)) / "SlideMemo-diag.log")
_fh = open(LOG, "a", encoding="utf-8", buffering=1)  # 줄마다 바로 쓴다 (꺼지기 직전 기록도 남게)


def log(kind: str, text: str) -> None:
    _fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{kind}] {text}\n")


# ----- 처리하지 않은 예외: 종류와 호출 경로만 (메시지·변수 값은 남기지 않는다)
def record_exception(etype, _value, tb) -> None:
    frames = traceback.extract_tb(tb)
    path = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames))
    log("예외", f"{etype.__name__} at {path or '(호출 경로 없음)'}")


M.EXCEPTION_LISTENERS.append(record_exception)

# ----- Qt 경고·치명적 메시지 (예: "QThread: Destroyed while thread is still running")
_MODES = {QtMsgType.QtDebugMsg: None, QtMsgType.QtInfoMsg: None, QtMsgType.QtWarningMsg: "Qt 경고",
          QtMsgType.QtCriticalMsg: "Qt 심각", QtMsgType.QtFatalMsg: "Qt 치명"}


def qt_message(mode, context, message) -> None:
    kind = _MODES.get(mode)
    if kind:
        where = f" ({Path(context.file).name}:{context.line})" if context.file else ""
        log(kind, f"{message}{where}")


qInstallMessageHandler(qt_message)

# ----- 프로그램 수준 충돌 (파이썬 예외가 아닌 것)
faulthandler.enable(file=_fh, all_threads=True)


# ----- 화면 변화와 그때의 창 위치
def _screens() -> str:
    app = QGuiApplication.instance()
    return ", ".join(f"{s.name()} {s.geometry().getRect()} x{s.devicePixelRatio():g}" for s in app.screens())


_orig_watch = M.SlideMemoWindow._watch_screens
_orig_fit = M.SlideMemoWindow._fit_to_screen


def _watch_screens(self) -> None:
    _orig_watch(self)
    app = QGuiApplication.instance()
    app.screenAdded.connect(lambda s: log("화면", f"추가: {s.name()} → {_screens()}"))
    app.screenRemoved.connect(lambda s: log("화면", f"제거: {s.name()}"))
    app.primaryScreenChanged.connect(lambda s: log("화면", f"주 모니터: {s.name()}"))
    log("화면", f"켤 때: {_screens()}")


def _fit_to_screen(self) -> None:
    _orig_fit(self)
    log("화면", f"가장자리에 다시 붙임: 창 {self.geometry().getRect()} (화면 {_screens()})")


M.SlideMemoWindow._watch_screens = _watch_screens
M.SlideMemoWindow._fit_to_screen = _fit_to_screen

# ----- 업데이트 안내를 띄우지 않는다
M.UpdateChecker.start = lambda self: None

if __name__ == "__main__":
    log("시작", f"SlideMemo-diag {M.APP_VERSION} (기록: 예외 종류·호출 경로, Qt 경고, 충돌, 화면)")
    code = M.main()
    log("끝", f"종료 코드 {code}")
    sys.exit(code)
