"""AI 요청이 앱에 넣은 키와 정해진 주소로만 나가는지 검증 (인터넷 접속 없음).

PC 환경 변수에 가짜 키·주소·프록시 전환을 넣어 두고, httpx 전송을 가로채
실제로 나가려던 주소와 키를 본다. 가로챈 요청은 밖으로 보내지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENV_TRAPS = {
    "ANTHROPIC_API_KEY": "env-key", "OPENAI_API_KEY": "env-key", "GEMINI_API_KEY": "env-key",
    "GOOGLE_API_KEY": "env-key",
    "ANTHROPIC_BASE_URL": "https://evil.example", "ANTHROPIC_API_BASE": "https://evil.example",
    "OPENAI_BASE_URL": "https://evil.example", "OPENAI_API_BASE": "https://evil.example",
    "GEMINI_API_BASE": "https://evil.example",
    "USE_LITELLM_PROXY": "True", "LITELLM_PROXY_API_BASE": "https://evil.example",
    "SSL_VERIFY": "False",
}


class _Caught(Exception):
    pass


def demo():
    os.environ.update(ENV_TRAPS)
    import httpx

    sent: list[httpx.Request] = []

    def fake_send(self, request, **kw):
        sent.append(request)
        raise _Caught()

    httpx.Client.send = fake_send

    import ai_provider as AP
    from ai_provider import AIProvider, MissingKeyError

    # 1) 키가 없으면 아무 요청도 만들지 않는다
    for p in ("anthropic", "openai", "gemini"):
        try:
            AIProvider(p, AP.PROVIDERS[p]["default_model"], api_key="").call("s", "u")
            raise AssertionError(f"{p}: 키 없이 요청이 나감")
        except MissingKeyError:
            pass
    assert not sent
    ok, msg = AIProvider("anthropic", "claude-haiku-5-5", api_key="").test_connection()
    assert not ok and "키" in msg, msg

    # 2) 키가 있으면 앱의 키와 정해진 주소로만
    expect = {
        "anthropic": "https://api.anthropic.com/",
        "openai": "https://api.openai.com/v1/",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/",
    }
    for p, base in expect.items():
        sent.clear()
        try:
            AIProvider(p, AP.PROVIDERS[p]["default_model"], api_key="app-key").call("s", "u")
        except Exception:
            pass
        assert sent, f"{p}: 요청이 안 만들어짐"
        req = sent[-1]
        assert str(req.url).startswith(base), f"{p}: {req.url}"
        auth = " ".join(req.headers.get(h, "") for h in ("x-api-key", "authorization", "x-goog-api-key"))
        assert "app-key" in auth and "env-key" not in auth, f"{p}: {auth}"

    # 3) 막은 설정은 프로세스에서 지워졌다 (.env도 안 읽음)
    for name in AP._BLOCKED_ENV:
        assert name not in os.environ, name
    assert os.environ["LITELLM_MODE"] == "PRODUCTION"

    # 4) litellm 모델 목록에 없는 이름도 제공자별 공식 주소로 (AI 기능과 [키 확인하기] 두 길)
    import json
    lit = AP._litellm()
    unknown = {
        "anthropic": ("claude-made-up-9", "https://api.anthropic.com/v1/messages"),
        "openai": ("gpt-made-up-9", "https://api.openai.com/v1/chat/completions"),
        "gemini": ("gemini/gemini-made-up-9",
                   "https://generativelanguage.googleapis.com/v1beta/models/gemini-made-up-9:"),
    }
    for p, (model, url) in unknown.items():
        assert model not in lit.model_cost and model.split("/")[-1] not in lit.model_cost, \
            f"{model}가 litellm 목록에 생겼다 — 다른 지어낸 이름으로 바꿔야 시험이 뜻이 있다"
        for path in ("call", "test_connection"):
            sent.clear()
            ai = AIProvider(p, model, api_key="app-key")
            try:
                ai.call("s", "u", max_tokens=64) if path == "call" else ai.test_connection()
            except Exception:
                pass
            assert sent, f"{p} {path}: 요청이 안 만들어짐 (제공자를 못 찾았나?)"
            req = sent[-1]
            assert str(req.url).startswith(url), f"{p} {path}: {req.url}"
            auth = " ".join(req.headers.get(h, "") for h in ("x-api-key", "authorization", "x-goog-api-key"))
            assert "app-key" in auth and "env-key" not in auth, f"{p} {path}: {auth}"
            body = json.loads(req.content)
            if p != "gemini":  # Gemini는 모델 이름이 주소에 들어간다 (위 url)
                assert body["model"] == model, body.get("model")
            limit = {"anthropic": body.get("max_tokens"), "openai": body.get("max_completion_tokens"),
                     "gemini": body.get("generationConfig", {}).get("max_output_tokens")}[p]
            assert limit == AP.MIN_CLOUD_MAX_TOKENS, f"{p} {path}: 길이 한도 {limit}"
            if p == "openai":
                assert "max_tokens" not in body, "OpenAI 추론 모델은 max_tokens를 받지 않는다"

    # 5) 목록에 없는 모델도 응답을 받아 글을 돌려준다 (비용 계산이 실패해도 멈추지 않는다)
    def fake_reply(self, request, **kw):
        sent.append(request)
        return httpx.Response(200, request=request, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-made-up-9",
            "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1}})

    httpx.Client.send = fake_reply
    assert AIProvider("anthropic", "claude-made-up-9", api_key="app-key").call("s", "u") == ("OK", 4)
    httpx.Client.send = fake_send

    # 6) Ollama: 받아 둔 모델 목록과 연결 확인은 내 PC(localhost)에만 묻는다
    import urllib.request
    asked: list[str] = []

    def fake_open(self, req, *a, **kw):
        asked.append(req if isinstance(req, str) else req.full_url)
        raise OSError("Ollama 꺼짐")

    real_open = urllib.request.OpenerDirector.open
    urllib.request.OpenerDirector.open = fake_open
    sent.clear()
    assert AP.ollama_models() is None
    ok, msg = AIProvider("ollama", "ollama/llama3.2").test_connection()
    assert not ok and "Ollama" in msg, msg
    assert asked and all(u.startswith("http://localhost:11434/") for u in asked), asked
    assert not sent, "Ollama 연결 확인이 모델을 부르면 안 된다"
    urllib.request.OpenerDirector.open = real_open

    # 7) 설정 화면: 제공자를 바꾸면 그 제공자의 기본 모델, 직접 넣은 이름은 앞뒤 빈칸을 지워 저장,
    #    Ollama는 키 칸 대신 안내와 [연결 확인]
    import tempfile
    from pathlib import Path
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import settings_dialog as SD
    from database import MemoDatabase

    app = QApplication.instance() or QApplication(sys.argv)
    SD.load_api_key = lambda p: None  # OS 키링은 건드리지 않는다
    SD.save_api_key = SD.delete_api_key = lambda *a: None
    SD.ollama_models = lambda: ["ollama/mine:latest"]  # 내 PC의 Ollama 대신
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = MemoDatabase(Path(d) / "t.db")
        db.set_setting_str("ai_provider", "anthropic")
        db.set_setting_str("ai_model", "claude-opus-5")  # 추천 목록에서 빠진 예전 모델
        dlg = SD.SettingsDialog(db)
        assert dlg._model_name() == "claude-opus-5", "저장된 모델이 다른 모델로 바뀌면 안 된다"
        for p in ("openai", "gemini", "anthropic"):
            dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData(p))
            assert dlg._model_name() == AP.PROVIDERS[p]["default_model"], (p, dlg._model_name())
            assert dlg._model_combo.findText("claude-opus-5") == -1, "다른 제공자의 모델이 남았다"
            assert not dlg._key_edit.isHidden() and dlg._key_none_lbl.isHidden()
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        assert dlg._model_name() == "ollama/mine:latest", dlg._model_name()
        assert dlg._key_edit.isHidden() and dlg._eye_btn.isHidden(), "Ollama인데 빈 키 칸이 보인다"
        assert not dlg._key_none_lbl.isHidden() and dlg._test_btn.text() == "연결 확인"
        SD.ollama_models = lambda: None
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("anthropic"))
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        assert "응답하지 않아요" in dlg._model_hint_lbl.text() and dlg._model_name() == "ollama/llama3.2"
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("anthropic"))
        dlg._model_combo.setEditText("  claude-new-model-10  ")
        dlg._save_and_accept()
        assert db.get_setting_str("ai_model") == "claude-new-model-10", db.get_setting_str("ai_model")
        db.close()
    print("test_ai_env OK")


if __name__ == "__main__":
    demo()
