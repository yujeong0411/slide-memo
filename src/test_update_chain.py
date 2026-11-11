# ponytail: 배포 저장소를 옮겨도 2.0.0 → 2.1.0(지금 저장소) → 2.1.1(새 저장소)로 이어지는지 self-check.
# GitHub에 접속하지 않고 가짜 응답을 쓴다. run: python src/test_update_chain.py
import json
import os
import subprocess
import sys
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from PyQt6.QtWidgets import QApplication  # noqa: E402

import links  # noqa: E402
import main as M  # noqa: E402

OLD, NEW = "yujeong0411/slide-memo", "yujeong0411/slide-memo-releases"
latest = {}   # 저장소 → 최신 태그
asked = []


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    url = req.full_url
    asked.append(url)
    repo = url.split("/repos/", 1)[1].rsplit("/releases/latest", 1)[0]
    tag = latest[repo]
    return _Resp(json.dumps({"tag_name": f"v{tag}", "assets": [{"name": "SlideMemo-Setup.exe"}]}).encode())


urllib.request.urlopen = fake_urlopen


def check(app_version, repo):
    M.APP_VERSION, M._GITHUB_REPO = app_version, repo
    got = []
    checker = M.UpdateChecker()
    checker.update_available.connect(lambda cur, lat: got.append(lat))
    checker.run()  # 같은 줄에서 바로 돌린다
    return got


app = QApplication([])
opened = []
M.QDesktopServices.openUrl = lambda url: opened.append(url.toString())

# 2.0.0 설치본은 지금 저장소를 본다 (태그 v2.0.0의 코드)
old_main = subprocess.run(["git", "show", "v2.0.0:src/main.py"], cwd=here, capture_output=True, text=True,
                          encoding="utf-8").stdout
assert f'_GITHUB_REPO = "{OLD}"' in old_main, "2.0.0이 보는 저장소가 예상과 다름"
assert links.UPDATE_REPO == NEW and M._GITHUB_REPO == NEW, "이 버전부터는 새 저장소를 본다"

# 1) 2.1.0을 두 곳에 올린 뒤: 2.0.0 사용자는 지금 저장소에서 2.1.0을 받는다
latest.update({OLD: "2.1.0", NEW: "2.1.0"})
assert check("2.0.0", OLD) == ["2.1.0"] and asked[-1].endswith(f"/repos/{OLD}/releases/latest")
M.UpdateDialog("2.0.0", "2.1.0")._open_download()
assert opened[-1] == f"https://github.com/{OLD}/releases/latest/download/SlideMemo-Setup.exe"
# 2.1.0을 설치하면 새 저장소를 본다. 같은 버전이면 안내하지 않는다
assert check("2.1.0", NEW) == []

# 2) 2.1.1은 새 저장소에만: 2.1.0 사용자는 새 저장소에서 받는다
latest[NEW] = "2.1.1"
assert check("2.1.0", NEW) == ["2.1.1"] and asked[-1].endswith(f"/repos/{NEW}/releases/latest")
M.UpdateDialog("2.1.0", "2.1.1")._open_download()
assert opened[-1] == links.SETUP_URL == f"https://github.com/{NEW}/releases/latest/download/SlideMemo-Setup.exe"

# 3) 늦게 업데이트하는 2.0.0 사용자: 지금 저장소의 다리(2.1.0) → 새 저장소의 2.1.1로 이어진다
assert check("2.0.0", OLD) == ["2.1.0"], "지금 저장소에는 2.1.0이 마지막으로 남아 있어야 한다"
assert check("2.1.0", NEW) == ["2.1.1"]

# 응답이 망가져도 조용히 넘어간다 (업데이트 확인이 앱을 멈추지 않는다)
latest[NEW] = ""
assert check("2.1.0", NEW) == []
print("update chain OK", flush=True)
os._exit(0)
