# swing_analysis

## Android / Chrome 영상 선택·업로드

- `image_picker`/`camera`의 `XFile`을 리뷰 화면과 `AnalysisApi`까지 그대로 전달한다.
  `length()`와 `openRead()`로 multipart `video`를 만들며 파일명, MIME,
  `handedness`, 로그인 세션의 `user_id`, UTC ISO 8601 `recorded_at`을 전송한다.
  `recorded_at`은 현재 업로드 시각이며 원본 영상 메타데이터의 촬영 시각은 아니다.
- Android는 기존 파일 컨트롤러와 촬영 흐름을 사용한다. Chrome은 선택한
  Blob URL을 `VideoPlayerController.networkUrl`로 재생하고 탭으로 재생을 시작한다.
  리뷰는 원본 비율을 유지하고, 초기화 실패/30초 초과 시 오류와 재시도를 표시한다.
- 리뷰 취소 시 Blob URL을 해제한다. 업로드 성공 시 `pushReplacement`와 `first=1`
  polling을 유지하고 같은 Blob을 종합 피드백 화면으로 넘긴다. 결과 조회 실패 시에도
  결과 화면 종료 시 해제한다. URL은 라우트의 메모리 값이며 DB 등에 저장하지 않는다.
  결과 화면에서 Blob 재생 실패 시 '저장된 영상으로 재시도'로 Signed URL을 요청한다.
- 설치된 `cross_file 0.3.5+5`의 웹 `openRead()`는 Blob을 바이트로 변환하고,
  `http 1.6.0` BrowserClient는 multipart 전체를 버퍼링한다. 앱에서 별도의
  `readAsBytes()` 복사를 추가하지 않지만, 웹에서 완전한 스트리밍 업로드는 아니다.
  대용량 파일은 메모리 부담이 있으며 실제 브라우저 성능 검증이 필요하다.
- 웹 카메라는 HTTPS/localhost와 카메라·마이크 권한이 필요하고 브라우저별 녹화 형식이
  다르다. 현재 서버 허용 확장자는 mp4/mov/avi/mkv/m4v이며 WebM은 허용하지 않는다.
  MIME을 바꾸거나 확장자를 위장하지 않으며 서버 415 오류를 표시한다.
  이번 검증은 갤러리 파일 선택 우선이다. 재생 가능 여부는 브라우저/OS 코덱에 달려 있다.
  서버 기본 업로드 제한은 200MB이며 실제 설정에 따라 달라진다.

Mock 검증: `flutter test --no-pub`.
브라우저 분기와 Blob 수명 검증: `flutter test --no-pub --platform chrome test/swing_upload_test.dart`.
웹 빌드: `flutter build web --no-pub`. 패키지 추가/갱신 없이 실행한다.

현재 Windows 환경에서 일반 테스트는 150개 통과(웹 전용 3개 제외), 정적 분석과
웹 빌드도 통과했다. 별도 Chrome 자동 테스트는 Flutter 테스트 서버의
`/canvaskit/chromium/canvaskit.js`·`.wasm` 요청이 404로 실패해 테스트 시작 전
로딩 단계에서 중단했다. SDK/패키지는 수정하지 않았으며 웹 전용 3개는 미검증이다.
이는 실제 Chrome 앱의 수동 검증 결과를 의미하지 않는다.

수동 검증(사용자 실행): 로그인 → 촬영 가이드 닫기 → 왼쪽 아래 갤러리에서 짧은
MP4(H.264/AAC) 선택 → 미리보기 탭·일시정지 → 좌타/우타 선택 → 분석 요청 →
종합 피드백과 영상 확인 → 뒤로 가기 → 현재 달의 기록 확인. 개발자 도구에서
POST multipart와 `first=1` 이후 분석 GET 요청을 확인한다. 이후 과거 기록을 다시
열면 Signed URL로 재생한다. `SWING_MOCK=1`의 분석 값은 실제 AI 정확도 검증이 아니다.
자동 테스트는 실제 API/Supabase에 데이터를 생성하지 않는다.

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## 분석 응답 매핑 (모델 0.1 / 0.2)

