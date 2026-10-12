# swing_analysis

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
