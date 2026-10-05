/// 종합 피드백 화면에서 쓰는 데이터 모델.
///
/// 한 화면이 두 상태를 모두 표현한다.
///  - 첫 피드백   : 비교할 이전 스윙이 없다. [previousTotalScore] 가 null.
///                  부위는 프로 기준 대비 [level] 로 "잘한 / 개선 필요" 를 나눈다.
///  - 반복 피드백 : 이전 스윙과 비교한다. [previousTotalScore] 와 각 항목의
///                  [previousScore] 로 증감(→, +8/-9)을 보여주고
///                  "개선 / 개선 필요 / 유지" 로 나눈다.
library;

/// 신체 부위. 아이콘·색 구분에만 쓴다.
enum BodyPart { leg, arm, torso }

/// 부위별 피드백 한 줄.
class FeedbackItem {
  const FeedbackItem({
    required this.label,
    required this.part,
    required this.currentScore,
    required this.description,
    this.previousScore,
    this.level = 'good',
  });

  /// 화면에 보이는 이름. 예) "왼쪽 다리", "오른쪽 팔", "몸통".
  final String label;

  /// 아이콘·색 구분용 부위.
  final BodyPart part;

  /// 이번 점수. 예) 80.
  final int currentScore;

  /// 설명 문구(2줄 내외).
  final String description;

  /// 이전 점수. 첫 피드백이면 null → 증감 화살표를 숨긴다.
  final int? previousScore;

  /// 프로 기준 대비 수준. 'good' | 'caution' | 'warning'.
  /// 첫 피드백에서 "잘한 / 개선 필요" 를 나누는 기준(백엔드 z-score 판정값).
  final String level;

  /// 이전 대비 증감. 첫 피드백이면 null.
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
