// Presentation policy only: never recalculates scores or mutates the report.
import '../models/feedback.dart';

bool reliableFeedback(dynamic value) => value == 'high' || value == 'medium';
double? feedbackValue(dynamic v) =>
    v is num && v.isFinite ? v.toDouble() : null;
List<Map<String, dynamic>> feedbackRows(dynamic v) =>
    v is List ? v.whereType<Map<String, dynamic>>().toList() : [];

const _featureParts = <String, String>{
  'lead_elbow_angle': 'lead_arm',
  'hand_x_from_shoulder': 'lead_arm',
  'hand_y_from_shoulder': 'lead_arm',
  'rear_elbow_angle': 'rear_arm',
  'lead_knee_angle': 'lead_leg',
  'lead_ankle_x_from_hip': 'lead_leg',
  'lead_ankle_y_from_hip': 'lead_leg',
  'rear_knee_angle': 'rear_leg',
  'torso_lean': 'torso',
  'shoulder_tilt': 'torso',
  'hip_tilt': 'torso',
  'shoulder_x_from_hip': 'torso',
  'shoulder_y_from_hip': 'torso',
  'shoulder_turn': 'torso',
  'hip_turn': 'torso',
  'hip_shoulder_separation': 'torso',
};
const _phases = {'stride', 'transition', 'swing', 'follow'};
bool _quality(Map<String, dynamic> row) =>
    row['available'] == true && reliableFeedback(row['reliability']);

Map<String, Map<String, dynamic>> _uniqueRows(
  dynamic raw,
  String key,
  Set<String> allowed,
) {
  final rows = feedbackRows(raw);
  final counts = <String, int>{};
  for (final row in rows) {
    final value = row[key];
    if (value is String) counts[value] = (counts[value] ?? 0) + 1;
  }
  return {
    for (final row in rows)
      if (allowed.contains(row[key]) && counts[row[key]] == 1)
        row[key] as String: row,
  };
}

bool _consistentPhase(Map<String, dynamic> p) {
  final user = feedbackValue(p['user_mean']),
      ref = feedbackValue(p['reference_mean']);
  final diff = feedbackValue(p['diff']), z = feedbackValue(p['z_score']);
  if (p['available'] != true ||
      user == null ||
      ref == null ||
      diff == null ||
      z == null ||
      (user - ref - diff).abs() > .151) {
    return false;
  }
  final level = p['level'], direction = p['direction'];
  final az = z.abs();
  if (level == 'good') return az <= 1.01 && direction == 'similar';
  if (level == 'caution' && (az < .99 || az > 2.01)) return false;
  if (level == 'warning' && az < 1.99) return false;
  if (level != 'caution' && level != 'warning') return false;
  // Phase mean diff and mean standardized z may legitimately have different signs.
  return (direction == 'higher' || direction == 'lower') &&
      ((diff > 0) == (direction == 'higher'));
}

