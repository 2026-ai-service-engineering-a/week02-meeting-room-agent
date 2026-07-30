"""에이전트 도구 — v0.1 services/ 함수를 감싼 얇은 래퍼.

모델에게 보이는 것(스키마)과 코드가 실제로 부르는 것(서비스 함수)을 나눕니다.
겹침·인원·설비 같은 결정적 규칙은 services/ 에 있고, 도구는 그 결과를 모델이
읽을 형태로 돌려줄 뿐 — 새 쿼리를 발명하지 않습니다.

1회전은 읽기 전용 도구 2종입니다. 예약 생성(2회전)·취소(3회전)가 뒤에 더해집니다.
"""

from datetime import datetime

from app.services import rooms as room_service

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


_DISPATCH = {
    "search_rooms": _search_rooms,
    "check_availability": _check_availability,
}


def run_tool(name: str, arguments: dict) -> object:
    """도구 이름과 인자로 서비스 함수를 부른다. 결과는 모델이 읽을 수 있는 값이어야 한다."""
    func = _DISPATCH.get(name)
    if func is None:
        return {"error": f"알 수 없는 도구: {name}"}
    return func(**arguments)
