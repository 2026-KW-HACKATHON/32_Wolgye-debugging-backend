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
├── main.py              # FastAPI 앱 생성, 라우터 등록
├── core/config.py       # 환경 변수 설정 (pydantic-settings)
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
└── schemas/             # Pydantic 요청·응답 스키마
alembic/                 # 마이그레이션 (versions/0001, 0002)
docs/                    # 설계 문서
tests/
```

## 도메인 모델

| 테이블 | 설명 | 주요 화면 |
|---|---|---|
| `buildings` | 빌라/건물. 운영팀이 등록하며, 입주민은 `invite_code`로 합류 | 건물 합류 n9 |
| `parking_zones` | 운영팀이 미리 등록하는 구역(필로티 안쪽·건물 앞·골목) | 전체 |
| `parking_slots` | 구역 안의 **번호**로 특정하는 칸. 2.5D 로컬 좌표(`render_*`), 바로 앞 칸(`front_slot_id`), 사용·공유 여부 | 배치도 n11, 차 배치 n15, 구역 설정 n43 |
| `garages` | 시간제 공유 차고지(가용 시간·요일, 시간당 요금, 최대 이용 시간, 공개 여부). 칸이 `garage_id`로 소속 | n32, n34, n45 |
| `residents` | 사용자(입주민/관리자). 이메일·비밀번호 해시·닉네임, 매너온도 | 가입 n4, 프로필 n51 |
| `vehicles` | 차량. `owner_id`가 NULL이면 관리자가 등록한 **미확인 차량** | n10, n52 |
| `parking_assignments` | 차량이 칸에 배치된 기록. `released_at`이 NULL이면 주차 중, `is_permanent`는 상시 주차 | n15 |
| `departure_schedules` | 출차 예정(날짜·시간, 반복 요일, AI 추정 여부, 메모) | n15, n18, n20 |
| `share_requests` | 공유 칸 시간제 이용 요청과 수락/거절(사유 포함) | n34, n41, n47 |
| `move_requests` | 이동 요청. 받는 사람은 `target_vehicle.owner_id` | n29, n41 |
| `notifications` | 전날 밤 출차 알림, 공유·이동 요청 알림. 원인이 된 요청을 FK로 연결 | 알림 |

**DB가 직접 막는 규칙** (마이그레이션 `0002`)
- 한 칸에는 주차 중인 차가 한 대, 한 차는 한 칸에만 있음 (부분 UNIQUE 인덱스)
- 같은 칸에서 **수락된** 공유 요청끼리 시간이 겹치지 않음 (`EXCLUDE USING gist`)
- 구역 이름은 건물 안에서, 칸 번호는 구역 안에서 중복 불가. 대표 차량은 사용자당 하나. 같은 차에 대기 중인 이동 요청은 하나
- `is_active`와 `released_at`의 일관성, 반복 요일 값은 0~6, 공유 시작 시각이 종료 시각보다 앞섬 (CHECK 제약)

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

## 마이그레이션 (Alembic)
| 리비전 | 내용 |
|---|---|
| `0001` | PostGIS 확장 활성화 |
| `0002` | 도메인 스키마 전체 생성과 `btree_gist` 확장 |

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
- `GET  /health`
- `GET|POST /api/v1/buildings`, `GET /api/v1/buildings/{id}`
- `GET|POST /api/v1/parking-slots?building_id=`, `GET /api/v1/parking-slots/{id}`
- `GET|POST /api/v1/vehicles`, `GET /api/v1/vehicles/{id}`
- `GET|POST /api/v1/departures?vehicle_id=`, `GET /api/v1/departures/{id}`
- `GET|POST /api/v1/share-requests?status=`
- `POST /api/v1/share-requests/{id}/decision`: 관리자 수락/거절. `status`는 `accepted`/`rejected`, `reject_reason`은 선택

구역, 차고지, 이동 요청, 인증 API는 아직 없습니다. 구현할 때는 `docs/db-design-issues.md` 5장의 체크리스트를 참고하세요.

## 개발 규칙
- 엔드포인트에서는 DB 세션을 `db: DbSession`(`app/api/deps.py`)으로 받습니다. 기본값에 `Depends()`를 쓰는 방식은 lint(B008)에 걸립니다.
- 커밋 전에 아래를 실행합니다.
  ```bash
  ruff check .      # 규칙은 pyproject.toml, 버전은 requirements-dev.txt 에 고정
  pytest -q
  ```

## CI (`.github/workflows/ci.yml`)
`main`에 push하거나 PR을 올리면 실행됩니다.
1. **test** job: PostGIS 서비스를 띄운 뒤 `ruff check .` → `alembic upgrade head` → `alembic check` → `pytest -q`
2. **docker** job: `docker build`로 이미지 빌드
