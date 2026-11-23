// Presentation policy only: never recalculates scores or mutates the report.
import '../models/feedback.dart';
import 'feedback_language.dart';

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

// Only advertise the existing chart when paired finite samples can be shown.
// This is a statistical comparison, not an available reference-player video.
bool feedbackHasReferenceSeries(Map<String, dynamic> joint) {
  final series = joint['series'];
  if (series is! Map) return false;
  final user = series['user'], reference = series['reference'];
  if (user is! List ||
      reference is! List ||
      user.length < 2 ||
      user.length != reference.length) {
    return false;
  }
  for (var i = 0; i < user.length; i++) {
    if (feedbackValue(user[i]) != null && feedbackValue(reference[i]) != null) {
      return true;
    }
  }
  return false;
}

// These are normalized pipeline names: left is the lead side. Do not swap again
// for left-handed input. Visibility is a whole-video processed tracking signal,
// not proof of occlusion or frame-wise jitter (filled values can become zero).
String feedbackTrackingNotice(
  Map<String, dynamic> result,
  Map<String, dynamic> joint,
) {
  final series = joint['series'];
  final user = series is Map ? series['user'] : null;
  if (user is List &&
      user.isNotEmpty &&
      user.any((v) => feedbackValue(v) == null)) {
    return '이 관절의 전체 비교 곡선에 비어 있는 측정값이 있어요. 원본에서 관절 위치를 먼저 확인해 주세요.';
  }
  final points = const <String, List<String>>{
    'hip_tilt': ['left_hip', 'right_hip'],
    'lead_ankle_x_from_hip': [
      'left_ankle',
      'left_hip',
      'right_hip',
      'left_shoulder',
      'right_shoulder',
    ],
    'hand_y_from_shoulder': [
      'left_wrist',
      'right_wrist',
      'left_shoulder',
      'right_shoulder',
    ],
    'lead_elbow_angle': ['left_shoulder', 'left_elbow', 'left_wrist'],
    'rear_elbow_angle': ['right_shoulder', 'right_elbow', 'right_wrist'],
  }[joint['key']];
  final overall = result['overall'];
  final quality = overall is Map ? overall['quality'] : null;
  final visibility = quality is Map ? quality['joint_visibility'] : null;
  if (points != null && visibility is Map) {
    for (final point in points) {
      final value = feedbackValue(visibility[point]);
      if (value != null && value >= 0 && value < .5) {
        return '관련 관절의 전체 영상 평균 추적 지표가 낮아요. 원본에서 해당 위치가 잘 보이는지 먼저 확인해 주세요.';
      }
    }
  }
  return '';
}

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
  if (direction == 'similar') return '기준과 비슷하게 나타났어요';
  if (direction != 'higher' && direction != 'lower') return '차이 방향을 확인할 수 없어요';
  const labels = <String, List<String>>{
    'lead_elbow_angle': ['더 펴진 것으로 나타났어요', '더 굽혀진 것으로 나타났어요'],
    'rear_elbow_angle': ['더 펴진 것으로 나타났어요', '더 굽혀진 것으로 나타났어요'],
    'lead_knee_angle': ['더 펴진 것으로 나타났어요', '더 굽혀진 것으로 나타났어요'],
    'rear_knee_angle': ['더 펴진 것으로 나타났어요', '더 굽혀진 것으로 나타났어요'],
    'torso_lean': ['투수 쪽으로 더 기울어 있어요', '포수 쪽으로 더 기울어 있어요'],
    'shoulder_tilt': ['뒤 어깨가 더 내려가 있어요', '앞 어깨가 더 내려가 있어요'],
    'hip_tilt': ['뒤 골반이 더 내려가 있어요', '앞 골반이 더 내려가 있어요'],
    'hand_x_from_shoulder': ['투수 쪽으로 더 나가 있어요', '포수 쪽으로 더 들어가 있어요'],
    'hand_y_from_shoulder': ['높게 나타났어요', '낮게 나타났어요'],
    'lead_ankle_x_from_hip': ['더 멀리 나가 있어요', '덜 나가 있어요'],
    'lead_ankle_y_from_hip': ['더 높이 들려 있어요', '더 낮아요'],
    'shoulder_x_from_hip': ['투수 쪽으로 더 쏠려 있어요', '포수 쪽으로 더 남아 있어요'],
    'shoulder_y_from_hip': ['더 높아요', '더 낮아요'],
    'shoulder_turn': ['더 열려 있어요', '덜 열려 있어요'],
    'hip_turn': ['더 열려 있어요', '덜 열려 있어요'],
    'hip_shoulder_separation': ['꼬임이 덜해요 (어깨가 더 열림)', '꼬임이 더 커요 (어깨가 더 닫힘)'],
  };
  if (key == 'hip_tilt' || key == 'shoulder_tilt') {
    final side = direction == 'higher' ? '뒤쪽' : '앞쪽';
    final subject = key == 'hip_tilt' ? '골반이' : '어깨가';
    return '화면에서 $side $subject 기준보다 낮게 나타났어요';
  }
  if (key == 'lead_ankle_x_from_hip') {
    return '화면에서 골반 기준 앞발이 기준보다 투수 쪽으로 '
        '${direction == 'higher' ? '더' : '덜'} 나와 있었어요';
  }
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
    '${phase?.isNotEmpty == true ? '$phase 구간에서 ' : '구간 정보 미제공: '}'
    '${featureDirection(key, direction, serverText: serverText)}';

