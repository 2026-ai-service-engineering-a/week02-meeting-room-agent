# week02-meeting-room-agent — 회의실 예약 에이전트

가상 회사의 **멀티 팀 회의실 예약 서비스**입니다. 2주차 라이브 세션에서
docker compose 개발환경과 Git Flow(지시 → 검증 → 커밋 → PR → CI → 머지)를
시연하는 저장소입니다.

- **v0.1** — 시연 시작점. 인증(회원가입·로그인)과 회의실 검색·예약·취소가
  **이미 진짜로 동작하는** 서비스입니다. 없는 것은 자연어 통로
  (`POST /reserve` → 501) 하나뿐입니다
- **v1.0** — 시연 종료점. 기존 서비스 함수를 도구로 감싼 AI 에이전트가
  `/reserve`에 연결됩니다 (feature 브랜치 3회전으로 추가)
- **v1.5** — 심화(선택). 관리자 전용 자연어 SQL 조회 도구 (`feature/sql-console`)

시연에서 무엇이 만들어졌는지는 태그 간 diff 하나로 볼 수 있습니다.

```bash
git diff v0.1 v1.0
```

## 구조

```plaintext
week02-meeting-room-agent (v0.1)
├── app/
│   ├── main.py              # FastAPI — 인증 + 예약 서비스 엔드포인트
│   │                        #   /signup /login /me · /rooms · /reservations
│   │                        #   /reserve(에이전트)만 아직 미구현(501)
│   ├── auth/                # 회원가입 · 로그인 · 토큰 검증 (아래 해설)
│   ├── services/            # 예약 서비스 로직 — 도구가 재사용할 계층
│   │   ├── rooms.py         #   회의실 검색 · 가용 조회
│   │   └── reservations.py  #   예약 생성(겹침·인원) · 취소(본인·관리자)
│   │                        #   겹침 판정 overlaps()는 순수 함수로 분리
│   └── db.py                # PostgreSQL 연결 헬퍼 (DATABASE_URL)
├── web/
│   └── index.html           # 예약 화면 — 검색·예약·취소 폼 (이미 동작)
├── db/
│   └── init.sql             # 스키마 + 시드 (팀 2, 사용자 4, 회의실 6, 기존 예약)
│                            #   conversations·messages 테이블 포함 (에이전트 대화용, 빈 상태)
├── tests/
│   ├── test_auth.py         # 인증 테스트
│   ├── test_overlap.py      # 겹침 순수 함수 유닛테스트 (경계 케이스 포함)
│   └── test_reservations.py # 예약 생성·취소 통합 테스트
├── .github/workflows/
│   └── test.yml             # PR 시 pytest (postgres 서비스 컨테이너 포함)
├── docker-compose.yml       # app + db 공통 정의
├── docker-compose.dev.yml   # 개발 오버라이드 (볼륨·--reload·db 포트)
├── Dockerfile               # uv 기반 의존성 설치
├── .env.example             # GEMINI/ANTHROPIC/OPENAI_API_KEY, MODEL, FALLBACK_MODELS, DB 접속 정보
├── pyproject.toml           # fastapi, litellm, psycopg, pytest 등 선언 완료
├── PROMPT.md                # 시연 지시 프롬프트가 누적될 자리
└── README.md
```

## 실행 방법

필요한 것은 **git과 Docker뿐**입니다. Python·uv·PostgreSQL은 전부 컨테이너
안에 들어 있습니다.

### 0. 저장소 받기 (v0.1로 시작)

기본 브랜치 `main`은 **완성본(v1.5)** 입니다. 시연을 처음부터 따라 하려면
그냥 클론하지 말고, 시작점인 **v0.1 태그**에서 작업 브랜치를 만들어 시작하세요.

```bash
git clone https://github.com/2026-ai-service-engineering-a/week02-meeting-room-agent.git
cd week02-meeting-room-agent
git switch -c week02 v0.1   # v0.1 태그에서 작업 브랜치 생성 (detached HEAD 방지)
```

완성본과 비교는 태그로 봅니다: `git checkout v1.0` · `git checkout v1.5` ·
`git diff v0.1 v1.0`. (`--depth 1` 얕은 클론은 다른 태그·diff가 안 되니 전체 클론을 쓰세요.)

### 1. 환경변수 준비

```bash
cp .env.example .env
```

v0.1 예약 서비스는 **키 없이 전부 동작**합니다. LLM 프로바이더 키는 v1.0
에이전트(`/reserve`)를 돌릴 때만 필요합니다. LiteLLM이 `MODEL` 문자열의
접두사(`gemini/`·`anthropic/`·`openai/`)를 보고 알맞은 키로 호출합니다.

