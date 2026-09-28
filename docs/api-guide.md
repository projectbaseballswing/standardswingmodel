# 스윙 분석 API 가이드

프론트엔드·백엔드 작업용 문서입니다. 모든 경로는 `/api` 로 시작합니다.

> **중요:** 현재 피드백 **수치는 임시값**입니다. 기준 스윙 모델을 다시 만드는 중이라
> 점수와 각도 차이는 바뀝니다. 응답의 **형식(필드 이름·타입)은 고정**했으니 그대로 작업하시면 됩니다.
> 무엇이 어떻게 바뀔지는 아래 "앞으로 바뀔 것"에 정리했습니다.

## 1. 서버 실행

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload        # http://127.0.0.1:8000/docs
```

(가상환경을 쓴다면 먼저 `python3.12 -m venv .venv && source .venv/bin/activate`)

### 목업 모드 (프론트 개발 권장)

```bash
SWING_MOCK=1 uvicorn api.main:app --reload
```

- YOLO·MediaPipe 를 불러오지 않아 **설치가 가볍고 즉시 뜹니다** (`requirements.txt` 없이 fastapi/uvicorn 만 있어도 동작).
- 영상을 올리면 **바로 `done`** 상태가 되고, 고정된 샘플 결과(`api/fixtures/analysis_sample.json`)를 돌려줍니다.
- 실제 분석은 영상당 10~20초 걸리므로, 화면 개발에는 목업 모드가 편합니다.
- 회원 기능(`/api/register` 등)은 목업 모드에서도 실제로 동작합니다.
- `GET /api/health` 의 `mock: true` 로 목업 여부를 확인할 수 있습니다.

## 2. 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 회원가입 (`id`, `password`, `e-mail`, `nickname`) |
| POST | `/api/login` | 로그인 (`e-mail`, `password`) |
| POST | `/api/me` | 내 정보 (`user`) |
| GET | `/api/health` | 서버 상태, 모델 버전, 목업 여부 |
| POST | `/api/analyses` | 영상 업로드 → 분석 작업 등록 (202) |
| GET | `/api/analyses/{id}` | 작업 상태 + 전체 결과 |
| GET | `/api/analyses/{id}/overall` | 종합 피드백 |
| GET | `/api/analyses/{id}/joints` | 관절별 피드백 |
| GET | `/api/analyses/{id}/phases` | 구간별 피드백 |
| GET | `/api/analyses/{id}/speed` | 속도 피드백 (현재 비어 있음) |

## 3. 분석 흐름

```
POST /api/analyses  (multipart: video, handedness=right|left)
  → 202 { "analysis_id": "...", "status": "queued" }

GET /api/analyses/{id}   (1~2초 간격으로 폴링)
  → { "status": "processing", "stage": "tracking_player", ... }
  → { "status": "done", "result": { ... } }
  → { "status": "failed", "error": { "code": "...", "message": "..." } }
