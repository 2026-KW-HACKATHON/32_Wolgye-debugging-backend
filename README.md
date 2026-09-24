# backend

빌라 주차 스택 관리 앱의 백엔드 서버입니다.
서비스 전체 소개는 [32_Wolgye-debugging](https://github.com/2026-KW-HACKATHON/32_Wolgye-debugging)을 참고하세요.

> 서비스 한 줄 정의: 좁은 골목 빌라의 종렬 주차에서 각자 예상 출차 시간을 공유해, "내가 나갈 때 앞차가 막지 않는 자리"를 고르게 해주는 지역 한정(서울 노원구 월계1동) 앱

## 기술 스택 (미확정 항목 포함)

| 구분 | 내용             |
| --- |----------------|
| 언어/프레임워크 | 미정             |
| DB | 미정             |
| 인증 | 미정             |
| 알림 | 미정             |
| AI | 미정             |
| CI | GitHub Actions |

## 핵심 로직

- 주차장(Lot)은 여러 개의 lane(열)으로 이루어지고, lane은 스택입니다. `position 0`이 가장 안쪽입니다.
- **불변식**: 안쪽으로 갈수록 예상 출차 시간이 늦어야 합니다.
- **입차 안전 판정**: 내 예상 출차 시간 ≤ 해당 lane 맨 바깥 차의 예상 출차 시간이면 안전합니다.
- **lane 추천**: 안전한 lane 중 맨 바깥 차와 출차 시간 차이가 가장 작은 lane을 고릅니다. 여유가 큰 lane을 아껴 나중에 늦게 나가는 차를 받기 위함입니다 (patience sorting 계열 그리디).
- **동시성**: 같은 lane에 동시 입차 시 순서가 꼬이므로 lane 단위 잠금 트랜잭션으로 처리합니다.

## 주요 기능 (MVP)

1. 
2. 주차장 / lane 조회
3. 입차 등록 (칸 선택 + 예상 출차 시간)
4. 자리 추천 및 막힘 경고
5. FCM 알림 (앞차 출차 임박, 내 차가 막고 있음, 이동 요청 수신)
6. 이동 요청 (전화번호 노출 없이 앱 내 전송)
7. 미등록 차량 ("출차 시간 미상" 차량 등록)

## 데이터 모델 (초안)

```
User(id, kakao_id, nickname)
Vehicle(id, user_id, plate_masked)
Lot(id, name, lat, lng, admin_id, invite_code)
Lane(id, lot_id, order, capacity)
ParkingSession(id, vehicle_id, lane_id, position, entered_at,
               expected_exit_at, actual_exit_at, status)
MoveRequest(id, from_user_id, target_session_id, status, created_at)
```

## 개발 원칙

- API 키는 코드에 하드코딩하지 않고 환경변수로 관리합니다.
- LLM 호출은 반드시 백엔드를 경유합니다 (자연어 출차시간 파싱, 이동 요청 문구 생성).
- 차량번호는 마스킹해서 저장합니다 (예: `12가 ****`). 전화번호는 노출하지 않습니다.
- 칸 확정은 사용자가 직접 선택합니다 (GPS로는 칸 판별 불가).

## 실행 방법

스택 확정 후 작성 예정입니다.

## 폴더 구조

스택 확정 후 작성 예정입니다.
