import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/data/feedback_guidance.dart';
import 'package:swing_analysis/data/feedback_language.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';

import 'feedback_guidance_test.dart' show sample, repoFor;

void main() {
  tearDown(Session.instance.clear);

  test(
    'display descriptions distinguish image geometry from coaching targets',
    () {
      final hip = feedbackFeatureDescription('hip_tilt', 'legacy');
      expect(hip, contains('화면'));
      expect(hip, contains('수평으로 맞추라는 뜻은 아니에요'));
      final foot = feedbackFeatureDescription(
        'lead_ankle_x_from_hip',
        '스트라이드 폭.',
        modelVersion: '0.2.3-draft',
      );
      expect(foot, contains('실제 보폭·스탠스 폭·이동 거리가 아니에요'));
      expect(foot, isNot(contains('스트라이드 폭.')));
      expect(
        feedbackFeatureDescription('unknown', 'original meaning'),
        'original meaning',
      );
      expect(
        feedbackFeatureDescription('hip_shoulder_separation', ''),
        contains('판단할 수는 없어요'),
      );
    },
  );

  test(
    'directions and Korean particles work for dynamic joint and phase combinations',
    () {
      for (final phase in ['스트라이드', '착지 후 준비', '스윙', '팔로우스루']) {
        for (final key in [
          'lead_elbow_angle',
          'rear_elbow_angle',
          'hip_tilt',
          'hand_y_from_shoulder',
          'lead_ankle_x_from_hip',
        ]) {
          for (final direction in ['higher', 'lower', 'similar']) {
            final text = feedbackObservation(
              key,
              key,
              phase,
              featureDirection(key, direction),
            );
            expect(text, contains('$phase 구간 평균'));
            expect(text, isNot(contains('..')));
            expect(text, isNot(contains('구간 평균의')));
            expect(text, isNot(contains('에서 화면에서')));
            expect(text, isNot(contains('보폭을 넓')));
          }
        }
      }
      expect(feedbackTopic('팔꿈치'), '팔꿈치는');
      expect(feedbackTopic('골반'), '골반은');
      expect(featureDirection('lead_elbow_angle', 'higher'), contains('펴진'));
      expect(featureDirection('lead_elbow_angle', 'lower'), contains('굽혀진'));
      expect(featureDirection('hip_tilt', 'higher'), contains('뒤쪽 골반이'));
      expect(featureDirection('hip_tilt', 'lower'), contains('앞쪽 골반이'));
      expect(featureDirection('hand_y_from_shoulder', 'lower'), contains('낮게'));
    },
  );

  test(
    'rotation notices retain numbers without asserting force or exact event truth',
    () {
      expect(
        feedbackReportNotice('착지부터 임팩트까지 골반이 61도 돌아갔어요.'),
        '착지부터 추정 임팩트 시점까지 골반이 약 61도 돌아간 것으로 나타났어요.',
      );
      expect(
        feedbackReportNotice('임팩트까지 꼬임이 풀리면서 어깨가 골반을 따라 돌았어요.'),
        contains('정확한 회전 순서까지 판단할 수는 없어요'),
      );
      expect(feedbackReportNotice('알 수 없는 기존 안내'), '알 수 없는 기존 안내');
    },
  );

  test('reliable comparisons preserve the original two-point band', () {
    FeedbackItem item(double score, String reliability) => FeedbackItem(
      key: 'lead_arm',
      label: '앞팔',
      part: BodyPart.arm,
      currentScore: score,
      previousScore: 60,
      reliability: reliability,
      description: '',
      features: const [
        FeatureAnalysis(
          key: 'lead_elbow_angle',
          name: '팔꿈치',
          level: 'good',
          direction: 'similar',
        ),
      ],
    );
    for (final reliability in ['high', 'medium']) {
      expect(
        item(70, reliability).status(hasComparison: true),
        JointStatus.improved,
      );
      expect(
        item(50, reliability).status(hasComparison: true),
        JointStatus.worsened,
      );
      expect(
        item(62, reliability).status(hasComparison: true),
        JointStatus.unchanged,
      );
    }
    for (final score in [10.0, 60.0, 95.0]) {
      expect(
        item(score, 'low').status(hasComparison: true),
        JointStatus.limited,
      );
      expect(
        item(score, 'low').status(hasComparison: false),
        JointStatus.limited,
      );
    }
  });

  test(
    'low body reliability also withholds otherwise reliable joint advice',
    () async {
      final report = sample();
      final torso = (report['overall']['group_scores'] as List).firstWhere(
        (g) => g['key'] == 'torso',
      );
      torso['reliability'] = 'low';
      final before = jsonEncode(report);
      final repo = repoFor(report);
      addTearDown(repo.dispose);
      final feedback = await repo.fetchFeedback('fixture');
      final item = feedback.items.firstWhere((i) => i.key == 'torso');
      expect(item.currentScore, torso['score']);
      expect(item.features, isEmpty);
      expect(item.status(hasComparison: false), JointStatus.limited);
      expect(feedback.priorities.any((e) => e.part == 'torso'), isFalse);
      expect(
        feedback.items.any((i) => i.key != 'torso' && i.features.isNotEmpty),
        isTrue,
      );
      expect(jsonEncode(report), before);
    },
  );

  testWidgets(
    'low-reliability drop is neutral in overall and joint screens; actual scores retained',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      Session.instance.signIn('local-test');
      final report = sample();
      final rear = (report['overall']['group_scores'] as List).firstWhere(
        (g) => g['key'] == 'rear_arm',
      );
      rear['score'] = 20.0;
      rear['reliability'] = 'low';
      report['overall']['group_scores'] = [rear];
      report['joints'] = (report['joints'] as List)
          .where((j) => j['body_part'] == 'rear_arm')
          .toList();
      final before = jsonEncode(report);
      final repo = repoFor(
        report,
        comparison: {
          'has_previous': true,
          'comparable': true,
          'overall_previous_score': 70,
          'parts': [
            {'key': 'rear_arm', 'previous_score': 90},
          ],
        },
      );
      final f = await repo.fetchFeedback('fixture');
      expect(jsonEncode(report), before);
      expect(f.items.single.currentScore, 20);
      expect(f.items.single.previousScore, 90);
      expect(repo.buildPartAnalyses(f).single.status, JointStatus.limited);
      expect(f.priorities.any((e) => e.part == 'rear_arm'), isFalse);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(analysisId: 'fixture', repository: repo),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('측정 확인 필요'), findsOneWidget);
      expect(find.text('개선이 필요한 부분'), findsNothing);
      expect(find.textContaining('이전 90점 · 현재 20점'), findsOneWidget);
      expect(find.textContaining('(-70)'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(
        MaterialApp(
          home: JointAnalysisScreen(
            feedback: f,
            videoBuilder: (_) => const SizedBox(height: 80),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('이전 점수 · 참고'), findsOneWidget);
      expect(find.text('현재 점수 · 참고'), findsOneWidget);
      expect(find.text('점수 변화'), findsNothing);
      expect(find.text('개선 필요'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
