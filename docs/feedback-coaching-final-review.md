# StandardSwing 3-E 최종 검수 및 PR 준비

## 판단

규칙 기반 피드백 개선, 근거 입력·검증, 미승인 GPT 차단, 점수 요약/상세 분리는 **팀의 코드 검토용 PR에 포함할 수 있다**. GPT 생성 품질 개선이나 운영 승인 절차가 완성됐다는 의미는 아니다. 실제 GPT B는 `review_required`이고 승인하거나 사용자에게 노출하지 않았다.

이번 작업은 로컬 검수와 초안 작성까지다. Commit·Push·PR 생성·main 병합, OpenAI 호출, 운영 Supabase 변경은 수행하지 않았다.

## Git 기준과 충돌

- 작업 공간: `swing-feedback-stage3e`
- 브랜치: `feat/feedback-coaching-integration`
- 최신 `origin/main`: `42eacc244d3fb5aad2e01709c50c958262ea815c`
- 시작 시 `git fetch origin main`으로 확인했으며 현재 HEAD와 동일했다. 이 기준에서는 뒤늦게 추가된 main 변경이나 텍스트 병합 충돌이 없다.
- main의 관절·구간 피드백 UI를 유지한다. 향후 해당 화면/API 파일에 새 변경이 들어오면 PR 직전에 다시 비교해야 한다.
- 원래 33개 미커밋 파일의 시작 해시/상태를 `.local/feedback-stage3e-final/stage3e-before.json`에 보존했다. 기존 3-A/B/C/D의 32/31/20/29개 파일과 HEAD/status도 이전 보호 기록과 동일함을 확인했다.
- 점수 모델·피처·인증·Storage·3D·원본 삭제 알고리즘의 파일은 HEAD와 동일하다. 기존 코칭 원문을 다시 쓰지 않았다.

## 이번 검수의 최소 변경

`overall_feedback_screen.dart`에서 자세·속도 구성점수를 기존 ‘점수가 산출된 이유’ 펼침 영역으로 옮겼다. 기본 화면에는 총점·요약·신뢰도를 유지한다. 가중치를 확인할 수 없을 때 비어 있는 ‘반영’ 표시를 제거했다. 점수 값·산식·코칭 원문은 바꾸지 않았다.

`feedback_guidance_test.dart`의 모바일 테스트에서 기본 접힘/펼침 표시를 확인하고, 가중치 미확정 시 비율을 만들어 표시하지 않는 테스트를 추가했다. 그 외 서비스 기능은 추가하지 않았다.

로컬 연구 도구 README에는 외부 실험 자료와 Windows 도구 의존성을 명시했다. 새 clone에서 즉시 실행되는 서비스 필수 모듈과 혼동하지 않도록 했다.

## 검증 범위와 환경

기본 Python은 `swing-llm/.venv/Scripts/python.exe`다. API 테스트는 일회용 SQLite와 임시 Storage만 사용하며 OpenAI/Supabase 연결을 비운다. 추가 패키지 설치와 SDK 수정은 하지 않았다.

| 최종 소스 기준 | 결과 |
|---|---|
| Flutter analyze | 경고 없음 |
| Flutter VM 전체 | 310 통과 / 기존 6개 제외 |
| 웹 전용 Blob 테스트 | 실제 Chrome에서 3/3 통과, 아래 Windows 정적 자산 우회 사용 |
| Web build | 성공 (`API_BASE_URL=127.0.0.1:8906`) |
| 지정 Python의 전체 백엔드 테스트 | 265 통과 / cv2 환경 오류 3개 / 제외 14개 |
| 영상 처리 환경의 동일 3건 보완 | 모두 통과, 합계 고유 268건 확인 |
| 6개 리포트·점수·피처 | 불변, overall/full 근거 압축 후 완전 복원 |
| 실제 저장 A/B | 원문 불변, A 차단/B 검토 대기, 모두 표시 불가 |
| Chrome 격리 앱 최종 회귀 | 53/53 통과, 미처리 JavaScript 예외 0 |

VM 제외 6개 중 웹 전용 3개는 이번 Chrome 실행으로 보완했다. 남은 3개는 main에서 P0/raw 전환이 보류되어 의도적으로 제외한 기존 모드 전환·전체 생략 복구·시간 보존 테스트다. 기능을 임의로 켜거나 제외 조건을 바꾸지 않았다.

로그와 최종 소스 해시는 `.local/feedback-stage3e-final/frontend/validation-summary.json` 및 `backend/summary.json`, `backend/audit.json`에 있다. 전체 테스트와 Web build는 최소 UI 수정이 끝난 소스에서 수행했다.

### 실제 앱 회귀

