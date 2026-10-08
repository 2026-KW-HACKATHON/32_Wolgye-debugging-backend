# 차곡차곡 — Backend

빌라 골목 주차를 관리하는 앱 **차곡차곡**의 백엔드입니다. FastAPI와 PostgreSQL(PostGIS)로 만들었습니다.
화면은 Manyfast 와이어프레임을 기준으로 합니다. 같은 와이어프레임이 Figma `월계디버깅` 파일에도 있습니다.
DB 설계에서 남은 과제는 [`docs/db-design-issues.md`](docs/db-design-issues.md)를 참고하세요.

## 스택
- Python 3.12, FastAPI, Pydantic v2
- SQLAlchemy 2.x (async, asyncpg), GeoAlchemy2
- PostgreSQL 16 + PostGIS 3.4, `btree_gist` 확장(공유 시간대 겹침 금지 제약에 사용)
- Alembic (마이그레이션)
- Ruff (lint), pytest
- Docker Compose (db + api)

## 폴더 구조
```
app/
├── main.py              # FastAPI 앱 생성, 라우터 등록, 전역 예외 핸들러(도메인 예외·IntegrityError → HTTP)
├── core/
│   ├── config.py        # 환경 변수 설정 (pydantic-settings)
│   └── db_errors.py     # DB 제약 이름 → 409 응답 메시지
├── api/
│   ├── deps.py          # 의존성 주입. 엔드포인트는 `db: DbSession`으로 세션을 받음
│   └── v1/
│       ├── router.py    # v1 라우터 묶음
│       └── endpoints/   # 리소스별 라우터
├── db/
│   ├── base_class.py    # DeclarativeBase
│   ├── base.py          # Alembic용: Base와 전체 모델 노출
│   └── session.py       # async 엔진과 세션
├── models/              # SQLAlchemy 모델. __init__.py에서 전체 모델을 등록
├── schemas/             # Pydantic 요청·응답 스키마
└── services/            # 비즈니스 규칙·트랜잭션(commit). HTTP를 모르고 실패는 services/exceptions.py 예외로 알림
alembic/                 # 마이그레이션 (versions/0001~0003)
docs/                    # 설계 문서
tests/
```

## 도메인 모델

| 테이블 | 설명 | 주요 화면 |
|---|---|---|
| `alleys` | **골목**. 최상위 운영 단위. 골목 > 빌라 > 차고지 > 칸 | 전체 |
| `buildings` | 빌라/건물. 골목에 속하고, 운영팀이 등록하며, 입주민은 `invite_code`로 합류 | 건물 합류 n9 |
| `garages` | **차고지**. 빌라에 속한 주차 공간(필로티 안쪽·필로티 바깥·골목 노상) | 전체 |
| `parking_slots` | 차고지 안의 **번호**로 특정하는 칸. 2.5D 로컬 좌표(`render_*`), 바로 앞 칸(`front_slot_id`), 사용 여부 | 배치도 n11, 차 배치 n15, 구역 설정 n43 |
| `share_offers` | 칸 **공유 조건**. 기간(`start_date`~`end_date`), 요일, 정시 단위 시간(`start_hour`~`end_hour`), 시간당 토큰, 최대 이용 시간, 공개 여부. 칸 하나에 여러 개 가능 | n32, n34, n45 |
| `residents` | 사용자(입주민/관리자). 이메일·비밀번호 해시·닉네임, 매너온도, **보유 토큰**(`token_balance`) | 가입 n4, 프로필 n51 |
| `token_transfers` | 토큰 이동 기록(보낸 사람, 받는 사람, 양, 원인 공유 요청). 보낸 사람이 NULL이면 시스템 지급 | - |
| `vehicles` | 차량. `owner_id`가 NULL이면 관리자가 등록한 **미확인 차량** | n10, n52 |
| `parking_assignments` | 차량이 칸에 배치된 기록. `released_at`이 NULL이면 주차 중, `is_permanent`는 상시 주차 | n15 |
| `departure_schedules` | 출차 예정(날짜·시간, 반복 요일, AI 추정 여부, 메모) | n15, n18, n20 |
| `share_requests` | 공유 조건(`offer_id`)에 대한 정시 단위 이용 요청(`request_date`, `start_hour`~`end_hour`)과 수락/거절. 요청할 때 가격(`total_price`, 토큰)을 고정 | n34, n41, n47 |
| `move_requests` | 이동 요청. 받는 사람은 `target_vehicle.owner_id` | n29, n41 |
| `notifications` | 전날 밤 출차 알림, 공유·이동 요청 알림. 원인이 된 요청을 FK로 연결 | 알림 |

