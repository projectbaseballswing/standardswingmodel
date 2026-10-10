# 스윙 분석 API 가이드

프론트엔드·백엔드 작업용 문서입니다. 모든 경로는 `/api` 로 시작합니다.

> **중요:** 현재 피드백 **수치는 임시값**입니다. 기준 스윙 모델을 다시 만드는 중이라
> 점수와 각도 차이는 바뀝니다. 응답의 **형식(필드 이름·타입)은 고정**했으니 그대로 작업하시면 됩니다.
> 무엇이 어떻게 바뀔지는 아래 "앞으로 바뀔 것"에 정리했습니다.

## 1. 서버 실행

```bash
pip install -r requirements.txt
# .env 설정은 docs/backend-setup.md 참고
alembic upgrade head
uvicorn api.main:app --port 8000     # http://127.0.0.1:8000/docs
```

(가상환경을 쓴다면 먼저 `python3.12 -m venv .venv && source .venv/bin/activate`)

### 목업 모드 (프론트 개발 권장)

```bash
SWING_MOCK=1 uvicorn api.main:app --reload
```

- YOLO·MediaPipe를 불러오지 않습니다. `pip install -r requirements-api.txt`로 설치할 수 있습니다.
- 영상을 올리면 **바로 `done`** 상태가 되고, 고정된 샘플 결과(`api/fixtures/analysis_sample.json`)를 돌려줍니다.
- 실제 분석은 영상당 10~20초 걸리므로, 화면 개발에는 목업 모드가 편합니다.
- 회원 기능(`/api/register` 등)은 목업 모드에서도 실제로 동작합니다.
- **DB와 Storage는 mock 처리하지 않습니다.** 실제 업로드·영속 저장 후 고정된 분석 결과를 저장합니다.
- `GET /api/health` 의 `mock: true` 로 목업 여부를 확인할 수 있습니다.

## 2. 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 회원가입 (`id`, `password`, `email`, `nickname`) |
| POST | `/api/login` | 로그인 (`id`, `password`) |
| POST | `/api/me` | 내 정보 (`user`) |
| GET | `/api/check-email` | 이메일 중복 확인 (`email` query) |
| GET | `/api/health` | 서버 상태, 모델 버전, 목업 여부 |
| POST | `/api/analyses` | 영상 업로드 → 분석 작업 등록 (202) |
| ~~POST~~ | ~~`/api/analyses/features`~~ | 개발 전용(문서·Swagger 비공개). 사용자는 영상만 올립니다 |
| GET | `/api/users/{user_id}/swings` | 회원별 스윙 목록 조회. `year`, `month` 선택 필터 |
| GET | `/api/analyses/{id}` | 작업 상태 + 전체 결과 |
| GET | `/api/analyses/{id}/video` | 원본 영상 signed URL (`analysis_id`, `url`, `expires_in`) |
| GET | `/api/analyses/{id}/overall` | 종합 피드백 |
| GET | `/api/analyses/{id}/joints` | 관절별 피드백 |
| GET | `/api/analyses/{id}/phases` | 구간별 피드백 |
| GET | `/api/analyses/{id}/speed` | 속도 피드백 (현재 비어 있음) |

## 회원별 스윙 목록 조회 (Flutter 달력/기록 화면)

```http
GET /api/users/testuser01/swings?year=2026&month=10
```

- `user_id`: 목록을 조회할 회원 ID (없는 회원은 404)
- `year` + `month`: 둘 다 입력하면 해당 월만 반환. 둘 다 생략하면 전체 기록
- 하나만 입력하거나 범위를 벗어나면 422 (`year`: 1900~9998, `month`: 1~12)
- `tz_offset_minutes`: 선택, 기본 `540`(한국시간 +09:00). 월 경계는 이 시간대 기준
- 오프셋 범위는 -720~840이며, 월 시작은 포함하고 다음 달 시작은 제외
- 정렬: 표시 날짜 최신순 (`recorded_at` 없으면 `created_at` 기준)
- 결과가 없으면 200과 `count: 0`, `items: []`

응답 예시 (예시 데이터):

```json
{
  "user_id": "testuser01",
  "year_month": "2026-10",
  "count": 1,
  "items": [
    {
      "analysis_id": "1234abcd1234abcd1234abcd1234abcd",
      "recorded_at": "2026-10-09T09:30:00Z",
      "status": "done",
      "score": 77.3,
      "thumbnail_url": null
    }
  ]
}
```