기존 8906/8990 개발 서버가 실행 중임을 확인하여 종료하거나 설정을 바꾸지 않았다. 테스트용으로 API 8907, 웹 8992, Chrome CDP 9568을 사용했다. 별도 Web 출력은 `.local/feedback-stage3e-final/web`이며 기존 `frontend/build/web`을 보존했다. 추가 빌드는 상대 경로에서 Windows shader compiler가 실패했으나 절대 출력 경로로 지정하여 성공했다. 두 로그를 보존했고 소스 변경이나 패키지 설치는 없었다.

기존 하네스는 로컬 wrapper에서 포트·출력 경로만 바꾸어 재사용했다. 새 SQLite/LocalPrivateStorage에 fixture를 생성했다. 확인 항목은 다음과 같다.

- 기존 51개 항목: 로그인·401/403, 승인 상태별 공개/비공개, 규칙 폴백, 관절/구간 화면, 추이, 삭제 취소, 실제 로컬 파일 잠금으로 502 실패 후 재시도 성공, 삭제 후 점수·피드백·3D·날짜 유지, 3D 재생·프레임 이동·확대, 재로그인.
- 새 UI 2개 항목: 기본 화면에서 총점 67.3·요약을 유지하고 구성점수를 숨김. 펼치면 기존 자세 80.4·속도 36.6과 70%/30%를 그대로 표시.
- 실제 B는 계속 `review_required`, 실제 A는 `blocked`다. 승인 표시에는 직접 작성한 합성 예시만 사용했다.

최종 결과는 `.local/feedback-stage3e-final/app/browser-validation.json`에 있다. 캡처 `screenshots/03a-score-summary-collapsed.png`, `03b-score-components-expanded.png`에서 요약/상세 배치를 확인할 수 있다. 재생 오류 placeholder는 테스트용 영상 컨테이너를 쓴 결과로, 실제 원본 영상의 디코딩 회귀를 검증한 자료가 아니다. 3D도 합성 좌표 기반이다.

현재 검토용 앱은 `http://127.0.0.1:8992/`, API는 `http://127.0.0.1:8907/api/health`다. 이전 검증 결과와 DB/Storage는 덮어쓰지 않았다. 새 앱의 안전한 로그인 및 종료 명령은 아래와 같다. 비밀번호는 출력하지 않는다.

```powershell
cd C:\Users\DO\project\team\swing-feedback-stage3e
& ..\swing-llm\.venv\Scripts\python.exe -X utf8 -B .local\feedback-stage3e-final\verify_app_final.py --open
& ..\swing-llm\.venv\Scripts\python.exe -X utf8 -B .local\feedback-stage3e-final\verify_app_final.py --stop
```

이 wrapper는 현재 로컬 검수 산출물이며 PR 필수 파일이 아니다. `--stop`은 이 실행이 생성한 PID/생성 시각이 맞는 프로세스만 종료하고 DB·결과를 보존한다.

### 백엔드 초기 환경 오류의 정확한 상태

지정 Python의 전체 테스트는 282개를 수집하여 265 통과, 3 환경 오류, 14 제외였다. 세 오류는 지정 환경에 `cv2`가 없어 발생한다. 이 환경에 OpenCV를 새로 설치해 해결한 것은 아니다.

다음 세 테스트를 기존 `standardswingmodel/.venv/Scripts/python.exe -B`로 다시 실행해 모두 통과했다. 합쳐 고유 268개를 확인했으며, 한 환경에서 282개 전체가 통과했다고 표현하지 않는다.

- `test_observer_failure_does_not_change_image_score`
- `test_same_calls_and_bitwise_unchanged_image_score_arrays`
- `test_same_decode_pixels_and_exact_pts_without_second_read`

제외 14개는 실제 스켈레톤이 없는 점수 비교 10개, 이벤트 모델/스켈레톤이 없는 2개, 실제 Supabase opt-in 1개, Windows 심볼릭 링크 권한 1개다. 추가 모델 추론이나 원격 검증을 켜지 않았다. 상세 항목은 `.local/feedback-stage3e-final/backend/summary.json`에 있다.

### 웹 전용 테스트 재확인

이전에 로딩을 완료하지 못한 세 테스트를 실제 Chrome에서 실행했다.

- 웹 Blob 실패 시 저장 영상 대체 안내
- 검토 취소 시 Blob URL 해제
- 결과 화면 오류 종료 시 Blob URL 해제

Windows Flutter 테스트 서버의 `/canvaskit/canvaskit.js`와 `/canvaskit/chromium/canvaskit.js` 요청이 원래 HTTP 404임을 기록했다. 검증 브라우저의 CDP Fetch에서 **설치된 SDK의 동일 CanvasKit JS/WASM 두 파일만** 제공했다. 앱/API 응답은 대체하지 않았고 SDK·테스트 소스도 수정하지 않았다. 제공 파일 SHA와 명령은 `frontend/flutter-web-tests.json`에 기록했다.

