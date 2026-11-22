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
        def ollama_reply() -> None:
            """뒤에서 받아 온 목록이 화면에 들어올 때까지 기다린다."""
            dlg._ollama_req.wait()
            app.processEvents()

        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        assert "찾는 중" in dlg._model_hint_lbl.text(), "받아 오는 동안 창이 기다리면 안 된다"
        ollama_reply()
        assert dlg._model_name() == "ollama/mine:latest", dlg._model_name()
        assert dlg._key_edit.isHidden() and dlg._eye_btn.isHidden(), "Ollama인데 빈 키 칸이 보인다"
        assert not dlg._key_none_lbl.isHidden() and dlg._test_btn.text() == "연결 확인"
        # 받아 오는 동안 사용자가 고친 이름은 덮어쓰지 않는다
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("anthropic"))
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        dlg._model_combo.setEditText("ollama/typed")
        ollama_reply()
        assert dlg._model_name() == "ollama/typed", dlg._model_name()
        # 늦게 온 옛 결과는 버린다 (그새 다른 제공자로 바꿨다)
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        old = dlg._ollama_req
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("openai"))
        old.wait()
        app.processEvents()
        assert dlg._model_name() == AP.PROVIDERS["openai"]["default_model"], dlg._model_name()
        SD.ollama_models = lambda: None
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("ollama"))
        ollama_reply()
        assert "응답하지 않아요" in dlg._model_hint_lbl.text() and dlg._model_name() == "ollama/llama3.2"
        dlg._provider_combo.setCurrentIndex(dlg._provider_combo.findData("anthropic"))
        dlg._model_combo.setEditText("  claude-new-model-10  ")
        dlg._save_and_accept()
        assert db.get_setting_str("ai_model") == "claude-new-model-10", db.get_setting_str("ai_model")

        # 8) 생각 수준(effort): 받는 모델엔 low, 받지 않는 이름은 빼고, 거절하면 빼고 한 번만 다시 보낸 뒤 기억한다
        def effort_in(body: dict, p: str):
            if p == "anthropic":
                return body.get("output_config", {}).get("effort")
            if p == "openai":
                return body.get("reasoning_effort")
            return body.get("generationConfig", {}).get("thinkingConfig", {}).get("thinkingLevel")

        def bodies(p, model, path="call", **kw):
            sent.clear()
            ai = AIProvider(p, model, api_key="app-key", **kw)
            try:
                ai.call("s", "u") if path == "call" else ai.test_connection()
            except Exception:
                pass
            return [json.loads(r.content) for r in sent], ai

        for p, model in (("anthropic", "claude-haiku-5-5"), ("anthropic", "claude-made-up-9"),
                         ("openai", "gpt-6-luna"), ("gemini", "gemini/gemini-3.5-flash-lite")):
            for path in ("call", "test_connection"):
                got, _ = bodies(p, model, path)
                assert got and effort_in(got[-1], p) == "low", (p, model, path, got[-1:])
        for p, model in (("anthropic", "claude-haiku-4-5"), ("anthropic", "claude-sonnet-4-5-20250929"),
                         ("openai", "gpt-4o-mini"), ("gemini", "gemini/gemini-2.5-flash")):
            got, _ = bodies(p, model)
            assert got and effort_in(got[-1], p) is None, (p, model, "받지 않는 이름엔 보내지 않는다")
        got, _ = bodies("anthropic", "claude-haiku-5-5", send_effort=False)  # 거절한 적 있는 모델
        assert got and effort_in(got[-1], "anthropic") is None

        def ok_reply(request):
            return httpx.Response(200, request=request, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": "m",
                "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 1}})

        def bad_request(request, message):
            return httpx.Response(400, request=request, json={
                "type": "error", "error": {"type": "invalid_request_error", "message": message}})

        def rejects_effort(self, request, **kw):  # 생각 수준 값이 있으면 400, 없으면 정상 답
            sent.append(request)
            if "output_config" in json.loads(request.content):
                return bad_request(request, "output_config.effort: Extra inputs are not permitted")
            return ok_reply(request)

        def always_400(self, request, **kw):  # 값과 상관없는 400
            sent.append(request)
            return bad_request(request, "messages: text content blocks must be non-empty")

        # 값을 거절하는 400: 값을 빼고 한 번만 다시 보내 답을 받고, 거절했다고 표시한다
        sent.clear()
        httpx.Client.send = rejects_effort
        ai = AIProvider("anthropic", "claude-old-9", api_key="app-key")
        assert ai.call("s", "u") == ("OK", 4)
        reqs = [json.loads(r.content) for r in sent]
        assert len(reqs) == 2 and "output_config" in reqs[0] and "output_config" not in reqs[1], reqs
        assert ai.effort_rejected
        # 값과 상관없는 400: 다시 보내지 않고 그대로 오류
        sent.clear()
        httpx.Client.send = always_400
        ai = AIProvider("anthropic", "claude-old-9", api_key="app-key")
        try:
            ai.call("s", "u")
            raise AssertionError("오류가 나야 한다")
        except AssertionError:
            raise
        except Exception:
            pass
        assert len(sent) == 1 and not ai.effort_rejected, len(sent)
        httpx.Client.send = fake_send

        # 거절한 모델은 기억해서 다음부터 처음부터 뺀다 (AI 기능·[키 확인하기] 모두 화면 스레드에서 기억)
        from ai_provider import no_effort_models, wants_effort

        assert no_effort_models(db) == set()

        class Done:  # 끝난 작업 흉내 (거절 표시와 모델 이름)
            effort_rejected = True
            _model = "claude-old-9"

        dlg._test_worker = Done()
        dlg._on_test_result(True, "연결됐어요.")
        assert no_effort_models(db) == {"claude-old-9"}
        assert not wants_effort("anthropic", "claude-old-9", no_effort_models(db))
        assert wants_effort("anthropic", "claude-haiku-5-5", no_effort_models(db))
        assert not wants_effort("ollama", "ollama/llama3.2"), "Ollama에는 보내지 않는다"
        db.close()

        # 9) AI 기능 길: 메모 창에서 AI 기능을 쓰다 거절되면 기억하고, 다음 요청에서는 처음부터 뺀다
        import main as M

        AP.load_api_key = lambda p: "app-key"  # 메모 창·AI 작업이 이 함수로 키를 읽는다 (OS 키링은 건드리지 않는다)
        wdb = MemoDatabase(Path(d) / "w.db")
        for key, value in {"ai_enabled": "1", "ai_provider": "anthropic", "ai_model": "claude-old-10",
                           "ai_show_preview": "0"}.items():
            wdb.set_setting_str(key, value)
        memo = wdb.create("t", "<p>요약할 글</p>")
        win = M.SlideMemoWindow(wdb)
        win._load_memo(memo)

        def run_feature() -> list[dict]:
            sent.clear()
            win._run_ai_feature("summarize")
            win._ai_worker.wait(10000)
            app.processEvents()  # 결과 신호를 화면 스레드에서 받는다
            return [json.loads(r.content) for r in sent]

        httpx.Client.send = rejects_effort
        first = run_feature()
        assert len(first) == 2 and "output_config" in first[0] and "output_config" not in first[1], first
        assert no_effort_models(wdb) == {"claude-old-10"}, "AI 기능 길에서도 거절한 모델을 기억해야 한다"
        assert "OK" in win.editor.toPlainText(), "다시 보낸 요청의 답이 들어가야 한다"
        second = run_feature()
        assert len(second) == 1 and "output_config" not in second[0], "기억한 모델에는 처음부터 빼야 한다"
        httpx.Client.send = fake_send
        win._quitting = True
        win.close()
    print("test_ai_env OK")


if __name__ == "__main__":
    demo()

import testkit  # noqa: E402  창을 만든 시험은 마지막에 정리한다 (끝날 때 꺼지는 일 방지)

testkit.finish()
