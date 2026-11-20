/// 종합 피드백 / 관절별 분석 화면에서 쓰는 데이터 모델.
///
/// 백엔드(compare_v2)는 스윙을 5개 부위로 묶어 준다.
///   앞팔(lead_arm) · 뒷팔(rear_arm) · 몸통(torso) · 앞다리(lead_leg) · 뒷다리(rear_leg)
/// 각 부위는 실제 0~100 점수(overall.group_scores.score)를 가지고, 그 안에
/// 세부 항목([FeatureAnalysis]: 팔꿈치 각도, 손 높이 등)이 여러 개 들어 있다.
///
/// 한 화면이 두 상태를 모두 표현한다.
///  - 비교 없음  : [previousScore] 가 null. 첫 스윙이라는 의미는 아니다.
///                  부위는 프로 기준 대비 점수로 "잘함 / 개선 필요" 를 나눈다.
///  - 비교 있음  : 실제 이전 스윙과 비교한 경우만 [previousScore] 로 증감을
///                  보여주고 "개선 / 개선 필요 / 유지" 로 나눈다.
library;

import '../data/feedback_language.dart';

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
    this.available = true,
  });

  /// 서버 그룹 키. 예) 'lead_arm'.
  final String key;

  /// 화면에 보이는 이름. 예) "왼쪽 팔", "몸통".
  final String label;

  /// 아이콘·색 구분용 부위.
  final BodyPart part;

  /// 이번 부위 점수(0~100). 서버 group_scores.score 실제값.
  final double? currentScore;
  final bool available;
  bool get limited =>
      !available || currentScore == null || reliability == 'low';

  /// 설명 문구(2줄 내외).
  final String description;

  /// 실제 비교한 이전 점수. 비교하지 않았으면 null → 증감 화살표를 숨긴다.
  final double? previousScore;

  /// 부위 수준. 'good' | 'caution' | 'warning'.
  /// 부위 점수로 판정한다(점수와 배지가 어긋나지 않게).
  final String level;

  /// 검출 신뢰도. 'low' | 'medium' | 'high'.
  final String reliability;

  /// 이 부위를 이루는 세부 항목(피처) 목록.
  final List<FeatureAnalysis> features;

  /// 이전 대비 증감. 비교하지 않았으면 null.
  double? get delta => previousScore == null || currentScore == null
      ? null
      : currentScore! - previousScore!;
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
    this.directionText,
    this.unit = 'deg',
    this.description = '',
    this.comment = '',
    this.impact,
    this.rangeOfMotion,
    this.series,
    this.phaseScores,
    this.reliability = 'medium',
    this.eventBasedSeries = false,
    this.evidence,
    this.ruleComment = '',
    this.contribution,
  });

  /// 부위 내 점수 영향 비중(0~1). 같은 부위의 표시 피처들끼리 합하면 1.
  /// 저신뢰 피처나 0.2.x 이전 기록에는 없어 null.
  final double? contribution;

  /// 서버 피처 키. 예) 'lead_elbow_angle'.
  final String key;

  /// 화면에 보이는 이름. 예) "앞팔 팔꿈치 각도".
  final String name;

  /// 프로 기준 대비 수준. 'good' | 'caution' | 'warning'.
  final String level;

  /// 기준 대비 방향. 'higher' | 'lower' | 'similar'.
  final String direction;

  /// 서버가 피처에 맞게 만든 방향 문구. 예) "기준보다 더 펴져 있어요".
  /// 0.2.2 이전 기록에는 없어서 null 이면 [direction] 으로 문구를 만든다.
  final String? directionText;

  /// 값 단위. 'deg'(각도) 등.
  final String unit;

  /// 피처 설명(각도 정의 등).
  final String description;

  /// 이 관절에 대한 LLM(백엔드) 코멘트. 없으면 '' → 화면에서 표시하지 않는다.
  /// 서버 `coaching.joints[]` 중 key 가 이 피처와 같은 항목의 comment.
  final String comment;
  final String reliability;
  final bool eventBasedSeries;
  final FeedbackEvidence? evidence;
  final String ruleComment;
  String get displayedComment => comment.isNotEmpty ? comment : ruleComment;
  String get commentSource =>
      comment.isNotEmpty ? 'GPT 코칭 · 검토 완료' : '분석 결과 안내 · 기본 설명';

  /// 임팩트 순간의 내 값 vs 기준.
  final Measure? impact;

  /// 움직임 폭(최대-최소)의 내 값 vs 기준.
  final Measure? rangeOfMotion;

  /// 스윙 시계열. 0.2는 구간 4개 × 20등분, 0.1은 기준 프레임 시간축을 쓴다.
  /// `?include_series=true` 로 받았을 때만 채워진다.
  final List<SeriesSample>? series;

  /// 관절 z-score 환산 참고 점수. 서버의 구간 종합 점수와 별개이며 결측은 null.
  final List<JointPhaseScore>? phaseScores;

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
///  - [limited]   : 점수·세부 정보 부족 또는 낮은 신뢰도로 평가 제한(연한 회색).
///
/// 이전 스윙과 비교하지 않았으면 프로 기준 대비로:
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
    this.pointsSource = '분석 결과 안내 · 기본 설명',
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
  final double? currentScore;

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
  final String pointsSource;

  /// 포인트 상자 불릿 목록.
  final List<String> points;

  /// 이전 점수. 비교 대상이 없으면 null.
  final double? previousScore;

  /// 이전 대비 증감. 비교 대상이 없으면 null.
  double? get delta => previousScore == null || currentScore == null
      ? null
      : currentScore! - previousScore!;
}

