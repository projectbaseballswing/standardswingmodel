# standardswingmodel

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
| GET | `/api/analyses/{id}/overall` | 종합 피드백: 유사도 점수, 그룹별 점수, 주요 문제점 |
| GET | `/api/analyses/{id}/joints` | 관절별 피드백: 각도 7개의 구간별/임팩트/움직임 폭 비교 |
| GET | `/api/analyses/{id}/phases` | 구간별 피드백: 준비/로딩/스윙/팔로우스루 템포와 유사도 |

회원 API(`/api/register`, `/api/login`, `/api/me`)와 같은 앱으로 묶여 있습니다. 진입점은 `api/main.py` 하나이고, 모든 경로가 `/api` 로 시작합니다.

코드 구조: `feedback/` (피처 정의, 템플릿 로딩, 비교 계산, 영상 파이프라인), `api/` (앱 조립, 회원·피드백 라우터, 작업 큐, 스키마, DB)

업로드의 `user_id`에 로그인 응답의 `user`를 넣으면 회원과 연결됩니다. 기존 클라이언트 호환을 위해 생략도 허용합니다.
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