따라서 ‘기존 미검증 웹 3개가 실행돼 통과’한 것과 ‘일반 Windows 명령이 우회 없이 통과’하는 것은 구분해야 한다. GitHub의 기존 Linux CI는 같은 테스트를 일반 Chrome 명령으로 실행하도록 구성돼 있으나 이번에 새 CI 실행은 만들지 않았다.

## PR에 포함할 범위

| 범위 | 판단 |
|---|---|
| 신뢰도·근거 기반 규칙 안내, 우선 확인 후보, 상세 근거 UI | 포함 가능 |
| GPT 입력의 근거 보존 압축 및 출력 검증 | 포함 가능. 실제 생성 효과는 미검증으로 명시 |
| 미승인 후보 비공개 처리·정확한 승인 버전만 표시·규칙 폴백 | 포함 가능 |
| 기존 응답 JSON에 선택적 검토 상태 추가, 비교 GET의 자동 생성 제거 | 포함 가능. 동작 변경을 PR에 명시 |
| 실제 GPT B의 자동 승인 또는 공개 | 포함 불가 |
| 합성 승인 fixture를 운영 데이터로 복사 | 포함 불가 |
| 실제 응답·키·로컬 DB·Storage·캡처·브라우저 캐시 | Git 제외 |
| 외부 3-A/B/D 자료를 요구하는 재현 스크립트 | 선택적 연구 보조도구. 외부 입력 조건과 함께 별도 구분 |

전체 파일 목록은 [변경 파일 목록](feedback-stage3e-files.md), 본문은 [PR 초안](PR-feedback-coaching-draft.md)을 참고한다.

## 배포 시 주의사항

1. **초기에는 규칙 기반 안내로 배포할 수 있다.** 검토 도구가 없더라도 미승인 코칭은 표시되지 않는다. 다만 해당 서버 프로세스에 `OPENAI_API_KEY`가 설정돼 있으면 업로드 분석 중 유료 후보 생성은 실행될 수 있다. 초기 배포에서 생성하지 않으려면 배포 설정에서 코칭용 키를 제공하지 않아야 한다. 이번 작업에서는 기존 키/환경을 바꾸지 않았다.
2. **DB migration은 추가하지 않는다.** 기존 결과 JSON에 검토 정보를 저장한다. 후보는 FastAPI 공개 응답에서 제거된다. 실제 Supabase 직접 테이블 접근/RLS·저장 역할이 비공개 후보를 보호하는지는 원격에서 검증하지 않았으므로 GPT 후보 저장 활성화 전에 확인해야 한다.
3. **승인 운영 절차는 별도다.** 권한 있는 검토자, 감사 이력, 트랜잭션·행 잠금·후보 버전 확인이 필요하다. Python 승인 함수가 관리자 인증을 대신하지 않는다. 구체적 설계는 [검토 생명주기](coaching-review-lifecycle.md)에 있다.
4. **기존 미승인 응답도 표시가 보류된다.** 원문은 삭제하지 않지만 화면이 규칙 안내로 바뀔 수 있다. 비교 GET도 새 GPT를 만들지 않고 검토된 저장 결과만 사용한다. 팀과 공유해야 할 의도된 변경이다.
5. **구버전으로 단순 롤백하면 차단이 해제될 수 있다.** 기존 코드가 승인 없는 `coaching`을 표시하거나 비교 조회 중 생성할 수 있으므로 표시 차단을 유지하는 롤백이 필요하다. 운영 DB를 임의로 초기화하거나 기존 결과를 지우지 않는다.

## 추가 검증이 필요한 항목

- 압축 입력으로 실제 GPT를 생성했을 때 근거 참조·한국어·과잉 교정이 개선되는지에 대한 별도 승인된 평가.
- 사람의 문장 검토 및 실제 사용자/코치 검증. 자동 정책 검사는 의미적 정확성이나 교정 효과를 인증하지 않는다.
- 관리자 권한·감사·PostgreSQL 동시 승인·Supabase 직접 접근 권한 검증.
- 실제 사용자 영상 업로드/디코딩/재추론, Android 실기기, 운영 환경 배포 회귀. 현재 Chrome 회귀는 합성 fixture 기반이다.
- PR 생성 이후 실제 GitHub CI. 현재는 로컬 검증 결과이며 원격 CI 통과를 주장하지 않는다.

참고: 일부 `limited` 부위가 ‘참고용’과 ‘유지된 부분’에 중복 분류되는 경우는 HEAD에도 있는 기존 동작이다. 이번 회귀로 분류하지 않았고 범위 밖이므로 수정하지 않았다.
