"""회의실 예약 서비스 API — 인증·검색·예약·취소.

자연어 통로(/reserve)는 v1.0에서 에이전트가 연결됩니다.
"""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import ConversationError, run_agent
from app.auth.deps import CurrentUser, get_current_user
from app.auth.service import AuthError, login, signup
from app.services import reservations as reservation_service
from app.services import rooms as room_service
from app.services.reservations import ReservationError

BASE_DIR = Path(__file__).resolve().parent.parent

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


# ── 회의실 검색·가용 조회 (읽기) ────────────────────────────────────────


@api.get("/rooms")
def get_rooms(capacity: int | None = None, equipment: str | None = None) -> list[dict]:
    """회의실 검색 — equipment는 쉼표 구분 (예: equipment=화면공유,화이트보드)."""
    wanted = (
        [item.strip() for item in equipment.split(",") if item.strip()]
        if equipment
        else None
    )
    return room_service.search_rooms(capacity=capacity, equipment=wanted)


@api.get("/rooms/{room_id}/availability")
def get_room_availability(room_id: int, start: datetime, end: datetime) -> dict:
    """조회 범위의 기존 예약(busy)과 빈 시간(free)."""
    if room_service.get_room(room_id) is None:
        raise HTTPException(status_code=404, detail=f"회의실 id={room_id} 는 없습니다")
    return room_service.get_availability(room_id, start, end)


# ── 예약 생성·취소 (쓰기 — 결정적 규칙은 services/ 에 있습니다) ─────────


class ReservationRequest(BaseModel):
    room_id: int
    starts_at: datetime
    ends_at: datetime
    purpose: str = ""
    attendees: int | None = None  # 수용 인원 검사에만 쓰이고 저장되지는 않습니다


@api.get("/reservations")
def get_reservations(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """내 예약 목록 — 관리자는 전체."""
    return reservation_service.list_reservations(user_id=user.id, role=user.role)


@api.post("/reservations", status_code=201)
def post_reservation(
    request: ReservationRequest, user: CurrentUser = Depends(get_current_user)
) -> dict:
    try:
        # 예약자는 항상 인증된 현재 사용자 — 요청 본문으로는 정할 수 없습니다
        return reservation_service.create_reservation(
            room_id=request.room_id,
            user_id=user.id,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
            purpose=request.purpose,
            attendees=request.attendees,
        )
    except ReservationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@api.delete("/reservations/{reservation_id}")
def delete_reservation(
    reservation_id: int, user: CurrentUser = Depends(get_current_user)
) -> dict:
    try:
        cancelled = reservation_service.cancel_reservation(
            reservation_id=reservation_id,
            requester_id=user.id,
            requester_role=user.role,
        )
    except ReservationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return {"cancelled": cancelled["id"]}


# ── 자연어 통로 — 에이전트가 검색·가용 도구로 답합니다 (1회전: 읽기 전용) ──


class ReserveRequest(BaseModel):
    message: str
    conversation_id: int | None = None  # 없으면 새 대화, 있으면 이어가기 (소유자만)


@api.post("/reserve")
def post_reserve(
    request: ReserveRequest, user: CurrentUser = Depends(get_current_user)
) -> dict:
    """자연어 한 문장 → 에이전트 응답 + conversation_id. 예약 생성은 다음 회전에서."""
    try:
        return run_agent(
            user=user,
            message=request.message,
            conversation_id=request.conversation_id,
        )
    except ConversationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


app.include_router(api)

# 웹 예약 화면 — API 라우트보다 뒤에 마운트해야 라우트가 가려지지 않습니다.
# 정적 파일 자체는 공개지만, 화면이 부르는 API는 전부 토큰이 필요합니다.
app.mount("/", StaticFiles(directory=BASE_DIR / "web", html=True), name="web")