`score`는 분석 결과의 `overall.score`이며 분석이 끝나지 않았거나 실패한 경우에는 `null`입니다.
`thumbnail_url`은 아직 썸네일 생성이 없어 `null`이며, 원본 영상은
`GET /api/analyses/{analysis_id}/video`에서 별도로 조회합니다.
`recorded_at`이 누락된 과거 분석은 목록 표시용으로 DB의 `created_at`(등록 시각)을 사용합니다.
반환 시각은 UTC ISO 8601 형식이므로 Flutter에서 `.toLocal()`로 표시해야 합니다.
전체 조회는 `GET /api/users/testuser01/swings`이며 `year_month`는 `null`입니다.
페이지 나누기는 아직 없으며 `count`는 반환된 `items` 개수입니다.

**보안 주의:** 현재는 JWT 인증이나 사용자별 소유권 검사가 없어 `user_id`는
조회 필터일 뿐 실제 로그인한 사용자임을 증명하지 않습니다.
서비스 외부 공개 전에 인증 및 본인 기록만 조회하도록 접근 제어를 추가해야 합니다.

## 3. 분석 흐름

```
POST /api/analyses  (multipart: video, handedness=right|left, user_id?, recorded_at?)
  → DB에 경로·메타데이터 기록 → Supabase Storage 업로드 → 기존 분석 또는 mock → DB 결과 저장
  → 202 { "analysis_id": "...", "status": "queued" }

GET /api/analyses/{id}   (1~2초 간격으로 폴링)
  → { "status": "processing", "stage": "tracking_player", ... }
  → { "status": "done", "result": { ... } }
  → { "status": "failed", "error": { "code": "...", "message": "..." } }
```

`stage` 값: `uploading` → `loading_models` → `reading_video` → `tracking_player` → `extracting_pose` → `building_features` → `comparing`
진행률 표시에 쓸 수 있습니다.

선택 form 필드 `user_id`는 기존 회원 ID, `recorded_at`은 시간대가 포함된 ISO 8601 촬영 시각입니다.
`user_id` 생략 시 DB의 사용자 관계는 null이고, `recorded_at` 생략 시 업로드 시각을 사용합니다.
존재하지 않는 회원 ID는 404입니다. 전체 결과 조회에는 `user_id`, `recorded_at` 두 필드만 추가되었습니다.
생성 응답은 `{analysis_id, status}`를 유지하며 `swing_id`로 바꾸지 않습니다.

영상 URL은 `GET /api/analyses/{id}/video`에서 필요할 때 발급받습니다. `expires_in`은 발급 시점 기준 초이며
기본 900초입니다. URL을 DB에 저장하지 않습니다. `.npy` 분석에는 원본 영상이 없으므로 영상 조회가 404입니다.
이 엔드포인트는 기존 API와 마찬가지로 토큰 인증이 없습니다. `user_id`는 관계 정보이지 인증 수단이 아닙니다.

### 에러 코드

| 코드 | 의미 | 사용자 안내 예시 |
|---|---|---|
| `INVALID_VIDEO` | 영상을 읽지 못함 | 다른 형식으로 다시 올려주세요 |
| `PLAYER_NOT_FOUND` | 타자를 찾지 못함 | 전신이 보이게 촬영해주세요 |
| `TRACKING_GAP_TOO_LONG` | 타자를 오래 놓침 | 가려짐 없이 촬영해주세요 |
| `POSE_NOT_DETECTED` | 관절 검출 실패 | 밝은 곳에서 다시 촬영해주세요 |
| `INTERNAL_ERROR` | 서버 오류 | 잠시 후 다시 시도해주세요 |
| `STORAGE_UPLOAD_FAILED` | 영상 저장 요청 실패/전송 결과 불확실 | 설정·연결을 확인하고 다시 업로드해주세요 |
| `SERVER_RESTARTED` | 해당 작업의 서버가 중단 후 재시작됨 | 영상을 다시 업로드해주세요 |

HTTP 상태: `404` 없는 분석 / `409` 아직 분석 중 / `415` 지원하지 않는 형식 / `413` 용량 초과(기본 200MB) / `422` 분석 실패

