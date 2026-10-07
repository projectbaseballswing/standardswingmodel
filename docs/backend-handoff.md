# DB / Storage 인수인계 및 검증 결과

검증일: 2026-10-04. 대상은 `standardswingmodel` 백엔드이며 commit/push는 하지 않았다.
회원 요청 명세는 2026-10-05에 단순화했다. 아래 API 계약은 현재 명세이며 실제 Supabase 검증 기록은 2026-10-04 기준이다.
DB·영상·기존 분석 결과 영속화와 팀 환경 문서를 인수인계할 수 있는 상태다.
실제 Supabase 검증은 **SWING_MOCK=1**로 수행했다. 실제 스윙 영상의 모델 분석 성공을 의미하지 않는다.

## 1. 코드 점검 결과와 구현 범위

기존 회원 저장은 이미 SQLAlchemy + 로컬 `users.db` SQLite였다. 모든 회원이 메모리에만 있던 구조는 아니다.
분석 작업/결과는 프로세스 메모리에, 업로드 영상은 분석용 임시 파일에 의존했다.
기존 ORM과 분석 파이프라인을 유지하고 회원·분석 정보를 Supabase PostgreSQL로, 원본 영상을 private Storage로 연결했다.
기존 SQLite 회원을 Supabase로 자동 이전하는 작업은 포함하지 않는다.

| 항목 | 현재 구현 |
|---|---|
| 회원 | bcrypt 해시 저장. 이메일·닉네임 unique, ID primary key. 생성 시각 추가 |
| 회원/분석 관계 | `swings.user_id → users.id` FK. 선택 입력이며 생략 시 null; 없는 회원 ID는 404 |
| 인덱스 | 분석 PK, `user_id`, `worker_id`; 회원 ID/이메일/닉네임 고유 제약 |
| 시각 | PostgreSQL timezone-aware timestamp. `recorded_at`은 시간대 필수이며 UTC로 정규화 |
| 영상 원본 | private `swing-videos`, `swings/<analysis_id>/original.<ext>` |
| 분석 결과 | 기존 report를 `swings.result` JSONB에 저장. 별도 Feedback 테이블은 만들지 않음 |
| 일반 job | 프로세스 내부 ThreadPoolExecutor 1개 작업자. queued → processing → done / failed |
| mock | 무거운 분석만 생략. 영상·DB·샘플 결과는 실제 저장; queued → done |
| 업로드 응답 | 기존 202 `{analysis_id, status: "queued"}` 유지. 이후 GET 결과의 status가 현재 상태 |
| 재시작 | 동일 worker ID의 queued/processing을 failed / SERVER_RESTARTED로 기록. 완료 결과는 유지 |
| signed URL | video 조회 때 새로 발급. DB에는 URL 대신 bucket/path만 저장 |

성공 상태 이름은 `done`이다. `succeeded`/`completed`를 새로 추가하지 않았다.
`created_at`, `recorded_at`, `finished_at`으로 현재 API 요구를 충족하므로 `updated_at`은 추가하지 않았다.

## 2. DB schema

- `users`: `id` PK, `email` unique, `nickname` unique, `password_hash`, `created_at`.
- `swings`: `analysis_id` PK, nullable `user_id` FK, `recorded_at`, `video_storage_path`, `storage_bucket`,
  `video_size_bytes`, `content_type`, `worker_id`, `status`, `stage`, `created_at`, `finished_at`,
  `input`, `error`, `result`. 마지막 세 필드는 PostgreSQL JSONB이며 error/result는 nullable이다.
- `alembic_version`: 적용된 schema revision.

실제 DB current와 코드 head는 모두 **0002**였다. 이번 마무리에서 적용된 migration을 다시 쓰거나
실제 DB에 migration을 재실행하지 않았다. `users`/`swings` RLS가 활성화된 것도 확인했다.
이는 FastAPI의 사용자별 접근 권한 검사를 대신하지 않는다.

## 3. 실패 처리와 운영 조건

- 파일 크기, 확장자, MIME, 최소 컨테이너 헤더, 회원, 시간대 검증을 통과해야 저장한다.
  파일 전체 디코딩이나 실제 스윙 검출을 하는 검증은 아니다.
- DB에 예정 object path를 먼저 저장한다. 이 단계가 실패하면 Storage 업로드를 시작하지 않는다.
- Storage 실패는 failed / STORAGE_UPLOAD_FAILED로 기록하며 502를 반환한다.
  네트워크 타임아웃 뒤 원격 저장이 성공했을 수 있으므로 영상은 자동 삭제하지 않고 DB 경로로 추적한다.
