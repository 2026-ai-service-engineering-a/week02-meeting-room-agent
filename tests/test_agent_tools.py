"""도구 계층 통합 테스트 — 예약 생성 도구가 서비스 규칙을 그대로 태우는지.

겹침 판정 자체(overlaps)는 v0.1 유닛테스트(test_overlap.py)가 지킨다. 여기서는
'도구로 만든 예약이 같은 방 같은 시간 재시도에서 서비스에 의해 거절되는가'라는
연결부만 확인한다 — 빠른 순수 테스트는 v0.1에서 물려받고, 느린 통합만 새로 쓴다.
"""

from app.auth.deps import CurrentUser
from app.db import get_conn
from app.tools import run_tool


def test_create_reservation_tool_rejects_overlap(new_user):
    # 예약자는 인증 컨텍스트에서 온다 — 도구가 user.id를 코드로 주입한다.
    user = CurrentUser(**new_user()["user"])
    args = {
        "room_id": 5,  # 포커스룸1 (수용 4)
        "starts_at": "2030-01-01T10:00:00",
        "ends_at": "2030-01-01T11:00:00",
        "purpose": "도구 통합 테스트",
    }

    created = run_tool("create_reservation", dict(args), user=user)
    try:
        # 정상 생성 — 거절이 아니라 예약 정보가 돌아온다
        assert "error" not in created, created
        assert "id" in created

        # 같은 방 같은 시간 재시도 → 서비스가 겹침으로 거절.
        # 예외로 터지지 않고 결과({error, code})로 돌아와야 에이전트가 대안을 제시한다.
        dup = run_tool("create_reservation", dict(args), user=user)
        assert dup.get("code") == "TimeConflict", dup
    finally:
        # 테스트 격리 — 만든 예약은 정리해 재실행해도 깨끗하게 한다
        if isinstance(created, dict) and "id" in created:
            with get_conn() as conn:
                conn.execute("DELETE FROM reservations WHERE id = %s", (created["id"],))
