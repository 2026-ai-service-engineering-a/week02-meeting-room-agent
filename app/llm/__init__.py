"""LiteLLM 래퍼 — 모든 LLM 호출이 지나는 단 한 곳.

어떤 모델을 부를지는 코드가 아니라 MODEL 환경변수가 정합니다. LiteLLM이 모델
이름의 접두사(gemini/ · anthropic/ · openai/)를 보고 알맞은 키로 호출하므로,
이 위층(agent·tools)은 프로바이더를 알지 못합니다.

재시도·폴백 체인(FALLBACK_MODELS)과 토큰·비용 로그는 3회전(feature/hardening)에서
이 파일에 더해집니다. 1회전은 '한 모델을 부른다'까지입니다.
"""

import os

import litellm
from dotenv import load_dotenv

# 호스트에서 직접 실행할 때 .env 를 읽습니다 (컨테이너는 compose의 env_file로 주입).
load_dotenv()

DEFAULT_MODEL = "gemini/gemini-2.5-flash"


def complete(messages: list[dict], tools: list[dict] | None = None):
    """대화 이력(+도구 스키마)을 모델에 넘기고 응답을 그대로 돌려줍니다."""
    return litellm.completion(
        model=os.environ.get("MODEL", DEFAULT_MODEL),
        messages=messages,
        tools=tools,
        tool_choice="auto" if tools else None,
    )
