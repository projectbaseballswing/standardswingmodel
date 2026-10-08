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
    this.phaseScores,
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

  /// 스윙 구간별(0~100) 현재 점수. [SwingPhase] 순서(4개).
  /// 서버 `phases` 의 구간별 z_score 를 점수로 환산한 실제 값.
  /// 구간 데이터가 없으면(반복 피드백 샘플 등) null.
  final List<int>? phaseScores;

  /// 이전 대비 증감. 첫 피드백이면 null.
  int? get delta =>
      previousScore == null ? null : currentScore - previousScore!;
}

// ---------------------------------------------------------------------------
// 관절별 분석(상세 피드백) 모델
// ---------------------------------------------------------------------------

/// 스윙 4단계. 단계별 점수 그래프의 x축.
///
/// [key] 는 백엔드가 주는 구간 키(`JointFeedback.phases[].phase`)와 같다.
enum SwingPhase {
  stance('stance', 'Stance', '준비 자세'),
  load('load', 'Load', '로딩'),
  swing('swing', 'Swing', '스윙'),
  followThrough('follow_through', 'Follow-through', '팔로우스루');

  const SwingPhase(this.key, this.en, this.ko);

  /// 백엔드 구간 키.
  final String key;

  /// 영문 라벨(윗줄).
  final String en;

  /// 국문 라벨(아랫줄).
  final String ko;
}

/// 관절의 상태.
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

/// 관절 하나의 상세 분석.
///
/// 종합 피드백([OverallFeedback.items])을 바탕으로 만든다. 단계별 점수와 코치
/// 문장은 아직 백엔드가 주지 않아 프론트에서 임시로 채운다.
class JointAnalysis {
  const JointAnalysis({
    required this.label,
    required this.part,
    required this.status,
    required this.currentScore,
    required this.currentPhaseScores,
    required this.summary,
    required this.coachComment,
    required this.pointsTitle,
    required this.points,
    this.previousScore,
    this.previousPhaseScores,
  });

  /// 화면에 보이는 이름. 예) "오른쪽 팔".
  final String label;

  /// 아이콘·인체 그림 영역 구분용 부위.
  final BodyPart part;

  /// 이전 대비 변화 상태.
  final JointStatus status;

  /// 이번 점수.
  final int currentScore;

  /// 단계별 현재 스윙 점수(6개, [SwingPhase] 순서).
  final List<int> currentPhaseScores;

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

  /// 단계별 이전 스윙 점수(6개). 비교 대상이 없으면 null.
  final List<int>? previousPhaseScores;

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