`FeedbackRepository`는 새 업로드의 polling 결과와 과거 기록의 단일 GET 결과에
같은 매핑을 적용한다. 모두 `include_series=true`로 조회한다.
종합 화면은 영상·종합/부위 점수·신뢰도·속도를 표시하고, 구간 상세는
`/phase-feedback`으로 이동해 표시한다. 별도 구간 화면은 전달받은
`OverallFeedback.phases`의 `AnalysisPhase`를 직접 사용하며 추가 GET을 하지 않는다.
팀원의 스텝퍼·2열 구간 카드·선택 상세 레이아웃을 유지한다.
구간 선택은 서버 key를 사용하고 이름·순서는 응답 그대로 보존한다.
상단 전체 점수도 서버 `overall.score`이며 구간 점수를 평균 내지 않는다.
관절 점수를 평균 내는 `buildPhaseAnalyses`와 샘플 비교값은 사용하지 않는다.
구간 배지는 측정 완료/점수 미제공/참고용/분석 불가 상태를 나타내며,
점수 임계값으로 임의의 자세 등급을 만들지 않는다. 템포 판정은 서버 값만 사용한다.
계약은 `../feedback/compare_v2.py`, `../feedback/compare.py`, `../api/schemas.py`를
기준으로 한다. `../api/fixtures/analysis_sample.json`은 0.2-draft 예시다.

| 응답 필드 | Flutter 표시 및 결측 처리 |
| --- | --- |
| `overall.score`, `group_scores[].score` | 실제 소수점 점수. `available=false` 또는 null이면 `-`. 서버 부위 이름을 사용한다. |
| `overall.reliability`, `quality.warnings` | 종합 카드에 신뢰도와 경고 표시. 낮은 신뢰도를 0점이나 좋음·나쁨으로 해석하지 않는다. |
| 부위/관절 `reliability` | 낮은 신뢰도의 세부 관절은 제외하지만 실제 부위 점수는 참고용으로 남긴다. |
| `phases.phases[]` | 서버 `key`로 구분하여 실제 점수, 사용자·기준 소요 시간(ms), 신뢰도, 경고와 주요 관절 차이를 표시한다. |
| `tempo_ratio`, `tempo_level` | 비율 > 1은 더 긴 시간, < 1은 더 짧은 시간. `tempo_level=null`이면 판정 보류이며 비율로 좋음·나쁨을 추정하지 않는다. |
| `speed.metrics[]` | 실제 사용자·기준 값과 단위, 신뢰도. `body/s`는 체장 기준 상대속도이며 m/s 또는 km/h로 변환하지 않는다. |
| `phases.events` | 유효한 프레임이 있는 앞발 착지·스윙 시작·팔로우 종료만 표시. `ms_from_impact < 0`은 임팩트 이전이다. |

관절별 **참고 점수**는 기존 공식을 유지한다:
`round(100 * 0.8 ^ abs(z_score))`를 0~100 범위로 제한한다.
이는 `joints[].phases[]`의 편차를 그리기 위한 Flutter 환산값이며,
서버가 주는 `phases.phases[].score`(구간 종합 점수)와 다른 값이다.
`available=false`, null z-score는 그리지 않고 정상 구간은 남긴다.

시계열은 `user`, `reference`, `reference_std`를 그대로 사용한다.
null 또는 짧은 배열의 빠진 지점을 보간하거나 0으로 채우지 않는다.
선과 기준 ±표준편차 밴드는 결측에서 끊고, 고립된 측정값은 점으로 표시한다.
0.2 시계열만 stride / transition / swing / follow의 4×20 시간축을 사용한다.
0.1은 기준 프레임 시간축이므로 0.2 구간 경계를 붙이지 않고,
관절 참고 점수에는 0.1 서버의 구간 키·이름을 유지한다.

0.1의 pose/velocity 등 그룹 점수를 팔·다리 점수로 바꾸지 않는다.
그룹에 연결되지 않은 관절은 점수 없는 상세 부위로 보존한다.
속도 항목이 비어 있으면 섹션을 숨기고, 미제공 항목은 숫자 대신 안내를 표시한다.
응답에서 제공하지 않는 이전 스윙 비교 점수·증감은 생성하지 않는다.
코치 문구는 기존 규칙 기반이며 별도 AI 생성 문장이 아니다.

아직 전용 UI가 없는 값: 전체 거리/프레임별 거리, 최악 구간, 전체 강점·약점 목록,
rhythm, 이벤트의 기준 시간·편차, 속도 지표의 z-score·등급.
영상 재생, 업로드, 라우팅은 기존 흐름을 사용한다.

`test/fixtures/analysis_v2.json`은 계약을 반영한 합성 Mock 응답이다.
실제 영상 분석이나 Supabase 데이터가 아니며, 80개 시계열을 포함한다.
주요 매핑·화면 검증: `flutter test --no-pub test/model_v2_feedback_test.dart`.
