import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'model_v2_feedback_test.dart' show v2, repository, smallView, noVideo;

void main() {
  Map<String, dynamic> body() {
    final raw = v2();
    raw['result']['overall']['score_contributions'] = [
      {
        'key': 'lead_arm',
        'name': '앞팔',
        'share': .72,
        'score': 70,
        'reliability': 'high',
      },
    ];
    raw['result']['joints'][0]['contribution'] = .63;
    return raw;
  }

  test(
    'main contribution values coexist with evidence and unpublished coaching',
    () async {
      final raw = body();
      final before = jsonEncode(raw);
      final feedback = await repository(raw).fetchFeedback('compat');
      expect(feedback.scoreContributions.single.share, .72);
      expect(feedback.items.first.features.single.contribution, .63);
      expect(feedback.scoreExplanation, isNotEmpty);
      expect(feedback.coaching, isNull);
      expect(jsonEncode(raw), before);
    },
  );

  testWidgets('score explanation and relative contributions both render', (
    tester,
  ) async {
    smallView(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: OverallFeedbackScreen(
          analysisId: 'compat',
          repository: repository(body()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('score-evidence')), findsOneWidget);
    expect(find.text('점수 영향도'), findsOneWidget);
    expect(find.text('72%'), findsOneWidget);
    expect(find.textContaining('종합점수가 몇 점 낮아졌다는 뜻은 아니에요'), findsOneWidget);
  });

  testWidgets('PR87 joint chart keeps independent denominator', (tester) async {
    smallView(tester);
    final feedback = await repository(body()).fetchFeedback('compat');
    await tester.pumpWidget(
      MaterialApp(
        home: JointAnalysisScreen(feedback: feedback, videoBuilder: noVideo),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('63%'), 150);
    expect(find.textContaining('비교 범위가 달라요'), findsOneWidget);
    expect(find.text('63%'), findsOneWidget);
  });
}
