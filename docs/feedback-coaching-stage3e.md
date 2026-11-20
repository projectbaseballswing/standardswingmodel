# StandardSwing 3-E — 코칭 통합 및 개발환경 검증

이 문서는 초기 3-E 검증 기록이다. 후속 최소 UI 변경, 웹 전용 3개 재검증 및 최신 PR 준비 판단은 [최종 검수 보고서](feedback-coaching-final-review.md)에 정리했다.

3-A의 규칙 기반 안내와 3-C의 근거 입력·출력 검사를 최신 main에 통합했다. GPT 생성 성공만으로 사용자에게 노출하지 않고, 검토 승인된 정확한 응답만 표시한다. 이번 단계에는 OpenAI 호출, 운영 Supabase 접근, migration, commit/push/PR/병합을 수행하지 않았다.

## 작업 기준과 보존

- 작업 공간: `C:\Users\DO\project\team\swing-feedback-stage3e`
- 브랜치: `feat/feedback-coaching-integration`
- 시작 기준: `origin/main` `42eacc2` (구간별 피드백 시각화 PR #84 포함).
- 3-A/B/C/D의 HEAD·git status와 변경 파일/주요 로컬 실험 결과 해시를 확인한다. 기존 one-shot 실행 기록과 A/B 원문은 읽기만 한다.
- `compare_v2.py`, `swing_features.py`, 분석 fixture, 인증·Storage·3D·라우터·추이 코드는 변경하지 않았다. 점수와 좌표 추론을 수정하지 않고 코칭 선택·표시 경로만 통합했다.
- 최신 main의 구간 영상 플레이어와 주요 차이 막대 그래프를 유지했다. 3-A 파일 전체를 main에 덮어쓰지 않았다.

## 통합한 내용

### 근거 입력과 규칙 안내

관절·부위·구간의 사용 가능 여부와 신뢰도를 확인한다. 검증된 관절/구간의 표준화 차이 `|z|`로 우선 확인 후보를 정하고, 동일 관절의 중복 후보를 줄인다. 이는 종합점수 감점 기여도나 실제 교정 효과의 순위가 아니다. 부위 점수는 부위 안의 모든 구간이 안정적이라는 뜻으로 쓰지 않는다.

종합점수의 구성점수가 실제로 맞을 때만 자세 70% + 속도 30%를 설명한다. 과거 리포트에 구성점수나 신뢰도가 부족하면 산식을 추정해 채우지 않는다. 속도 점수는 손 속도 기반 지표이며 배트/타구 속도가 아니다. 부위 점수 평균을 종합점수로 설명하지 않는다.

화면은 잘한 구간, 가장 먼저 확인할 동작, 원본에서 볼 내용, 작은 조절, 확인 연습 순서로 안내한다. 점수 산식·측정 해석·우선순위의 한계는 펼쳐 보는 상세 근거로 분리한다. 규칙 문구는 GPT로 표시하지 않는다.

### 3-D에서 확인한 7개 문제

| 문제 | 변경 | 검증 한계 |
|---|---|---|
| 구간 평균을 순간 목표로 해석 | 프롬프트에 평균/순간의 차이 명시, `average_as_exact_target` 검토 신호, 원본 구간 확인 안내 | 새 GPT 응답의 개선 여부는 아직 평가하지 않음 |
| 비교자료 미제공을 과거 기록 부재로 단정 | `previous_report_not_provided` 유지, `history_absence_not_confirmed` 검사 | 실제 이력 유무는 API 조회 범위에 따라 별도 판단 |
| 정규화 수치가 일반 문구에 노출 | 사용자 문구에서는 동작 의미로 설명, 상세 측정 화면에 분리, 노출 검토 신호 | 자연스러움과 이해도는 사람 평가 필요 |
| 좋은 부위 점수로 문제 구간 누락 | 좋은 구간과 문제 구간 근거를 함께 보존, `part_adverse_phase_omitted` 검사 | 강점/문제 균형을 자동으로 완전히 보장하지 않음 |
| `diff`/`z` 부호 차이로 과도한 제외 | 부호 일치 조건 제거. 평균 차이와 시점별 표준화 차이 평균을 구분 | 수치 일관성·신뢰도 검사는 유지 |
| `range_of_motion` 누락 | ROM의 실제 `user/reference/diff` 계약으로 전달 | 존재하지 않는 ROM `z`/등급은 만들지 않음 |
| 부정문 오탐 | 개념/절 단위 부정 범위를 검사. 단순 문장 전체 면제는 하지 않음 | 복합 문맥의 오탐·미탐 가능, 의미 검토 필수 |

대표 fixture에서 `hip_shoulder_separation.follow`의 유효 근거 한 건과 ROM 15건을 복원했다. 원본 리포트의 숫자는 바꾸지 않았다.

### 서비스 검토 상태

| 상태 | GPT 원문 공개 | 화면 |
|---|---|---|
| `approved` + 해시/컨텍스트/정책 일치 | 허용 | 검토 완료 GPT 코칭 |
| `review_required` | 차단 | 검토 대기 안내 + 규칙 문구 |
| `blocked` | 차단 | 코칭 검증 차단 안내 + 규칙 문구 |
| `generation_failed` | 없음 | 생성 불가/미생성 안내 + 규칙 문구 |

비공개 후보는 기존 `Swing.result` JSON의 `_coaching_review`에 저장하고 API 응답에서 제거한다. 공개 JSON에는 `coaching_review` 상태만 추가한다. 기존 Coaching JSON 필드·형태는 유지한다. 승인 없는 과거 GPT 원문도 DB에서 삭제하지 않고 표시만 보류한다.

Flutter도 `approved`, `display_allowed=true`, `source=openai`를 모두 요구한다. 비교 코칭은 현재·이전 분석 ID와 각 근거에 묶이며, 비교 GET은 새 GPT를 생성하거나 DB를 변경하지 않는다. 후보/분석/정책 버전이 바뀌면 재검토한다. 확장 코칭을 새로 병합해도 이전 승인을 재사용하지 않는다.

승인 HTTP API는 추가하지 않았다. 권한 있는 운영자용 순수 함수와 저장 설계만 제공한다. 실제 관리자 인증·권한·감사·잠금 기반 저장 도구는 서비스 공개 전에 필요하다. 상세 절차는 [검토 생명주기](coaching-review-lifecycle.md)를 참고한다.

## 입력 압축

중복 관절·구간 정보를 한 번 저장하고 근거 ID로 참조한다. 컬럼 이름이 있는 측정값 표와 공통 메타데이터를 사용하며, 복원 함수로 전체 구조의 동등성을 검사한다. 입력 근거를 줄이는 요약이 아니다.

| 대표 fixture 기준 | 크기 |
|---|---:|
| 3-D B 기존 JSON | 76,515 bytes |
| 누락 근거를 복원한 3-E 전체 JSON | 78,044 bytes |
| 3-E 압축 전송 JSON | 19,912 bytes |
| 기존 JSON 대비 감소 | 73.98% |
| 시스템 프롬프트 + JSON 기준 감소 | 66.12% |

기존 B의 27,252 입력 토큰은 실제 과거 사용량이다. 새 토크나이저를 설치하거나 GPT를 호출하지 않았으므로 **새 토큰 수·비용·응답시간 감소율은 미측정**이다. 표의 크기는 UTF-8 기준이며 API wrapper/JSON schema는 시스템+입력 비교에 포함하지 않는다.

6개 리포트의 overall/full 근거를 압축 후 복원했을 때 전체 데이터 구조가 동일했다. 유효 근거가 없는 작은 `fixture_v2`는 참조 안내의 고정 비용으로 2,932→3,320 bytes로 증가한다. 이 경우 생성 함수가 유효 부위 없음으로 호출을 생략한다. 나머지 5건은 68.67~75.36% 감소했다.

## 저장된 실제 A/B 재검사

- A: 3-B의 실제 응답. 3-E 기준 구조 차단 1건, 의미 검토 16건.
- B: 3-D의 실제 응답. 구조 차단 0건, 의미 검토 5건.
- B의 과거 ‘배트/타구 속도가 아님’ 부정문 오탐은 해소되었다. 새 검사에서는 순간 목표 지시, 과거 기록 없음 단정, 정규화 수치, 좋은 부위의 문제 구간 누락 등을 확인한다.
- 검사 항목 수는 품질 점수가 아니다. 검사 범위가 늘었으므로 3-D 당시 숫자와 단순 성능 비교할 수 없다.
- 실제 A/B 어느 것도 이번 작업에서 승인하지 않았다. 앱의 승인 화면은 **직접 작성한 합성 테스트 문구**로 표시 분기만 검사한다.

## 개발환경 확인 방법

- 근거/입력/실제 A·B 검사 보고서: `http://127.0.0.1:8991/`
- 격리 Flutter 앱: `http://127.0.0.1:8990/`
- 격리 FastAPI: `http://127.0.0.1:8906/api/health`
- 실행·암호를 출력하지 않는 로그인·종료: [앱 검증 도구 안내](../scripts/coaching_stage3e/README.md).

SQLite와 LocalPrivateStorage만 사용한다. 원격 연결 변수와 OpenAI 키를 비운 프로세스를 실행한다. 로그인·소유권·코칭 공개·삭제 기능은 실제 API 경로로 동작하지만 분석 리포트·영상 컨테이너·3D 좌표는 테스트 fixture이다. 실제 사용자 영상의 모델 재추론, 원격 파일 삭제, Android 실기기 검증과 구분한다.

## 검증 기록과 PR 범위

`.local/feedback-stage3e/`에는 전체 로그, 재생 결과, 캡처와 로컬 데이터가 저장되며 Git에 포함하지 않는다. 변경 파일 전체는 [PR 포함 후보 목록](feedback-stage3e-files.md)에 기록한다.

향후 PR에는 `api/`의 코칭 경로 4개, `feedback/`의 코칭 모듈, Flutter 코칭 표시/테스트, 관련 Python 테스트, 재현 스크립트와 문서만 포함한다. `.env`, 키, 계정 비밀번호·토큰, SQLite/Storage, 실제 A/B 실험 응답 파일, 브라우저 프로필과 빌드 결과는 제외한다.

서비스 적용 전에는 압축 입력으로 생성한 후보의 승인된 유료 평가, 다양한 리포트와 독립 코치/사용자 검토, 운영자 검토 절차 구현, 실제 배포 환경에서의 회귀 검증이 필요하다. 규칙·표시 통합 성공을 새로운 GPT 코칭 품질 또는 교정 효과 검증으로 해석하지 않는다.

## 자동 검증 결과

| 검증 | 결과 |
|---|---|
| 지정 swing-llm Python의 전체 `pytest tests` | 265 통과 / 3 환경 오류 / 14 제외 |
| 환경 오류 3건 보완 | 기존 standardswingmodel Python으로 동일 3건 모두 통과 |
| Flutter 정적 분석 | 경고 없음 |
| Flutter VM 전체 테스트 | 309 통과 / 기존 6 제외 |
| Flutter Web build | 성공, API 주소 `127.0.0.1:8906` |
| 저장된 6개 리포트 | 입력 불변, 3-A와 같은 점수 스냅샷, overall/full 근거 완전 복원 |
| 현재 Flutter 문구 재생 | 6건 / 477문구; 실제 노출 여부를 별도 표시 |
| API Coaching JSON 스키마 | 기존 7개 Pydantic 출력 모델 AST 동일 |
| 기존 3-A/B/C/D | 32/31/20/29개 파일 해시와 HEAD/status 보존 |

백엔드의 세 환경 오류는 `test_pose3d_pipeline.py`의 `test_observer_failure_does_not_change_image_score`, `test_same_calls_and_bitwise_unchanged_image_score_arrays`, `test_same_decode_pixels_and_exact_pts_without_second_read`이다. 지정 Python에 OpenCV가 없어 import 단계에서 실패했다. 기존 `standardswingmodel/.venv/Scripts/python.exe -B`로 세 테스트만 재실행해 통과했다. 패키지 설치나 환경 변경은 하지 않았으며, 최초 전체 실행이 단일 환경에서 전부 통과했다고 표현하지 않는다. 보완을 합쳐 고유 268개 테스트를 확인했다.

백엔드 제외 14건은 스켈레톤 데이터가 없는 `test_compare_v2.py` 10건, 이벤트 모델/스켈레톤이 없는 `test_event_lstm.py` 2건, 명시적 opt-in이 필요한 실제 Supabase 1건, Windows 심볼릭 링크 권한이 필요한 LocalPrivateStorage 1건이다. 모델 추론 데이터를 새로 복사하거나 운영 연결을 켜지 않았다.

Flutter의 기존 제외 6건 중 3건은 main에서 P0/raw 모드 전환을 보류하여 `skip:true`인 3D 모드 전환·전체 생략 복구·시간 보존 테스트이다. 나머지 3건은 `kIsWeb`에서만 실행되는 Blob URL fallback·취소 시 revoke·오류 종료 시 revoke 테스트이다. Chrome 전용 보완 실행과 실제 앱 검증은 별도 기록으로 구분한다.

Chrome 전용 업로드 테스트는 실제로 시도했지만 로딩 단계에서 완료되지 않았다. 초기 직접 SDK snapshot 실행의 `currentPackageConfig` 오류는 `dart --packages=.../flutter_tools/.dart_tool/package_config.json` 옵션으로 해결했으나, 그 뒤 로딩 대기가 남아 실제 앱 검증과의 자원 경합을 피하려고 해당 테스트 프로세스만 종료했다. **웹 전용 3건은 미검증**이다. 과거 Windows CanvasKit 경로 문제와 유사하지만 이번에 같은 원인임을 입증하지 못했다. SDK/패키지는 변경하지 않았다.

Flutter `.bat`의 SDK 잠금 대기는 기존 캐시의 `dart.exe`와 `flutter_tools.snapshot` 직접 실행으로 피했다. 실제 앱 검증 도구의 프로세스 소유 확인은 기존 영상 처리 환경의 같은 Python 3.11용 `psutil` 패키지만 읽어 재사용한다. 기본 API/평가 실행기는 요청한 swing-llm Python이며 새 패키지는 설치하지 않았다.

재현 로그: `.local/feedback-stage3e/backend-tests.{log,xml}`, `backend-video-supplement.{log,xml}`, `replay-validation.json`, `flutter-replay.json`, `.local/frontend-merge/flutter-analyze.log`, `flutter-test-final.log`, `flutter-web-build.log`.

## Chrome 실제 앱 결과

격리 FastAPI + 실제 Flutter Web 앱에서 **51개 확인 항목이 통과**했고 미처리 JavaScript 예외는 없었다. 앱과 API는 위 주소에서 계속 실행 중이다. `stage3e-review` 테스트 계정으로 로그인하며, 임의 생성 비밀번호는 현재 Windows 계정용 DPAPI로만 보관한다. [검증 도구의 `--open`](../scripts/coaching_stage3e/README.md)으로 비밀번호 출력 없이 로그인할 수 있다.

- 실제 로그인과 401/403 접근 차단.
- 승인된 합성 문구 표시, 실제 B의 검토 대기 및 실제 A의 차단, 생성 실패를 각각 구분. 미승인 원문은 API와 Flutter에서 노출하지 않음.
- 점수 근거 펼치기, main의 구간·관절 화면, 4건의 추이 표시.
- 삭제 취소 시 DELETE 없음. 테스트 파일을 실제로 잠가 Storage 502 실패를 만들고, 잠금 해제 뒤 재시도 성공.
- 삭제 후 원본 URL 410 및 기존 로컬 URL 사용 불가. 타인 파일 유지.
- 점수·날짜·피드백·승인 메타데이터와 전체 3D payload 불변. 3D 재생 진행·프레임 이동·확대 조작 확인.
- 새 로그인 후 삭제 상태·추이·피드백 유지.

원본 파일은 격리 폴더에 만든 테스트 컨테이너이며 실제 방송 영상 디코딩·업로드 추론을 재검증한 것이 아니다. 실제 Supabase 삭제나 3D 추정 정확도도 평가하지 않았다.

실행 중 초기에 Chrome 포커스와 JavaScript 로딩 타임아웃으로 중단된 시도는 최종 성공에 합산하지 않았다. 포커스/대기 처리와 동시 테스트 자원 경합을 조정한 뒤 동일 앱 빌드로 확인했다. 최종 근거는 `.local/feedback-stage3e/app/browser-validation.json`, 캡처는 `app/screenshots/`에 있다. 기존 서버/브라우저는 종료하지 않았다.
