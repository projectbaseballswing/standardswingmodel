# 피드백 최종 통합 검증 및 PR 준비

2026-11-24 · 기준 `origin/main 4e1ab160a90593eddcf462ead7aa7a96f9eebba3`

기존 간결화·최종 보완 결과를 유지하며 실제 신규 분석 비교를 검증했다. 이전 단계 기록은 [간결화 검토](feedback-concise-independent-review.md), [문구·측정 계약 검수](feedback-final-fixes.md)에 보존한다. 이 문서가 후속 검증 결과다.

## 실제 영상 분석 E2E

운영 Supabase를 사용하지 않고 새 SQLite DB, LocalPrivateStorage, FastAPI HTTP 서버로 실행했다. `SWING_MOCK=0`, `OPENAI_COACHING_ENABLED=0`, API 키·Supabase 설정은 빈 값이다. 기존 YOLO·MediaPipe와 기준 모델 0.2.3을 사용했고 추가 설치·학습은 없다.

| 항목 | 결과 |
|---|---|
| 회원가입·로그인 | 새 로컬 테스트 계정, 실제 API 인증 성공 |
| 친구 영상 1 | 실제 업로드·추론·저장 성공, 79.6점 |
| 친구 영상 2 | 실제 업로드·추론·저장 성공, 74.1점 |
| 계약 저장 | 두 결과의 `analysis_contract`를 HTTP 응답 및 별도 SQLite 연결로 확인 |
| 같은 계약 비교 | 동일 사용자 2번 기록에서 `has_previous=true`, `comparable=true`, 점수 차이 −5.5 |
| 첫 기록 | `has_previous=false`, `no_previous` |
| 원본 영상 | 저장 영상 조회 HTTP 200, 업로드 원본과 SHA-256 동일 |
| 3D | 두 기록 모두 HTTP 200, 실제 추출 World 기반 데이터 조회 |
| 추이용 목록 | done 상태 2건과 점수 유지 |
| 피드백 | 종합·관절·구간·속도·기준 동작 API HTTP 200 |
| GPT | 비활성화, `coaching=null`, `display_allowed=false` |
| 권한 | 비로그인 조회 401, 다른 테스트 계정의 분석·3D 조회 403 |

−5.5는 같은 계산 계약에서의 점수 차이다. 촬영 조건이나 실제 자세 악화·타격 성과 차이를 검증한 수치는 아니다. 친구 두 영상의 실제 새 분석은 우타이며, 좌타의 신규 영상 추론은 이번 추가 검증에서 수행하지 않았다.

다른 모델·기준 SHA·계산 SHA·계약 누락은 **실제 결과의 별도 복제 테스트 기록**을 만들어 HTTP로 검증했다. 4조건 모두 `has_previous=true`, `comparable=false`, 이전 ID 유지, 점수 증감·비교 코칭 차단을 확인했다. 이는 계약을 다르게 설정한 테스트이며, 서로 다른 모델을 실제로 재추론한 E2E라고 주장하지 않는다. 실제 생성한 원래 두 기록은 변경하지 않았다.

이번 E2E는 실제 HTTP API·파일 Storage·SQLite까지 검증했다. 실제 Flutter의 새 계정 로그인부터 업로드까지 연결한 브라우저 E2E나 PostgreSQL 운영 배포 검증은 아니다. 기존 31개 Chrome 화면 검증과 이번 Flutter 회귀 테스트를 별도로 사용한다. 운영 Supabase·기존 분석 기록에 접근하지 않았다.

## 골반 문구

친구 2의 기존 검토 사례는 다음 안내를 유지한다.

> 스윙을 마무리할 때 몸이 흔들리거나 뒤로 쏠려 보이는지 확인해 보세요.

이 문장은 팔로우스루에서 사용자가 관찰할 행동이다. 골반선 기울기만으로 실제 체중 이동·균형 이상을 판정하지 않는다. 상세 설명에 무게중심 미측정과 외관만으로 균형 문제를 확정하지 않는다는 한계를 유지하고, 연습은 원본에서 실제 균형 문제가 확인됐을 때만 제안한다. 이번에는 문장을 다시 늘리지 않고 해당 조건의 회귀 테스트를 추가했다.

새 0.2.3 분석의 우선 후보를 과거 문구 사례에 맞춰 바꾸지 않았다. 실제 모델의 후보와 과거 저장 리포트의 문구 검토를 구분한다. 프로 4개와 사람의 측정 정확성 평가는 여전히 미검토다.

## 자동 검증

| 항목 | 결과 / 한계 |
|---|---|
| Flutter analyze | 통과 |
| Flutter 전체 VM 테스트 | 358 통과, 6 제외 |
| 제외 중 웹 전용 3개 | 아래 Windows 경로 우회 환경에서 3개 모두 통과 |
| 나머지 VM 제외 3개 | 기존 P0/원본 모드 토글 테스트의 보류 정책 유지 |
| Flutter Web release | `lib/main.dart` 빌드 성공, API URL은 로컬 개발 서버 |
| 백엔드 전체 `tests/` | 359 통과, 2 제외 |
| 백엔드 제외 | 운영 Supabase opt-in 1개, OS 심볼릭 링크 생성 권한 없음 1개 |
| Android | 연결된 실기기·에뮬레이터 없음. 실기기 표시 미검증 |

