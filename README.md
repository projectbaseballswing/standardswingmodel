# standardswingmodel

## 피드백 API

사용자 스윙 영상을 전체 선수 기준 스윙 템플릿(`reference_templates.npz`의 `global_mean_template`)과 비교해서
종합 / 관절별 / 구간별 수치를 돌려줍니다.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server:app --reload   # 문서: http://127.0.0.1:8000/docs
.venv/bin/python -m pytest tests
```

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/analyses` | 영상 업로드(`video`, `handedness`) → 작업 등록 (202) |
| POST | `/api/analyses/features` | 추출된 피처 `.npy`로 바로 비교 (영상 처리 없이 테스트용) |
| GET | `/api/analyses/{id}` | 상태 + 전체 결과 |
| GET | `/api/analyses/{id}/overall` | 종합 피드백: 유사도 점수, 그룹별 점수, 주요 문제점 |
| GET | `/api/analyses/{id}/joints` | 관절별 피드백: 각도 7개의 구간별/임팩트/움직임 폭 비교 |
| GET | `/api/analyses/{id}/phases` | 구간별 피드백: 준비/로딩/스윙/팔로우스루 템포와 유사도 |

회원 API(`backend/`)와 같은 앱으로 묶여 있습니다. 진입점은 `server.py` 하나이고, 모든 경로가 `/api` 로 시작합니다.

코드 구조: `feedback/` (피처 정의, 템플릿 로딩, 비교 계산, 영상 파이프라인), `api/` (라우터, 작업 큐, 스키마), `server.py` (앱 조립)