String safeTempoWarning(String warning, double? analysisFps) {
  if (!warning.contains('더 높은 fps') || !warning.contains('구간이 짧아')) {
    return feedbackReportNotice(warning);
  }
  final frames = RegExp(r'\((\d+)프레임\)').firstMatch(warning)?.group(1);
  return '기준 구간을 분석 프레임으로 환산하면 ${frames == null ? '너무 짧아' : '약 $frames프레임이라'} '
      '동작 시간 비교를 보류했어요. 사용자 영상의 프레임 수는 아니에요. 촬영 FPS만 높여 해결된다고 보장할 수는 없어요.';
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
            name: feedbackFeatureName(key, j['name'] as String? ?? key),
            phase: p['phase'] as String,
            phaseName:
                p['phase_name'] as String? ??
                phase['name'] as String? ??
                p['phase'],
            z: z,
            directionCode: p['direction'] as String? ?? '',
            practiceEligible: feedbackTrackingNotice(result, j).isEmpty,
            qualityNotice: feedbackTrackingNotice(result, j),
            hasReferenceSeries: feedbackHasReferenceSeries(j),
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
      '이번 종합 점수 ${feedbackNumber(total)}점은 자세 ${feedbackNumber(posture)}점(70%)과 손 속도 ${feedbackNumber(speed)}점(30%)을 합친 결과예요. ',
    );
  } else if (posture != null && speed == null && total == posture) {
    text.write('속도 점수가 없어 자세 점수 ${feedbackNumber(posture)}점만 종합 점수로 제공됐어요. ');
  } else {
    text.write('이 기록은 점수 구성 항목이 부족해 합산 과정을 확인하기 어려워요. 기록된 종합 점수는 그대로 보여드려요. ');
  }
  text.write(
    '자세·부위 점수는 관절 움직임이 기준 선수들의 동작과 얼마나 비슷한지 비교한 결과예요. '
    '종합 점수는 부위 점수의 단순 평균이 아니에요. 한 부위가 몇 점을 낮췄는지도 따로 계산하지 않았어요. ',
  );
  if (speed != null) {
    text.write(
      '손 속도 점수는 추정 임팩트 시점 주변의 최대 손 속도를 기준 선수들과 비교해요. '
      '기준 선수들의 중간 수준을 80점, 상위 10% 수준을 100점으로 환산했어요. 실제 타구 속도는 아니에요. ',
    );
  }
  if (o['posture_capped'] == true) {
    text.write('이 기록은 골반·어깨 회전 확인이 모두 미충족되어 자세 점수에 40점 상한이 적용됐어요. ');
  }
  text.write('점수는 추정한 자세를 비교한 참고 지표예요. 실제 경기 성적이나 부상 위험을 직접 평가한 것은 아니에요.');
  return text.toString();
}