- 분석 실패는 기존 오류 코드·메시지와 failed 상태를 기록한다. 원본 영상과 관계를 유지한다.
- 업로드 뒤 DB 장애가 지속되면 상태 갱신이 불가능하다. 연결 복구 후 **같은 worker ID로 재시작**하면
  미완료 기록을 failed로 정리한다. 자동 작업 재시도/재개는 없다.
- video 조회에서 없는 객체는 404, Storage 장애는 502다. DB 요청 실패는 503이다.
- 같은 worker ID로 여러 프로세스를 동시에 실행하지 않는다. 팀원별 ID는 달라야 하며 재시작 때 유지한다.
  `--workers 2` 이상의 실행은 지원하지 않는다.
- 정상 종료는 접수한 분석을 기다린다. 강제 종료 시 임시 파일은 남을 수 있다.
  DB/Storage 데이터 삭제와 실패 영상의 보관 기간 자동화는 구현하지 않았다.

## 4. API 계약과 호환성

- 회원가입은 `id`, `password`, `email`, `nickname` 네 필드만 받는다.
- 로그인은 `id`, `password` 두 필드만 받는다. 필수 필드 누락이나 명세에 없는 필드는 422다.
- 기존 회원가입·로그인 응답과 `POST /api/me {"user":"..."}` 형식은 유지한다.
- 영상은 기존 multipart `video`, `handedness`에 선택 필드 `user_id`, `recorded_at`을 추가했다.
- 분석 응답에 선택 정보 `user_id`, `recorded_at`을 추가하고 `GET /api/analyses/{analysis_id}/video`를 제공한다.
- 종합/관절/구간/속도 결과의 기존 형태를 유지한다. 속도 placeholder와 미구현 기능은 그대로다.

2026-10-05에 가입의 `e-mail` alias와 이메일 로그인을 제거했다. 클라이언트는 위 회원 요청 명세를 따라야 한다.
영상 검증은 그대로 유지한다. 텍스트를 mp4로 위장한 파일, 경로가 포함된 파일명,
잘못된 MIME 등은 거부한다. bcrypt 입력은 UTF-8 기준 1~72바이트로 검증하며 길이 초과는 가입 422/로그인 실패다.
새 DB 환경에는 migration이 필요하다. 상세 예제와 polling은 [API 가이드](api-guide.md)를 따른다.

2026-10-05 회원 요청 명세 정리 후 전체 pytest 결과는 **50 passed, 1 skipped, 1 warning (48.63초)**다.
Swagger 필드와 필수 여부, 제거한 요청의 422 응답, 기존 회원·분석 영속성 테스트를 포함한다.
skip은 명시적 opt-in이 필요한 실제 Supabase 테스트이며, 이번 명세 변경에서는 외부 E2E를 재실행하지 않았다.

## 5. 검증 결과 (2026-10-04)

| 검증 | 결과 |
|---|---|
| 기본 전체 pytest | 47 passed, 1 skipped, 1 warning (18.85초) |
| 실제 Supabase opt-in pytest | 1 passed (12.72초), 기본 suite에서 skip한 테스트를 별도 실행 |
| 독립 Supabase E2E 스크립트 | 성공, 서버 종료 후 새 프로세스에서 재조회까지 완료 |
| Python compileall | api / migrations / tests / 검증 스크립트 통과 |
| pip check | 의존성 충돌 없음 |
| git diff --check | 통과 |
| secret 검사 | Git 대상 텍스트 파일에서 실제 설정값 및 주요 secret 패턴 미검출; .env 미추적 |

warning 1개는 Starlette TestClient가 사용하는 HTTPX 관련 upstream deprecation이다.
기본 pytest는 격리된 SQLite와 가짜 Storage/HTTP transport를 사용하며 실제 Supabase를 변경하지 않는다.
추가 테스트는 회원 중복·동시 가입, 비밀번호 해시, 회원 요청 검증, FK/시간대, 업로드 검증,
Storage/DB/분석 실패, 실제 작업 상태 전이, 재시작, signed URL 경로를 다룬다.

실제 Supabase에서는 Uvicorn을 직접 실행하여 다음을 확인했다.

| 요청 / 확인 | 결과 |
|---|---|
| GET /api/health, /docs | 200, mock=true |
| POST /api/register | 200, users row와 bcrypt 해시 확인 |
| POST /api/login | ID 로그인 200; 잘못된 비밀번호·없는 회원 401 |
| POST /api/me | 200, 가입한 회원과 일치 |
| POST /api/analyses | 202 queued, 회원 FK·UTC 촬영 시각·영상 metadata 저장 |
| GET /api/analyses/{id} | 200, done, DB 결과와 API 결과 일치 |
| /overall, /joints, /phases, /speed | 모두 200, 속도 available=false 유지 |
| /video 및 발급된 URL 다운로드 | 200, private bucket, 원본과 다운로드 SHA-256 일치 |
| signed URL 저장 여부 | swings에 영구 저장되지 않음 |
| 서버 종료 후 새 서버 | 로그인·회원·동일 분석·동일 영상 재조회 성공 |