/// LLM(백엔드)이 만든 부위별 코칭. 없으면 규칙 기반 문구를 쓴다.
class PartCoaching {
  const PartCoaching({
    required this.summary,
    this.keepPoints = const [],
    this.improvePoints = const [],
  });

  final String summary;
  final List<String> keepPoints;
  final List<String> improvePoints;

  /// 유지/개선 포인트를 합친 목록. (개선 포인트를 먼저 보여준다)
  List<String> get points => [...improvePoints, ...keepPoints];
}

/// LLM(백엔드)이 만든 구간별 코칭. 서버 `coaching.phases[]` 한 건.
class PhaseCoaching {
  const PhaseCoaching({this.cardLine = '', this.comment = '', this.tip = ''});

  /// 구간 카드용 짧은 한 줄(상태 중심).
  final String cardLine;

  /// 구간 상세 서술(수치·가장 벌어진 관절 근거).
  final String comment;

  /// 구간 개선 실천 팁 한 문장.
  final String tip;
}

/// "AI 코치의 한마디"를 문제→원인→교정→추천훈련 4단으로 펼친 것.
/// LLM 코칭일 때만 있고, 규칙 기반 폴백이면 null (그땐 한 문장 코멘트를 쓴다).
class CoachFeedback {
  const CoachFeedback({
    required this.problem,
    required this.cause,
    required this.fix,
    required this.drill,
  });

  /// 무엇이 아쉬운지.
  final String problem;

  /// 왜 그런지(원인).
  final String cause;

  /// 어떻게 고치면 되는지(교정).
  final String fix;

  /// 추천 훈련(드릴).
  final String drill;
}

/// LLM(백엔드)이 만든 코칭 묶음. 서버 응답 result.coaching 을 담는다.
///
/// 생성에 실패했거나(키 없음·504·할당량 초과 등) 서버가 안 주면 null 이고,
/// 그때는 기존 규칙 기반 문구로 자동 폴백한다.
class Coaching {
  const Coaching({
    required this.overallSummary,
    required this.overallCoach,
    this.coachFeedback,
    this.parts = const {},
    this.joints = const {},
    this.phases = const {},
    this.extendedStatus,
  });

  /// 종합 요약 (점수 옆 분홍 박스).
  final String overallSummary;

  /// 종합 코칭 한마디 헤드라인 (AI 코치의 한마디 제목 아래 한 줄).
  final String overallCoach;

  /// AI 코치의 한마디 4단 상세(문제/원인/교정/추천훈련). 없으면 null(한 문장만 표시).
  final CoachFeedback? coachFeedback;

  /// 부위 key → 부위별 코칭.
  final Map<String, PartCoaching> parts;

  /// 피처(관절) key → LLM 코멘트. scope='full' 일 때만 채워진다(아니면 비어 있음).
  final Map<String, String> joints;

  /// 구간 key → LLM 구간 코칭. scope='full' 일 때만 채워진다.
  final Map<String, PhaseCoaching> phases;

  /// 관절·구간(joints/phases) 생성 상태. 종합을 먼저 주고 뒤이어 채울 때:
  /// 'pending'=생성 중(화면은 '작성 중' 표시 후 재조회), 'done'=완료, 'failed'=실패.
  /// null 이면 애초에 확장 코칭을 만들지 않은 응답(옛 캐시·규칙 기반 등).
  final String? extendedStatus;

  /// 관절·구간 서술이 아직 생성 중이라 재조회가 필요한 상태인지.
  bool get isExtendedPending => extendedStatus == 'pending';
  String get sourceLabel => 'GPT 코칭 · 검토 완료';
}

/// Approval metadata is independent of whether the response contains text.
/// Legacy or malformed metadata never grants permission to display GPT text.
class CoachingReview {
  const CoachingReview({
    this.status = 'unverified',
    this.source = 'rules',
    this.displayAllowed = false,
  });