백엔드 전체 테스트에는 인증·소유권, 비교, 점수 영향도, 저장·영상 삭제, 스윙 목록, 3D·미승인 GPT 차단·폴백 회귀가 포함된다. 계산·이벤트·기준 모델 파일은 main 대비 변경이 없다. 저장 리포트 6개와 기존 평가 자료는 보존한다.

### 웹 테스트 로딩 원인과 재실행

Flutter 3.44.9의 `flutter_web_platform.dart`는 CanvasKit 요청을 Windows 파일 경로로 변환한 뒤 `startsWith('canvaskit/')`를 검사한다. Windows의 역슬래시 경로가 이 검사와 맞지 않아 설치된 파일이 있어도 `/canvaskit/chromium/canvaskit.js`와 `.wasm`에 404가 발생했다. 브라우저의 네트워크 오류와 SDK 소스를 함께 확인했다. 따라서 원래 명령만 실행한 결과는 로딩 실패다.

SDK를 수정·업그레이드하지 않고 전용 테스트 브라우저의 해당 두 요청에 기존 SDK 파일을 그대로 제공했다. 제공한 파일의 SHA-256을 기록했다. 앱·테스트 본문·assertion은 변경하지 않았다. 이 환경에서 Blob 실패 시 저장 영상 재시도, 취소 시 Blob 해제, 결과 오류 시 Blob 해제 3개가 모두 실행·통과했다. 일반 Windows 명령이 수정됐다고 주장하지 않는다. Linux GitHub CI의 원래 웹 테스트 실행 결과를 별도로 확인해야 한다.

## 변경 파일 분류

기존 29파일과 이번 최종 문서 1개를 합해 PR 후보는 30파일이다. 이번 후속 검증에서 기존 코드에 추가한 변경은 골반 의미 회귀 테스트이며, 기능 구현은 이전 변경을 유지한다. 한 파일에 여러 범주가 함께 있는 경우 아래에 표시했다.

| 범주 | 파일 |
|---|---|
| 1. 문구·Flutter 표시 | `frontend/lib/data/feedback_language.dart`, `feedback_overview_text.dart` |
| 1. 종합·관절·구간 화면 | `frontend/lib/screens/overall_feedback_screen.dart`, `joint_analysis_screen.dart`, `phase_feedback_screen.dart` |
| 1. 표시 테스트 | `frontend/test/action_feedback_test.dart`, `action_feedback_ui_test.dart`, `feedback_language_test.dart`, `feedback_overview_text_test.dart` |
| 1. 검토 문서 | `docs/feedback-concise-independent-review.md`, `feedback-final-fixes.md`, `feedback-final-readiness.md` |
| 2. 측정 정의·짧은 구간 | `frontend/lib/data/feedback_measurement_contract.dart`, `feedback_phase_support.dart`, `feedback_guidance.dart`, `feedback/coaching_evidence.py` |
| 2. 측정·품질 테스트 | `frontend/test/model_v2_feedback_test.dart`, `tests/test_coaching_compact.py`, `test_coaching_review.py`, `test_llm_coach.py` |
| 2·3. 공통 계약 및 UI 매핑 | `feedback/report_contract.py`, `frontend/lib/data/feedback_repository.dart`, `frontend/lib/models/feedback.dart` |
| 2·3. 공통 회귀 테스트 | `tests/test_report_contract.py`, `frontend/test/feedback_contract_test.dart`, `feedback_repository_test.dart` |
| 3. 비교 저장·조회 | `api/jobs.py`, `api/schemas.py`, `api/swings.py`, `tests/test_comparison.py` |

PR에 포함하지 않는 자료: `.local/` 전체(실제 영상·분석 JSON·SQLite·3D·화면·로그·브라우저 프로필·환경 우회 도구), `.env`, 비밀번호·토큰·키, 원본 NPZ·모델 가중치, 빌드 결과 및 캐시. 기존 문서의 localhost 링크는 로컬 검토 자료이며 PR 첨부 파일이 아니다.

## 배포·리뷰 주의사항

1. 과거 결과에는 당시 기준/계산 식별 정보가 없어 이전 대비 비교가 보류된다. 과거 기록을 소급 변경하지 않는다. 새 계약을 저장한 호환 기록 두 건부터 비교할 수 있다.
2. 백엔드와 Flutter를 함께 배포해야 비교 보류 이유를 표시한다. API 필드 추가 자체는 호환적이나 구버전 Flutter에는 새 안내가 없다. DB migration은 없다.
3. 계산 소스 SHA는 보수적이다. 의미 없는 소스 서식 변경도 비교 보류를 만들 수 있다. 검증 없이 자동으로 같은 계약이라 간주하지 않는다.
4. 2프레임 간격 이하의 보류는 표현 정책이다. 이벤트 경계의 실제 정확도나 임계값의 임상·스포츠 과학적 타당성이 증명된 것은 아니다. 점수와 원본 신뢰도는 유지한다.
5. GPT 생성·승인 정책은 그대로다. 키만 설정해 자동 생성하거나 미승인 후보를 공개하지 않는다.
6. Android 실기기, PostgreSQL 운영 E2E, 독립 이벤트 경계 주석은 남아 있다. GitHub CI와 팀 코드 리뷰 확인 전에는 병합하지 않는다.

로컬 증거는 `.local/pr-readiness-20261124/`에 별도로 보관한다. 이전 `.local/feedback-final-fixes/` 자료는 덮어쓰지 않는다. PR은 코드와 문서만 올리고 main은 변경하지 않는다.
