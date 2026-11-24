import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/data/feedback_overview_text.dart';
import 'package:swing_analysis/models/feedback.dart';

FeedbackEvidence item(String key, {bool eligible = true, bool issue = true}) =>
    FeedbackEvidence(
      joint: key,
      part: 'torso',
      name: key,
      phase: 'swing',
      phaseName: '스윙',
      z: 3,
      direction: '기준보다 높게 나타났어요',
      directionCode: 'higher',
      isIssue: issue,
      practiceEligible: eligible,
    );

void main() {
  test(
    'short overview keeps the established practice gate for each feature',
    () {
      for (final key in [
        'hip_tilt',
        'lead_ankle_x_from_hip',
        'hand_y_from_shoulder',
        'lead_elbow_angle',
        'rear_elbow_angle',
      ]) {
        final e = item(key);
        expect(
          overviewVideoCheck(e).length,
          lessThanOrEqualTo(e.action.length),
        );
        expect(
          overviewOptionalPractice(e)!.length,
          lessThan(e.practice!.length),
        );
        expect(overviewOptionalPractice(item(key, eligible: false)), isNull);
        expect(overviewOptionalPractice(item(key, issue: false)), isNull);
      }
      expect(overviewOptionalPractice(item('lead_knee_angle')), isNull);
    },
  );
  test('conditions prohibit an unjustified numeric target or wider stance', () {
    expect(
      overviewOptionalPractice(item('hip_tilt')),
      contains('실제 균형 문제가 확인될 때만'),
    );
    expect(
      overviewOptionalPractice(item('hip_tilt')),
      contains('수평으로 맞추지는 마세요'),
    );
    expect(
      overviewOptionalPractice(item('lead_ankle_x_from_hip')),
      contains('보폭을 넓히려는 연습은 아니'),
    );
    expect(
      overviewVideoCheck(item('lead_elbow_angle')),
      contains('각도 차이만으로 교정하지 않아요'),
    );
    expect(
      overviewOptionalPractice(item('lead_elbow_angle')),
      contains('실제 팔 모양을 확인한 경우에만'),
    );
  });
}
