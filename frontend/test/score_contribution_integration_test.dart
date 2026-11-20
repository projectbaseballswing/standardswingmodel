import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'model_v2_feedback_test.dart' show v2, repository, smallView, noVideo;

void main() {
  Map<String, dynamic> body() {
    final data = v2();
    data['result']['overall']['score_contributions'] = [
      {
        'key': 'rear_arm',
        'name': '오른쪽 팔',
        'share': .8,
        'score': 20,
        'reliability': 'low',
      },
      {
        'key': 'lead_arm',
        'name': '왼쪽 팔',
        'share': .2,
        'score': 63.8,
        'reliability': 'high',
      },
    ];
    return data;
  }

  test(
    'contributions preserve server values and do not change priorities or scores',
    () async {
      final raw = body();
      final snapshot = jsonEncode(raw);
      final previous = await repository(v2()).fetchFeedback('before');
      final feedback = await repository(raw).fetchFeedback('after');
      expect(feedback.totalScore, previous.totalScore);
      expect(
        feedback.items.map((i) => i.currentScore),
        previous.items.map((i) => i.currentScore),
      );
      expect(
        feedback.priorities.map((p) => p.joint),
        previous.priorities.map((p) => p.joint),
      );
      expect(feedback.scoreContributions.map((c) => c.share), [.8, .2]);
      expect(feedback.scoreContributions.first.isLowReliability, isTrue);
      expect(jsonEncode(raw), snapshot);
    },
  );

  testWidgets(
    'mobile contribution card is neutral for low reliability and retains high color',
    (tester) async {
      smallView(tester);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'new',
            repository: repository(body()),
          ),
        ),
      );
      await tester.pumpAndSettle();
      // Several independent scrollables exist in the actual feedback page.
      // The contribution card is already built; reveal its own ancestor.
      await tester.ensureVisible(find.text('점수 영향도'));
      await tester.pumpAndSettle();
      expect(find.textContaining('종합점수가 몇 점 낮아졌다는 뜻은 아니에요'), findsOneWidget);
      expect(find.text('오른쪽 팔\n측정 확인 필요'), findsOneWidget);
      final low = tester.widget<LinearProgressIndicator>(
        find.byKey(const ValueKey('score-contribution-rear_arm')),
      );
      final high = tester.widget<LinearProgressIndicator>(
        find.byKey(const ValueKey('score-contribution-lead_arm')),
      );
      expect(low.value, .8);
      expect(low.valueColor!.value, const Color(0xFFC9CDD3));
      expect(high.valueColor!.value, const Color(0xFF6B7FB3));
      expect(find.text('80%'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'joint feature contribution keeps PR87 values and distinguishes denominator',
    (tester) async {
      smallView(tester);
      final raw = body();
      raw['result']['joints'][0]['contribution'] = .72;
      final feedback = await repository(raw).fetchFeedback('joint-share');
      expect(feedback.items.first.features.single.contribution, .72);
      await tester.pumpWidget(
        MaterialApp(
          home: JointAnalysisScreen(feedback: feedback, videoBuilder: noVideo),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('feature-contribution-lead_elbow_angle')),
        250,
      );
      expect(find.text('72%'), findsOneWidget);
      expect(find.textContaining('종합 화면의 부위별 비중과는 비교 범위가 달라요'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'legacy report without contributions keeps feedback and hides empty chart',
    (tester) async {
      smallView(tester);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'old',
            repository: repository(v2()),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('점수 영향도'), findsNothing);
      expect(find.text('77.3'), findsOneWidget);
      expect(find.text('구간별 피드백 보기'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
