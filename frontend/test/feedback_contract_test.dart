import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/data/feedback_guidance.dart';
import 'package:swing_analysis/data/feedback_language.dart';
import 'package:swing_analysis/data/feedback_measurement_contract.dart';
import 'package:swing_analysis/data/feedback_phase_support.dart';
import 'package:swing_analysis/data/session.dart';
import 'feedback_guidance_test.dart' show sample, repoFor;

void main() {
  tearDown(Session.instance.clear);
  test(
    'normalized units follow stored versions rather than newest defaults',
    () {
      for (final key in [
        'hand_x_from_shoulder',
        'hand_y_from_shoulder',
        'shoulder_x_from_hip',
        'shoulder_y_from_hip',
      ]) {
        expect(
          feedbackFeatureDescription(key, '', modelVersion: '0.2.3-draft'),
          contains('몸통 길이'),
        );
        expect(
          feedbackFeatureDescription(key, '', modelVersion: '0.2.2-draft'),
          contains('어깨너비'),
        );
        expect(feedbackFeatureDescription(key, ''), contains('확인할 수 없어'));
      }
      expect(
        feedbackFeatureDescription(
          'lead_ankle_y_from_hip',
          '',
          modelVersion: '0.2.3-draft',
        ),
        contains('뒷발목'),
      );
      expect(
        feedbackFeatureDescription(
          'lead_ankle_y_from_hip',
          '',
          modelVersion: '0.2-draft',
        ),
        contains('골반 중심'),
      );
      expect(
        feedbackFeatureDescription(
          'lead_ankle_x_from_hip',
          '',
          modelVersion: '0.2.3-draft',
        ),
        contains('어깨너비'),
      );
      expect(
        feedbackReportVersion({
          'model_version': '0.2.3-draft',
          'overall': {'model_version': '0.2.2-draft'},
        }),
        'unknown',
      );
    },
  );

  test(
    'human wording describes observations in the actual phase, not measured center of mass',
    () {
      for (final phase in ['stride', 'transition', 'swing', 'follow']) {
        final hip = feedbackPositionVideoCheck('hip_tilt', phase);
        expect(hip, contains('뒤로 쏠려 보이는지'));
        expect(hip, isNot(contains('무게중심이 뒤로')));
        if (phase != 'follow') expect(hip, isNot(contains('스윙을 마친 뒤')));
        expect(
          hip.split(RegExp(r'[.!?]')).where((x) => x.trim().isNotEmpty).length,
          lessThanOrEqualTo(2),
        );
        final foot = feedbackPositionVideoCheck('lead_ankle_x_from_hip', phase);
        expect(foot, contains('골반'));
        expect(foot, isNot(contains('보폭을 넓')));
      }
      expect(
        feedbackPositionVideoCheck('lead_ankle_x_from_hip', 'swing'),
        '앞발을 어디에 디뎠는지, 디딘 뒤 골반이 어떻게 움직이는지 확인해 보세요.',
      );
    },
  );

  test(
    'hip observation does not diagnose weight shift and practice needs confirmation',
    () {
      expect(
        feedbackPositionVideoCheck('hip_tilt', 'follow'),
        '스윙을 마무리할 때 몸이 흔들리거나 뒤로 쏠려 보이는지 확인해 보세요.',
      );
      final limits = feedbackMeasurementLimits('hip_tilt');
      expect(limits, contains('무게중심 위치를 측정하지 않습니다'));
      expect(limits, contains('체중 이동이나 균형 문제를 확정하지 않습니다'));
      expect(
        feedbackConditionalPractice(
          'hip_tilt',
          'follow',
          'higher',
          eligible: false,
        ),
        isNull,
      );
      final practice = feedbackConditionalPractice(
        'hip_tilt',
        'follow',
        'higher',
        eligible: true,
      );
      expect(practice, startsWith('원본에서'));
      expect(practice, contains('실제 균형 문제가 확인될 때만'));
      expect(practice, contains('추정 임팩트 뒤 마무리하는 동안'));
    },
  );

  test(
    'one/two source frames withhold guidance even when reliability is high',
    () async {
      final r = sample();
      for (final p in r['phases']['phases']) {
        p['user_frames'] = [10, 12];
        p['reliability'] = 'high';
        p['user_duration_ms'] = 2000 / (r['phases']['user_fps'] as num);
      }
      final before = jsonEncode(r);
      final g = buildFeedbackGuidance(r);
      expect(g.issues, isEmpty);
      expect(g.strengths, isEmpty);
      final f = await repoFor(r).fetchFeedback('short');
      for (final p in f.phases.where((x) => x.available)) {
        expect(p.guidanceLimited, isTrue);
        expect(p.guidanceNotice, contains('2프레임'));
        expect(p.deviations, isEmpty);
        expect(p.coachTip, isEmpty);
        final raw = (r['phases']['phases'] as List).firstWhere(
          (x) => x['key'] == p.key,
        );
        expect(p.score, raw['score']);
        expect(p.reliability, 'high');
      }
      expect(
        f.items
            .expand((x) => x.features)
            .any((x) => x.measurementNotices.isNotEmpty),
        isTrue,
      );
      expect(jsonEncode(r), before);
    },
  );

  test(
    'source interval and timestamp validation cannot use 20 resampled points',
    () {
      expect(
        feedbackPhaseSupportNotice({
          'user_frames': [1, 3],
          'series': List.filled(20, 0),
        }, fps: 30),
        contains('2프레임'),
      );
      expect(
        feedbackPhaseSupportNotice({
          'user_frames': [1, 4],
          'user_duration_ms': 100,
        }, fps: 30),
        isNull,
      );
      expect(
        feedbackPhaseSupportNotice({
          'user_frames': [1, 4],
          'user_duration_ms': 500,
        }, fps: 30),
        isNotNull,
      );
      expect(feedbackPhaseSupportNotice({}), isNotNull);
    },
  );

  for (final reason in [
    'model_version_mismatch',
    'reference_model_mismatch',
    'scoring_definition_mismatch',
    'comparison_metadata_missing',
  ]) {
    test(
      'incompatible comparison $reason retains history without score judgements',
      () async {
        Session.instance.signIn('offline');
        final f = await repoFor(
          sample(),
          comparison: {
            'has_previous': true,
            'comparable': false,
            'comparison_reason': reason,
            'overall_previous_score': 10,
            'parts': [
              {'key': 'lead_arm', 'previous_score': 5},
            ],
          },
        ).fetchFeedback('incompatible');
        expect(f.hasPreviousRecord, isTrue);
        expect(f.hasComparison, isFalse);
        expect(f.previousTotalScore, isNull);
        expect(f.items.every((x) => x.previousScore == null), isTrue);
        expect(f.comparisonNotice, contains('이전 기록'));
        expect(f.comparisonNotice, isNot(contains('첫 스윙')));
        expect(f.coaching, isNull);
      },
    );
  }
}