**DB가 직접 막는 규칙** (마이그레이션 `0002`)
- 한 칸에는 주차 중인 차가 한 대, 한 차는 한 칸에만 있음 (부분 UNIQUE 인덱스)
- 같은 칸에서 **수락된** 공유 요청끼리 시간이 겹치지 않음 (`EXCLUDE USING gist`)
- 차고지 이름은 빌라 안에서, 칸 번호는 차고지 안에서 중복 불가. 대표 차량은 사용자당 하나. 같은 차에 대기 중인 이동 요청은 하나
- `is_active`와 `released_at`의 일관성, 반복 요일 값은 0~6, 공유 시간은 0~24시이고 시작 시가 종료 시보다 앞섬, 공유 기간 시작일 ≤ 종료일, 토큰 잔액 ≥ 0 (CHECK 제약)
- 공유 요청의 칸(`slot_id`)은 항상 그 공유 조건의 칸과 같음 (`(offer_id, slot_id)` 복합 FK) (마이그레이션 `0003`)

**공유와 토큰**
- 결제는 토큰으로만 합니다. 관리자가 요청을 **수락할 때** 요청자의 토큰 `total_price`가 공유 조건의 `host`에게 넘어가고, `token_transfers`에 기록됩니다. 잔액이 부족하면 409를 반환하고 수락되지 않습니다.
- 요청은 공유 조건의 기간·요일·시간·최대 이용 시간 안에서만 만들 수 있습니다(`app/services/share_requests.py`).
- 토큰 충전·선물 API는 아직 없습니다. 지급은 `app/services/tokens.transfer(sender_id=None, ...)`을 호출해서 합니다.

**참고**
- enum 컬럼에는 값이 아니라 **이름**이 저장됩니다. 예: `share_request_status`에는 `'PENDING'`이 들어가며, 이는 SQLAlchemy 기본 동작입니다.
- 차량번호와 전화번호는 기획 결정에 따라 비노출 대상이 아닙니다.
- `buildings.location`은 SRID 4326(위경도)이고 지도 검색에 씁니다. 2.5D 배치도는 칸의 로컬 좌표(`render_*`, 건물 기준 미터)로 그립니다.

## 실행

### 1) Docker Compose (권장)
```bash
cp .env.example .env
docker compose up -d db
docker compose run --rm api alembic upgrade head   # 스키마 생성
docker compose up --build api
```
- API 문서: http://localhost:8000/docs
- DB: localhost:5432 (user/password/db: `chagok`)

### 2) 로컬 파이썬으로 API만 실행 (DB는 Docker)
```bash
docker compose up -d db
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# .env 의 DATABASE_URL / DATABASE_URL_SYNC host 를 db → localhost 로 변경
alembic upgrade head
uvicorn app.main:app --reload
```

### 3) 전날 밤 막힘 알림 (cron)
앱 안에 스케줄러가 없습니다. 운영에서는 외부 cron으로 **매일 22:00 KST**에 아래를 실행합니다. 내일 출차할 차를 막고 있는 차의 주인에게 `BLOCK_ALERT` 알림을 만듭니다.
```bash
python -m app.jobs.block_alert
```

### 4) 시연용 시드 데이터
FE 연결·시연용으로 명세 Mock 시나리오(월계 한빛빌라 `HANBIT01`·햇살빌라, 계정 6개)를 넣습니다. 계정 목록은 `app/jobs/seed_demo.py` 맨 위에 있고 비밀번호는 모두 `chagok1234`입니다. 이미 들어가 있으면 건너뜁니다.
```bash
alembic upgrade head
python -m app.jobs.seed_demo
```

### 5) 운영 배포 (AWS EC2)
개발은 `dev`에서 하고, 배포할 때 `dev` → `main` PR을 머지합니다. `main`에 머지되어 CI가 통과하면 `.github/workflows/deploy.yml`이 이미지를 ECR에 올리고 EC2에 배포합니다. DB는 RDS를 씁니다. 운영 구성은 `docker-compose.prod.yml`(api + nginx)과 `deploy/`에 있고, 로컬 개발용 `docker-compose.yml`과는 별개입니다. AWS 처음 설정, 롤백 방식, 운영 명령은 [`docs/worklog`의 AWS 배포 문서](docs/worklog/2026-10-06-2205-aws-ec2-배포.md)에 있습니다.

## 마이그레이션 (Alembic)
| 리비전 | 내용 |
|---|---|
| `0001` | PostGIS 확장 활성화 |
| `0002` | 도메인 스키마 전체 생성과 `btree_gist` 확장 |
| `0003` | 골목(`alleys`) 추가, 구역 → 차고지(`garages`), 공유 조건(`share_offers`), 정시 단위 공유 요청, 토큰(`token_balance`, `token_transfers`). 기존 공유 요청은 새 구조로 옮길 수 없어 삭제 |