String featureDirection(String key, String direction, {String? serverText}) {
  if (direction == 'similar') return '기준 범위와 비슷하게 측정됐어요';
  if (direction != 'higher' && direction != 'lower') return '차이 방향을 확인할 수 없어요';
  const labels = <String, List<String>>{
    'lead_elbow_angle': ['더 펴져 있어요', '더 굽혀져 있어요'],
    'rear_elbow_angle': ['더 펴져 있어요', '더 굽혀져 있어요'],
    'lead_knee_angle': ['더 펴져 있어요', '더 굽혀져 있어요'],
    'rear_knee_angle': ['더 펴져 있어요', '더 굽혀져 있어요'],
    'torso_lean': ['투수 쪽으로 더 기울어 있어요', '포수 쪽으로 더 기울어 있어요'],
    'shoulder_tilt': ['뒤 어깨가 더 내려가 있어요', '앞 어깨가 더 내려가 있어요'],
    'hip_tilt': ['뒤 골반이 더 내려가 있어요', '앞 골반이 더 내려가 있어요'],
    'hand_x_from_shoulder': ['투수 쪽으로 더 나가 있어요', '포수 쪽으로 더 들어가 있어요'],
    'hand_y_from_shoulder': ['더 높아요', '더 낮아요'],
    'lead_ankle_x_from_hip': ['더 멀리 나가 있어요', '덜 나가 있어요'],
    'lead_ankle_y_from_hip': ['더 높이 들려 있어요', '더 낮아요'],
    'shoulder_x_from_hip': ['투수 쪽으로 더 쏠려 있어요', '포수 쪽으로 더 남아 있어요'],
    'shoulder_y_from_hip': ['더 높아요', '더 낮아요'],
    'shoulder_turn': ['더 열려 있어요', '덜 열려 있어요'],
    'hip_turn': ['더 열려 있어요', '덜 열려 있어요'],
    'hip_shoulder_separation': ['꼬임이 덜해요 (어깨가 더 열림)', '꼬임이 더 커요 (어깨가 더 닫힘)'],
  };
  final pair = labels[key];
  if (pair != null) return '기준보다 ${pair[direction == 'higher' ? 0 : 1]}';
  return serverText?.isNotEmpty == true
      ? serverText!
      : '측정값이 기준보다 ${direction == 'higher' ? '커요' : '작아요'} (동작 의미는 확인 필요)';
}

String contextualDirection(
  String key,
  String direction,
  String? phase, {
  String? serverText,
}) =>
    '${phase?.isNotEmpty == true ? '$phase 구간: ' : '구간 정보 미제공: '}'
    '${featureDirection(key, direction, serverText: serverText)}';

String safeTempoWarning(String warning, double? analysisFps) {
  if (!warning.contains('더 높은 fps') || !warning.contains('구간이 짧아')) {
    return warning;
  }
  final frames = RegExp(r'\((\d+)프레임\)').firstMatch(warning)?.group(1);
  return '기준 구간 길이가 분석 FPS${analysisFps == null ? '' : ' $analysisFps'}에서 '
      '${frames == null ? '짧게' : '약 $frames프레임으로'} 환산되어 템포 판정을 보류했어요. '
      '사용자 영상의 프레임 수가 아니며, 촬영 FPS만 높여 해결된다고 보장할 수 없어요.';
}

class FeedbackGuidance {
  const FeedbackGuidance({
    this.issues = const [],
    this.strengths = const [],
    this.eligibleJoints = const {},
    this.observations = const [],
    this.scoreExplanation = '',
  });
  final List<FeedbackEvidence> issues, strengths;
  final List<FeedbackEvidence> observations;
  final Set<String> eligibleJoints;
  final String scoreExplanation;
}

