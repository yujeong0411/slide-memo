"""AI API 키 저장 동작 검증.

OS 키링은 건드리지 않는다 — settings_dialog가 이름으로 가져다 쓰는
save/load/delete_api_key를 메모리 dict로 바꿔치기해서 확인한다.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

import settings_dialog as SD
from database import MemoDatabase

_KEYS: dict[str, str] = {}


def _install_fake_keyring() -> None:
    SD.save_api_key = lambda p, k: _KEYS.__setitem__(p, k)
    SD.load_api_key = lambda p: _KEYS.get(p)
    SD.delete_api_key = lambda p: _KEYS.pop(p, None)


def _dialog(db, provider: str):
    db.set_setting_str("ai_provider", provider)
    return SD.SettingsDialog(db)


def demo():
    app = QApplication.instance() or QApplication(sys.argv)
    _install_fake_keyring()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = MemoDatabase(Path(d) / "t.db")

        # 1) 키 칸을 비우고 확인 → keyring에서 지워져야 한다
        _KEYS.clear()
        _KEYS["anthropic"] = "sk-ant-old"
        dlg = _dialog(db, "anthropic")
        assert dlg._key_edit.text() == "sk-ant-old"
        dlg._key_edit.setText("")
        dlg._save_and_accept()
        assert "anthropic" not in _KEYS, f"키를 비웠는데 남아 있다: {_KEYS}"

        # 2) 새 키 입력은 그대로 저장
        dlg = _dialog(db, "anthropic")
        dlg._key_edit.setText("sk-ant-new")
        dlg._save_and_accept()
        assert _KEYS["anthropic"] == "sk-ant-new"

        # 3) provider가 openai여도 같은 방식으로 저장된다
        _KEYS.clear()
        _KEYS["openai"] = "sk-shared"
        dlg = _dialog(db, "openai")
        dlg._key_edit.setText("sk-shared-v2")
        dlg._save_and_accept()
        assert _KEYS["openai"] == "sk-shared-v2", _KEYS

        # 4) 다른 제공자를 저장해도 예전에 넣은 OpenAI 키(녹음용이던 것 포함)는 그대로 남는다 (2.2.0)
        _KEYS["anthropic"] = "sk-ant"
        dlg = _dialog(db, "anthropic")
        dlg._save_and_accept()
        assert _KEYS == {"openai": "sk-shared-v2", "anthropic": "sk-ant"}, _KEYS

        # 5) 목록에서 빠진 구버전 모델을 쓰고 있었으면 그 선택이 유지돼야 한다
        db.set_setting_str("ai_model", "claude-sonnet-4-6")
        dlg = _dialog(db, "anthropic")
        assert dlg._model_combo.currentData() == "claude-sonnet-4-6", (
            f"고른 모델이 {dlg._model_combo.currentData()}로 바뀌었다"
        )
        dlg._save_and_accept()
        assert db.get_setting_str("ai_model") == "claude-sonnet-4-6"

        # 6) 저장된 모델이 아예 없으면 기본 모델(=가장 싼 쪽)로
        db.set_setting_str("ai_model", "")
        dlg = _dialog(db, "anthropic")
        assert dlg._model_combo.currentData() == "claude-haiku-4-5"

        db.close()
    print("ai keys OK")


if __name__ == "__main__":
    demo()
