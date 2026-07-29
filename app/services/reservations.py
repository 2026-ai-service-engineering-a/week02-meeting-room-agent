"""예약 생성·취소 — 겹침·인원·권한의 결정적 규칙이 사는 곳.

사람(웹·REST)이 쓰든 에이전트 도구(v1.0)가 쓰든 반드시 이 함수들을 거치므로,
규칙은 한 곳에만 존재하고 누구에게나 똑같이 적용됩니다.
"""

from datetime import datetime

from app.db import get_conn
from app.services.rooms import ensure_tz, get_room


class ReservationError(Exception):
    """예약 도메인 거절 — status는 HTTP 응답 코드 힌트입니다."""

    status = 400


class RoomNotFound(ReservationError):
    status = 404


class ReservationNotFound(ReservationError):
    status = 404


class InvalidTimeRange(ReservationError):
    status = 422


class CapacityExceeded(ReservationError):
    status = 409


class TimeConflict(ReservationError):
    status = 409


class PermissionDenied(ReservationError):
    status = 403


def overlaps(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime
) -> bool:
    """두 시간 구간이 겹치는가 — 경계가 딱 붙는 것(끝 == 시작)은 겹침이 아닙니다."""
    return start_a < end_b and start_b < end_a


def create_reservation(
    *,
    room_id: int,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
    purpose: str = "",
    attendees: int | None = None,
) -> dict:
    """겹침·인원 검사를 통과하면 예약을 확정합니다. 거절은 전부 예외로 알립니다.

    예약자(user_id)는 호출자가 인증 컨텍스트에서 읽어 넘깁니다 —
    v1.0 도구에서도 모델이 아니라 코드가 이 값을 주입합니다.
    """
    starts_at, ends_at = ensure_tz(starts_at), ensure_tz(ends_at)
    if starts_at >= ends_at:
        raise InvalidTimeRange("종료 시각은 시작 시각보다 뒤여야 합니다")
    room = get_room(room_id)
    if room is None:
        raise RoomNotFound(f"회의실 id={room_id} 는 없습니다")
    if attendees is not None and attendees > room["capacity"]:
        raise CapacityExceeded(
            f"'{room['name']}'의 수용 인원은 {room['capacity']}명입니다"
            f" (요청 {attendees}명)"
        )
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT starts_at, ends_at FROM reservations WHERE room_id = %s",
            (room_id,),
        ).fetchall()
        for other in existing:
            if overlaps(starts_at, ends_at, other["starts_at"], other["ends_at"]):
                raise TimeConflict(
                    f"'{room['name']}'에 그 시간과 겹치는 예약이 이미 있습니다"
                    f" ({other['starts_at']:%Y-%m-%d %H:%M}~{other['ends_at']:%H:%M})"
                )
        row = conn.execute(
            """
            INSERT INTO reservations (room_id, user_id, starts_at, ends_at, purpose)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, room_id, user_id, starts_at, ends_at, purpose
            """,
            (room_id, user_id, starts_at, ends_at, purpose),
        ).fetchone()
    return {**row, "room_name": room["name"]}


def cancel_reservation(
    *, reservation_id: int, requester_id: int, requester_role: str
) -> dict:
    """본인 예약이거나 관리자(role='admin')만 취소할 수 있습니다.

    취소자의 id·role도 인증 컨텍스트에서 옵니다 — 요청 본문이나 모델 인자로는
    누구도 자신을 다른 사람·관리자라고 주장할 수 없습니다.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, room_id, user_id, starts_at, ends_at, purpose
            FROM reservations
            WHERE id = %s
            """,
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ReservationNotFound(f"예약 id={reservation_id} 는 없습니다")
        if row["user_id"] != requester_id and requester_role != "admin":
            raise PermissionDenied("본인 예약만 취소할 수 있습니다 (관리자 제외)")
        conn.execute("DELETE FROM reservations WHERE id = %s", (reservation_id,))
    return row


def list_reservations(*, user_id: int, role: str) -> list[dict]:
    """내 예약 목록 — 관리자는 전체를 봅니다."""
    query = """
        SELECT r.id, r.room_id, m.name AS room_name, r.user_id,
               u.name AS reserved_by, r.starts_at, r.ends_at, r.purpose
        FROM reservations r
        JOIN rooms m ON m.id = r.room_id
        JOIN users u ON u.id = r.user_id
        {where}
        ORDER BY r.starts_at
    """
    with get_conn() as conn:
        if role == "admin":
            return conn.execute(query.format(where="")).fetchall()
        return conn.execute(
            query.format(where="WHERE r.user_id = %s"), (user_id,)
        ).fetchall()
