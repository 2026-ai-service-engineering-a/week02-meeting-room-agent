"""v1.5 관리자 전용 SQL 콘솔 — 세 겹 방어를 코드로 검증한다.

reporter 롤·리포팅 뷰·전용 관리자 계정은 db/init.sql이 만든다 (CI도 같은 init.sql
을 적용하고 REPORTING_DATABASE_URL을 준다).
"""

from app.auth.deps import CurrentUser
from app.tools import run_tool, schemas_for

_ADMIN = CurrentUser(id=1, email="a@x", name="관리자", role="admin", team_id=1)
_MEMBER = CurrentUser(id=2, email="m@x", name="사용자", role="member", team_id=1)


def _tool_names(user) -> set[str]:
    return {schema["function"]["name"] for schema in schemas_for(user)}


def test_sql_tool_only_exposed_to_admin():
    # (1) 관리자 게이트 — 비관리자에게는 도구가 아예 노출되지 않는다
    assert "run_sql_query" in _tool_names(_ADMIN)
    assert "run_sql_query" not in _tool_names(_MEMBER)


def test_sql_tool_rejects_non_admin_execution():
    # 노출을 우회해 직접 불러도 실행 단계에서 role을 코드가 확인해 거부
    out = run_tool("run_sql_query", {"query": "SELECT 1"}, user=_MEMBER)
    assert out.get("code") == "PermissionDenied", out


def test_sql_tool_rejects_writes_and_multi_statement():
    # (2) SELECT 전용 파싱 — 쓰기·DDL·다중 문은 실행 전에 거부
    for bad in [
        "DELETE FROM rpt_reservations",
        "INSERT INTO rpt_users VALUES (1)",
        "UPDATE rpt_users SET role = 'admin'",
        "SELECT 1; DROP TABLE users",
        "DROP VIEW rpt_users",
    ]:
        out = run_tool("run_sql_query", {"query": bad}, user=_ADMIN)
        assert out.get("code") in {"NotSelectOnly", "QueryError"}, (bad, out)


def test_sql_tool_admin_can_aggregate():
    out = run_tool(
        "run_sql_query",
        {"query": "SELECT count(*) AS n FROM rpt_reservations"},
        user=_ADMIN,
    )
    assert "rows" in out, out
    assert out["rows"][0]["n"] >= 0


def test_sql_tool_cannot_reach_sensitive_data():
    # (3) 읽기 전용 롤 — 파싱을 통과해도 DB가 막는다
    # 리포팅 뷰에 없는 민감 컬럼
    out1 = run_tool(
        "run_sql_query", {"query": "SELECT password_hash FROM rpt_users"}, user=_ADMIN
    )
    assert out1.get("code") == "QueryError", out1
    # 베이스 테이블 직접 접근 → reporter 롤에 권한이 없어 거부
    out2 = run_tool("run_sql_query", {"query": "SELECT * FROM users"}, user=_ADMIN)
    assert out2.get("code") == "QueryError", out2
    # 토큰 테이블 직접 접근 → 거부
    out3 = run_tool(
        "run_sql_query", {"query": "SELECT * FROM auth_tokens"}, user=_ADMIN
    )
    assert out3.get("code") == "QueryError", out3
