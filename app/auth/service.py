"""회원가입·로그인·토큰 검증.

토큰은 DB 저장 방식의 불투명 문자열입니다 — 서버는 요청 사이에 아무것도
기억하지 않고, 검증은 매번 DB 조회로 합니다. (JWT 같은 표준 토큰은 README 참조)
"""

import secrets

from app.auth.passwords import hash_password, verify_password
from app.db import get_conn


class AuthError(Exception):
    """가입·로그인 거절 — 이미 있는 이메일, 잘못된 자격증명 등."""


def signup(email: str, name: str, password: str, team_id: int) -> dict:
    """항상 member로 가입합니다 — 관리자는 시드(DB)에서만 지정, 승급 API 없음."""
    with get_conn() as conn:
        team = conn.execute("SELECT id FROM teams WHERE id = %s", (team_id,)).fetchone()
        if team is None:
            raise AuthError("존재하지 않는 팀입니다")
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email = %s", (email,)
        ).fetchone()
        if exists:
            raise AuthError("이미 가입된 이메일입니다")
        return conn.execute(
            """
            INSERT INTO users (email, name, password_hash, role, team_id)
            VALUES (%s, %s, %s, 'member', %s)
            RETURNING id, email, name, role, team_id
            """,
            (email, name, hash_password(password), team_id),
        ).fetchone()


def login(email: str, password: str) -> str:
    """자격증명이 맞으면 불투명 토큰을 발급해 DB에 저장하고 돌려줍니다."""
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = %s", (email,)
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            raise AuthError("이메일 또는 비밀번호가 올바르지 않습니다")
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id) VALUES (%s, %s)",
            (token, user["id"]),
        )
    return token


def get_user_by_token(token: str) -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT u.id, u.email, u.name, u.role, u.team_id
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = %s
            """,
            (token,),
        ).fetchone()
