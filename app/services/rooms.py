"""회의실 검색·가용 조회 — 읽기 계층.

v1.0에서 에이전트 도구(search_rooms·check_availability)가 이 함수들을 그대로
감쌉니다. 도구는 새 쿼리를 발명하지 않고 여기를 재사용합니다.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import get_conn

LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Seoul"))


def ensure_tz(value: datetime) -> datetime:
    """타임존 없는 입력은 서비스 표준 시간대(기본 Asia/Seoul)로 해석합니다."""
    return value if value.tzinfo else value.replace(tzinfo=LOCAL_TZ)


def _parse_equipment(raw: str) -> list[str]:
    return [item for item in raw.split(",") if item]


def search_rooms(
    capacity: int | None = None, equipment: list[str] | None = None
) -> list[dict]:
    """조건에 맞는 회의실 목록 — 요청한 설비를 '모두' 갖춘 방만 통과합니다.

    수용 인원이 조건에 맞는 방 중 작은 방부터 돌려줍니다 (자원 아껴 쓰기).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, capacity, equipment
            FROM rooms
            WHERE capacity >= %s
            ORDER BY capacity, id
            """,
            (capacity or 0,),
        ).fetchall()
    rooms = [{**row, "equipment": _parse_equipment(row["equipment"])} for row in rows]
    if equipment:
        rooms = [
            room
            for room in rooms
            if all(item in room["equipment"] for item in equipment)
        ]
    return rooms


def get_room(room_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, capacity, equipment FROM rooms WHERE id = %s",
            (room_id,),
        ).fetchone()
    if row is None:
        return None
    return {**row, "equipment": _parse_equipment(row["equipment"])}


def get_availability(room_id: int, start: datetime, end: datetime) -> dict:
    """조회 범위와 겹치는 기존 예약(busy), 그 사이의 빈 시간(free)을 돌려줍니다."""
    start, end = ensure_tz(start), ensure_tz(end)
    with get_conn() as conn:
        busy = conn.execute(
            """
            SELECT r.id, r.starts_at, r.ends_at, r.purpose, u.name AS reserved_by
            FROM reservations r
            JOIN users u ON u.id = r.user_id
            WHERE r.room_id = %s AND r.starts_at < %s AND %s < r.ends_at
            ORDER BY r.starts_at
            """,
            (room_id, end, start),
        ).fetchall()
    free = []
    cursor = start
    for item in busy:
        if cursor < item["starts_at"]:
            free.append({"starts_at": cursor, "ends_at": item["starts_at"]})
        cursor = max(cursor, item["ends_at"])
    if cursor < end:
        free.append({"starts_at": cursor, "ends_at": end})
    return {"busy": busy, "free": free}
