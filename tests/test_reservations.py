"""예약 검색·생성·취소 통합 테스트 — 시드가 든 dev DB 위에서 돕니다.

테스트는 실행마다 먼 미래의 무작위 날짜 하나를 골라 그날 안에서만 예약을
만들므로, 시드 데이터·지난 실행의 잔여물과 충돌하지 않습니다.
"""

import random
from datetime import date, timedelta

import pytest

BASE_DAY = date.today() + timedelta(days=random.randint(60, 3000))


def slot(start: str, end: str) -> dict:
    """'HH:MM' 두 개를 BASE_DAY의 ISO 시각 쌍으로 바꿉니다."""
    day = BASE_DAY.isoformat()
    return {"starts_at": f"{day}T{start}:00", "ends_at": f"{day}T{end}:00"}


@pytest.fixture(scope="session")
def rooms_by_name(client, admin_headers) -> dict:
    resp = client.get("/rooms", headers=admin_headers)
    assert resp.status_code == 200
    return {room["name"]: room for room in resp.json()}


@pytest.fixture(scope="session")
def focus_room(rooms_by_name) -> dict:
    return rooms_by_name["포커스룸1"]  # capacity 4, 시드 예약 없음


# ── 검색 ────────────────────────────────────────────────────────────


def test_search_by_capacity(client, new_user):
    user = new_user()
    resp = client.get("/rooms", params={"capacity": 10}, headers=user["headers"])
    assert resp.status_code == 200
    rooms = resp.json()
    assert rooms and all(room["capacity"] >= 10 for room in rooms)


def test_search_by_equipment(client, new_user):
    user = new_user()
    resp = client.get(
        "/rooms",
        params={"capacity": 6, "equipment": "화면공유,화이트보드"},
        headers=user["headers"],
    )
    assert resp.status_code == 200
    names = [room["name"] for room in resp.json()]
    assert "대회의실A" in names
    assert "포커스룸1" not in names  # 설비 미달


# ── 생성: 겹침·인원·경계 ────────────────────────────────────────────


def test_create_and_listed(client, new_user, focus_room):
    user = new_user()
    resp = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], "purpose": "1:1 미팅", **slot("09:00", "10:00")},
        headers=user["headers"],
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    mine = client.get("/reservations", headers=user["headers"]).json()
    assert created["id"] in [item["id"] for item in mine]


def test_overlapping_reservation_rejected(client, new_user, focus_room):
    user = new_user()
    first = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("10:00", "11:00")},
        headers=user["headers"],
    )
    assert first.status_code == 201, first.text
    conflict = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("10:30", "11:30")},
        headers=user["headers"],
    )
    assert conflict.status_code == 409
    assert "겹치는 예약" in conflict.json()["detail"]


def test_adjacent_reservation_allowed(client, new_user, focus_room):
    # 경계가 딱 붙는 예약(위 테스트의 10~11시 다음 11~12시)은 허용됩니다
    user = new_user()
    resp = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("11:00", "12:00")},
        headers=user["headers"],
    )
    assert resp.status_code == 201, resp.text


def test_capacity_exceeded_rejected(client, new_user, focus_room):
    user = new_user()
    resp = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], "attendees": 20, **slot("13:00", "14:00")},
        headers=user["headers"],
    )
    assert resp.status_code == 409
    assert "수용 인원" in resp.json()["detail"]


def test_invalid_time_range_rejected(client, new_user, focus_room):
    user = new_user()
    resp = client.post(
        "/reservations",
        json={
            "room_id": focus_room["id"],
            "starts_at": slot("15:00", "16:00")["ends_at"],
            "ends_at": slot("15:00", "16:00")["starts_at"],
        },
        headers=user["headers"],
    )
    assert resp.status_code == 422


def test_unknown_room_rejected(client, new_user):
    user = new_user()
    resp = client.post(
        "/reservations",
        json={"room_id": 9999, **slot("09:00", "10:00")},
        headers=user["headers"],
    )
    assert resp.status_code == 404


# ── 가용 조회 ───────────────────────────────────────────────────────


def test_availability_busy_and_free(client, new_user, rooms_by_name):
    room = rooms_by_name["포커스룸2"]  # 시드 예약이 없는 방에서 자체 데이터로 검증
    user = new_user()
    for start, end in (("10:00", "11:00"), ("13:00", "14:00")):
        created = client.post(
            "/reservations",
            json={"room_id": room["id"], **slot(start, end)},
            headers=user["headers"],
        )
        assert created.status_code == 201, created.text
    day = BASE_DAY.isoformat()
    resp = client.get(
        f"/rooms/{room['id']}/availability",
        params={"start": f"{day}T09:00:00", "end": f"{day}T15:00:00"},
        headers=user["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["busy"]) == 2
    assert len(body["free"]) == 3  # 09~10, 11~13, 14~15


# ── 취소: 본인·타인·관리자 ──────────────────────────────────────────


def test_cancel_own_reservation(client, new_user, focus_room):
    user = new_user()
    created = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("14:00", "15:00")},
        headers=user["headers"],
    ).json()
    resp = client.delete(f"/reservations/{created['id']}", headers=user["headers"])
    assert resp.status_code == 200
    mine = client.get("/reservations", headers=user["headers"]).json()
    assert created["id"] not in [item["id"] for item in mine]


def test_cancel_others_reservation_forbidden(client, new_user, focus_room):
    owner, attacker = new_user(), new_user(team_id=2)
    created = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("15:00", "16:00")},
        headers=owner["headers"],
    ).json()
    resp = client.delete(f"/reservations/{created['id']}", headers=attacker["headers"])
    assert resp.status_code == 403
    # 예약은 그대로 남아 있어야 합니다
    mine = client.get("/reservations", headers=owner["headers"]).json()
    assert created["id"] in [item["id"] for item in mine]


def test_admin_can_cancel_others_reservation(client, new_user, admin_headers, focus_room):
    owner = new_user()
    created = client.post(
        "/reservations",
        json={"room_id": focus_room["id"], **slot("16:00", "17:00")},
        headers=owner["headers"],
    ).json()
    resp = client.delete(f"/reservations/{created['id']}", headers=admin_headers)
    assert resp.status_code == 200


# ── 전역 인증 원칙 + 미구현 통로 ────────────────────────────────────


def test_endpoints_require_login_including_reserve(client):
    assert client.get("/rooms").status_code == 401
    assert client.get("/reservations").status_code == 401
    assert client.post("/reserve").status_code == 401  # 501보다 인증이 먼저


def test_reserve_is_not_implemented_yet(client, new_user):
    user = new_user()
    resp = client.post("/reserve", headers=user["headers"])
    assert resp.status_code == 501  # 자연어 통로는 v1.0에서 열립니다
