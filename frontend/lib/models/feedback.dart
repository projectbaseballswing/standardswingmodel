/// 종합 피드백 / 관절별 분석 화면에서 쓰는 데이터 모델.
///
/// 백엔드(compare_v2)는 스윙을 5개 부위로 묶어 준다.
///   앞팔(lead_arm) · 뒷팔(rear_arm) · 몸통(torso) · 앞다리(lead_leg) · 뒷다리(rear_leg)
/// 각 부위는 실제 0~100 점수(overall.group_scores.score)를 가지고, 그 안에
/// 세부 항목([FeatureAnalysis]: 팔꿈치 각도, 손 높이 등)이 여러 개 들어 있다.
///
/// 한 화면이 두 상태를 모두 표현한다.
///  - 첫 피드백   : 비교할 이전 스윙이 없다. [previousScore] 가 null.
///                  부위는 프로 기준 대비 점수로 "잘함 / 개선 필요" 를 나눈다.
///  - 반복 피드백 : 이전 스윙과 비교한다(아직 샘플). [previousScore] 로 증감을
///                  보여주고 "개선 / 개선 필요 / 유지" 로 나눈다.
library;

/// 신체 부위. 아이콘·색·인체 그림 구분에만 쓴다.
enum BodyPart { leg, arm, torso }

/// 부위(앞팔/뒷팔/몸통/앞다리/뒷다리) 한 줄. 종합 피드백 목록의 한 항목.
///
/// 점수([currentScore])는 서버 `overall.group_scores.score` 의 실제 부위 점수다.
/// 세부 항목([features])은 이 부위를 이루는 피처들(신뢰도 낮은 것은 제외).
class FeedbackItem {
  const FeedbackItem({
    required this.key,
    required this.label,
    required this.part,
    required this.currentScore,
    required this.description,
    this.previousScore,
    this.level = 'good',
    this.reliability = 'high',
    this.features = const [],
  });

  /// 서버 그룹 키. 예) 'lead_arm'.
  final String key;

  /// 화면에 보이는 이름. 예) "왼쪽 팔", "몸통".
  final String label;

  /// 아이콘·색 구분용 부위.
  final BodyPart part;

  /// 이번 부위 점수(0~100). 서버 group_scores.score 실제값.
  final int currentScore;

  /// 설명 문구(2줄 내외).
  final String description;

  /// 이전 점수. 첫 피드백이면 null → 증감 화살표를 숨긴다.
  final int? previousScore;

  /// 부위 수준. 'good' | 'caution' | 'warning'.
  /// 부위 점수로 판정한다(점수와 배지가 어긋나지 않게).
  final String level;

  /// 검출 신뢰도. 'low' | 'medium' | 'high'.
  final String reliability;

  /// 이 부위를 이루는 세부 항목(피처) 목록.
  final List<FeatureAnalysis> features;

  /// 이전 대비 증감. 첫 피드백이면 null.
  int? get delta =>
      previousScore == null ? null : currentScore - previousScore!;
}

/// 부위를 이루는 세부 항목(피처) 하나. 예) 앞팔 팔꿈치 각도, 손 높이.
///
/// 서버 `joints[]` 한 건에 대응한다. 부위 상세에서 "무엇이 문제인지" 를 보여준다.
class FeatureAnalysis {
  const FeatureAnalysis({
    required this.key,
    required this.name,
    required this.level,
    required this.direction,
    this.unit = 'deg',
    this.description = '',
    this.impact,
    this.rangeOfMotion,
    this.series,
    this.phaseScores,
  });

  /// 서버 피처 키. 예) 'lead_elbow_angle'.
  final String key;

  /// 화면에 보이는 이름. 예) "앞팔 팔꿈치 각도".
  final String name;

  /// 프로 기준 대비 수준. 'good' | 'caution' | 'warning'.
  final String level;

  /// 기준 대비 방향. 'higher' | 'lower' | 'similar'.
  final String direction;

  /// 값 단위. 'deg'(각도) 등.
  final String unit;

  /// 피처 설명(각도 정의 등).
  final String description;

  /// 임팩트 순간의 내 값 vs 기준.
  final Measure? impact;

  /// 움직임 폭(최대-최소)의 내 값 vs 기준.
  final Measure? rangeOfMotion;

  /// 스윙 전체(구간 4개 × 20등분 = 80점) 각도 시계열. 그래프용.
  /// `?include_series=true` 로 받았을 때만 채워진다.
  final List<SeriesSample>? series;

  /// 스윙 4구간(SwingPhase 순서)의 0~100 점수.
  /// 서버가 구간별 피처 점수를 직접 주지 않아, 구간 z_score 를 환산한 값이다.
  /// 4구간이 모두 측정됐을 때만 채워진다.
  final List<int>? phaseScores;

  /// 비교할 만한 수치가 하나라도 있으면 true.
  bool get hasDetail => series != null || impact != null;
}

/// 내 값과 기준 값 한 쌍. impact, range_of_motion 에 쓴다.
class Measure {
  const Measure({this.user, this.reference, this.diff});
  final double? user;
  final double? reference;
  final double? diff;
}

