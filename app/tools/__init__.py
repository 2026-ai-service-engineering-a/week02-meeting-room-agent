"""에이전트 도구 — v0.1 services/ 함수를 감싼 얇은 래퍼.

모델에게 보이는 것(스키마)과 코드가 실제로 부르는 것(서비스 함수)을 나눕니다.
겹침·인원·설비 같은 결정적 규칙은 services/ 에 있고, 도구는 그 결과를 모델이
읽을 형태로 돌려줄 뿐 — 새 쿼리를 발명하지 않습니다.

1회전은 읽기 전용 도구 2종입니다. 예약 생성(2회전)·취소(3회전)가 뒤에 더해집니다.
"""

import re
from datetime import datetime

from app.db import get_reporting_conn
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


# ── v1.5: 관리자 전용 SQL 콘솔 (세 겹 방어) ────────────────────────────

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 3000

# 시스템 프롬프트에 넣어 모델이 조회 가능한 뷰·컬럼을 알게 한다 (관리자에게만 보임).
REPORTING_SCHEMA_HINT = (
    "run_sql_query로 조회할 수 있는 리포팅 뷰와 컬럼 (읽기 전용, 단일 SELECT):\n"
    "- rpt_users(id, email, name, role, team_id)\n"
    "- rpt_teams(id, name)\n"
    "- rpt_rooms(id, name, capacity, equipment)\n"
    "- rpt_reservations(id, room_id, user_id, starts_at, ends_at, purpose)\n"
    "베이스 테이블·비밀번호·토큰은 보이지 않습니다."
)

SQL_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_sql_query",
        "description": (
            "리포팅 뷰에 단일 SELECT 문을 실행해 임의 집계·탐색 질문에 답한다"
            " (관리자 전용, 읽기 전용). 예약 건수·순위·기간 집계처럼 다른 도구로"
            " 안 되는 통계 질문에만 쓴다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "실행할 단일 SELECT 문 (리포팅 뷰만 참조)",
                }
            },
            "required": ["query"],
        },
    },
}

# 데이터 변경·DDL·권한 명령 — 파싱 단계의 belt. 진짜 방어선은 읽기 전용 롤이다.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|merge|call)\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)  # 라인 주석
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)  # 블록 주석
    return sql


def _is_single_select(sql: str) -> tuple[bool, str]:
    """단일 SELECT 문인지 검사 — (통과, 사유). 실행 전에 거른다."""
    body = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if not body:
        return False, "빈 쿼리입니다"
    if ";" in body:
        return False, "세미콜론(다중 문)은 허용되지 않습니다 — 단일 SELECT만 됩니다"
    lowered = body.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "SELECT(또는 WITH … SELECT) 문만 실행할 수 있습니다"
    if _FORBIDDEN.search(body):
        return False, "쓰기·DDL·권한 명령이 포함되어 거부되었습니다 (읽기 전용)"
    return True, ""


def _run_sql_query(*, user, query: str):
    # (1) 관리자 게이트 — role은 인증 컨텍스트에서 온다. 비관리자는 여기서 끝.
    if getattr(user, "role", None) != "admin":
        return {"error": "이 도구는 관리자만 사용할 수 있습니다", "code": "PermissionDenied"}
    # (2) SELECT 전용 파싱
    ok, reason = _is_single_select(query)
    if not ok:
        return {"error": reason, "code": "NotSelectOnly"}
    # (3) 읽기 전용 롤 + LIMIT·타임아웃. 실제 권한 경계는 reporter 롤(DB)이 강제한다.
    wrapped = (
        f"SELECT * FROM (\n{_strip_sql_comments(query).strip().rstrip(';')}\n)"
        f" AS _q LIMIT {MAX_ROWS}"
    )
    try:
        with get_reporting_conn() as conn:
            conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            rows = conn.execute(wrapped).fetchall()
        return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= MAX_ROWS}
    except Exception as exc:
        # DB가 막은 것(권한·타임아웃·문법)도 예외가 아니라 결과로 돌려줘 모델이 고치게.
        return {"error": str(exc), "code": "QueryError"}


def schemas_for(user) -> list[dict]:
    """사용자에게 노출할 도구 스키마 — SQL 콘솔은 관리자에게만 보인다."""
    if getattr(user, "role", None) == "admin":
        return [*TOOL_SCHEMAS, SQL_TOOL_SCHEMA]
    return TOOL_SCHEMAS


def run_tool(name: str, arguments: dict, *, user) -> object:
    """도구를 실행한다.

    search_rooms·check_availability는 모델 인자를 그대로 쓴다. 나머지는 사용자
    소유·권한이 걸리므로, 예약자·취소자·조회 범위·관리자 여부를 모델이 아니라 인증
    컨텍스트(user)에서 코드가 주입·검사한다 — 위험하거나 사적인 도구일수록 모델의
    재량이 줄어든다.
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
    if name == "run_sql_query":
        return _run_sql_query(user=user, **arguments)
    return {"error": f"알 수 없는 도구: {name}"}
