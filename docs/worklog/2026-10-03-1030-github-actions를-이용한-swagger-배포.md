# GitHub Actions를 이용한 Swagger 배포

- 관련 이슈: 없음 (문서 공유용 인프라) · 브랜치: `ci/swagger-pages`
- 작업: 메인 세션, 2026-10-03 사용자 요청
- 결과 주소: **https://2026-kw-hackathon.github.io/32_Wolgye-debugging-backend/**

## 목표
- `docs/openapi-mock.yaml`(API 명세)을 FE·디자인 팀원이 설치 없이 브라우저에서 보게 한다
- 명세를 고쳐 `main`에 머지하면 페이지도 자동으로 바뀌게 한다
- `docs/` 폴더의 다른 문서(worklog, DB 설계 메모)는 배포하지 않는다

## 왜 Actions 방식인가
GitHub Pages는 두 가지 방식으로 배포할 수 있다.

| 방식 | 설정 | 단점 |
|---|---|---|
| 브랜치 배포 (`main` / `/docs`) | Settings에서 폴더만 고르면 끝 | `docs/` 전체가 공개 페이지가 된다. 루트 주소(`/`)에 `index.html`이 없어 404가 난다. Jekyll이 `.md` 파일을 변환한다 |
| **GitHub Actions 배포** (선택) | 워크플로 파일 1개 + Source 설정 | 처음 한 번 설정이 필요하다 |

Actions 방식은 배포할 파일을 직접 골라 `_site/` 폴더에 담아 올린다. 그래서 Swagger 두 파일만 올라가고, `swagger-mock.html`을 `index.html`로 이름을 바꿔 루트 주소에서 바로 열 수 있다.

## 구성

### 배포 대상 파일
| 리포 경로 | 배포 경로 | 역할 |
|---|---|---|
| `docs/swagger-mock.html` | `/index.html` | Swagger UI 페이지. CSS·JS는 jsDelivr CDN에서 불러온다 |
| `docs/openapi-mock.yaml` | `/openapi-mock.yaml` | 명세 본문. HTML이 상대 경로 `url: "openapi-mock.yaml"`로 fetch한다 |

HTML이 YAML을 **상대 경로**로 읽기 때문에 두 파일을 같은 폴더에 두기만 하면 된다. HTML은 고치지 않았다.

### 워크플로: `.github/workflows/pages.yml`
```yaml
on:
  push:
    branches: [main]
    paths:                       # 명세나 워크플로가 바뀔 때만 실행
      - docs/openapi-mock.yaml
      - docs/swagger-mock.html
      - .github/workflows/pages.yml
  workflow_dispatch:             # Actions 탭에서 수동 실행도 가능

permissions:
  contents: read                 # checkout
  pages: write                   # Pages 배포
  id-token: write                # deploy-pages 가 OIDC 토큰으로 인증

concurrency:
  group: pages
  cancel-in-progress: false      # 배포 도중 끊기지 않게 순서대로 처리
```

job은 `deploy` 하나이고 단계는 다음과 같다.
1. `actions/checkout@v4`: 리포를 받는다
2. **Build site**: `_site/` 폴더를 만들고 두 파일을 복사한다 (HTML은 `index.html`로 이름을 바꾼다)
3. `actions/configure-pages@v5`: Pages 설정을 읽어 확인한다
4. `actions/upload-pages-artifact@v3`: `_site/`를 Pages용 아티팩트(tar)로 올린다
5. `actions/deploy-pages@v4`: 아티팩트를 Pages에 배포한다. 결과 URL은 `environment.url`로 Actions 화면에 표시된다

job에 `environment: github-pages`를 지정했다. 배포는 이 환경을 통해서만 된다.

## 리포 설정 (처음 한 번)
워크플로 파일만으로는 배포되지 않는다. Pages를 켜고 Source를 **GitHub Actions**로 바꿔야 한다.

### 방법 A: 웹 UI
1. 리포 → **Settings** → 왼쪽 **Pages**
2. **Build and deployment → Source**를 `GitHub Actions`로 바꾼다
3. 조직 리포라 리포 admin 권한이 필요하다

### 방법 B: gh CLI (이번에 사용)
```bash
# Pages 켜기 + Source = GitHub Actions
gh api -X POST repos/2026-KW-HACKATHON/32_Wolgye-debugging-backend/pages -f build_type=workflow

# 이미 켜져 있고 Source만 바꿀 때
gh api -X PUT repos/2026-KW-HACKATHON/32_Wolgye-debugging-backend/pages -f build_type=workflow

# 상태 확인
gh api repos/2026-KW-HACKATHON/32_Wolgye-debugging-backend/pages
```
2026-10-03에 실행했고 `"build_type":"workflow"`, `html_url`이 위 주소로 나왔다.

### 자동으로 생기는 것: `github-pages` 환경
Pages를 켜면 리포에 `github-pages` 환경이 생긴다. 이 환경은 **`main` 브랜치에서만 배포할 수 있다** (branch policy). 그래서
- PR 브랜치에서 워크플로를 돌려도 배포 단계에서 거부된다
- **PR이 `main`에 머지된 뒤에 첫 배포가 된다**

확인 명령:
```bash
gh api repos/2026-KW-HACKATHON/32_Wolgye-debugging-backend/environments/github-pages/deployment-branch-policies
```

## 평소 사용법
- 명세 수정: `docs/openapi-mock.yaml`을 고쳐 PR → `main` 머지 → 1분 안팎으로 페이지가 갱신된다
- 수동 배포: Actions 탭 → **Swagger Pages** → **Run workflow** (`main` 선택). CLI로는 `gh workflow run pages.yml --ref main`
- 배포 결과 확인
  ```bash
  gh run list --workflow pages.yml --limit 3
  gh run watch <run-id>
  ```
- 브라우저 캐시 때문에 옛 명세가 보이면 강력 새로고침(`Ctrl+Shift+R`)

## 문제 해결
| 증상 | 원인 / 해결 |
|---|---|
| push 할 때 `refusing to allow an OAuth App to create or update workflow ... without \`workflow\` scope` | `.github/workflows/` 파일을 push 하려면 gh 토큰에 `workflow` 권한이 필요하다. `gh auth refresh -h github.com -s workflow` 로 권한을 추가한 뒤 다시 push 한다 (이번 작업에서 실제로 겪었다) |
| 배포 단계에서 `Branch "..." is not allowed to deploy to github-pages` | `main`이 아닌 브랜치에서 실행했다. 머지 후 `main`에서 실행한다 |
| `configure-pages` 단계에서 `Get Pages site failed` | Pages가 꺼져 있거나 Source가 Actions가 아니다. 위 "리포 설정"을 한다 |
| 페이지는 뜨는데 "Failed to load API definition" | YAML 문법 오류이거나 파일 이름이 바뀌었다. `swagger-mock.html`의 `url`과 워크플로의 복사 경로를 맞춘다 |
| 명세를 고쳤는데 워크플로가 안 돈다 | `paths` 필터에 없는 파일만 바뀌었다. 새 파일을 배포하려면 `paths`와 Build site 단계에 추가한다 |
| Try it out 요청이 실패한다 | 정상이다. 명세의 `servers`가 `http://localhost:8000/api/v1`이라 로컬 서버를 띄워야 한다. Pages(https)에서 http 로컬 서버로 보내는 요청은 브라우저가 막을 수도 있다 |

## 바꾼 파일
- `.github/workflows/pages.yml` (새 파일)
- `README.md` "API 명세" 절에 Pages 주소 추가
- 이 문서
