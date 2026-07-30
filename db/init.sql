-- 회의실 예약 서비스 — 스키마 + 시드 (한 파일로 관리)
--
-- PostgreSQL 컨테이너 첫 기동 시 docker-entrypoint-initdb.d 에서 자동 적용됩니다.
-- 이미 데이터 볼륨이 있으면 다시 실행되지 않습니다 — 처음부터 다시 만들려면:
--   docker compose down -v && docker compose up

SET TIME ZONE 'Asia/Seoul';

-- ── 스키마 ──────────────────────────────────────────────────────────

CREATE TABLE teams (
    id   serial PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE users (
    id            serial PRIMARY KEY,
    email         text NOT NULL UNIQUE,
    name          text NOT NULL,
    password_hash text NOT NULL,
    role          text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'admin')),
    team_id       int  NOT NULL REFERENCES teams (id)
);

-- 로그인 토큰 — DB 저장 방식의 불투명 토큰 (서버는 무상태, 검증은 조회로)
CREATE TABLE auth_tokens (
    token      text PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rooms (
    id        serial PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    capacity  int  NOT NULL,
    equipment text NOT NULL DEFAULT ''  -- 쉼표 구분 설비 목록 (예: '화면공유,화이트보드')
);

CREATE TABLE reservations (
    id        serial PRIMARY KEY,
    room_id   int NOT NULL REFERENCES rooms (id),
    user_id   int NOT NULL REFERENCES users (id),
    starts_at timestamptz NOT NULL,
    ends_at   timestamptz NOT NULL,
    purpose   text NOT NULL DEFAULT '',
    CHECK (starts_at < ends_at)
);

-- 에이전트 대화 이력 (v1.0에서 사용 — 스키마만 미리 준비, 시드는 비움)
CREATE TABLE conversations (
    id         serial PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id              serial PRIMARY KEY,
    conversation_id int   NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role            text  NOT NULL,
    content         jsonb NOT NULL,  -- 도구 호출·결과 메시지까지 그대로 저장 (루프 재개용)
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ── 시드 ────────────────────────────────────────────────────────────
-- 모든 시드 계정의 비밀번호는 'demo1234' 입니다 (app/auth 와 같은 pbkdf2 형식).
-- 관리자는 여기(시드)에서만 지정합니다 — /signup 은 항상 member, 승급 API 없음.

INSERT INTO teams (name) VALUES
    ('플랫폼팀'),
    ('그로스팀');

INSERT INTO users (email, name, password_hash, role, team_id) VALUES
    ('admin@example.com', '김운영', 'pbkdf2_sha256$210000$69f91bfba29ab06533a57266bcbd11d7$f754015a2ed45f8a0014f0c53d395ed4b4bff06d704bf712fbc273319a697d82', 'admin',  1),
    ('hana@example.com',  '박하나', 'pbkdf2_sha256$210000$180633238c224d53bbe9539459ba3dc9$0bf27c3940797911f7a9c6bf64ca8a43b0bbc09cd285f21ba6290b28afea3b1c', 'member', 1),
    ('duri@example.com',  '이두리', 'pbkdf2_sha256$210000$b3c3a3cd53410a544e2a059d7fef72bf$50b2df5fdd948fb5b96d04d9f3fa551aa449e3cd9112fd63d68d66dabc57525b', 'member', 2),
    ('semi@example.com',  '최세미', 'pbkdf2_sha256$210000$fb4f6886d72142fd54c1adccf2febcbc$84f121b1d26a353e104cde5f5e51c192edf08b5e262f598d11e6039540c742b4', 'member', 2);

INSERT INTO rooms (name, capacity, equipment) VALUES
    ('대회의실A',      12, '화면공유,화상회의,화이트보드'),
    ('대회의실B',      10, '화면공유,화이트보드'),
    ('세미나실',       20, '화면공유,프로젝터,마이크'),
    ('브레인스토밍룸',  6, '화이트보드,화면공유'),
    ('포커스룸1',       4, '모니터'),
    ('포커스룸2',       4, '');

-- 기존 예약 — 시연 시나리오가 기대는 데이터입니다.
--   · 대회의실A 는 내일(시드 적용일 기준) 오후 13~18시가 꽉 찬 인기 방
--     → 도구 연쇄 시연: 검색 1순위가 막혀 다른 방으로 넘어감
--   · 내일 14시 대회의실A 예약은 그로스팀 이두리 소유
--     → 인젝션 시연: 다른 팀 예약 취소 공격의 대상
--   · 같은 방 같은 시간을 다시 예약하면 겹침으로 거절 → 겹침 시연
INSERT INTO reservations (room_id, user_id, starts_at, ends_at, purpose) VALUES
    (1, 2, (CURRENT_DATE + 1) + time '13:00', (CURRENT_DATE + 1) + time '14:00', '플랫폼 주간회의'),
    (1, 3, (CURRENT_DATE + 1) + time '14:00', (CURRENT_DATE + 1) + time '15:00', '그로스 캠페인 리뷰'),
    (1, 4, (CURRENT_DATE + 1) + time '15:00', (CURRENT_DATE + 1) + time '16:30', '제품 데모 준비'),
    (1, 2, (CURRENT_DATE + 1) + time '16:30', (CURRENT_DATE + 1) + time '18:00', '채용 인터뷰'),
    (2, 3, (CURRENT_DATE + 1) + time '10:00', (CURRENT_DATE + 1) + time '11:00', '스프린트 플래닝'),
    (3, 1, (CURRENT_DATE + 2) + time '09:00', (CURRENT_DATE + 2) + time '12:00', '전사 타운홀');

-- ── v1.5: 관리자 전용 SQL 콘솔 (feature/sql-console) ──────────────────
-- 자연어 → SQL 조회 도구는 이 리소스만 씁니다. 세 겹 방어의 DB 절반이 여기 있습니다.

-- (1) 분석·개발용 전용 관리자 계정 — 비밀번호는 다른 시드와 같은 'demo1234'.
--     SQL 콘솔 도구는 role='admin' 에게만 열립니다.
INSERT INTO users (email, name, password_hash, role, team_id) VALUES
    ('analyst@example.com', '데이터분석', 'pbkdf2_sha256$210000$588c29d01e3f330606985731d0a029ab$8f16c21f62aa216e84dcfdaa857727cb6251e62adafd8e8423a0b7c61122bf83', 'admin', 1);

-- (2) 리포팅 뷰 — password_hash·토큰을 애초에 뺀다. SQL 콘솔은 이 뷰만 본다.
CREATE VIEW rpt_users AS
    SELECT id, email, name, role, team_id FROM users;
CREATE VIEW rpt_teams AS
    SELECT id, name FROM teams;
CREATE VIEW rpt_rooms AS
    SELECT id, name, capacity, equipment FROM rooms;
CREATE VIEW rpt_reservations AS
    SELECT id, room_id, user_id, starts_at, ends_at, purpose FROM reservations;

-- (3) 읽기 전용 롤 — SELECT 를 리포팅 뷰에만 준다.
--     베이스 테이블(users·auth_tokens·messages …)과 쓰기는 롤에 권한이 없어 DB가 거부.
--     뷰는 소유자(postgres) 권한으로 베이스 테이블을 읽으므로, reporter 는 뷰 너머를 못 본다.
CREATE ROLE reporter WITH LOGIN PASSWORD 'reporter';
GRANT USAGE ON SCHEMA public TO reporter;
GRANT SELECT ON rpt_users, rpt_teams, rpt_rooms, rpt_reservations TO reporter;
