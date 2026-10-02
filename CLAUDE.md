# CLAUDE.md

빌라 골목 주차 공유 앱 **차곡차곡**의 백엔드 (FastAPI + PostgreSQL/PostGIS, async SQLAlchemy 2.x).
스택·폴더 구조·도메인 모델·실행 방법은 `README.md`, DB 규칙과 남은 과제는 `docs/db-design-issues.md`에 있다. 여기에는 작업할 때 지켜야 할 규칙만 적는다.

## 기준 문서 (우선순위)
1. **화면**: Figma `월계디버깅` 와이어프레임
2. **요구사항**: Manyfast 프로젝트 "차곡차곡"
3. **API 명세**: `docs/openapi-mock.yaml` (Figma 기준으로 정리한 설계 명세, 엔드포인트 45개). 맨 위 "열린 질문" 표에 미정 항목이 있다
4. Notion "API 명세 v0.2"는 임시안. 위와 다르면 위를 따른다

- 현재 구현된 `/alleys`, `/share-offers` 등은 **구 API**이고 명세와 경로·응답 모양이 다르다. 새 작업은 명세를 따르고, 구 API는 이슈 #15에서 제거한다.
- 명세에 없거나 애매한 부분은 **추측해서 구현하지 않는다.** 해당 이슈에 댓글로 질문을 남기고 작업 보고에 포함한다.