/// 시계열 한 지점. 기준 평균([reference])과 그 ±편차([referenceStd]) 밴드를 담는다.
class SeriesSample {
  const SeriesSample({this.user, this.reference, this.referenceStd});

  /// 내 스윙 값. 영상에 없는 구간이면 null(선을 끊는다).
  final double? user;

  /// 기준(프로 평균) 값.
  final double? reference;

  /// 기준의 편차. 그래프에 옅은 밴드로 그린다.
  final double? referenceStd;
}

// ---------------------------------------------------------------------------
// 관절별 분석(상세 피드백) 모델
// ---------------------------------------------------------------------------

/// 스윙 4단계. 상세 그래프 x축 구간 라벨.
///
/// [key] 는 백엔드(compare_v2 PHASE_EVENTS)가 주는 구간 키와 같다.
/// 관절 `phases[].phase` 및 80점 시계열의 구간 순서가 이 순서와 일치한다.
enum SwingPhase {
  stride('stride', 'Stride', '스트라이드'),
  transition('transition', 'Transition', '착지 후 준비'),
  swing('swing', 'Swing', '스윙'),
  follow('follow', 'Follow-through', '팔로우스루');

  const SwingPhase(this.key, this.en, this.ko);

  /// 백엔드 구간 키.
  final String key;

  /// 영문 라벨(윗줄).
  final String en;

  /// 국문 라벨(아랫줄).
  final String ko;
}

/// 부위의 상태.
///
/// 반복 피드백(이전 스윙과 비교)에서는 증감으로:
///  - [improved]  : 점수가 올라 개선됨(초록).
///  - [worsened]  : 점수가 내려 개선 필요(빨강).
///  - [unchanged] : 변화가 거의 없음(회색).
///  - [limited]   : 비교할 이전 스윙이 없어 평가 제한(연한 회색).
///
/// 첫 피드백(비교 대상 없음)에서는 프로 기준 대비로:
///  - [proGood]   : 프로 기준에 잘 맞음 → "잘함"(초록).
///  - [proBad]    : 프로 기준과 차이 있음 → "개선 필요"(빨강).
enum JointStatus { improved, worsened, unchanged, limited, proGood, proBad }

/// 부위 하나의 상세 분석. 종합 피드백([OverallFeedback.items])에서 만든다.
///
/// 점수·세부 항목은 서버 실제 값이고, 코치 문장·포인트는 아직 규칙 기반 임시다.
class PartAnalysis {
  const PartAnalysis({
    required this.key,
    required this.label,
    required this.part,
    required this.isLeft,
    required this.status,
    required this.currentScore,
    required this.reliability,
    required this.features,
    required this.summary,
    required this.coachComment,
    required this.pointsTitle,
    required this.points,
    this.previousScore,
  });

  /// 서버 그룹 키. 예) 'lead_arm'.
  final String key;

  /// 화면에 보이는 이름. 예) "왼쪽 팔".
  final String label;

  /// 아이콘·인체 그림 영역 구분용 부위.
  final BodyPart part;

  /// 인체 그림에서 왼쪽/오른쪽 구분.
  final bool isLeft;

  /// 이전 대비(또는 프로 대비) 상태.
  final JointStatus status;

  /// 이번 부위 점수.
  final int currentScore;

  /// 검출 신뢰도. 'low' | 'medium' | 'high'.
  final String reliability;

  /// 이 부위를 이루는 세부 항목(피처) 목록.
  final List<FeatureAnalysis> features;

  /// 점수 박스 아래 색 상자 문구.
  final String summary;

  /// "AI 코치의 피드백" 본문.
  final String coachComment;

  /// 포인트 상자 제목. 예) "유지 포인트" / "개선 포인트".
  final String pointsTitle;

  /// 포인트 상자 불릿 목록.
  final List<String> points;

  /// 이전 점수. 비교 대상이 없으면 null.
  final int? previousScore;

  /// 이전 대비 증감. 비교 대상이 없으면 null.
  int? get delta =>
      previousScore == null ? null : currentScore - previousScore!;
}

/// 종합 피드백 1건.
class OverallFeedback {
  const OverallFeedback({
    required this.recordedAt,
    required this.totalScore,
    required this.summary,
    required this.coachComment,
    required this.items,
    this.previousTotalScore,
  });

  /// 촬영/분석 시각.
  final DateTime recordedAt;

  /// 전체 스윙 점수(0~100).
  final int totalScore;

  /// 점수 옆 분홍 박스에 들어가는 한 줄 요약.
  final String summary;

  /// "AI 코치의 한마디" 본문.
  final String coachComment;

  /// 부위별 피드백 목록.
  final List<FeedbackItem> items;

  /// 이전 전체 점수. 첫 피드백이면 null.
  final int? previousTotalScore;

  /// 비교할 이전 스윙이 없으면(=첫 피드백) true.
  bool get isFirst => previousTotalScore == null;

  /// 전체 점수 증감. 첫 피드백이면 null.
  int? get totalDelta =>
      previousTotalScore == null ? null : totalScore - previousTotalScore!;
}
