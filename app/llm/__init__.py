"""LiteLLM 래퍼 — 모든 LLM 호출이 지나는 단 한 곳.

어떤 모델을 부를지도, 실패하면 어디로 넘어갈지도 코드가 아니라 환경변수가 정한다:
  MODEL            — 기본 모델
  FALLBACK_MODELS  — 실패 시 시도할 모델들 (쉼표 구분, 앞에서부터 순서대로)
LiteLLM이 모델 이름의 접두사(gemini/ · anthropic/ · openai/)를 보고 알맞은 키로
호출하므로, 위층(agent·tools)은 프로바이더도 폴백 순서도 알지 못한다.

신뢰성 두 겹:
  1) 재시도 — 같은 모델의 일시 장애(429·5xx·타임아웃)는 지수 백오프로 다시 시도
  2) 폴백  — 그래도 죽으면 다음 프로바이더로 넘어간다
"""

import logging
import os
import sys
import time

import litellm
from dotenv import load_dotenv

# 호스트에서 직접 실행할 때 .env 를 읽는다 (컨테이너는 compose의 env_file로 주입).
load_dotenv()

DEFAULT_MODEL = "gemini/gemini-2.5-flash"
MAX_ATTEMPTS = 3  # 프로바이더당 시도 횟수 (첫 시도 + 재시도)
BACKOFF_BASE = 0.5  # 지수 백오프 기준 초 — 0.5, 1.0, 2.0 …

log = logging.getLogger("agent.llm")
if not log.handlers:  # docker 로그(stdout)에 확실히 찍히도록 핸들러를 붙인다
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def _retryable_types() -> tuple[type, ...]:
    """일시 장애로 보고 재시도할 예외들. 없는 방·잘못된 요청 등은 재시도해도 소용없다."""
    names = [
        "RateLimitError",
        "Timeout",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
    ]
    found = [getattr(litellm, name, None) for name in names]
    return tuple(t for t in found if isinstance(t, type))


_RETRYABLE = _retryable_types()


def _model_chain() -> list[str]:
    """[기본, 폴백…] 순서. 중복은 순서를 지키며 제거한다."""
    chain = [os.environ.get("MODEL", DEFAULT_MODEL)]
    for model in os.environ.get("FALLBACK_MODELS", "").split(","):
        model = model.strip()
        if model and model not in chain:
            chain.append(model)
    return chain


def _log_usage(model: str, response) -> None:
    """매 호출의 모델·토큰·비용을 남긴다 — 관측이 없으면 비용은 월말 청구서로 배운다."""
    usage = getattr(response, "usage", None)
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        cost = None  # 비용표에 없는 모델이면 토큰만 남긴다
    log.info(
        "ok model=%s prompt_tokens=%s completion_tokens=%s cost=%s",
        model,
        getattr(usage, "prompt_tokens", "?"),
        getattr(usage, "completion_tokens", "?"),
        f"${cost:.6f}" if cost is not None else "?",
    )


def _call_with_retry(model: str, messages: list[dict], tools: list[dict] | None):
    """한 모델을 부른다. 일시 장애면 지수 백오프로 재시도, 그 외 예외는 즉시 올린다."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return litellm.completion(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
        except _RETRYABLE as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS - 1:
                wait = BACKOFF_BASE * (2**attempt)
                log.warning(
                    "retry model=%s attempt=%s err=%s — %.1fs 후 재시도",
                    model,
                    attempt + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
    raise last_error  # 재시도를 다 쓰고도 실패


def complete(messages: list[dict], tools: list[dict] | None = None):
    """대화 이력(+도구 스키마)을 모델에 넘긴다. 실패하면 폴백 체인으로 넘어간다."""
    last_error: Exception | None = None
    for model in _model_chain():
        try:
            response = _call_with_retry(model, messages, tools)
            _log_usage(model, response)
            return response
        except Exception as exc:  # 이 프로바이더가 죽으면(재시도 후에도) 다음 폴백으로
            log.warning("fail model=%s err=%s — 다음 폴백 시도", model, exc)
            last_error = exc
    raise last_error
