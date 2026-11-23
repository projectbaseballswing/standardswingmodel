import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/data/feedback_guidance.dart';
import 'package:swing_analysis/data/feedback_language.dart';
import 'feedback_guidance_test.dart' show sample, repoFor;

void main() {
  test('weighted score shares do not determine the observation priority', () {
    final report = sample();
    List<String> priorities() => buildFeedbackGuidance(
      report,
    ).issues.map((e) => '${e.joint}/${e.phase}/${e.z}').toList();
    final before = priorities();
    expect(before, isNotEmpty);
    report['overall']['score_contributions'] = [
      {'key': 'rear_arm', 'share': .95, 'reliability': 'low'},
      {'key': 'torso', 'share': .05, 'reliability': 'high'},
    ];
    final snapshot = jsonEncode(report);
    expect(priorities(), before);
    expect(jsonEncode(report), snapshot);
    expect(
      feedbackMeasurementLimits('hip_tilt'),
      contains('점수 영향도 순서나 전문적인 교정 우선순위는 아닙니다'),
    );
  });

  test(
    'joint and phase display mapping contains each video-check instruction once',
    () async {
      final report = sample();
      final repo = repoFor(report);
      final feedback = await repo.fetchFeedback('fixture');
      for (final part in repo.buildPartAnalyses(feedback)) {
        final issue = part.features
            .where((f) => f.evidence?.isIssue == true)
            .firstOrNull;
        if (issue == null) continue;
        final action = issue.evidence!.action;
        final displayed = [
          part.coachComment,
          ...part.features.map((f) => f.ruleComment),
        ].join('\n');
        expect(displayed.split(action).length - 1, 1);
      }
      for (final phase in feedback.phases) {
        expect(phase.ruleTip.split('원본 영상의').length - 1, lessThanOrEqualTo(1));
        expect(phase.ruleTip, isNot(contains('관절이 가려졌다면')));
      }
    },
  );
  test(
    'five feature checks distinguish relative motion and never assert occlusion',
    () {
      for (final key in [
        'hip_tilt',
        'lead_ankle_x_from_hip',
        'hand_y_from_shoulder',
        'lead_elbow_angle',
        'rear_elbow_angle',
      ]) {
        final action = feedbackObservationAction(key, key, '스윙');
        expect(action, contains('처음·중간·끝'));
        expect(action, isNot(contains('가려졌')));
      }
      expect(
        feedbackObservationAction('lead_ankle_x_from_hip', '', '스윙'),
        contains('골반이 움직인 것인지'),
      );
      expect(
        feedbackObservationAction('hand_y_from_shoulder', '', '스윙'),
        contains('양손의 가운데'),
      );
      expect(feedbackMeasurementLimits('hip_tilt'), contains('기준에도 기울기'));
      expect(
        feedbackObservationAction('lead_knee_angle', '', '스윙'),
        contains('앞무릎의 움직임'),
      );
      expect(
        feedbackMeasurementLimits('lead_ankle_x_from_hip'),
        contains('실제 보폭·스탠스 폭·이동 거리가 아니'),
      );
    },
  );

  test(
    'practices require reliable measured differences and supported feature and phase',
    () {
      for (final key in [
        'hip_tilt',
        'lead_ankle_x_from_hip',
        'hand_y_from_shoulder',
        'lead_elbow_angle',
        'rear_elbow_angle',
      ]) {
        for (final phase in ['stride', 'transition', 'swing', 'follow']) {
          for (final direction in ['higher', 'lower']) {
            expect(
              feedbackConditionalPractice(
                key,
                phase,
                direction,
                eligible: false,
              ),
              isNull,
            );
            final advice = feedbackConditionalPractice(
              key,
              phase,
              direction,
              eligible: true,
            )!;
            expect(advice, anyOf(contains('영상에서'), contains('원본에서')));
            expect(advice, contains('배트 없이'));
            expect(advice, isNot(contains('보폭을 넓')));
            expect(advice, isNot(contains('수평으로')));
            expect(advice, isNot(contains('기준과의 차이가 반복해서 확인되면')));
            expect(advice, contains('원하면 추가 촬영'));
            expect(advice, contains('다시 찍을 필요는 없어요'));
          }
          expect(
            feedbackConditionalPractice(key, phase, 'similar', eligible: true),
            isNull,
          );
        }
        expect(
          feedbackConditionalPractice(key, 'unknown', 'higher', eligible: true),
          isNull,
        );
      }
      expect(
        feedbackConditionalPractice(
          'unknown',
          'swing',
          'higher',
          eligible: true,
        ),
        isNull,
      );
      expect(
        feedbackConditionalPractice(
          'hand_y_from_shoulder',
          'stride',
          'higher',
          eligible: true,
        ),
        contains('기준 수치에 맞춰 손을 올리거나 내리지 말고'),
      );
      expect(
        feedbackConditionalPractice(
          'hand_y_from_shoulder',
          'stride',
          'lower',
          eligible: true,
        ),
        contains('기준 수치에 맞춰 손을 올리거나 내리지 말고'),
      );
      expect(
        feedbackConditionalPractice(
          'lead_elbow_angle',
          'transition',
          'higher',
          eligible: true,
        ),
        contains('측정된 차이만큼 각도를 꺾지 마세요'),
      );
      expect(
        feedbackConditionalPractice(
          'lead_elbow_angle',
          'swing',
          'higher',
          eligible: true,
        ),
        contains('자연스럽게 펴지는 팔을 멈추거나'),
      );
    },
  );

  test(
    'hip practice requires an observed balance problem, never a tilt target',
    () {
      for (final direction in ['higher', 'lower']) {
        final practice = feedbackConditionalPractice(
          'hip_tilt',
          'swing',
          direction,
          eligible: true,
        )!;
        expect(practice, contains('실제 균형 문제가 확인될 때만'));
        expect(practice, isNot(contains('줄여')));
        expect(practice, contains('기울기 수치를 맞추기보다'));
      }
    },
  );

  test('medium and a large elbow difference never establish a correction', () {
    final report = sample();
    final elbow = (report['joints'] as List)
        .cast<Map<String, dynamic>>()
        .firstWhere((j) => j['key'] == 'lead_elbow_angle');
    elbow['reliability'] = 'medium';
    elbow['series'] = {
      'user': [176.2, 176.2],
      'reference': [111.6, 111.6],
    };
    final phase = (elbow['phases'] as List)
        .cast<Map<String, dynamic>>()
        .firstWhere((p) => p['phase'] == 'swing');
    phase.addAll({
      'available': true,
      'user_mean': 176.2,
      'reference_mean': 111.6,
      'diff': 64.6,
      'z_score': 3.0,
      'level': 'warning',
      'direction': 'higher',
    });
    final before = jsonEncode(report);
    final evidence = buildFeedbackGuidance(report).observations.firstWhere(
      (e) => e.joint == 'lead_elbow_angle' && e.phase == 'swing',
    );
    expect(evidence.action, contains('실제 팔 모양부터 확인'));
    expect(evidence.action, contains('관절별 분석 그래프'));
    expect(evidence.practice, contains('실제 팔 모양을 확인할 수 있고'));
    expect(evidence.practice, isNot(contains('조금 줄여')));
    expect(evidence.limitations, contains('medium/high는 교정의 타당성을 확인했다는 뜻이 아니'));
    expect(jsonEncode(report), before);
  });

  test(
    'reference chart access requires paired data and never implies a video',
    () {
      for (final series in [
        null,
        {},
        {
          'user': [1],
          'reference': [2],
        },
        {
          'user': [1],
          'reference': [],
        },
        {
          'user': [null],
          'reference': [1],
        },
        {
          'user': [1],
          'reference': [double.nan],
        },
        {
          'user': [1, null],
          'reference': [null, 2],
        },
      ]) {
        expect(feedbackHasReferenceSeries({'series': series}), isFalse);
      }
      expect(
        feedbackHasReferenceSeries({
          'series': {
            'user': [null, 2],
            'reference': [null, 3],
          },
        }),
        isTrue,
      );
      final noChart = feedbackObservationAction('hip_tilt', '', '스윙');
      expect(noChart, contains('비교 가능한 기준 그래프나 기준 영상이 없어'));
      final withChart = feedbackObservationAction(
        'hip_tilt',
        '',
        '스윙',
        hasReferenceSeries: true,
      );
      expect(withChart, contains('기준과의 수치 차이는 관절별 분석 그래프'));
      expect(withChart, contains('기준 영상은 제공되지 않아'));
      expect(withChart, isNot(contains('원본에서 기준과의 차이')));
    },
  );

  test('tracking evidence is not an occlusion or frame-jitter diagnosis', () {
    final report = sample();
    final joint = (report['joints'] as List)
        .cast<Map<String, dynamic>>()
        .firstWhere((j) => j['key'] == 'hand_y_from_shoulder');
    // Unrelated or invalid signals must not diagnose this feature.
    report['overall']['quality'] = {
      'joint_visibility': {
        'left_ankle': .1,
        'left_wrist': -1,
        'right_wrist': 3,
      },
      'max_missing_gap': 9,
    };
    expect(feedbackTrackingNotice(report, joint), isEmpty);
    report['overall']['quality']['joint_visibility']['left_wrist'] = .4;
    final text = feedbackTrackingNotice(report, joint);
    expect(text, contains('전체 영상 평균 추적 지표'));
    expect(text, isNot(contains('가려졌')));
    expect(text, isNot(contains('프레임별')));
    final before = jsonEncode(report);
    final evidence = buildFeedbackGuidance(
      report,
    ).observations.where((e) => e.joint == 'hand_y_from_shoulder');
    expect(evidence, isNotEmpty);
    expect(
      evidence.every((e) => e.practice == null && e.qualityNotice == text),
      isTrue,
    );
    expect(jsonEncode(report), before);
    joint['series'] = {
      'user': [1.0, null, 2.0],
    };
    expect(feedbackTrackingNotice(report, joint), contains('비어 있는 측정값'));
    final foot = (report['joints'] as List)
        .cast<Map<String, dynamic>>()
        .firstWhere((j) => j['key'] == 'lead_ankle_x_from_hip');
    // Shoulder width is also the denominator of the relative ankle measurement.
    report['overall']['quality']['joint_visibility'] = {
      'left_ankle': .9,
      'left_hip': .9,
      'right_hip': .9,
      'left_shoulder': .49,
      'right_shoulder': .9,
    };
    expect(feedbackTrackingNotice(report, foot), contains('평균 추적 지표'));
    report['overall']['quality']['joint_visibility']['left_shoulder'] = .5;
    expect(feedbackTrackingNotice(report, foot), isEmpty);
  });

  test(
    'low reliability, unavailable and inconsistent evidence never authorizes a practice',
    () {
      for (final mutate in <void Function(Map<String, dynamic>)>[
        (j) => j['reliability'] = 'low',
        (j) => j['available'] = false,
        (j) {
          for (final p in j['phases']) {
            p['user_mean'] = null;
          }
        },
      ]) {
        final report = sample();
        final joint = (report['joints'] as List)
            .cast<Map<String, dynamic>>()
            .firstWhere((j) => j['key'] == 'hip_tilt');
        mutate(joint);
        final before = jsonEncode(report);
        final g = buildFeedbackGuidance(report);
        expect(g.observations.any((e) => e.joint == 'hip_tilt'), isFalse);
        expect(
          g.observations.any((e) => e.joint == 'rear_elbow_angle'),
          isFalse,
        );
        expect(g.strengths.every((e) => e.practice == null), isTrue);
        expect(jsonEncode(report), before);
      }
      expect(feedbackReportNotice('일부 관절이 가려져 있습니다.'), contains('원인은 알 수 없어요'));
    },
  );
}
