"""회의실 예약 서비스 API — 인증·검색·예약·취소.

자연어 통로(/reserve)는 v1.0에서 에이전트가 연결됩니다.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.auth.deps import CurrentUser, get_current_user
from app.auth.service import AuthError, login, signup

app = FastAPI(title="회의실 예약 에이전트", version="0.1.0")


# ── 공개 엔드포인트 — /signup·/login 딱 둘뿐입니다 ──────────────────────


class SignupRequest(BaseModel):
    email: str
    name: str
    password: str
    team_id: int


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/signup", status_code=201)
def post_signup(request: SignupRequest) -> dict:
    try:
        return signup(request.email, request.name, request.password, request.team_id)
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/login")
def post_login(request: LoginRequest) -> dict:
    try:
        return {"token": login(request.email, request.password)}
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ── 이하 전부 인증 필수 — 로그인 없이는 아무것도 안 됩니다 ──────────────
# 라우터에 의존성을 일괄 적용합니다. 엔드포인트마다 검사 코드를 반복하지 않습니다.

api = APIRouter(dependencies=[Depends(get_current_user)])


@api.get("/me")
def get_me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """토큰 검증 확인용 — 역할(role)까지 돌려줍니다."""
    return asdict(user)


app.include_router(api)