```

`stage` 값: `loading_models` → `reading_video` → `tracking_player` → `extracting_pose` → `building_features` → `comparing`
진행률 표시에 쓸 수 있습니다.

### 에러 코드

| 코드 | 의미 | 사용자 안내 예시 |
|---|---|---|
| `INVALID_VIDEO` | 영상을 읽지 못함 | 다른 형식으로 다시 올려주세요 |
| `PLAYER_NOT_FOUND` | 타자를 찾지 못함 | 전신이 보이게 촬영해주세요 |
| `TRACKING_GAP_TOO_LONG` | 타자를 오래 놓침 | 가려짐 없이 촬영해주세요 |
| `POSE_NOT_DETECTED` | 관절 검출 실패 | 밝은 곳에서 다시 촬영해주세요 |
| `INTERNAL_ERROR` | 서버 오류 | 잠시 후 다시 시도해주세요 |

HTTP 상태: `404` 없는 분석 / `409` 아직 분석 중 / `415` 지원하지 않는 형식 / `413` 용량 초과(기본 200MB) / `422` 분석 실패

## 4. 응답에서 꼭 확인할 필드

모든 피드백 섹션에 공통으로 들어갑니다.

| 필드 | 의미 | 화면 처리 |
|---|---|---|
| `model_version` | 비교 모델 버전 (현재 `"0.1"`) | 버전이 바뀌면 해석이 달라집니다 |
| `available` | 이 항목을 분석할 수 있었는지 | `false` 면 수치 대신 "분석 불가" 표시 |
| `reliability` | `high` / `medium` / `low` | `low` 면 "참고용" 배지 |
| `level` | `good` / `caution` / `warning` | 색상 구분 |

**모든 수치 필드는 null 이 될 수 있습니다.** `available: false` 인 항목은 수치가 비어 있습니다.

`reliability` 는 영상 품질로 정합니다(복사 프레임 수, 결측 비율, 관절 검출 신뢰도).
`overall.quality.warnings` 에 사람이 읽을 수 있는 경고 문구가 들어 있으니 그대로 노출해도 됩니다.

## 5. 각 피드백 구조

### 종합 `/overall`
```jsonc
{
  "model_version": "0.1", "available": true, "reliability": "high",
  "score": 81.5,                    // 0~100
  "group_scores": [ { "key": "pose", "name": "관절 위치", "score": 55.1 } ],
  "worst_segment": { "start_frame": 65, "end_frame": 70, "phase": "follow_through" },
  "frame_distances": [ /* 80개 */ ],
  "top_issues": [ { "joint_name": "골반 라인 기울기", "phase_name": "로딩", "user": 76.4,
                    "reference": 1.9, "diff": 74.5, "z_score": 3.2, "level": "warning" } ],
  "quality": { "warnings": ["..."], "joint_visibility": { "left_wrist": 0.9 } }
}
```
`top_issues` 가 화면에 바로 쓰기 좋은 요약입니다.

### 관절별 `/joints`
각도 7개(앞팔/뒷팔 팔꿈치, 앞다리/뒷다리 무릎, 상체·골반·어깨 기울기)에 대해
구간별 평균, 임팩트 순간 값, 움직임 폭을 기준과 비교합니다. 단위는 도(°).

`?include_series=true` 를 붙이면 80프레임 시계열(`series.user`, `series.reference`, `series.reference_std`)이 들어옵니다. 그래프용입니다. 응답이 커지므로 필요할 때만 쓰세요.

### 구간별 `/phases`
```jsonc
{ "model_version": "0.1", "phases": [
    { "key": "stance", "name": "준비 자세", "available": true,
      "user_duration_ms": 1068, "reference_duration_ms": 1067,
      "tempo_ratio": 1.0, "tempo_level": "good", "score": 83.5,
      "top_deviations": [ { "joint_name": "어깨 라인 기울기", "z_score": 3.8 } ] } ] }
```
**구간 개수와 key 는 모델 버전에 따라 달라집니다.** 배열을 순서대로 그리고, `key` 로 구분하세요.

### 속도 `/speed`
현재는 `available: false` 이고 `metrics` 안의 값도 비어 있습니다.
다음 모델에서 스윙 시간, 최대 손 속도, 회전 속도, 꼬임 순서가 채워집니다.
자리만 잡아두었으니 UI 는 "준비 중"으로 두시면 됩니다.

## 6. 앞으로 바뀔 것

| 항목 | 현재 | 예정 (model_version 0.2) |
|---|---|---|
| 구간 | 준비 / 로딩 / 스윙 / 팔로우스루 (고정 프레임) | 준비 / 로딩 / 스트라이드 / 스윙 / 팔로우스루 (동작 기준) |
| `available` | 항상 true | 영상에 없는 구간은 false |
| 점수 | 임시 기준 | 실제 프로 스윙 분포로 보정 |
| 템포 | 거의 항상 1.0 (의미 없음) | 실제 구간 길이 비교 |
| 속도 | 비어 있음 | 값이 채워짐 |
| 각도 수치 | 기준 모델 문제로 신뢰 어려움 | 재생성 후 정상화 |

형식 변경은 **필드 추가와 null 허용** 범위로 유지할 계획입니다. 필드 삭제나 타입 변경이 필요하면 미리 공유하겠습니다.

## 7. 백엔드 쪽 남은 작업

- **분석 결과가 서버 메모리에만 있습니다.** 재시작하면 사라지고, 최근 200건만 유지하며, 사용자 구분이 없습니다.
  `users` 테이블이 생겼으니 분석 결과도 DB에 사용자 ID와 함께 저장하면 "내 분석 기록"을 만들 수 있습니다.
  저장 위치는 `api/jobs.py` 한 곳이라 교체 범위는 작습니다.
- **DB 파일 경로가 상대 경로**(`sqlite:///./users.db`)라 서버를 켠 폴더에 생깁니다. 배포 전에 절대 경로로 바꾸는 편이 안전합니다.
- 분석은 워커 1개가 순서대로 처리합니다(YOLO 추적 특성상 동시 실행 불가). 동시 요청이 많아지면 프로세스를 늘려야 합니다.