FeedbackGuidance buildFeedbackGuidance(Map<String, dynamic> result) {
  final overall = result['overall'] as Map<String, dynamic>? ?? {};
  final phases = result['phases'] as Map<String, dynamic>? ?? {};
  final groups = _uniqueRows(
    overall['group_scores'],
    'key',
    _featureParts.values.toSet(),
  );
  final phaseMap = _uniqueRows(phases['phases'], 'key', _phases);
  final joints = _uniqueRows(
    result['joints'],
    'key',
    _featureParts.keys.toSet(),
  );
  final eligible = <String>{};
  final all = <FeedbackEvidence>[];
  if (_quality(overall)) {
    for (final j in joints.values) {
      final group = groups[j['body_part']];
      if (!_quality(j) ||
          group == null ||
          !_quality(group) ||
          j['body_part'] != _featureParts[j['key']] ||
          !const ['deg', 'body'].contains(j['unit'])) {
        continue;
      }
      final key = j['key'] as String? ?? '';
      for (final p in _uniqueRows(j['phases'], 'phase', _phases).values) {
        final phase = phaseMap[p['phase']];
        final z = feedbackValue(p['z_score']);
        if (phase == null ||
            !_quality(phase) ||
            z == null ||
            !_consistentPhase(p)) {
          continue;
        }
        final level = p['level'];
        if (!const ['good', 'caution', 'warning'].contains(level)) continue;
        eligible.add(key);
        all.add(
          FeedbackEvidence(
            joint: key,
            part: j['body_part'] as String,
            name: j['name'] as String? ?? key,
            phase: p['phase'] as String,
            phaseName:
                p['phase_name'] as String? ??
                phase['name'] as String? ??
                p['phase'],
            z: z,
            direction: featureDirection(
              key,
              p['direction'] as String? ?? '',
              serverText: p['direction_text'] as String?,
            ),
            isIssue: level != 'good',
          ),
        );
      }
    }
  }
  List<FeedbackEvidence> rank(bool issue) {
    final candidates = all.where((r) => r.isIssue == issue).toList();
    candidates.sort((a, b) {
      final byMagnitude = issue
          ? b.z.abs().compareTo(a.z.abs())
          : a.z.abs().compareTo(b.z.abs());
      if (byMagnitude != 0) return byMagnitude;
      final byJoint = a.joint.compareTo(b.joint);
      return byJoint != 0 ? byJoint : a.phase.compareTo(b.phase);
    });
    final seen = <String>{};
    return candidates.where((r) => seen.add(r.joint)).toList();
  }

  return FeedbackGuidance(
    issues: rank(true),
    strengths: rank(false),
    eligibleJoints: eligible,
    observations: all..sort((a, b) => b.z.abs().compareTo(a.z.abs())),
    scoreExplanation: explainScores(result),
  );
}

String explainScores(Map<String, dynamic> result) {
  final o = result['overall'] as Map<String, dynamic>? ?? {};
  final version = (result['model_version'] ?? o['model_version'] ?? '')
      .toString();
  if (!version.startsWith('0.2')) {
    return '저장된 모델 $version의 점수입니다. 현재 모델의 합산 비율을 과거 점수에 적용하지 않아요.';
  }
  final total = feedbackValue(o['score']),
      posture = feedbackValue(o['posture_score']),
      speed = feedbackValue(o['speed_score']);
  final text = StringBuffer();
  if (posture != null &&
      speed != null &&
      total != null &&
      (posture * .7 + speed * .3 - total).abs() <= .11) {
    text.write(
      '자세 ${feedbackNumber(posture)}점 × 70% + 속도 ${feedbackNumber(speed)}점 × 30%로 종합 ${feedbackNumber(total)}점이 산출됐어요. ',
    );
  } else if (posture != null && speed == null && total == posture) {
    text.write('속도 점수가 없어 자세 점수 ${feedbackNumber(posture)}점만 종합 점수로 제공됐어요. ');
  } else {
    text.write(
      '이 기록에는 현재 합산식을 확인할 구성 점수가 충분하지 않아요. 저장된 종합 점수를 그대로 표시하며 기여도를 추정하지 않아요. ',
    );
  }
  text.write(
    '자세·부위 점수는 관절과 구간의 차이를 프로 선수의 변동 폭에 맞춰 비교한 점수예요. '
    '종합 점수는 부위 점수의 단순 평균이 아니며, 특정 부위가 몇 점을 낮췄는지는 계산하지 않아요. ',
  );
  if (speed != null) {
    text.write(
      '속도 점수는 임팩트 주변 최대 손 속도를 기준 분포와 비교해요. 프로 중앙값은 80점, 상위 10% 기준은 100점이며 실제 타구 속도는 아니에요. ',
    );
  }
  if (o['posture_capped'] == true) {
    text.write('이 기록은 골반·어깨 회전 확인이 모두 미충족되어 자세 점수에 40점 상한이 적용됐어요. ');
  }
  text.write('점수와 차이의 크기는 실제 자세 정확도나 부상·타격 성과를 뜻하지 않아요.');
  return text.toString();
}
