"""AI 제공자 추상화 레이어 (litellm + keyring)."""
from __future__ import annotations

import json
import os
import re
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
MIN_CLOUD_MAX_TOKENS = 2048  # 클라우드 제공자의 응답 길이 한도 최소값 (_build_kwargs)

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic",
        # models는 추천 목록이다. 설정에서 다른 이름을 직접 넣어도 된다 (새 모델이 나와도 앱 업데이트 없이).
        "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
        # 사용자가 자기 키로 결제하므로 기본값은 가장 싼 쪽 (2026-11 가격표: Haiku 5.5 $0.10/$0.50)
        "default_model": "claude-haiku-5-5",
        "key_format": "sk-ant-...",
        "needs_key": True,
        "api_base": "https://api.anthropic.com",
    },
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-6-luna", "gpt-5.6-sol"],
        "default_model": "gpt-6-luna",  # 2026-11 가격표: $0.10/$0.50 (gpt-5.6-sol은 $4/$20)
        "key_format": "sk-...",
        "needs_key": True,
        "api_base": "https://api.openai.com/v1",
    },
    "gemini": {
        "name": "Google Gemini",
        "models": ["gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash-lite"],
        "default_model": "gemini/gemini-3.5-flash-lite",
        "key_format": "AIza...",
        "needs_key": True,
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
    },
    "ollama": {
        "name": "Ollama (로컬)",
        # 설정 화면은 내 PC의 Ollama가 받아 둔 모델을 먼저 보여 준다 (ollama_models). 이건 Ollama가 꺼져 있을 때의 추천
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
    AI_KEY_MODEL: PROVIDERS["anthropic"]["default_model"],
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


# ----- 내 PC의 Ollama -----

def ollama_models(timeout: float = 1.5) -> list[str] | None:
    """내 PC의 Ollama가 받아 둔 모델 이름 (ollama/이름). 꺼져 있거나 없으면 None.
    주소는 PROVIDERS의 localhost로 고정하고, 프록시 설정을 거치지 않는다 (이 PC 밖으로 나가지 않기)."""
    import json
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(PROVIDERS["ollama"]["api_base"] + "/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    return [f"ollama/{m['name']}" for m in data.get("models", []) if m.get("name")]


# ----- AIProvider 클래스 -----

class MissingKeyError(Exception):
    """앱에 저장된 키가 없다. 요청을 보내지 않는다."""


# ----- 생각 수준 (effort) -----
# AI 기능은 모두 짧은 작업(요약·번역·맞춤법·제목·키워드)이라 새 모델에 생각을 낮게(low) 요청한다.
# 이 값을 받지 않는 모델은 400 오류를 낸다 → 확실한 이름은 미리 빼고, 나머지는 보내 본 뒤
# 오류 내용에 값 이름이 나오면 빼고 한 번만 다시 보낸다 (400은 요금이 나가지 않는다).
EFFORT_LEVEL = "low"
AI_KEY_NO_EFFORT = "ai_no_effort_models"  # 값을 거절한 모델 이름 목록 (JSON). 다음부터는 처음부터 뺀다
NO_EFFORT_PREFIXES = (  # 받지 않는 게 확실한 이름 (날짜가 붙은 이름도 앞부분으로 잡는다)
    "claude-3", "claude-haiku-4-5", "claude-sonnet-4-5",
    "gpt-4o", "gpt-4.1",
    "gemini/gemini-2.", "gemini-2.",  # 2.x는 thinkingLevel 대신 thinkingBudget을 쓴다
)
_EFFORT_ERROR = re.compile(r"effort|output_config|reasoning|thinking", re.IGNORECASE)


def effort_kwargs(provider: str) -> dict[str, Any]:
    """제공자별 생각 수준 값. OpenAI·Gemini는 litellm이 목록에 없는 모델에 막아서 extra_body로 그대로 넘긴다."""
    if provider == "anthropic":
        return {"output_config": {"effort": EFFORT_LEVEL}}
    if provider == "openai":
        return {"extra_body": {"reasoning_effort": EFFORT_LEVEL}}
    if provider == "gemini":
        return {"extra_body": {"generationConfig": {"thinkingConfig": {"thinkingLevel": EFFORT_LEVEL}}}}
    return {}  # Ollama: 보내지 않는다


def wants_effort(provider: str, model: str, rejected: set[str] | frozenset[str] = frozenset()) -> bool:
    name = model.strip().lower()
    return bool(effort_kwargs(provider)) and not name.startswith(NO_EFFORT_PREFIXES) and model not in rejected


def no_effort_models(db) -> set[str]:
    """값을 거절한 적 있는 모델 이름. DB는 화면 스레드에서만 읽는다."""
    try:
        return set(json.loads(db.get_setting_str(AI_KEY_NO_EFFORT, "[]") or "[]"))
    except (ValueError, TypeError):
        return set()


def remember_no_effort(db, model: str) -> None:
    names = no_effort_models(db) | {model}
    db.set_setting_str(AI_KEY_NO_EFFORT, json.dumps(sorted(names), ensure_ascii=False))


class AIProvider:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str | None = None,
        *,
        send_effort: bool = True,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key if api_key is not None else load_api_key(provider)
        self._info = PROVIDERS.get(provider, {})
        self.send_effort = send_effort
        self.effort_rejected = False  # 이 모델이 생각 수준 값을 거절했다 → 부른 쪽이 remember_no_effort로 기억

    def _build_kwargs(self, max_tokens: int) -> dict[str, Any]:
        # 키와 주소를 늘 직접 넘긴다. 빠뜨리면 litellm이 환경 변수(ANTHROPIC_API_KEY,
        # OPENAI_BASE_URL 등)에서 찾아 쓴다.
        # 제공자도 직접 넘긴다. 모델 이름만 주면 litellm이 설치본 안의 모델 목록에서 제공자를 찾는데,
        # 목록에 없는 새 모델(claude-opus-5 등)은 "LLM Provider NOT provided"로 실패한다.
        kwargs: dict[str, Any] = {
            "model": self.model, "custom_llm_provider": self.provider, "api_base": self._info["api_base"],
        }
        if self.provider != "ollama":
            # 새 모델은 생각(thinking·reasoning)에 쓴 토큰도 이 한도에 들어간다. 너무 작으면 빈 응답이 온다.
            # 쓴 만큼만 요금이 나가서 한도를 올려도 비용은 늘지 않는다
            max_tokens = max(max_tokens, MIN_CLOUD_MAX_TOKENS)
        # OpenAI 추론 모델은 max_tokens를 받지 않는다. litellm은 목록에 없는 모델에 max_tokens를 보낸다
        kwargs["max_completion_tokens" if self.provider == "openai" else "max_tokens"] = max_tokens
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
        litellm = _litellm()
        effort = effort_kwargs(self.provider) if self.send_effort and wants_effort(self.provider, self.model) else {}
        try:
            response = litellm.completion(**kwargs, **effort)
        except litellm.BadRequestError as e:
            if not effort or not _EFFORT_ERROR.search(str(e)):
                raise
            # 이 모델은 생각 수준 값을 받지 않는다: 값을 빼고 한 번만 다시 보낸다
            self.effort_rejected = True
            response = litellm.completion(**kwargs)
        text = response.choices[0].message.content or ""
        tokens = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return text, int(tokens)

    def test_connection(self) -> tuple[bool, str]:
        """(성공 여부, 메시지) 반환. 실제 짧은 호출로 확인. Ollama는 내 PC의 Ollama가 응답하는지만 본다."""
        if self.provider == "ollama":
            models = ollama_models()
            if models is None:
                return False, "✗ 내 PC의 Ollama가 응답하지 않아요. Ollama를 켜 주세요"
            return True, f"내 PC의 Ollama가 응답해요. (받아 둔 모델 {len(models)}개)"
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
