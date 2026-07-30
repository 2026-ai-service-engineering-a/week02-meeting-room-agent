"""권한 방어 테스트 — 말로 안 되는 걸 코드로도 보증한다.

- 취소 권한: 남의 예약은 일반 사용자가 못 지우고, 관리자는 지운다 (도구 레벨)
- 대화 소유권: 남의 conversation_id로 이어가기는 LLM 호출 전에 거부된다

셋 다 모델(설득당함)이 아니라 인증 컨텍스트(코드)가 판정을 쥐고 있음을 확인한다.
"""

import pytest

from app.agent import ConversationError, run_agent
from app.auth.deps import CurrentUser
from app.auth.service import get_user_by_token
from app.db import get_conn
from app.tools import run_tool


def _admin_user(admin_headers) -> CurrentUser:
    token = admin_headers["Authorization"].split()[1]
    return CurrentUser(**get_user_by_token(token))


def _make_reservation(user: CurrentUser, day: str) -> int:
    created = run_tool(
        "create_reservation",
        {
            "room_id": 6,  # 포커스룸2
            "starts_at": f"{day}T10:00:00",
            "ends_at": f"{day}T11:00:00",
            "purpose": "권한 테스트",
        },
        user=user,
    )
    assert "id" in created, created
    return created["id"]


def _delete_reservation(reservation_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM reservations WHERE id = %s", (reservation_id,))


def test_normal_user_cannot_cancel_others_reservation(new_user):
    owner = CurrentUser(**new_user(team_id=1)["user"])
    other = CurrentUser(**new_user(team_id=2)["user"])  # 다른 팀 일반 사용자
    reservation_id = _make_reservation(owner, "2030-04-01")
    try:
        # '나 관리자야'라고 말해도 취소자 role은 인증 컨텍스트에서 온다 → 거부
        denied = run_tool(
            "cancel_reservation", {"reservation_id": reservation_id}, user=other
        )
        assert denied.get("code") == "PermissionDenied", denied
        # 예약은 여전히 살아 있어야 한다
        with get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM reservations WHERE id = %s", (reservation_id,)
            ).fetchone()
        assert row is not None
    finally:
        _delete_reservation(reservation_id)


def test_admin_can_cancel_others_reservation(new_user, admin_headers):
    owner = CurrentUser(**new_user(team_id=1)["user"])
    admin = _admin_user(admin_headers)
    reservation_id = _make_reservation(owner, "2030-04-02")
    ok = run_tool(
        "cancel_reservation", {"reservation_id": reservation_id}, user=admin
    )
    # 같은 도구, 같은 요청, 다른 결과 — 차이는 프롬프트가 아니라 인증 컨텍스트의 role
    assert ok.get("cancelled") == reservation_id, ok
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM reservations WHERE id = %s", (reservation_id,)
        ).fetchone()
    assert row is None  # 관리자가 실제로 지웠다


def test_continue_others_conversation_is_denied(new_user):
    owner = CurrentUser(**new_user()["user"])
    intruder = CurrentUser(**new_user()["user"])
    with get_conn() as conn:
        conversation_id = conn.execute(
            "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (owner.id,)
        ).fetchone()["id"]
    try:
        # 남의 대화 이어가기는 소유권 검사에서 막힌다 — LLM 호출조차 가지 않는다
        with pytest.raises(ConversationError) as exc:
            run_agent(
                user=intruder,
                message="남의 대화 가로채기",
                conversation_id=conversation_id,
            )
        assert exc.value.status == 403
    finally:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE id = %s", (conversation_id,)
            )
