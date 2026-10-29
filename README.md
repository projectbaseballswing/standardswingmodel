# standardswingmodel

## 사용자별 3D 스윙

로그인 후 업로드한 영상의 기존 점수·피드백에서 **3D 스윙 보기**를 열 수 있습니다.
실제 World 추정 좌표에 P2/S2 표시 처리를 한 뒤 Flutter가 O1/F1/H4를 적용합니다.
원본/P0 비교, 재생·배속·탐색·카메라 조작과 품질 경고를 제공합니다. 샘플 대체는 없습니다.

기존 회원과 분석은 `public`에서 그대로 사용합니다. 로그인 토큰을 보호 API의
`Authorization: Bearer <access_token>` 헤더로 보내야 합니다. Flutter와 API를 함께 배포하세요.
운영 `0002 → 0003` migration은 [영향·백업·롤백 계획](docs/swing-3d-migration.md)을 검토하고
승인받은 뒤 실행해야 합니다. 아래 일반 개발 명령을 운영 DB에 바로 실행하지 마세요.

[통합 결과·검증 한계](docs/swing-3d-integration.md) · [좌표 계약](docs/swing-3d-pipeline.md)

## 피드백 API

사용자 스윙 영상을 전체 선수 기준 스윙 템플릿(`reference_templates.npz`의 `global_mean_template`)과 비교해서
종합 / 관절별 / 구간별 수치를 돌려줍니다.

```bash
pip install -r requirements.txt
cp .env.example .env           # 실제 DB/Storage 값은 .env에만 입력
alembic upgrade head          # .env 설정 후 실행
uvicorn api.main:app --port 8000   # 문서: http://127.0.0.1:8000/docs
python -m pytest tests
```

(가상환경을 쓴다면 먼저 `python3.12 -m venv .venv && source .venv/bin/activate`)

**처음 실행하는 팀원은 [DB·Storage 설정 안내](docs/backend-setup.md)를 먼저 확인하세요.**
Supabase PostgreSQL에 회원·분석 결과를 저장하고, private Storage bucket에 원본 영상을 저장합니다.
DB schema는 Alembic으로 관리합니다. 서버 실행만으로 테이블을 생성하지 않습니다.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt  # mock/피처 API용
Copy-Item .env.example .env     # 처음 한 번만. 기존 .env를 덮어쓰지 마세요.
# .env에 팀에서 전달받은 DATABASE_URL과 Supabase 설정 입력
python -m alembic upgrade head
$env:SWING_MOCK="1"
python -m uvicorn api.main:app --port 8000
```

mock 실행은 `requirements-api.txt`만 설치해도 됩니다. mock에서도 DB와 Storage는 실제로 사용합니다.

```powershell
$env:SWING_MOCK="1"
python -m uvicorn api.main:app --port 8000
```

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/analyses` | 영상 업로드(`video`, `handedness`) → 작업 등록 (202) |
| GET | `/api/analyses/{id}` | 상태 + 전체 결과 |
| GET | `/api/analyses/{id}/video` | 원본 영상의 만료되는 signed URL 발급 |
| GET | `/api/analyses/{id}/pose-3d` | 본인 분석의 3D 표시 좌표 또는 생성 상태·실패 원인 |
| GET | `/api/analyses/{id}/overall` | 종합 피드백: 유사도 점수, 그룹별 점수, 주요 문제점 |
| GET | `/api/analyses/{id}/joints` | 관절별 피드백: 각도 7개의 구간별/임팩트/움직임 폭 비교 |
| GET | `/api/analyses/{id}/phases` | 구간별 피드백: 준비/로딩/스윙/팔로우스루 템포와 유사도 |

회원 API(`/api/register`, `/api/login`, `/api/me`)와 같은 앱으로 묶여 있습니다. 진입점은 `api/main.py` 하나이고, 모든 경로가 `/api` 로 시작합니다.

코드 구조: `feedback/` (피처 정의, 템플릿 로딩, 비교 계산, 영상 파이프라인), `api/` (앱 조립, 회원·피드백 라우터, 작업 큐, 스키마, DB)

업로드 소유자는 서버가 검증한 로그인 토큰으로 결정합니다. `user_id`는 생략 가능하지만,
보내는 경우 토큰 소유자와 일치해야 합니다. 로그인 응답의 `user`만으로 인증할 수 없습니다.
식별자는 기존 `analysis_id`를 유지합니다. 추이·LLM 피드백·새 분석 모델은 이번 영속 저장 변경에 포함하지 않습니다.

회원가입은 `id`, `password`, `email`, `nickname`만 받고, 로그인은 `id`, `password`만 받습니다.
명세에 없는 필드나 필수 필드가 빠진 요청은 422입니다.

`POST /api/register`:

```json
{"id":"demo-user","password":"example-password","email":"demo@example.com","nickname":"demo"}
```

`POST /api/login`:

```json
{"id":"demo-user","password":"example-password"}
```

실제 영상 분석은 `requirements.txt`를 설치하고 `SWING_MOCK=0`으로 실행하세요.

자동 테스트는 `python -m pytest tests -q`로 실행합니다. 실제 Supabase 테스트는 기본으로 건너뛰며,
[환경 문서의 opt-in 검증 절차](docs/backend-setup.md#8-실제-supabase-자동-검증)를 따릅니다.
구현 범위·확인 결과·남은 작업은 [백엔드 인계 기록](docs/backend-handoff.md)을 참고하세요.
