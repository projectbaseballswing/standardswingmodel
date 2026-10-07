# 백엔드 DB·영상 저장 설정

대상 저장소는 `standardswingmodel`입니다. 기존 FastAPI/SQLAlchemy와 영상 분석 워커를 사용합니다.
팀 환경은 Supabase PostgreSQL + private Supabase Storage입니다. `.env`는 공유 저장소에 올리지 않습니다.

## 1. Supabase에서 준비할 것

1. 팀 프로젝트를 생성하거나 기존 팀 프로젝트의 접근 권한을 받습니다. 같은 팀 DB를 쓸 경우 새 프로젝트를 만들 필요는 없습니다.
2. **Connect**에서 PostgreSQL 연결 문자열을 확인합니다. 일반 서버는 Direct connection 또는
   **Session pooler의 5432 포트**를 사용합니다. IPv4 PC에서는 Session pooler를 사용하세요.
   이 안내는 transaction pooler(6543)를 대상으로 하지 않습니다.
3. 연결 문자열의 스킴을 `postgresql+psycopg://`로 지정하고 SSL 옵션 `?sslmode=require`를 포함합니다.
   비밀번호의 `@`, `:`, `/`, `%`, `#` 등 특수문자는 URL 인코딩해야 합니다. 비밀번호를 터미널 명령/로그에 출력하지 마세요.
4. 프로젝트 URL과 **서버 전용 service_role 키**를 확인합니다. publishable/anon 키로 대체하지 않습니다.
   이 키와 DB 비밀번호는 서버 `.env`에만 보관하며 Flutter 코드나 앱 빌드에 포함하지 않습니다.
5. Storage에서 `swing-videos`라는 **private bucket**을 생성합니다. 다른 이름을 쓰면 환경변수도 맞춥니다.
   프로젝트·bucket 업로드 한도와 `SWING_MAX_UPLOAD_MB`를 맞추세요. 프로젝트 한도가 더 작으면 서버 설정도 낮춥니다.
   MIME 제한을 사용할 경우 `video/mp4`, `video/quicktime`, `video/x-msvideo`, `video/x-matroska`, `video/x-m4v`를 허용합니다.
6. 파일은 백엔드 service role로만 업로드·서명합니다. 일반 클라이언트에 bucket 쓰기 권한을 열 필요가 없습니다.

회원은 기존 `public.users`와 bcrypt를 유지합니다. **Supabase Auth로 회원 체계를 교체하지 않았습니다.**
SQLAlchemy는 PostgreSQL에 직접 접속하고, Storage만 기존 의존성인 HTTPX로 REST API를 호출합니다.
Migration은 `users`, `swings`에 RLS를 활성화하며 클라이언트용 정책을 만들지 않습니다.
DB 연결 계정은 migration/백엔드 실행 권한이 있는 서버 계정이어야 합니다.

