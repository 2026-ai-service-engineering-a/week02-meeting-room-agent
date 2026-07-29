"""인증 테스트 — 가입·로그인·토큰, 그리고 전역 인증 원칙."""


def test_signup_login_me(client, new_user):
    user = new_user()
    me = client.get("/me", headers=user["headers"])
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == user["email"]
    assert body["role"] == "member"


def test_signup_is_always_member(client, new_user):
    # 페이로드에 role을 끼워 넣어도 무시됩니다 — 관리자는 시드(DB)에서만
    import uuid

    email = f"user-{uuid.uuid4().hex[:12]}@test.example"
    signup = client.post(
        "/signup",
        json={
            "email": email,
            "name": "승급시도",
            "password": "test1234",
            "team_id": 1,
            "role": "admin",
        },
    )
    assert signup.status_code == 201
    assert signup.json()["role"] == "member"


def test_duplicate_email_rejected(client, new_user):
    user = new_user()
    again = client.post(
        "/signup",
        json={
            "email": user["email"],
            "name": "중복가입",
            "password": "test1234",
            "team_id": 1,
        },
    )
    assert again.status_code == 409


def test_unknown_team_rejected(client):
    import uuid

    resp = client.post(
        "/signup",
        json={
            "email": f"user-{uuid.uuid4().hex[:12]}@test.example",
            "name": "없는팀",
            "password": "test1234",
            "team_id": 999,
        },
    )
    assert resp.status_code == 409


def test_wrong_password_rejected(client, new_user):
    user = new_user()
    resp = client.post(
        "/login", json={"email": user["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_endpoints_require_login(client):
    # 전역 인증 원칙 — /signup·/login 을 제외한 모든 엔드포인트는 토큰 없으면 401
    assert client.get("/me").status_code == 401


def test_invalid_token_rejected(client):
    resp = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