파일은 1,128,375바이트의 [MDN 공개 MP4 예제](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/video)를 사용했다.
스윙 영상이 아니며 Storage 전달 검증용이다. mock이므로 실제 YOLO/MediaPipe 추론은 실행하지 않았다.
일반 모드의 processing 전이는 모델 추출 부분을 대체한 자동 테스트에서 별도로 확인했다.

### 보존한 테스트 데이터

이번 검증으로 다음 2건씩의 회원·분석·Storage 객체를 생성했다. 기존 데이터와 테스트 데이터 모두 삭제하지 않았다.

| 실행 | user_id | analysis_id |
|---|---|---|
| 독립 E2E | `e2e_20261004_363a135c53` | `fb777def6faf41feb721db782b2e97f7` |
| opt-in pytest | `e2e_20261004_dc1b6b4440` | `29e2f4d308e24f75b212ac0163b33d17` |

각 영상 경로는 `swings/<위 analysis_id>/original.mp4`다. 임의 생성한 테스트 비밀번호는 공유·보고하지 않는다.
로컬 상세 보고서는 Git에서 제외된 `.venv/supabase-e2e-first.json`, `.venv/supabase-e2e-last.json`에 있다.
보고서는 식별자·상태·검증 결과만 담으며 secret과 signed URL은 담지 않는다.

## 6. 보안 확인과 남은 범위

비밀번호는 bcrypt 해시이고 `.env`는 Git에서 제외했다. 설정 객체 표현/DB 파라미터 로그에도 secret 노출을 줄였으며,
응답에는 DB 연결정보나 service key를 넣지 않는다. DB 요청은 ORM 바인딩을 사용한다.
사용자 파일명을 저장 경로로 쓰지 않고 분석 ID와 검증한 확장자로 경로를 만든다.

현재 로그인은 토큰을 발급하지 않으며 `user_id`는 소유권 인증 수단이 아니다.
분석 ID를 아는 요청자는 결과/영상 URL을 조회할 수 있다. **외부 공개 전 JWT 등 인증 및 소유자 접근 제어가 필요하다.**
CORS는 개발용 모든 origin 허용, credentials=false이며 배포 시 허용 도메인을 정해야 한다.

이번 담당 범위 완료: DB 저장, 원본 영상 저장, 기존 분석 결과 저장, Supabase 선택/연결,
팀 환경 재현 문서, mock 실제 통합 검증.
후속 통합 확인: 실제 스윙 영상 + 기존 무거운 분석 모델 실행, Flutter 담당자의 API 연결 확인.
별도 기능 범위: 새 구간 모델, LLM 텍스트, 장기간 스윙 추이, Flutter UI.
팀에서 결정할 운영 범위: 인증/권한, 배포, 백업·보관/삭제 정책, 작업 재시도/다중 worker 필요 여부.

## 7. 팀원에게 전달할 파일과 실행법

- [README](../README.md): 진입 안내.
- [환경 설정](backend-setup.md): Supabase / .env / requirements / migration / PowerShell 실행 / 검증.
- [API 계약](api-guide.md): Flutter 요청·응답, 상태 polling, 영상 URL 갱신.
- `.env.example`, `requirements-api.txt`, `alembic.ini`, `migrations/`: 재현에 필요한 설정과 schema.
- `api/`, `tests/`, `scripts/verify_supabase.py`: 구현과 자동 검증. 실제 `.env`와 `.venv`는 공유하지 않는다.

```powershell
# standardswingmodel 저장소 루트, 가상환경 활성화 후
python -m pip install -r requirements-api.txt
# .env에 승인된 팀 설정 입력. 기존 .env를 덮어쓰지 않는다.
python -m alembic upgrade head
$env:SWING_MOCK="1"
python -m uvicorn api.main:app --port 8000
```

Swagger: `http://127.0.0.1:8000/docs`.
현재 로컬 상태는 DB/Storage 범위의 commit/PR 리뷰를 준비할 수 있다. 아직 commit/push하지 않았고 새 파일도 untracked다.
실제 secret은 코드/문서/Flutter에 넣지 말고 팀의 승인된 비공개 경로로만 전달한다.
