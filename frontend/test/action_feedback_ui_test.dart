import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/feedback_overview_text.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';

import 'feedback_guidance_test.dart' show sample, repoFor;
import 'model_v2_feedback_test.dart' show smallView;

/// Keep real measurement/reliability gates while isolating a known target.
Map<String, dynamic> focusedReport([String key = 'hip_tilt']) {
  final report = sample();
  report['joints'] = (report['joints'] as List)
      .where((joint) => joint['key'] == key)
      .toList();
  report['overall']['quality'] = {'warnings': []};
  return report;
}

void main() {
  setUp(() => Session.instance.clear());
  tearDown(() => Session.instance.clear());

  testWidgets(
    'mobile rules card separates observation, check and optional practice',
    (tester) async {
      smallView(tester);
      final report = focusedReport();
      final before = jsonEncode(report);
      final repo = repoFor(report);
      final feedback = await repo.fetchFeedback('action-ui');
      final first = feedback.priorities.first;
      expect(first.joint, 'hip_tilt');
      expect(first.practice, isNotNull);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'action-ui',
            repository: repo,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('coaching-review-notice')),
      );
      expect(find.text('잘한 점 · 기준과 가까운 구간'), findsOneWidget);
      expect(find.text('가장 먼저 확인할 동작'), findsOneWidget);
      expect(find.text('영상 확인 방법'), findsOneWidget);
      expect(find.text('선택적 연습'), findsOneWidget);
      expect(find.text(overviewVideoCheck(first)), findsOneWidget);
      expect(find.text(overviewOptionalPractice(first)!), findsOneWidget);
      expect(find.text(first.action), findsNothing);
      expect(find.text(first.practice!), findsNothing);
      expect(first.practice, contains('실제 균형 문제가 확인될 때만'));
      expect(first.practice, contains('다시 찍을 필요는 없어요'));
      expect(first.action, contains('기준 영상은 제공되지 않아'));
      expect(find.text('인식 품질 확인'), findsNothing);
      expect(find.text('원본에서 먼저 확인'), findsNothing);
      expect(find.text('원본을 보는 방법'), findsNothing);
      expect(find.text(first.limitations), findsNothing);
      final details = find.byKey(const Key('feedback-measurement-limits'));
      await tester.ensureVisible(details);
      await tester.tap(details);
      await tester.pumpAndSettle();
      expect(find.text(first.action), findsOneWidget);
      expect(find.text(first.practice!), findsOneWidget);
      expect(find.text(first.limitations), findsOneWidget);
      expect(first.limitations, contains('medium/high는 교정의 타당성을 확인했다는 뜻이 아니'));
      expect(jsonEncode(report), before);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'missing comparison series does not advertise a reference chart',
    (tester) async {
      smallView(tester);
      final report = focusedReport();
      report['joints'][0].remove('series');
      final repo = repoFor(report);
      final feedback = await repo.fetchFeedback('no-reference-series');
      final first = feedback.priorities.first;
      expect(first.hasReferenceSeries, isFalse);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'no-reference-series',
            repository: repo,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('coaching-review-notice')),
      );
      expect(find.text(overviewVideoCheck(first)), findsOneWidget);
      expect(find.text(first.action), findsNothing);
      final details = find.byKey(const Key('feedback-measurement-limits'));
      await tester.ensureVisible(details);
      await tester.tap(details);
      await tester.pumpAndSettle();
      expect(find.text(first.action), findsOneWidget);
      expect(first.action, contains('비교 가능한 기준 그래프나 기준 영상이 없어'));
      expect(first.action, isNot(contains('그래프에서 확인할 수 있어요')));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'joint graph identifies measured, reference and variation without changing data',
    (tester) async {
      smallView(tester);
      final report = focusedReport();
      final before = jsonEncode(report);
      final repo = repoFor(report);
      final feedback = await repo.fetchFeedback('chart-legend');
      await tester.pumpWidget(
        MaterialApp(
          home: JointAnalysisScreen(
            feedback: feedback,
            videoBuilder: (_) => const SizedBox(height: 50),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('몸통').first);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('━ 내 측정값'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
      expect(find.text('━ 내 측정값'), findsOneWidget);
      expect(find.text('━ 기준 평균'), findsOneWidget);
      expect(find.text('옅은 영역: 기준 ±편차'), findsOneWidget);
      expect(jsonEncode(report), before);
      expect(tester.takeException(), isNull);
    },
  );

  for (final condition in ['low', 'missing']) {
    testWidgets(
      '$condition measurements do not produce a conditional exercise',
      (tester) async {
        smallView(tester);
        final report = focusedReport();
        if (condition == 'low') {
          report['joints'][0]['reliability'] = 'low';
        } else {
          for (final phase in report['joints'][0]['phases']) {
            phase.remove('user_mean');
          }
        }
        final repo = repoFor(report);
        final feedback = await repo.fetchFeedback('limited-action-ui');
        expect(feedback.priorities, isEmpty);
        await tester.pumpWidget(
          MaterialApp(
            home: OverallFeedbackScreen(
              analysisId: 'limited-action-ui',
              repository: repo,
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.ensureVisible(
          find.byKey(const Key('coaching-review-notice')),
        );
        expect(find.text('선택적 연습'), findsNothing);
        expect(
          find.byKey(const Key('feedback-measurement-limits')),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('known curve gaps show a quality note and defer practice', (
    tester,
  ) async {
    smallView(tester);
    final report = focusedReport();
    report['joints'][0]['series']['user'][0] = null;
    final before = jsonEncode(report);
    final repo = repoFor(report);
    final feedback = await repo.fetchFeedback('quality-action-ui');
    final first = feedback.priorities.first;
    expect(first.qualityNotice, isNotEmpty);
    expect(first.practice, isNull);
    await tester.pumpWidget(
      MaterialApp(
        home: OverallFeedbackScreen(
          analysisId: 'quality-action-ui',
          repository: repo,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('coaching-review-notice')));
    expect(find.text('영상 확인 방법'), findsOneWidget);
    expect(find.text('인식 품질 확인'), findsOneWidget);
    expect(find.text(first.qualityNotice), findsOneWidget);
    expect(find.text('선택적 연습'), findsNothing);
    expect(jsonEncode(report), before);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'approved GPT text keeps its existing card instead of rule exercises',
    (tester) async {
      smallView(tester);
      final report = focusedReport();
      report['coaching_review'] = {
        'status': 'approved',
        'source': 'openai',
        'display_allowed': true,
        'reason': 'human_review_completed',
      };
      report['coaching'] = {
        'overall_summary': 'SYNTHETIC APPROVED SUMMARY',
        'overall_coach': 'SYNTHETIC APPROVED ACTION',
        'coach_feedback': {
          'problem': 'SYNTHETIC PROBLEM',
          'cause': 'SYNTHETIC CAUSE',
          'fix': 'SYNTHETIC FIX',
          'drill': 'SYNTHETIC DRILL',
        },
        'parts': [],
      };
      final before = jsonEncode(report);
      final repo = repoFor(report);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'approved-ui',
            repository: repo,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('coaching-review-notice')),
      );
      expect(find.text('검토가 완료된 GPT 코칭입니다.'), findsOneWidget);
      expect(find.text('SYNTHETIC APPROVED ACTION'), findsOneWidget);
      expect(find.text('SYNTHETIC FIX'), findsOneWidget);
      expect(find.text('SYNTHETIC DRILL'), findsOneWidget);
      expect(find.text('선택적 연습'), findsNothing);
      expect(find.text('영상 확인 방법'), findsNothing);
      expect(
        find.byKey(const Key('feedback-measurement-limits')),
        findsNothing,
      );
      expect(jsonEncode(report), before);
      expect(tester.takeException(), isNull);
    },
  );
}