추가: `502` Storage 실패 / `503` DB 실패 또는 Storage 환경 설정 누락.
업로드 중 Storage 실패는 `detail: {analysis_id, code, message}`로 응답하며 해당 분석은 DB에 `failed`로 남습니다.
파일이 이미 전송되었거나 분석만 실패한 경우에는 영상과 경로를 유지하여 원인을 추적합니다.
기존 회원가입·로그인 요청은 계속 허용합니다. 로그인 ID 입력을 추가하고 Swagger의 이메일 이름을 `email`로 정리했습니다.
회원 응답과 기존 피드백 결과 구조·임시 점수 계산은 그대로 유지합니다.

영상 확장자는 `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`이며 대소문자를 구분하지 않습니다.
파일명에 경로(`/`, `\\`)를 포함하거나 MIME·컨테이너 헤더가 명백히 맞지 않으면 415입니다.
빈 파일은 422, 크기 초과는 413입니다. `application/octet-stream`은 확장자에 맞는 MIME으로 보정합니다.
헤더 검사는 전체 영상 디코딩 검사가 아닙니다. mock에서는 실제 타자/스윙 검출을 하지 않습니다.
Storage의 해당 파일이 없으면 `/video`는 404, Storage 장애·권한 오류는 502입니다.

## 4. 응답에서 꼭 확인할 필드

모든 피드백 섹션에 공통으로 들어갑니다.

| 필드 | 의미 | 화면 처리 |
|---|---|---|
| `model_version` | 비교 모델 버전 (현재 `"0.1"`) | 버전이 바뀌면 해석이 달라집니다 |
| `available` | 이 항목을 분석할 수 있었는지 | `false` 면 수치 대신 "분석 불가" 표시 |
| `reliability` | `high` / `medium` / `low` | `low` 면 "참고용" 배지 |
| `level` | `good` / `caution` / `warning` | 색상 구분 |

**null 허용 여부는 Swagger의 각 필드 schema를 따릅니다.** 선택 항목인 종합 점수·속도 수치 등은 null일 수 있습니다.
필수 관절 각도·그룹 점수까지 모두 null을 허용하는 것은 아닙니다. `available`도 함께 확인하세요.

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

- 회원·분석 결과·원본 영상 영속 저장은 구현했습니다. 설정은 [backend-setup.md](backend-setup.md)를 따릅니다.
- 로그인 토큰/소유자 권한 확인은 아직 없습니다. 공개 서비스 전에 회원 인증과 분석·영상 접근 제어가 필요합니다.
- Flutter 업로드에 `user_id` 연결, 실제 회원별 목록 조회 및 화면 연결은 별도 작업입니다. 이번 변경은 Flutter를 수정하지 않습니다.
- 분석 워커는 서버당 1개입니다. `SWING_WORKER_ID`당 uvicorn 프로세스 1개만 실행하세요.
  서버 재시작 시 그 서버의 미완료 작업만 실패로 기록합니다. 완료 결과는 유지하며 자동 재분석하지 않습니다.
- 스윙 추이 계산, 새 점수 체계, LLM 텍스트 피드백은 구현하지 않았습니다. 속도 placeholder도 그대로입니다.

## 8. 프론트 팀용 요청·응답 계약

### 회원가입

```http
POST /api/register
Content-Type: application/json
```

```json
{"id":"demo-user","password":"example-password","email":"demo@example.com","nickname":"demo"}
```

```json
{"id-uniqueness":1,"nickname-uniqueness":1,"registered":true}
```

`id`, `password`, `email`, `nickname`은 모두 필수이며 이 네 필드만 받습니다.
이메일 키는 `email`만 사용합니다. 필수 필드 누락이나 명세에 없는 필드는 422입니다.
ID·이메일·닉네임 중복은 HTTP 200과 `registered:false`입니다. ID/닉네임 중복이면 해당 uniqueness가 0입니다.
이메일만 중복된 경우 두 uniqueness는 1일 수 있으므로 반드시 `registered`를 확인하세요.
이메일 중복 여부는 `GET /api/check-email?email=demo%40example.com`으로 확인할 수 있습니다.
비밀번호는 bcrypt 한도에 맞게 UTF-8 기준 1~72바이트이며 초과/빈 문자열은 422입니다.

