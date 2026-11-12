# ponytail: 앱을 켤 때 인터넷 접속은 업데이트 확인뿐인지 self-check. run: python src/test_startup_network.py
"""AI 기능을 켜지 않으면 앱을 켤 때 GitHub 업데이트 확인(api.github.com) 말고는 접속하지 않는다.
실제 연결은 막고, 어디에 접속하려 했는지만 기록한다."""
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)  # 앱이 직접 켜는지 본다
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

hosts: list[str] = []


def blocked(host, *args, **kwargs):
    hosts.append(str(host))
    raise OSError("test: network blocked")


socket.getaddrinfo = blocked

tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR = tmp
database.DB_PATH = tmp / "memos.db"
database.IMAGES_DIR = tmp / "images"
import main as M  # noqa: E402

for name, value in (("APP_DIR", tmp), ("IMAGES_DIR", tmp / "images")):
    if hasattr(M, name):
        setattr(M, name, value)
from PyQt6.QtWidgets import QApplication  # noqa: E402

checkers = []
_start = M.UpdateChecker.start
M.UpdateChecker.start = lambda self: (checkers.append(self), _start(self))[1]
M._show_palette_notice = lambda *a, **k: None


def fake_exec(*_a):
    for checker in checkers:  # 업데이트 확인이 접속을 시도하고 끝날 때까지 기다린다
        checker.wait(10000)
    QApplication.instance().processEvents()
    return 0


QApplication.exec = fake_exec
from PyQt6.QtCore import Qt  # noqa: E402

# 드롭다운·메뉴·툴팁 펼침 효과를 끄는지 (offscreen은 효과 값을 늘 끔으로 돌려주어, 부른 기록으로 본다)
_EFFECTS = (Qt.UIEffect.UI_AnimateCombo, Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_AnimateTooltip)
_effect_calls = []
_real_set_effect = QApplication.setEffectEnabled
QApplication.setEffectEnabled = staticmethod(lambda e, on=True: (_effect_calls.append((e, on)), _real_set_effect(e, on))[1])
assert M.main() == 0
assert {e for e, on in _effect_calls if not on} >= set(_EFFECTS), f"펼침 효과를 끄지 않았다: {_effect_calls}"
assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True", "앱이 가격표 받기를 끄지 않았다"
assert "litellm" not in sys.modules, "AI를 쓰지 않았는데 LiteLLM을 불러왔다"
assert "ai_provider" not in sys.modules, "AI를 쓰지 않았는데 ai_provider를 불러왔다"
assert set(hosts) == {"api.github.com"}, f"업데이트 확인 말고 다른 곳에 접속하려 했다: {sorted(set(hosts))}"

# AI를 처음 쓸 때 LiteLLM을 불러와도 가격표를 받으러 가지 않는다
hosts.clear()
import ai_provider  # noqa: E402

ai_provider._litellm()
assert "litellm" in sys.modules
assert hosts == [], f"LiteLLM을 불러올 때 접속하려 했다: {sorted(set(hosts))}"
shutil.rmtree(tmp, ignore_errors=True)
print("startup network OK", flush=True)
os._exit(0)
