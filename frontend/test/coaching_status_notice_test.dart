import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'model_v2_feedback_test.dart' show v2, repository, smallView;

void main() {
  // The backend HTTP tests assert against this exact public metadata too.
  final cases =
      jsonDecode(
            File(
              'test/fixtures/coaching_review_notices.json',
            ).readAsStringSync(),
          )
          as Map<String, dynamic>;
  for (final entry in cases.entries) {
    testWidgets('public API notice and GPT display gate: ${entry.key}', (
      tester,
    ) async {
      final row = entry.value as Map<String, dynamic>;
      final review = CoachingReview.fromJson(row['review']);
      final allowed = entry.key == 'approved';
      expect(review.reason, row['review']['reason']);
      expect(review.notice, row['notice']);
      expect(review.canDisplay, allowed);
      final body = v2();
      body['result']['coaching_review'] = row['review'];
      body['result']['coaching'] = {
        'overall_summary': 'SYNTHETIC APPROVED SUMMARY',
        'overall_coach': 'SYNTHETIC APPROVED ACTION',
        'parts': [],
      };
      final repo = repository(body);
      final feedback = await repo.fetchFeedback('notice');
      expect(feedback.coachingReview.notice, row['notice']);
      expect(feedback.coaching != null, allowed);
      smallView(tester);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(analysisId: 'notice', repository: repo),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('coaching-review-notice')),
      );
      expect(find.text(row['notice'] as String), findsOneWidget);
      expect(
        find.text('SYNTHETIC APPROVED ACTION'),
        allowed ? findsOneWidget : findsNothing,
      );
      expect(tester.takeException(), isNull);
    });
  }

  test(
    'missing or malformed metadata never throws or implies generation failure',
    () {
      for (final raw in <dynamic>[
        null,
        false,
        7,
        'invalid-json',
        [],
        {},
        {'status': [], 'source': {}, 'display_allowed': 'true', 'reason': []},
        {'status': 'unknown', 'reason': 'generation_failed'},
        {'status': 'approved', 'source': 'rules', 'display_allowed': true},
      ]) {
        final review = CoachingReview.fromJson(raw);
        expect(review.canDisplay, isFalse);
        expect(review.notice, '현재는 기본 피드백을 제공하고 있어요.');
      }
      for (final reason in <dynamic>[
        null,
        false,
        9,
        [],
        {},
        'private-provider-detail',
        'approved',
      ]) {
        final review = CoachingReview.fromJson({
          'status': 'generation_failed',
          'reason': reason,
        });
        expect(review.notice, '현재는 기본 피드백을 제공하고 있어요.');
        expect(review.canDisplay, isFalse);
      }
      expect(
        CoachingReview.fromJson({'status': 'generation_failed'}).notice,
        '현재는 기본 피드백을 제공하고 있어요.',
      );
    },
  );
}