  factory CoachingReview.fromJson(dynamic raw) {
    if (raw is! Map<String, dynamic>) return const CoachingReview();
    return CoachingReview(
      status: raw['status'] is String ? raw['status'] as String : 'unverified',
      source: raw['source'] is String ? raw['source'] as String : 'rules',
      displayAllowed: raw['display_allowed'] == true,
    );
  }

  final String status, source;
  final bool displayAllowed;
  bool get canDisplay =>
      status == 'approved' && source == 'openai' && displayAllowed;

  String get notice => switch (status) {
    'approved' when canDisplay => '검토가 완료된 GPT 코칭입니다.',
    'review_required' => 'GPT 코칭은 사람 검토가 필요해 표시하지 않습니다. 분석 근거 안내를 보여드려요.',
    'blocked' => '코칭 검증 조건을 충족하지 못해 분석 근거 안내를 보여드려요.',
    'generation_failed' => 'GPT 코칭 생성에 실패해 분석 근거 안내를 보여드려요.',
    _ => '현재는 분석 결과를 바탕으로 한 기본 안내를 보여드려요.',
  };
}

/// A measured joint/phase difference, not a causal explanation or score attribution.
class FeedbackEvidence {
  const FeedbackEvidence({
    required this.joint,
    required this.part,
    required this.name,
    required this.phase,
    required this.phaseName,
    required this.z,
    required this.direction,
    required this.isIssue,
  });
  final String joint, part, name, phase, phaseName, direction;
  final double z;
  final bool isIssue;
  String get observation =>
      feedbackObservation(joint, name, phaseName, direction);
  String get action => feedbackObservationAction(joint, name, phaseName);
}

/// 자세 계산에 사용한 표준화 차이 제곱합의 부위별 상대 비중.
///
/// 기준 자세와 많이 벌어진(편차가 큰) 부위일수록 [share] 가 크다.
/// 표시 부위의 [share] 합은 반올림 오차를 제외하면 1이다. 저신뢰도 계산에는
/// 포함하며, [reliability] 가 'low' 면 회색으로 참고용 표시한다.
class ScoreContribution {
  const ScoreContribution({
    required this.key,
    required this.name,
    required this.share,
    this.score,
    this.reliability = 'medium',
  });

  final String key;
  final String name;

  /// 0~1. 표시 부위 내 상대 비중. 종합 점수의 감점량이 아니다.
  final double share;

  /// 그 부위 점수(0~100). 막대 색/상태 판정용. 없을 수 있다.
  final double? score;
  final String reliability;

  bool get isLowReliability => reliability == 'low';
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
    this.modelVersion = 'unknown',
    this.videoStatus = 'unknown',
    this.available = true,
    this.reliability = 'medium',
    this.warnings = const [],
    this.phases = const [],
    this.speedMetrics = const [],
    this.events = const [],
    this.rotationChecks = const [],
    this.postureScore,
    this.speedScore,
    this.postureCapped = false,
    this.coaching,
    this.analysisId = '',
    this.priorities = const [],
    this.strengths = const [],
    this.scoreExplanation = '',
    this.coachSource = '분석 결과 안내 · 기본 설명',
    this.summarySource = '분석 결과 안내 · 기본 설명',
    this.coachingReview = const CoachingReview(),
    this.scoreContributions = const [],
  });

  /// 자세 차이의 부위별 상대 비중. 필드가 없는 과거 기록은 빈 목록.
  final List<ScoreContribution> scoreContributions;

  /// 분석 id. 관절·구간 코칭이 아직 생성 중(pending)일 때 상세 화면이 재조회하는 데 쓴다.
  final String analysisId;
  final List<FeedbackEvidence> priorities, strengths;
  final String scoreExplanation, coachSource, summarySource;
  final CoachingReview coachingReview;
  bool get confirmedComposite =>
      modelVersion.startsWith('0.2') &&
      postureScore != null &&
      speedScore != null &&
      totalScore != null &&
      (postureScore! * .7 + speedScore! * .3 - totalScore!).abs() <= .11;

  /// 촬영/분석 시각.
  final DateTime recordedAt;

  /// 백엔드 LLM 코칭. 없으면 null (규칙 기반 문구로 폴백).
  final Coaching? coaching;

  /// 전체 스윙 점수(0~100).
  final double? totalScore;
  final String modelVersion;
  final String videoStatus;
  final bool available;
  final String reliability;
  final List<String> warnings;
  final List<AnalysisPhase> phases;

  /// 종합 점수 = 자세 70% + 속도 30%. 0.2.1 이전 기록에는 없어서 null.
  final double? postureScore;
  final double? speedScore;

  /// 골반과 어깨가 모두 돌지 않아 자세 점수에 상한(40점)이 걸렸는지.
  final bool postureCapped;

  /// 착지 → 임팩트 몸통 회전 확인. 0.2.2 이전 기록에는 없다.
  final List<RotationCheck> rotationChecks;
  final List<SpeedMetric> speedMetrics;
  final List<SwingEvent> events;

  /// 점수 옆 분홍 박스에 들어가는 한 줄 요약.
  final String summary;

  /// "AI 코치의 한마디" 본문.
  final String coachComment;

  /// 부위별 피드백 목록.
  final List<FeedbackItem> items;

  /// 실제 비교한 이전 전체 점수. 비교하지 않았으면 null.
  final double? previousTotalScore;

  /// 실제 이전 스윙과 비교한 점수가 있는지 여부. 촬영 순서와는 무관하다.
  bool get hasComparison => previousTotalScore != null && totalScore != null;

  /// 전체 점수 증감. 비교하지 않았으면 null.
  double? get totalDelta =>
      !hasComparison ? null : totalScore! - previousTotalScore!;
}

