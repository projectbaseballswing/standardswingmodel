import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_guidance.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'package:swing_analysis/screens/phase_feedback_screen.dart';

Map<String, dynamic> sample() =>
    jsonDecode(File('../api/fixtures/analysis_sample.json').readAsStringSync())
        as Map<String, dynamic>;

FeedbackRepository repoFor(
  Map<String, dynamic> report, {
  Map<String, dynamic>? comparison,
}) {
  final repo = FeedbackRepository(
    api: AnalysisApi(
      client: MockClient(
        (r) async => http.Response(
          jsonEncode(
            r.url.path.endsWith('/comparison')
                ? comparison
                : {
                    'status': 'done',
                    'result': report,
                    'recorded_at': '2026-01-01T00:00:00Z',
                  },
          ),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    ),
  );
  addTearDown(repo.dispose);
  return repo;
}

void main() {
  setUp(() => Session.instance.clear());
  tearDown(() => Session.instance.clear());

  testWidgets(
    'sample guidance, sources and score explanation fit mobile screens',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(360, 800);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final r = sample();
      final repo = repoFor(r);
      final f = await repo.fetchFeedback('fixture');
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(analysisId: 'fixture', repository: repo),
        ),
      );
      await tester.pumpAndSettle();
      // Summary first; component scores and their explanation are opt-in.
      expect(find.text('67.3'), findsOneWidget);
      expect(find.text('자세 점수 · 반영 70%'), findsNothing);
      expect(find.text('속도 점수 · 반영 30%'), findsNothing);
      await tester.ensureVisible(find.byKey(const Key('score-evidence')));
      await tester.tap(find.byKey(const Key('score-evidence')));
      await tester.pumpAndSettle();
      expect(find.text('자세 점수 · 반영 70%'), findsOneWidget);
      expect(find.text('속도 점수 · 반영 30%'), findsOneWidget);
      expect(find.textContaining('80.4점(70%)'), findsOneWidget);
      expect(find.text('AI 코치의 한마디'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(
        MaterialApp(
          home: JointAnalysisScreen(
            feedback: f,
            videoBuilder: (_) => const SizedBox.shrink(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('feature-series-hand_y_from_shoulder')),
        250,
      );
      expect(find.textContaining('생성 출처 미확인'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(
        MaterialApp(home: PhaseFeedbackScreen(feedback: f)),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('분석 결과 안내 · 기본 설명'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.textContaining('원본 영상의 스트라이드'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'unconfirmed score composition has no invented weight or empty reflection label',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(360, 800);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final r = sample();
      r['overall'].remove('speed_score');
      final before = jsonEncode(r);
      final repo = repoFor(r);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(analysisId: 'fixture', repository: repo),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('67.3'), findsOneWidget);
      expect(find.text('자세 점수'), findsNothing);
      await tester.ensureVisible(find.byKey(const Key('score-evidence')));
      await tester.tap(find.byKey(const Key('score-evidence')));
      await tester.pumpAndSettle();
      expect(find.text('자세 점수'), findsOneWidget);
      expect(find.text('속도 점수'), findsOneWidget);
      expect(find.textContaining('점수 · 반영'), findsNothing);
      expect(find.textContaining('점수 구성 항목이 부족해'), findsOneWidget);
      expect(jsonEncode(r), before);
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'priorities use reliable per-phase differences, not array order or lowest body score',
    () {
      final r = sample();
      final before = jsonEncode(r);
      final g = buildFeedbackGuidance(r);
      expect(g.issues, isNotEmpty);
      expect(g.issues.map((e) => e.joint).toSet().length, g.issues.length);
      expect(g.issues.map((e) => e.joint), isNot(contains('rear_elbow_angle')));
      final arm = g.issues.where((e) => e.part == 'lead_arm').first;
      expect(arm.joint, 'hand_y_from_shoulder');
      expect(arm.phase, 'stride');
      expect(arm.action, contains('원본'));
      expect(arm.action, contains('양손의 가운데와 양어깨의 가운데'));
      expect(arm.action, contains('손이 움직인 것인지 어깨 높이가 달라진 것인지'));
      expect(arm.action, isNot(contains('관절이 가려졌다면')));
      expect(jsonEncode(r), before);
      r['joints'] = (r['joints'] as List).reversed.toList();
      expect(
        buildFeedbackGuidance(r).issues.map((e) => '${e.joint}/${e.phase}'),
        g.issues.map((e) => '${e.joint}/${e.phase}'),
      );
    },
  );

  for (final quality in ['low', 'unknown', null]) {
    test('overall $quality quality cannot produce correction candidates', () {
      final r = sample();
      r['overall']['reliability'] = quality;
      expect(buildFeedbackGuidance(r).issues, isEmpty);
      expect(buildFeedbackGuidance(r).strengths, isEmpty);
    });
  }

  test(
    'group, joint and phase gates reject unavailable or non-finite evidence',
    () {
      final r = sample();
      final top = buildFeedbackGuidance(r).issues.first;
      final joint = (r['joints'] as List).firstWhere(
        (j) => j['key'] == top.joint,
      );
      for (final row in joint['phases']) {
        row['z_score'] = double.nan;
      }
      expect(
        buildFeedbackGuidance(r).issues.map((e) => e.joint),
        isNot(contains(top.joint)),
      );
      for (final group in r['overall']['group_scores']) {
        group['reliability'] = 'low';
      }
      expect(buildFeedbackGuidance(r).issues, isEmpty);
      final p = sample();
      for (final phase in p['phases']['phases']) {
        phase['available'] = false;
      }
      expect(buildFeedbackGuidance(p).issues, isEmpty);
    },
  );

  test('semantics distinguish joint angles, heights and unmeasured fields', () {
    expect(featureDirection('lead_elbow_angle', 'higher'), contains('펴진'));
    expect(featureDirection('rear_knee_angle', 'lower'), contains('굽혀진'));
    expect(featureDirection('hand_y_from_shoulder', 'higher'), contains('높게'));
    expect(featureDirection('unknown', 'higher'), contains('동작 의미는 확인 필요'));
    expect(
      featureDirection('lead_elbow_angle', 'unknown'),
      contains('확인할 수 없어요'),
    );
  });

  test(
    'missing explicit availability keeps scores but withholds correction evidence',
    () async {
      final r = sample();
      final score = r['overall']['score'];
      r['overall'].remove('available');
      expect(buildFeedbackGuidance(r).observations, isEmpty);
      final f = await repoFor(r).fetchFeedback('fixture');
      expect(f.totalScore, score);
      expect(f.priorities, isEmpty);
    },
  );

  test('duplicate, unknown and inconsistent evidence fails closed', () {
    for (final mode in [
      'duplicate_joint',
      'unknown_joint',
      'wrong_part',
      'duplicate_phase',
      'bad_diff',
      'bad_level',
      'missing_available',
    ]) {
      final r = sample();
      final first = buildFeedbackGuidance(r).issues.first;
      final j = (r['joints'] as List).firstWhere(
        (j) => j['key'] == first.joint,
      );
      switch (mode) {
        case 'duplicate_joint':
          r['joints'].add(jsonDecode(jsonEncode(j)));
        case 'unknown_joint':
          j['key'] = 'head_direction';
        case 'wrong_part':
          j['body_part'] = 'unknown';
        case 'duplicate_phase':
          final p = (j['phases'] as List).firstWhere(
            (p) => p['phase'] == first.phase,
          );
          j['phases'].add(jsonDecode(jsonEncode(p)));
        case 'bad_diff':
          for (final p in j['phases']) {
            p['diff'] = 999999;
          }
        case 'bad_level':
          for (final p in j['phases']) {
            p['level'] = 'good';
            p['z_score'] = 20;
          }
        case 'missing_available':
          j.remove('available');
      }
      expect(
        buildFeedbackGuidance(r).observations.any(
          (e) => e.joint == first.joint && e.phase == first.phase,
        ),
        isFalse,
        reason: mode,
      );
    }
  });

  test('opposite diff and z signs remain valid when the phase means agree', () {
    final r = sample();
    final first = buildFeedbackGuidance(r).issues.first;
    final j = (r['joints'] as List).firstWhere((j) => j['key'] == first.joint);
    final p = (j['phases'] as List).firstWhere(
      (p) => p['phase'] == first.phase,
    );
    p['z_score'] = -p['z_score'];
    expect(
      buildFeedbackGuidance(r).observations.any(
        (e) => e.joint == first.joint && e.phase == first.phase,
      ),
      isTrue,
    );
  });

  for (final status in [
    'approved',
    'review_required',
    'blocked',
    'generation_failed',
  ]) {
    testWidgets('synthetic coaching lifecycle UI: $status', (tester) async {
      final r = sample();
      r['coaching_review'] = {
        'status': status,
        'source': status == 'approved' ? 'openai' : 'rules',
        'display_allowed': status == 'approved',
      };
      r['coaching'] = {
        'overall_summary': 'SYNTHETIC REVIEWED SUMMARY',
        'overall_coach': 'SYNTHETIC REVIEWED ACTION',
        'parts': [],
      };
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'fixture',
            repository: repoFor(r),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('coaching-review-notice')),
      );
      expect(
        find.text('SYNTHETIC REVIEWED ACTION'),
        status == 'approved' ? findsOneWidget : findsNothing,
      );
      if (status != 'approved') {
        expect(find.textContaining('SYNTHETIC REVIEWED SUMMARY'), findsNothing);
        expect(find.text('가장 먼저 확인할 동작'), findsOneWidget);
      }
      expect(tester.takeException(), isNull);
    });
  }

  test(
    'score explanation reconciles stored composition and withholds legacy formula',
    () {
      final r = sample();
      final text = explainScores(r);
      expect(text, contains('80.4점(70%)과 손 속도 36.6점(30%)'));
      expect(text, contains('단순 평균이 아니에요'));
      r['overall'].remove('speed_score');
      expect(explainScores(r), isNot(contains('(70%)')));
      r['overall']['score'] = r['overall']['posture_score'];
      expect(explainScores(r), contains('자세 점수 80.4점만'));
      r['model_version'] = '0.1';
      expect(explainScores(r), contains('과거 점수에 적용하지'));
    },
  );

  test('reference-frame warning is not a higher capture FPS prescription', () {
    const old = '구간이 짧아(3프레임) 템포를 판정하지 않았습니다. 더 높은 fps 로 촬영하면 판정할 수 있습니다.';
    final text = safeTempoWarning(old, 30.15);
    expect(text, contains('기준 구간'));
    expect(text, contains('약 3프레임'));
    expect(text, contains('사용자 영상의 프레임 수는 아니에요'));
    expect(safeTempoWarning('추적 품질 부족', 60), '추적 품질 부족');
  });

  test(
    'repository removes low-confidence deviations while preserving scores and raw report',
    () async {
      final r = sample();
      final before = jsonEncode(r);
      final repo = repoFor(r);
      final f = await repo.fetchFeedback('fixture');
      expect(f.totalScore, r['overall']['score']);
      expect(f.postureScore, r['overall']['posture_score']);
      expect(f.speedScore, r['overall']['speed_score']);
      expect(f.hasComparison, isFalse);
      expect(f.previousTotalScore, isNull);
      for (final p in f.phases) {
        expect(
          p.deviations.map((d) => d.joint),
          isNot(contains('rear_elbow_angle')),
        );
        final raw = (r['phases']['phases'] as List).firstWhere(
          (v) => v['key'] == p.key,
        );
        expect(p.score, raw['score']);
      }
      for (final item in f.items) {
        final raw = (r['overall']['group_scores'] as List).firstWhere(
          (v) => v['key'] == item.key,
        );
        expect(item.currentScore, raw['score']);
      }
      expect(f.coachSource, contains('기본 설명'));
      final parts = repo.buildPartAnalyses(f);
      expect(
        parts.map((p) => p.summary).join(),
        isNot(contains('각도가 기준 스윙과 가깝게 유지')),
      );
      expect(
        parts.expand((p) => p.points).join(),
        isNot(contains('같은 리듬으로 가져가')),
      );
      expect(jsonEncode(r), before);
    },
  );

  test(
    'stored coaching is unverified even when its text looks like GPT',
    () async {
      final r = sample();
      r['coaching'] = {'overall_summary': '저장 요약', 'overall_coach': '저장 문구'};
      final f = await repoFor(r).fetchFeedback('fixture');
      expect(f.coachSource, contains('기본 설명'));
      expect(f.summarySource, contains('기본 설명'));
      expect(f.coaching, isNull);
      expect(f.coachingReview.canDisplay, isFalse);
      r['overall']['reliability'] = 'low';
      final low = await repoFor(r).fetchFeedback('fixture');
      expect(low.coaching, isNull);
      expect(low.priorities, isEmpty);
    },
  );

  test(
    'a good average does not erase local deviations or assert tempo',
    () async {
      final r = sample();
      for (final g in r['overall']['group_scores']) {
        g['score'] = 95.0;
      }
      final repo = repoFor(r);
      final f = await repo.fetchFeedback('fixture');
      final arm = repo
          .buildPartAnalyses(f)
          .firstWhere((p) => p.key == 'lead_arm');
      expect(arm.pointsTitle, '먼저 확인할 움직임');
      expect(arm.summary, contains('순간마다 자세 차이는 있을'));
      expect(arm.points.first, contains('스트라이드'));
    },
  );
}
