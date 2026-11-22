"""AI 제공자 추상화 레이어 (litellm + keyring)."""
from __future__ import annotations

import os
import time
from typing import Any

import logging

logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)

import keyring
import keyring.errors


def _litellm():
    """LiteLLM은 무겁고, 불러올 때 인터넷(GitHub)에서 모델 가격표를 받으려 한다.
    AI 기능을 처음 쓸 때만 불러오고, 가격표는 설치본 안의 것을 쓴다.

    PC에 남은 설정이 요청을 다른 곳으로 돌리지 못하게 막는다 (개인정보처리방침:
    직접 넣은 키로, 제공자에게만). 키와 주소는 _build_kwargs가 늘 직접 넘긴다.
    """
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"  # 가격표를 받으러 나가지 않기
    os.environ["LITELLM_MODE"] = "PRODUCTION"  # 현재 폴더의 .env를 읽지 않기
    for name in _BLOCKED_ENV:
        os.environ.pop(name, None)
    import litellm

    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    return litellm


# 모든 요청을 LiteLLM 프록시로 돌리기, 인증서 확인 끄기, 추적 도구 켜기
_BLOCKED_ENV = ("USE_LITELLM_PROXY", "SSL_VERIFY", "USE_DDTRACE", "USE_DDPROFILER")

KEYRING_SERVICE = "memo_slide_ai"

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic",
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
        # 기본값은 haiku 유지 — 사용자가 자기 키로 결제하므로 가장 싼 쪽에서 시작.
        "default_model": "claude-haiku-4-5",
        "key_format": "sk-ant-...",
        "needs_key": True,
        "api_base": "https://api.anthropic.com",
    },
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-4.1", "gpt-4o", "gpt-4o-mini", "o3-mini"],
        "default_model": "gpt-4o-mini",
        "key_format": "sk-...",
        "needs_key": True,
        "api_base": "https://api.openai.com/v1",
    },
    "gemini": {
        "name": "Google Gemini",
        "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash"],
        "default_model": "gemini/gemini-2.5-flash",
        "key_format": "AIza...",
        "needs_key": True,
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
    },
    "ollama": {
        "name": "Ollama (로컬)",
        "models": ["ollama/llama3.2", "ollama/qwen2.5", "ollama/gemma2"],
        "default_model": "ollama/llama3.2",
        "key_format": "",
        "needs_key": False,
        "api_base": "http://localhost:11434",
    },
}

# AI 설정 DB 키 상수
AI_KEY_ENABLED = "ai_enabled"
AI_KEY_PROVIDER = "ai_provider"
AI_KEY_MODEL = "ai_model"
AI_KEY_USAGE_TOKENS = "ai_usage_tokens"
AI_KEY_USAGE_RESET = "ai_usage_reset"
AI_KEY_SHOW_PREVIEW = "ai_show_preview"

AI_DEFAULTS: dict[str, str] = {
    AI_KEY_ENABLED: "0",
    AI_KEY_PROVIDER: "anthropic",
    AI_KEY_MODEL: "claude-haiku-4-5",
    AI_KEY_USAGE_TOKENS: "0",
    AI_KEY_USAGE_RESET: "",
    AI_KEY_SHOW_PREVIEW: "0",
}


# ----- 키링 헬퍼 -----

def save_api_key(provider: str, key: str) -> None:
    keyring.set_password(KEYRING_SERVICE, provider, key)


def load_api_key(provider: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, provider)
    except Exception:
        return None


def delete_api_key(provider: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass


# ----- AIProvider 클래스 -----

class MissingKeyError(Exception):
    """앱에 저장된 키가 없다. 요청을 보내지 않는다."""


class AIProvider:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key if api_key is not None else load_api_key(provider)
        self._info = PROVIDERS.get(provider, {})

    def _build_kwargs(self, max_tokens: int) -> dict[str, Any]:
        # 키와 주소를 늘 직접 넘긴다. 빠뜨리면 litellm이 환경 변수(ANTHROPIC_API_KEY,
        # OPENAI_BASE_URL 등)에서 찾아 쓴다.
        kwargs: dict[str, Any] = {
            "model": self.model, "max_tokens": max_tokens, "api_base": self._info["api_base"],
        }
        if self._info.get("needs_key"):
            if not self.api_key:
                raise MissingKeyError("API 키를 넣어 주세요.")
            kwargs["api_key"] = self.api_key
        return kwargs

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
    ) -> tuple[str, int]:
        """(응답 텍스트, 사용 토큰 수) 반환."""
        kwargs = self._build_kwargs(max_tokens)
        kwargs["messages"] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response = _litellm().completion(**kwargs)
        text = response.choices[0].message.content or ""
        tokens = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return text, int(tokens)

    def test_connection(self) -> tuple[bool, str]:
        """(성공 여부, 메시지) 반환. 실제 짧은 호출로 확인."""
        litellm = _litellm()
        start = time.time()
        try:
            text, _ = self.call("You are a test assistant.", "Say OK", max_tokens=10)
            elapsed = time.time() - start
            if text.strip():
                return True, f"연결됐어요. ({elapsed:.1f}초)"
            return False, "✗ 응답이 비어 있습니다"
        except MissingKeyError as e:
            return False, f"✗ {e}"
        except litellm.AuthenticationError:
            return False, "✗ 인증 실패: API 키를 확인하세요"
        except litellm.APIConnectionError:
            return False, "✗ 연결 실패: 네트워크 또는 서버를 확인하세요"
        except litellm.RateLimitError:
            return False, "✗ 사용량 한도 초과"
        except litellm.BadRequestError as e:
            return False, f"✗ 잘못된 요청: {e}"
        except Exception as e:
            return False, f"✗ 오류: {type(e).__name__}: {e}"