### 로그인

`POST /api/login` 요청:

```json
{"id":"demo-user","password":"example-password"}
```

응답:

```json
{"success":true,"user":"demo-user"}
```

`id`, `password`는 모두 필수이며 이 두 필드만 받습니다. 이메일 로그인은 지원하지 않습니다.
없는 회원/잘못된 비밀번호는 모두 401, 필수 필드 누락이나 명세에 없는 필드는 422입니다.
로그인은 JWT·세션을 발급하지 않습니다. 응답의 `user`는 사용자 ID입니다.

### 내 정보

`POST /api/me` 요청과 응답:

```json
{"user":"demo-user"}
```

```json
{"id":"demo-user","email":"demo@example.com"}
```

기존 계약을 유지합니다. 사용자 ID만으로 조회하므로 인증된 '나'임을 검증하는 API는 아직 아닙니다.
JWT 도입 때 소유자 접근 제어와 함께 개선할 항목입니다.

### 영상 업로드와 polling

`POST /api/analyses`는 JSON이 아니라 **multipart/form-data**입니다.

| 필드 | 예 | 필수 |
|---|---|---|
| `video` | 실제 mp4 파일 | 필수 |
| `handedness` | `right` 또는 `left` | 필수 |
| `user_id` | 로그인 응답의 `user` | 선택, 생략 시 null |
| `recorded_at` | `2026-10-04T11:10:00+09:00` | 선택, 생략 시 업로드 시각 |

촬영 시각은 UTC로 정규화합니다. 위 예시는 `2026-10-04T02:10:00Z`와 같습니다.
응답은 HTTP 202입니다:

```json
{"analysis_id":"<반환된 ID>","status":"queued"}
```

이 응답은 접수 확인입니다. 1~2초 간격으로 `GET /api/analyses/{analysis_id}`를 조회해 실제 상태를 확인하세요.
일반 모드는 `queued → processing → done` 또는 `failed`입니다.
mock은 `queued → done`으로 바로 저장되므로 첫 조회부터 done일 수 있습니다. `succeeded`/`completed`는 사용하지 않습니다.

전체 결과 조회 응답의 핵심 부분(나머지 피드백 필드는 앞 절 참조):

```jsonc
{
  "analysis_id":"<반환된 ID>", "user_id":"demo-user",
  "recorded_at":"2026-10-04T02:10:00Z", "status":"done", "stage":null,
  "created_at":"2026-10-04T02:11:00Z", "finished_at":"2026-10-04T02:11:01Z",
  "input":{"type":"video","filename":"swing.mp4","handedness":"right","suffix":".mp4","mock":true},
  "error":null,
  "result":{ /* model_version, overall, joints, phases, speed */ }
}
```

실패 시 `status:"failed"`, `result:null`, `error:{"code":"...","message":"..."}`입니다.
완료 전에 `/overall` 등 섹션 조회를 호출하면 409, 실패 작업의 섹션 조회는 422입니다.

### 영상 접근

`GET /api/analyses/{analysis_id}/video`:

```json
{"analysis_id":"<반환된 ID>","url":"<그때 발급된 signed URL>","expires_in":900}
```

`url`을 영상 플레이어에 전달합니다. 만료되면 이 API를 다시 호출하세요.
DB에 저장되는 값은 bucket·object path이며 URL은 저장하지 않습니다.
현재 모든 분석/영상 조회에는 토큰 기반 소유자 검증이 없으므로 공개 배포 전에 별도 보완이 필요합니다.

### 호환성 정리

회원 요청 명세를 단순화했습니다. 클라이언트는 가입 시 `email`, 로그인 시 `id`와 `password`만 사용해야 합니다.
가입 시 `e-mail` alias와 이메일 로그인은 제거했으며, 회원 응답 형식은 유지합니다.
사용자 ID 없는 업로드를 포함한 다른 API의 동작은 변경하지 않았습니다.
의도적으로 강화한 동작은 잘못된 영상·파일명·MIME 거부와 bcrypt 길이 제한입니다.
빈 내용이나 텍스트를 `.mp4`로 바꾼 파일은 mock에서도 더 이상 성공하지 않습니다.
LLM 텍스트·장기간 추이·새 구간 모델 API는 추가하지 않았습니다.