## 작업 단위 = GitHub 이슈
- Epic #16에 전체 분담과 워크플로가 있다. 이슈 하나가 작업 하나다: `gh issue view <번호>`
- 담당: **건우** = 인증·공유·관리자·알림 (#6, #11~#14), **현서** = 차량·주차·막힘·이동 요청 (#7~#10), 공통 = #4, #15
- 명세의 열린 질문과 애매했던 점은 [#4 결정 댓글](https://github.com/2026-KW-HACKATHON/32_Wolgye-debugging-backend/issues/4#issuecomment-5944657022)에 확정되어 있다. 이슈 본문의 "결정 N"은 이 댓글의 번호다.
- 브랜치는 이슈별로 따로 만든다 (예: `feat/8-parkings`). PR 본문에 `Closes #<번호>`를 넣는다 → Epic 진행률에 반영된다.
- 커밋 메시지는 기존 형식을 따른다: `feat: …`, `fix: …`, `docs: …` (한국어 설명)

## 명령어
Python은 로컬 venv, Docker는 DB(PostGIS)에만 쓴다.
```bash
source .venv/bin/activate          # worktree 에서는 원본 리포의 .venv 를 쓴다
docker compose up -d db            # chagok-db, localhost:5432

ruff check .                       # lint (규칙: pyproject.toml, 버전: requirements-dev.txt 고정)
DATABASE_URL=postgresql+asyncpg://chagok:chagok@localhost:5432/chagok_test pytest -q
alembic upgrade head && alembic check   # 모델 ↔ 마이그레이션 일치 확인
```
- 테스트는 매번 전체 테이블을 TRUNCATE 한다. DB 이름이 `_test`로 끝나지 않으면 `tests/conftest.py`가 실행을 막는다.
- **여러 에이전트·사람이 동시에 테스트하면** DB를 따로 쓴다 (예: `chagok_8_test`, 이슈 번호를 넣고 `_test`로 끝나야 한다). 처음 한 번 만들고 마이그레이션한다.
  ```bash
  docker exec chagok-db psql -U chagok -d postgres -c "CREATE DATABASE chagok_8_test"
  DATABASE_URL_SYNC=postgresql+psycopg2://chagok:chagok@localhost:5432/chagok_8_test alembic upgrade head
  ```
- 완료 기준: `ruff check .`와 `pytest -q` 통과. 모델을 건드렸다면 `alembic check`도 통과. CI(`.github/workflows/ci.yml`)도 같은 순서로 검사한다.

## 코드 규칙
- **라우트는 얇게**: `app/api/v1/endpoints/`는 서비스 호출만 한다. 쿼리·비즈니스 규칙·`commit`은 `app/services/`에 둔다.
- **서비스는 HTTP를 모른다**: 실패는 `HTTPException`이 아니라 `app/services/exceptions.py`의 도메인 예외(`NotFoundError` 404 / `ConflictError` 409 / `ForbiddenError` 403 등)에 명세의 에러 `code`를 담아 알린다. 변환은 `app/main.py`의 전역 핸들러가 한다.
- **에러 응답 형식**은 명세대로 `{"error": {"code", "message", "detail"}}`이다. 코드는 명세 `ErrorCode` enum만 쓴다. 요청 검증 실패는 400 `INVALID_INPUT`. (이슈 #4에서 기존 `{"detail": ...}` 형식을 바꾼다)
- DB 세션은 `db: DbSession`(`app/api/deps.py`)으로 받는다. 기본값에 `Depends()`를 쓰면 lint(B008)에 걸린다.
- 인증·권한은 `app/api/deps.py`의 `CurrentUser`, `BuildingMember`, `BuildingAdmin`(경로에 `{building_id}` 필요)을 쓴다. 경로에 빌라 id가 없으면 서비스에서 `app/services/permissions.py`의 `ensure_building_member/admin`을 부른다. 인증은 `Authorization: Bearer <access_token>`(#6)이고, API 테스트는 `tests/helpers.auth_headers(resident)`로 헤더를 만든다.
- 공통 도구: 에러 코드 `app/core/error_codes.py`, 페이지네이션 `app/services/pagination.py`(`paginate`) + `app/schemas/common.py`(`Page[T]`) + `deps.py`(`CursorParam`, `LimitParam`), 번호판 `app/core/plates.py`·`PlateIn/PlateOut`, 요일 `app/core/weekdays.py`, 명세↔DB enum `app/core/enum_maps.py`.
- 구 API 라우터는 `app/api/v1/endpoints/legacy/`에 있다 (#15에서 삭제). 새 엔드포인트는 `endpoints/` 바로 아래 자기 파일에만 추가한다.
- DB 제약 위반(`IntegrityError`)은 전역 핸들러가 409로 바꾼다. 새 제약을 추가하면 `app/core/db_errors.py`에 제약 이름별 에러 코드와 메시지를 등록한다.
- 새 모델은 `app/models/__init__.py`에 반드시 import 한다. 빠지면 relationship 해석 실패(500)와 Alembic 누락이 생긴다.
- 테스트: 비즈니스 규칙은 `tests/services/`, API는 `tests/api/`. 데이터는 `tests/factories.py`로 만든다. 명세가 아직 바뀔 수 있으므로 응답 전체를 스냅샷처럼 고정하는 테스트는 피한다.

## 병렬 작업 규칙 (사람·에이전트 공통)
- **`app/models/`, `alembic/`은 고치지 않는다.** 현재 계획(#4 결정)으로는 스키마 변경이 필요 없다. 꼭 필요하면 새 이슈를 열어 한 사람이 맡는다. 여러 사람이 리비전을 만들면 `down_revision` 체인이 갈라진다.
- 공유 파일 `app/api/v1/router.py`, `app/services/exceptions.py`, `app/core/db_errors.py`는 이슈 #4에서 미리 틀을 만들고, 이후에는 자기 줄만 추가한다.
- 담당자 사이의 접점은 정해진 함수로만 주고받는다. 시그니처를 바꾸려면 상대와 먼저 합의한다.
  - `services/notifications.create(...)`: 건우가 제공, 현서가 호출
  - `services/blocking.py` 막힘 판정: 현서가 제공, 건우가 읽기 전용으로 사용
  - 칸·시간대별 수락된 공유 조회 (`services/share_requests`): 건우가 제공, 현서가 호출
- 자기 이슈 범위 밖의 파일은 고치지 않는다. 고쳐야 하면 보고에 이유를 적는다.

## 작업 보고 형식 (서브 에이전트)
코드를 붙여 넣지 말고 아래만 짧게 보고한다.
1. 이슈 번호, 브랜치, PR 링크
2. 바꾼 파일 목록
3. `ruff` / `pytest` 결과
4. 명세와 다르게 구현한 점과 그 이유
5. 남은 질문 (이슈에 댓글로 남긴 것)

## 주의할 점
- enum 컬럼에는 값이 아니라 **이름**(대문자, 예: `'PENDING'`)이 저장된다. raw SQL이나 부분 인덱스 조건에 소문자를 쓰지 않는다.
- 명세의 enum은 대문자(`PENDING`, `APPROVED`)이고 요일은 `MON`~`SUN`이다. 현재 구현은 소문자 값과 정수 요일(0=월)이라 새 API에서 명세에 맞춘다. 명세와 DB 이름이 다른 것(`ADMIN`↔`MANAGER`, `APPROVED`↔`ACCEPTED`, `is_default`↔`is_primary`, `alias`↔`nickname`)은 스키마(Pydantic)에서 변환한다.
- 결제는 원이 아니라 **토큰**이다 (`residents.token_balance`, `token_transfers`). 토큰 이동은 `app/services/tokens.py`만 통해서 한다. 가입 시 500,000 토큰을 시스템 지급(`sender_id=None`)한다.
- **막힘**: 앞 칸(`front_slot_id`)의 차가 내 차보다 늦게 나가면 막힘. 출차 시간이 없는 앞 칸 차(상시·미확인)는 늦게 나가는 것으로 본다. 판정은 `services/blocking.py` 한 곳에만 둔다.
- 시간은 **Asia/Seoul** 기준으로 해석한다. 출차는 `date + time`, 공유는 `date + 정시(0~24)`, 나머지는 `timestamptz`.
- `.env`의 DB host는 Docker 기준(`db`)이다. 로컬에서 돌릴 때는 `localhost`로 바꾼다.