- 기본 모델은 무료 티어가 있는 `gemini/gemini-2.5-flash`라 `GEMINI_API_KEY`
  하나면 시작할 수 있습니다
  ([Google AI Studio](https://aistudio.google.com/apikey)에서 무료 발급)
- 3회전의 폴백 시연(`FALLBACK_MODELS`)까지 재현하려면
  Claude(`ANTHROPIC_API_KEY`)와 OpenAI(`OPENAI_API_KEY`) 키도 `.env`에
  넣습니다

### 2. docker compose로 실행

**실행 모드** — 이미지에 구운 코드를 그대로 실행합니다.

```bash
docker compose up --build
```

**개발 모드** — 같은 정의 위에 dev 파일을 **덮어씁니다**. 소스가 마운트되고
`--reload`로 실행되어 코드 변경이 재빌드 없이 반영됩니다. 라이브 시연은 이
모드로 진행합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

첫 기동 때 PostgreSQL 컨테이너가 `db/init.sql`을 자동 적용합니다 — DB
스키마·시드가 코드로 관리됩니다. 처음부터 다시 만들려면:

```bash
docker compose down -v && docker compose up --build
```

### 3. 써 보기

**웹 화면**: <http://localhost:8000> — 로그인하면 검색·예약·취소가 클릭으로
전부 됩니다. **API 문서(Swagger)**: <http://localhost:8000/docs>

시드 계정 (비밀번호는 전부 `demo1234`):

| 이메일 | 이름 | 역할 | 팀 |
| --- | --- | --- | --- |
| admin@example.com | 김운영 | **admin** | 플랫폼팀 |
| hana@example.com | 박하나 | member | 플랫폼팀 |
| duri@example.com | 이두리 | member | 그로스팀 |
| semi@example.com | 최세미 | member | 그로스팀 |

**curl**로도 같은 일을 할 수 있습니다:

```bash
# 로그인 → 토큰
TOKEN=$(curl -s -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"email":"hana@example.com","password":"demo1234"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 회의실 검색 (6명 이상 + 화면공유)
curl -s "http://localhost:8000/rooms?capacity=6&equipment=화면공유" \
  -H "Authorization: Bearer $TOKEN"

# 예약 생성 (겹치면 409와 사유가 돌아옵니다)
curl -s -X POST http://localhost:8000/reservations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"room_id":1,"starts_at":"2026-08-03T10:00:00","ends_at":"2026-08-03T11:00:00","purpose":"팀 회의","attendees":6}'
```

`/signup`·`/login`을 제외한 **모든 엔드포인트는 토큰 없으면 401**입니다.
아직 미구현인 것은 `POST /reserve`(자연어 통로) 하나뿐이고, 로그인 후
호출하면 501이 돌아옵니다.

### 4. 테스트

```bash
docker compose exec app pytest
```

### 5. DB 들여다보기

```bash
docker compose exec db psql -U postgres -d meeting
# 예: SELECT * FROM rooms;  SELECT * FROM reservations;
```

개발 모드에서는 호스트 5432 포트로도 노출되므로 GUI 도구로
`postgresql://postgres:postgres@localhost:5432/meeting`에 붙을 수 있습니다.

## 인증 구조 해설

인증은 이번 주의 학습 목표가 아니라서 미리 만들어 두었지만, 원리를 알고
싶다면:

- **비밀번호**는 표준 라이브러리 pbkdf2로 해시해 저장합니다 (`app/auth/passwords.py`)
- **토큰**은 DB 저장 방식의 불투명 문자열입니다 (`auth_tokens` 테이블).
  서버는 요청 사이에 아무것도 기억하지 않고 매번 DB 조회로 검증합니다 —
  JWT 같은 표준 토큰은 이후 주차에서 언급합니다
- **전역 인증 원칙**: FastAPI 라우터 의존성 하나(`app/auth/deps.py`)로
  `/signup`·`/login` 밖의 모든 라우트를 일괄 잠급니다. 엔드포인트마다 검사
  코드를 반복하지 않습니다
- `/signup`은 **항상 member**로 가입합니다. 관리자는 시드(DB)에서만
  지정되고, 승급 API는 없습니다

## 예약 서비스 해설 — 도구가 재사용할 계층

`app/services/`가 이 시스템의 결정적 코드입니다. v1.0에서 에이전트 도구는
이 함수들을 감싸는 얇은 래퍼일 뿐, 겹침·인원·권한 규칙을 재발명하지
않습니다.

- **겹침 판정**은 DB와 무관한 순수 함수 `overlaps()`로 분리되어 있고,
  경계 케이스(끝 시각 == 시작 시각인 딱 붙는 예약은 허용)까지
  유닛테스트(`tests/test_overlap.py`)로 지킵니다
- **예약자·취소자는 요청 본문이 아니라 인증 컨텍스트에서 주입**됩니다.
  누구도 자신을 다른 사람이나 관리자라고 주장할 수 없습니다 — v1.0에서
  모델에게도 똑같이 적용될 원칙입니다
- 취소는 **본인 예약 또는 관리자(role='admin')**만 가능합니다
- 거절(겹침·인원 초과·없는 방·권한)은 도메인 예외로 올라와 HTTP
  403/404/409/422로 매핑됩니다

## CI 해설

`.github/workflows/test.yml` — PR을 올리면 GitHub Actions가 PostgreSQL
서비스 컨테이너를 띄우고, 로컬과 같은 `db/init.sql`로 스키마를 만든 뒤
`pytest`를 돌립니다. 핵심 기능이 아니라 **안전망**입니다: 머지 전에
초록불을 확인하는 습관이 이번 주 워크플로의 일부입니다.

## 브랜치 전략

git flow를 따릅니다.

- `main` — 릴리즈 전용 (v0.1, v1.0 태그)
- `develop` — 통합 브랜치
- `feature/*` — 작업 브랜치 (지시 프롬프트 하나 = 브랜치 하나)
