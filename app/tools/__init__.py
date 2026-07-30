"""에이전트 도구 — v0.1 services/ 함수를 감싼 얇은 래퍼.

모델에게 보이는 것(스키마)과 코드가 실제로 부르는 것(서비스 함수)을 나눕니다.
겹침·인원·설비 같은 결정적 규칙은 services/ 에 있고, 도구는 그 결과를 모델이
읽을 형태로 돌려줄 뿐 — 새 쿼리를 발명하지 않습니다.

1회전은 읽기 전용 도구 2종입니다. 예약 생성(2회전)·취소(3회전)가 뒤에 더해집니다.
"""

from datetime import datetime

from app.services import reservations as reservation_service
from app.services import rooms as room_service
from app.services.reservations import ReservationError

# ── 모델에게 보이는 스키마 (function calling) ──────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_rooms",
            "description": "조건에 맞는 회의실을 검색한다. 인원과 필요 설비로 거른다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "capacity": {
                        "type": "integer",
                        "description": "최소 수용 인원 — 이 인원 이상 들어가는 방만 통과",
                    },
                    "equipment": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "필요한 설비 목록. 방은 이 설비를 '모두' 갖춰야 통과한다"
                            " (예: ['화면공유', '화이트보드'])"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "특정 회의실의 조회 범위 안 기존 예약(busy)과 빈 시간(free)을 조회한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer", "description": "회의실 id"},
                    "start": {
                        "type": "string",
                        "description": "조회 시작 시각 (ISO 8601, 예: 2026-07-31T13:00:00)",
                    },
                    "end": {
                        "type": "string",
                        "description": "조회 종료 시각 (ISO 8601)",
                    },
                },
                "required": ["room_id", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reservation",
            "description": (
                "회의실을 예약한다. 겹침·인원 검사를 통과하면 확정하고, 아니면"
                " 거절 사유를 돌려준다. (예약자는 시스템이 자동 지정한다)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer", "description": "예약할 회의실 id"},
                    "starts_at": {
                        "type": "string",
                        "description": "시작 시각 (ISO 8601, 예: 2026-07-31T15:00:00)",
                    },
                    "ends_at": {
                        "type": "string",
                        "description": "종료 시각 (ISO 8601)",
                    },
                    "purpose": {"type": "string", "description": "회의 목적 (선택)"},
                    "attendees": {
                        "type": "integer",
                        "description": (
                            "예상 인원 — 수용 인원 초과 검사에만 쓰이고 저장되지"
                            " 않는다 (선택)"
                        ),
                    },
                },
                "required": ["room_id", "starts_at", "ends_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reservation",
            "description": (
                "예약을 취소한다. 본인 예약이거나 관리자만 취소할 수 있고, 권한은"
                " 시스템이 인증 컨텍스트로 검사한다 (취소자를 인자로 정할 수 없다)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reservation_id": {
                        "type": "integer",
                        "description": "취소할 예약 id",
                    },
                },
                "required": ["reservation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reservations",
            "description": (
                "현재 사용자의 예약 내역을 조회한다 (관리자는 전체). 각 항목에 예약"
                " id가 들어 있어, 사용자가 id 없이 설명한 예약을 취소할 때 먼저 여기서"
                " 찾는 용도로도 쓴다."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── 코드가 실제로 부르는 것 — 전부 services/rooms.py 재사용 ─────────────


def _search_rooms(capacity: int | None = None, equipment: list[str] | None = None):
    return room_service.search_rooms(capacity=capacity, equipment=equipment)


def _check_availability(room_id: int, start: str, end: str):
    if room_service.get_room(room_id) is None:
        return {"error": f"회의실 id={room_id} 는 없습니다"}
    return room_service.get_availability(
        room_id, datetime.fromisoformat(start), datetime.fromisoformat(end)
    )


def _create_reservation(
    *,
    user,
    room_id: int,
    starts_at: str,
    ends_at: str,
    purpose: str = "",
    attendees: int | None = None,
):
    # 예약자(user_id)는 모델이 아니라 인증 컨텍스트에서 온다 — 코드가 주입한다.
    try:
        return reservation_service.create_reservation(
            room_id=room_id,
            user_id=user.id,
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
            purpose=purpose,
            attendees=attendees,
        )
    except ReservationError as exc:
        # 거절은 예외로 터뜨리지 않고 결과로 돌려준다 — 에이전트가 대안을 제시하도록.
        return {"error": str(exc), "code": type(exc).__name__}


def _cancel_reservation(*, user, reservation_id: int):
    # 취소자 id·role은 모델 인자가 아니라 인증 컨텍스트에서 온다 — 코드가 주입한다.
    # '나 관리자야'라고 말해도 role은 여기서 서비스로 넘어가는 값이 진실이다.
    try:
        cancelled = reservation_service.cancel_reservation(
            reservation_id=reservation_id,
            requester_id=user.id,
            requester_role=user.role,
        )
        return {"cancelled": cancelled["id"]}
    except ReservationError as exc:
        return {"error": str(exc), "code": type(exc).__name__}


def _list_reservations(*, user):
    # 조회 범위(본인 vs 전체)를 가르는 id·role도 인증 컨텍스트에서 온다 —
    # member는 자기 예약만, admin은 전체. 모델이 남의 것을 보겠다고 정할 수 없다.
    return reservation_service.list_reservations(user_id=user.id, role=user.role)


def run_tool(name: str, arguments: dict, *, user) -> object:
    """도구를 실행한다.

    search_rooms·check_availability는 모델 인자를 그대로 쓴다. 나머지 셋은 사용자
    소유·권한이 걸리므로, 예약자·취소자·조회 범위를 모델이 아니라 인증 컨텍스트(user)
    에서 코드가 주입한다 — 위험하거나 사적인 도구일수록 모델의 재량이 줄어든다.
    """
    if name == "search_rooms":
        return _search_rooms(**arguments)
    if name == "check_availability":
        return _check_availability(**arguments)
    if name == "create_reservation":
        return _create_reservation(user=user, **arguments)
    if name == "cancel_reservation":
        return _cancel_reservation(user=user, **arguments)
    if name == "list_reservations":
        return _list_reservations(user=user)
    return {"error": f"알 수 없는 도구: {name}"}