공식 참고: [Postgres 연결](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Storage 접근 제어](https://supabase.com/docs/guides/storage/security/access-control),
[Storage REST API](https://supabase.com/docs/reference/self-hosting-storage/introduction).

## 2. 환경변수

저장소 루트에서 `.env.example`을 `.env`로 복사한 뒤 값을 입력합니다. 기존 `.env`는 덮어쓰지 마세요.
환경변수가 이미 설정되어 있으면 `.env`보다 우선합니다. `.env`는 실행 디렉터리와 무관하게 저장소 루트에서 읽습니다.

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | Supabase PostgreSQL 서버 접속 문자열. 필수, 기본 SQLite 자동 대체 없음 |
| `SUPABASE_URL` | `https://`로 시작하는 팀 프로젝트 URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버 전용 service_role 키 |
| `SUPABASE_STORAGE_BUCKET` | private bucket 이름, 예제는 `swing-videos` |
| `SUPABASE_SIGNED_URL_SECONDS` | 영상 URL 유효기간, 기본 900초 |
| `SWING_MOCK` | `1`이면 분석만 fixture로 대체. DB·Storage는 실제로 사용 |
| `SWING_MAX_UPLOAD_MB` | 영상 업로드 제한, 기본 200 MiB. 실제 Storage 한도도 적용 |
| `SWING_WORKER_ID` | 서버마다 다르고 재시작에도 유지되는 값. 빈 값은 호스트명 |

기존 모델 설정 `SWING_TEMPLATE_PATH`, `SWING_YOLO_WEIGHTS`, `SWING_POSE_MODEL`, `SWING_REFERENCE_FPS`도 유지합니다.
원본 모델 경로 기본값은 `modules/dtw_reference_template/reference_templates.npz`,
`weights/custom_yolo_model5.pt`, `models/pose_landmarker.task`입니다.
`SWING_MAX_JOBS`는 결과를 메모리에서 삭제하는 이전 설정이므로 더 이상 사용하지 않습니다.

같은 DB를 여러 팀원이 사용할 때 각자의 `SWING_WORKER_ID`를 다르게 설정하세요.
**같은 worker ID로 두 서버를 동시에 켜거나 `--workers 2` 이상으로 실행하지 않습니다.**
새 프로세스는 같은 worker ID의 미완료 작업을 이전 서버의 중단 작업으로 판단합니다.

## 3. 설치와 migration

새 가상환경에서 설치합니다. 일반 분석은 전체 requirements, mock/피처 API만 사용할 때는 작은 requirements를 사용합니다.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt
# 실제 YOLO/MediaPipe 분석도 실행할 때는 python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 편집기로 .env의 실제 값 입력
python -m alembic upgrade head
python -m alembic current
```

활성화 스크립트 실행이 제한된 PC에서는 실행 정책을 바꾸지 않고
`.\.venv\Scripts\python.exe -m pip ...`, `.\.venv\Scripts\python.exe -m uvicorn ...` 형태로 실행해도 됩니다.

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# .env 편집 후
python -m alembic upgrade head
```

팀 DB에는 담당자 한 명이 migration을 먼저 적용합니다. 서버는 자동으로 `create_all`을 실행하지 않습니다.
새 테이블/컬럼 변경은 migration 파일로 공유하고 다른 팀원도 서버 코드와 schema 버전을 맞춥니다.
새 DB에는 `upgrade head`만 실행하면 됩니다. `stamp`로 테이블 생성을 건너뛰지 마세요.

**기존 `users.db`를 그대로 사용해 확인할 경우에만:** `DATABASE_URL`을 해당 SQLite 파일의 절대 경로로 지정하고,
기존 스키마가 `id`, `email`, `nickname`, `password_hash`인 것을 확인한 뒤 `alembic stamp 0001`,
`alembic upgrade head` 순서로 실행합니다. 기존 회원을 보존하며 `created_at`은 migration 시각으로 채웁니다.
기존 SQLite 회원을 Supabase로 자동 복사하지는 않습니다. 필요하면 별도 데이터 이전 작업이 필요합니다.

## 4. 서버 실행

일반 실행:

```powershell
$env:SWING_MOCK="0"
uvicorn api.main:app --port 8000
```

PowerShell mock 실행:

```powershell
$env:SWING_MOCK="1"
python -m uvicorn api.main:app --port 8000
```

macOS/Linux mock 실행:

```bash
SWING_MOCK=1 uvicorn api.main:app --port 8000
```

Swagger는 `http://127.0.0.1:8000/docs`, 상태 확인은 `http://127.0.0.1:8000/api/health`입니다.
개발 중 `--reload`를 사용하면 코드 변경으로 진행 중 분석이 중단될 수 있습니다.

## 5. Swagger와 Supabase에서 실제 확인

1. `POST /api/register`에 `id`, `password`, `email`, `nickname` 네 필드만 입력합니다.
   Supabase Table Editor의 `users`에서 회원과 생성 시각을 확인합니다. 평문 비밀번호는 저장하지 않습니다.
2. `POST /api/login`에 `id`, `password` 두 필드만 보내 로그인하고 `user`를 기억합니다.
   `POST /api/me`에 `{"user":"로그인에서 받은 값"}`을 보내 조회합니다.
3. `POST /api/analyses`에서 `video` 파일, `handedness=right|left`, 선택 `user_id`를 입력합니다.
   촬영 시각이 있으면 `recorded_at`에 `2026-10-03T14:00:00+09:00`처럼 시간대도 입력합니다.
4. 202 응답의 `analysis_id`로 `GET /api/analyses/{analysis_id}`를 조회합니다.
   mock은 이미 `done`, 일반 모드는 `queued`/`processing` 후 `done` 또는 `failed`입니다.
5. Storage에서 `swings/<analysis_id>/original.mp4` 등의 객체를 확인합니다.
   `swings` 테이블에서 사용자 관계, 경로, 메타데이터, 상태, 결과 JSON을 확인합니다.
6. `/overall`, `/joints`, `/phases`, `/speed`를 조회합니다. 기존 결과와 속도 `available=false`를 확인합니다.
7. `/video`를 호출하고 반환된 `url`을 브라우저에서 열어 원본 영상이 재생/다운로드되는지 확인합니다.
   만료되면 `/video`를 다시 호출합니다. URL은 DB에 저장되지 않습니다.
8. 서버를 종료하고 **같은 DB·Storage 설정**으로 재시작합니다. 다시 로그인하고 같은 분석 ID로 결과·영상 URL을 조회합니다.
9. 일반 모드에서는 실제 영상 분석도 반복 확인합니다. mock 성공은 YOLO/MediaPipe 분석 성공을 의미하지 않습니다.

테스트 suite:

```powershell
python -m pytest tests -q
```

자동 테스트는 별도 임시 SQLite DB와 Storage fake/HTTP MockTransport를 사용합니다.
외부 Supabase나 실제 모델 가중치를 호출하지 않습니다. 실제 외부 DB·Storage 동작은 위 Swagger 절차로 따로 확인해야 합니다.

Windows의 공용 pytest 임시 폴더에 접근 오류가 있는 환경에서는 저장소 안의 **새 경로**를 지정하세요:

```powershell
python -m pytest tests -q --basetemp ".venv/pytest-$([guid]::NewGuid().ToString('N'))"
```

`--basetemp`는 해당 디렉터리를 정리할 수 있으므로 기존 데이터가 있는 경로를 지정하지 않습니다.

## 6. 저장 schema와 실패 처리

| 테이블 | 내용 |
|---|---|
| `users` | 기존 `id`, `email`(unique), `nickname`(unique), `password_hash` + `created_at` |
| `swings` | `analysis_id` PK, nullable `user_id` FK, `recorded_at`, bucket·object path·크기·MIME, worker ID, 상태·단계·시각, 입력·오류·결과 JSONB |
| `alembic_version` | 적용된 migration 버전 |

하나의 업로드와 분석이 1:1이므로 별도 Feedback 테이블을 만들지 않았습니다.
종합 점수, 관절별·구간별 결과, 모델 버전, 품질 정보, 시계열을 기존 report 그대로 JSONB에 저장합니다.
새 점수 계산/평균 집계/LLM 텍스트를 추가하지 않습니다. signed URL과 영상 바이너리는 DB에 넣지 않습니다.

object path는 `swings/<analysis_id>/original<확장자>`입니다. 사용자 파일명을 경로로 쓰지 않아 같은 이름도 충돌하지 않습니다.
사용자 관계는 DB FK로 관리합니다. 사용자 ID 생략 시 null이며 임의의 회원 계정을 만들지 않습니다.

- 확장자·용량·빈 파일·사용자·시각 검증 실패: DB 행과 Storage 객체를 만들지 않습니다.
- 컨테이너 헤더와 MIME도 확인합니다. 이 검사는 영상 전체 디코딩이나 스윙 검출을 대신하지 않습니다.
- DB 등록 실패: Storage 업로드를 시작하지 않습니다.
- Storage 요청 실패: `failed` / `STORAGE_UPLOAD_FAILED`와 예정 경로를 남깁니다.
  타임아웃은 원격 저장 성공 여부가 불확실하므로 해당 객체가 남을 수 있으며, DB 경로로 추적합니다.
- 분석 실패: 원본을 유지하고 기존 분석 오류 코드와 `failed` 상태를 저장합니다.
- 업로드 후 DB 연결 실패: 먼저 기록한 행과 경로가 남습니다. 연결 복구 후 같은 worker ID로 재시작하면
  미완료 행을 `failed` / `SERVER_RESTARTED`로 정리합니다. 자동 재시도는 하지 않습니다.
- 정상 종료: 이미 접수한 분석을 끝낸 뒤 종료합니다. 임시 영상은 처리 완료/요청 실패 시 삭제합니다.
- 강제 종료: 다음 시작에서 자기 worker의 미완료 작업만 실패 처리합니다. OS 임시 파일은 강제 종료 시 남을 수 있습니다.
  완료된 DB 결과와 Storage 원본은 유지합니다. 실패 영상의 삭제/보관 기간 자동화는 아직 없습니다.

DB와 Storage 사이에는 하나의 트랜잭션이 없습니다. 이번 규모에서는 업로드 전에 DB에 경로를 확정하는 방식으로
추적 불가능한 객체를 예방합니다. 전송 결과가 불확실할 때 자동 삭제하면 실제 성공한 영상을 잃을 수 있어 삭제하지 않습니다.
DB 장애가 지속되는 동안 상태 기록도 불가능하며, 연결 복구 후 같은 worker ID로 재시작해야 미완료 행이 정리됩니다.
`created_at`, `recorded_at`, `finished_at`과 현재 상태를 저장하며, 아직 수정 API/변경 이력 기능이 없어 `updated_at`은 추가하지 않았습니다.

## 7. 현재 범위와 팀 공유 사항

기존 로그인 응답은 토큰 없이 `user` ID만 반환합니다. `user_id` 입력은 회원 연결용이며 소유자 인증이 아닙니다.
기존 API 호환을 유지했으므로 분석 ID를 아는 사람이 결과·영상 URL을 조회할 수 있습니다.
외부 공개 전에는 인증 토큰과 소유자 접근 제어를 별도로 붙여야 합니다.

Flutter에는 변경이 없습니다. 기존 영상 업로드는 계속 동작하지만 회원 연결을 사용하려면 담당자가 `user_id`를 보내야 합니다.
스윙 목록 UI의 임시 데이터, 추이 계산, LLM 피드백, 새 모델은 이번 작업에서 변경하지 않았습니다.
팀에는 `.env.example`, migration, 두 requirements 파일, 이 문서를 공유하고 실제 secret은 승인된 비공개 경로로 전달하세요.

현재 CORS는 개발 편의를 위해 모든 origin을 허용하며 쿠키 credentials는 허용하지 않습니다.
실제 배포 때 프론트 도메인으로 제한하세요. 현재 사용자 조회·영상 조회를 보호하는 인증 정책은 아닙니다.

## 8. 실제 Supabase 자동 검증

검증 전에 저장소를 clone하고 `cd standardswingmodel`에서 앞 절의 설치·환경 설정을 끝내세요.
이 작업은 **실제 DB에 테스트 회원과 분석 1건, Storage에 영상 1개를 생성**합니다.
`e2e_...` ID로 구분하며 기존 데이터·신규 테스트 데이터 모두 자동 삭제하지 않습니다.
별도 포트와 고유 worker ID로 mock 서버를 두 번 실행해 재시작 영속성까지 확인하고 서버를 종료합니다.

```powershell
$env:RUN_SUPABASE_INTEGRATION_TESTS="1"
$env:SUPABASE_TEST_VIDEO="C:\영상폴더\작은영상.mp4"
python scripts/verify_supabase.py --video $env:SUPABASE_TEST_VIDEO
```

선택적으로 pytest에서도 같은 검증을 실행할 수 있습니다:

```powershell
python -m pytest tests/test_supabase_integration.py -q
Remove-Item Env:RUN_SUPABASE_INTEGRATION_TESTS
Remove-Item Env:SUPABASE_TEST_VIDEO
```

기본 전체 pytest에서는 이 테스트를 skip합니다. opt-in이어도 연결 설정/영상 경로가 없으면 skip합니다.
실제 키/비밀번호는 `.env`에서 읽으며 테스트 코드에 쓰지 않습니다.
보고서는 `.venv/supabase-e2e-last.json`이며 생성된 테스트 ID·상태·검사 결과만 저장합니다.
비밀번호·service key·signed URL은 출력하거나 보고서에 저장하지 않습니다.
스크립트는 migration을 실행하지 않으며 현재 revision과 head가 같은지 읽어서 검사합니다.
실패 후 재실행하면 새 테스트 데이터가 추가될 수 있으므로 남긴 보고서의 ID를 확인하세요.
