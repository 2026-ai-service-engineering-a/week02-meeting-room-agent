"""FastAPI 인증 의존성 — 전역 인증 원칙의 구현.

/signup·/login 을 제외한 모든 엔드포인트는 이 의존성 하나로 잠급니다.
엔드포인트마다 검사 코드를 반복하지 않습니다 (라우터에 일괄 적용).
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.service import get_user_by_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """인증된 요청 컨텍스트 — 도구·에이전트(v1.0)가 소비할 인터페이스입니다."""

    id: int
    email: str
    name: str
    role: str
    team_id: int


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    user = get_user_by_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
    return CurrentUser(**user)
