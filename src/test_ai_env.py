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
    ok, msg = AIProvider("anthropic", "claude-haiku-4-5", api_key="").test_connection()
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

    # 4) Whisper도 OPENAI_BASE_URL을 따라가지 않는다
    import tempfile
    from pathlib import Path
    from audio_recorder import WhisperWorker

    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        wav.write_bytes(b"RIFF0000WAVE")
        sent.clear()
        w = WhisperWorker(wav, "app-key")
        w.run()  # 스레드 없이 바로 실행
        assert sent and str(sent[-1].url).startswith("https://api.openai.com/v1/"), sent

    # 5) 설정의 녹음용 [키 확인하기]도 공식 주소로
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import settings_dialog as SD
    from database import MemoDatabase

    app = QApplication.instance() or QApplication(sys.argv)
    SD.load_api_key = lambda p: None  # OS 키링은 건드리지 않는다
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = MemoDatabase(Path(d) / "t.db")
        dlg = SD.SettingsDialog(db)
        dlg._whisper_key_edit.setText("app-key")
        sent.clear()
        dlg._run_whisper_test()
        assert sent, "키 확인 요청이 안 만들어짐"
        req = sent[-1]
        assert str(req.url).startswith("https://api.openai.com/v1/"), req.url
        assert req.headers.get("authorization") == "Bearer app-key", req.headers.get("authorization")
        dlg.deleteLater()
        db.close()
    print("test_ai_env OK")


if __name__ == "__main__":
    demo()