/// 사용자에게 보여줄 수치는 소수 첫째 자리까지 표시하고 null은 '-'로 둔다.
String feedbackNumber(num? value) => value == null
    ? '-'
    : value == value.roundToDouble()
    ? value.toInt().toString()
    : value.toStringAsFixed(1);

String reliabilityLabel(String value) => switch (value) {
  'high' => '신뢰도 높음',
  'medium' => '신뢰도 보통 · 참고해서 확인하세요',
  'low' => '신뢰도 낮음 · 참고용',
  _ => '신뢰도 정보 없음',
};

class JointPhaseScore {
  const JointPhaseScore({required this.key, required this.name, this.score});
  final String key;
  final String name;
  final int? score;
}

class PhaseDeviation {
  const PhaseDeviation({
    required this.joint,
    required this.name,
    required this.direction,
    required this.level,
    this.directionText,
    this.diff,
    this.zScore,
    this.description = '',
  });
  final String joint;
  final String name;
  final String direction;
  final String? directionText;
  final String level;
  final double? diff;
  final double? zScore;

  /// 이 관절이 뭘 재는지 한 줄 설명(예: "앞 어깨-팔꿈치-손목 각도. 클수록 팔이 펴져 있다.").
  /// 리포트의 joints[].description 에서 같은 key 로 찾아 채운다.
  final String description;
}

/// 착지 → 임팩트 몸통 회전 확인 하나. 서버 `overall.rotation_checks[]`.
class RotationCheck {
  const RotationCheck({
    required this.key,
    required this.name,
    required this.message,
    this.passed,
    this.affectsScore = false,
  });
  final String key;
  final String name;

  /// 통과 여부. 측정하지 못하면 null.
  final bool? passed;

  /// true 인 확인(골반, 어깨)이 모두 실패하면 자세 점수에 상한이 걸린다.
  final bool affectsScore;
  final String message;
}

class AnalysisPhase {
  const AnalysisPhase({
    required this.key,
    required this.name,
    required this.available,
    required this.reliability,
    this.score,
    this.unavailableReason,
    this.userDurationMs,
    this.referenceDurationMs,
    this.tempoRatio,
    this.tempoLevel,
    this.warnings = const [],
    this.deviations = const [],
    this.checks = const [],
    this.coachCardLine = '',
    this.coachComment = '',
    this.coachTip = '',
    this.ruleTip = '',
  });
  final String key;
  final String name;
  final bool available;
  final String reliability;
  final double? score;
  final String? unavailableReason;
  final double? userDurationMs;
  final double? referenceDurationMs;
  final double? tempoRatio;
  final String? tempoLevel;
  final List<String> warnings;
  final List<PhaseDeviation> deviations;

  /// 이 구간 카드에 보여줄 몸통 회전 확인. 스윙 구간에만 채운다.
  final List<RotationCheck> checks;

  /// LLM(백엔드) 구간 코칭. 서버 `coaching.phases[]` 중 key 가 같은 항목에서 온다.
  /// 비어 있으면('') 화면이 기존 규칙 기반 문구로 폴백한다.
  final String coachCardLine; // 구간 카드용 짧은 한 줄
  final String coachComment; // 구간 상세 서술(수치·가장 벌어진 관절 근거)
  final String coachTip; // 구간 개선 실천 팁
  final String ruleTip;
}

class SpeedMetric {
  const SpeedMetric({
    required this.key,
    required this.name,
    required this.unit,
    required this.available,
    required this.reliability,
    this.user,
    this.reference,
  });
  final String key;
  final String name;
  final String unit;
  final bool available;
  final String reliability;
  final double? user;
  final double? reference;
}

class SwingEvent {
  const SwingEvent({
    required this.key,
    required this.name,
    required this.frame,
    this.msFromImpact,
  });
  final String key;
  final String name;
  final int frame;
  final double? msFromImpact;
}