모델을 바꾼 뒤에는 아래 순서로 진행합니다.
```bash
alembic revision --autogenerate -m "설명"
# 생성된 파일을 반드시 검토: enum 추가/삭제, EXCLUDE 제약, 확장(extension)은 손으로 보완해야 할 수 있음
alembic upgrade head
alembic check        # 모델과 마이그레이션이 일치하면 "No new upgrade operations detected."
```
- `alembic/env.py`는 PostGIS 이미지에 기본으로 들어 있는 tiger/topology 테이블을 비교 대상에서 뺍니다. 그렇게 하지 않으면 autogenerate가 이 테이블들을 삭제하려고 합니다.
- 새 모델은 **`app/models/__init__.py`에 반드시 import 해 주세요.** 빠뜨리면 앱 실행 중 relationship 문자열 참조가 해석되지 않아 500 오류가 나고, Alembic도 새 테이블을 인식하지 못합니다.

## API
명세 `docs/openapi-mock.yaml`의 **49개 엔드포인트가 모두 구현**되어 있습니다. 자세한 요청·응답은 [명세 페이지](https://2026-kw-hackathon.github.io/32_Wolgye-debugging-backend/)나 서버 실행 후 http://localhost:8000/docs 에서 봅니다. 모든 경로 앞에 `/api/v1`이 붙습니다 (`/health` 제외).

| 태그 | 엔드포인트 | 이슈 |
|---|---|---|
| auth | `POST /auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/password-reset` | #6 |
| users | `GET` · `PATCH /users/me` | #6 |
| buildings | `POST /buildings/join`, `GET /buildings/{id}/layout`, `/status`, `/slots/recommendations` | #6, #9 |
| home | `GET /me/home` | #9 |
| vehicles | `GET` · `POST /me/vehicles`, `GET` · `PATCH` · `DELETE /me/vehicles/{id}`, `GET` · `PUT` · `DELETE /me/vehicles/{id}/recurring-schedule` | #7 |
| parkings | `POST /parkings`, `PUT /parkings/{id}/schedule`, `POST /parkings/{id}/exit` | #8 |
| move-requests | `POST /move-requests`, `GET /move-requests/{id}`, `POST /move-requests/{id}/done`, `GET /me/move-requests` | #10 |
| garages | `GET /garages`, `GET /garages/{id}` | #12 |
| share-requests | `POST /share-requests`, `GET /share-requests/{id}`, `GET /me/share-requests` | #12 |
| admin | `GET` · `POST /admin/buildings/{id}/share-offers`, `PATCH` · `DELETE /admin/share-offers/{id}`, `GET /admin/buildings/{id}/share-requests`, `PATCH /admin/share-requests/{id}`, `GET /admin/buildings/{id}/dashboard`, `GET /admin/buildings/{id}/slots`, `PATCH /admin/slots/{id}`, `POST /admin/buildings/{id}/unknown-vehicles` | #13, #14 |
| notifications | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | #11 |
| vehicle-reports | `POST /buildings/{id}/vehicle-reports`(multipart), `GET /vehicle-reports/{id}`, `GET /vehicle-reports/{id}/photo`, `GET /admin/buildings/{id}/vehicle-reports` | #52 |
| health | `GET /health` | — |

- 인증은 `Authorization: Bearer <access_token>` (access 30분, refresh 14일). 에러는 모두 `{"error": {"code", "message", "detail"}}`
- 명세 이전에 있던 구 API(`/alleys`, `/share-offers` 등)는 #15에서 삭제했습니다
- 전날 밤 막힘 알림은 API가 아니라 따로 실행하는 작업입니다 (위 "실행"의 3번)

### Swagger 명세서 (Mock 데이터)
서버나 DB 없이 API 명세를 볼 수 있습니다. **Figma 와이어프레임을 기준으로, Notion "차곡차곡 API 명세 v0.2"를 초안 삼아 만든 설계 명세**이고, 49개 엔드포인트의 예시 요청·응답과 에러 코드를 담았습니다. **예시 값은 전부 가짜 데이터**이고, 실제 서버가 이 값을 돌려주는 것은 아닙니다.

> 📌 **Notion의 기능 명세(API 명세 v0.2)는 임시 API 명세입니다.** 기능·화면의 기준은 **Figma 와이어프레임**이고(요구사항은 Manyfast), Notion 명세와 다르면 Figma 쪽에 맞춥니다. 엔드포인트·필드·에러 코드는 확정이 아니며, 이 Mock 명세도 최종 계약으로 보지 마세요. DB에 저장할 곳이 없는 기능(알림 설정, 푸시 구독 등)은 API로 만들지 않았습니다.

다만 아래 네 가지는 Notion 대신 **현재 DB 스키마(`app/models/`)를 따릅니다.**

- 결제는 원이 아니라 **토큰** (`residents.token_balance`, `token_transfers`)
- 차고지는 공유 상품이 아니라 **빌라의 주차장**(API `garage_id` = 빌라 id)이고, 공유 조건은 칸마다 두는 `share_offers`
- 계층은 **골목 > 빌라(차고지) > 주차 구역 > 칸** (주차 구역의 DB 테이블 이름은 `garages`, 막힘은 `front_slot_id`)
- **한 사용자는 한 빌라에만 소속** (`residents.building_id`)

> ⚠️ 현재 서버 구현(`/alleys`, `/share-offers` 등, 인증 없음)과는 경로·응답 모양이 다릅니다. 이전의 "현재 구현 기준" 명세는 git 이력(PR #1)에 있습니다.

- 명세 파일: [`docs/openapi-mock.yaml`](docs/openapi-mock.yaml) (OpenAPI 3.1, 화면 번호 #1~#23은 Notion 매핑표와 같음)
- 보기 페이지: [`docs/swagger-mock.html`](docs/swagger-mock.html) (Swagger UI를 CDN에서 불러오므로 인터넷 연결 필요)

**방법 0: 웹에서 바로 보기 (GitHub Pages)**
https://2026-kw-hackathon.github.io/32_Wolgye-debugging-backend/ — `main`에 명세가 머지되면 자동으로 갱신됩니다 (`.github/workflows/pages.yml`). 설정 방법은 [`docs/worklog`의 배포 문서](docs/worklog/2026-10-03-1030-github-actions를-이용한-swagger-배포.md)에 있습니다.

**방법 1: 로컬에서 열기** (Node.js 필요)
```bash
cd docs
npx http-server -p 8080
```
브라우저에서 http://localhost:8080/swagger-mock.html 을 엽니다. YAML을 fetch하는 구조라 파일을 더블클릭(`file://`)하면 열리지 않으니 꼭 HTTP로 여세요. 종료는 터미널에서 `Ctrl+C`.

**방법 2: 설치 없이 보기**
[editor.swagger.io](https://editor.swagger.io)에서 `docs/openapi-mock.yaml` 내용을 붙여 넣습니다.

주의할 점
- Swagger UI의 **Try it out**은 Mock이 아니라 `http://localhost:8000/api/v1`(실제 서버)로 요청을 보냅니다. 서버를 띄우지 않았다면 실패하는 게 정상입니다.
- 엔드포인트나 스키마를 바꾸면 `docs/openapi-mock.yaml`도 같이 고쳐 주세요. FastAPI가 자동 생성하는 명세는 서버 실행 후 http://localhost:8000/docs 에서 볼 수 있습니다.
- 이 명세의 enum은 **대문자 값**(`PENDING`, `APPROVED`), 요일은 `MON`~`SUN`, 금액은 토큰입니다. 현재 구현은 소문자 enum·정수 요일이라 서로 맞추는 작업이 필요합니다.
- 명세 맨 위 "열린 질문" 표에 팀 합의가 필요한 항목(홈 요약 칩 정의, 칸 이름 규칙 등)을 정리해 두었습니다.

## 개발 규칙
- 엔드포인트에서는 DB 세션을 `db: DbSession`(`app/api/deps.py`)으로 받습니다. 기본값에 `Depends()`를 쓰는 방식은 lint(B008)에 걸립니다.
- 라우트는 서비스(`app/services/`)를 호출만 합니다. 쿼리·규칙·`commit`은 서비스에 두고, 실패는 `HTTPException` 대신 `NotFoundError`/`ConflictError`/`ForbiddenError`로 알립니다.
- 테스트는 매번 전체 테이블을 TRUNCATE 하므로 **이름이 `_test`로 끝나는 DB**에서만 돕니다(CI는 예외). 처음 한 번 만들고 마이그레이션합니다.
  ```bash
  docker exec chagok-db psql -U chagok -d postgres -c "CREATE DATABASE chagok_test"
  DATABASE_URL_SYNC=postgresql+psycopg2://chagok:chagok@localhost:5432/chagok_test alembic upgrade head
  ```
- 커밋 전에 아래를 실행합니다.
  ```bash
  ruff check .      # 규칙은 pyproject.toml, 버전은 requirements-dev.txt 에 고정
  DATABASE_URL=postgresql+asyncpg://chagok:chagok@localhost:5432/chagok_test pytest -q
  ```

## CI (`.github/workflows/ci.yml`)
`dev`·`main`에 push하거나 두 브랜치로 PR을 올리면 실행됩니다.
1. **test** job: PostGIS 서비스를 띄운 뒤 `ruff check .` → `alembic upgrade head` → `alembic check` → `pytest -q`
2. **docker** job: `docker build`로 이미지 빌드
