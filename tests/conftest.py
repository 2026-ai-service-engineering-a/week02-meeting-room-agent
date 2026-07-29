"""pytest 공용 픽스처.

기준 실행 환경은 컨테이너 안입니다: `docker compose exec app pytest`
CI에서는 워크플로가 DATABASE_URL을 서비스 컨테이너로 지정합니다.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/meeting"
)

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def admin_headers(client) -> dict:
    """시드 관리자(admin@example.com / demo1234)의 인증 헤더."""
    login = client.post(
        "/login", json={"email": "admin@example.com", "password": "demo1234"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture
def new_user(client):
    """고유 이메일의 member를 가입·로그인시켜 인증 헤더와 함께 돌려주는 팩토리."""

    def _make(team_id: int = 1) -> dict:
        email = f"user-{uuid.uuid4().hex[:12]}@test.example"
        signup = client.post(
            "/signup",
            json={
                "email": email,
                "name": "테스트사용자",
                "password": "test1234",
                "team_id": team_id,
            },
        )
        assert signup.status_code == 201, signup.text
        login = client.post("/login", json={"email": email, "password": "test1234"})
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        return {
            "email": email,
            "user": signup.json(),
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make
