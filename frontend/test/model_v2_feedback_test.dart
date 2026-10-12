import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/phase_feedback_screen.dart';
import 'package:swing_analysis/theme/app_theme.dart';
import 'package:swing_analysis/widgets/feedback_metrics.dart';

Map<String, dynamic> v2() =>
    jsonDecode(File('test/fixtures/analysis_v2.json').readAsStringSync())
        as Map<String, dynamic>;

Map<String, dynamic> v1() {
  final body = v2();
  final result = body['result'];
  result['model_version'] = '0.1';
  result['overall']['model_version'] = '0.1';
  result['overall']['group_scores'] = [
    {'key': 'pose', 'name': '관절 위치', 'score': 70.5},
  ];
  result['phases'] = {
    'model_version': '0.1',
    'phases': [
      {'key': 'stance', 'name': '준비 자세', 'score': 80, 'user_duration_ms': 1000},
    ],
  };
  result['speed'] = {'model_version': '0.1', 'available': false, 'metrics': []};
  result['joints'] = [result['joints'][0]];
  result['joints'][0]['body_part'] = 'arm';
  result['joints'][0]['phases'] = [
    {'phase': 'stance', 'phase_name': '준비 자세', 'z_score': 0.5},
  ];
  return body;
}

/// 실제로 그려지는 경로를 검사해 결측값을 잇는 선/밴드가 생기지 않는지 확인한다.
class PlotCanvas implements Canvas {
  final paths = <({Path path, Color color, PaintingStyle style})>[];
  final dots = <({Offset at, Color color})>[];
  @override
  void drawPath(Path path, Paint paint) => paths.add((
    path: Path.from(path),
    color: paint.color,
    style: paint.style,
  ));
  @override
  void drawCircle(Offset c, double radius, Paint paint) =>
      dots.add((at: c, color: paint.color));
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

FeedbackRepository repository(
  Map<String, dynamic> body, {
  List<Uri>? requests,
}) {
  final repo = FeedbackRepository(
    api: AnalysisApi(
      client: MockClient((request) async {
        requests?.add(request.url);
        return http.Response(
          jsonEncode(body),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    ),
  );
  addTearDown(repo.dispose);
  return repo;
}

void smallView(WidgetTester tester) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(390, 850);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  test(
    '0.2 maps server scores, groups, phase times, warnings, speed and events',
    () async {
      final requests = <Uri>[];
      final repo = repository(v2(), requests: requests);
      final f = await repo.fetchFeedback('model-v2-test');
      expect(requests.single.path, '/api/analyses/model-v2-test');
      expect(requests.single.queryParameters, {'include_series': 'true'});
      expect(f.modelVersion, '0.2');
      expect(f.totalScore, 77.3);
      expect(f.reliability, 'high');
      expect(f.warnings, ['일부 관절이 가려져 있습니다.']);
      expect(f.items.map((i) => i.currentScore), [63.8, 51.2]);
      expect(f.items.last.features, isEmpty);
      expect(f.items.last.limited, isTrue);
      expect(repo.buildPartAnalyses(f).last.status, JointStatus.limited);
      expect(f.phases.map((p) => p.key), [
        'stride',
        'transition',
        'swing',
        'follow',
      ]);
      expect(f.phases[2].score, 71.4);
      expect(f.phases[0].userDurationMs, 600);
      expect(f.phases[0].referenceDurationMs, 500);
      expect(f.phases[0].tempoRatio, 1.2);
      expect(f.phases[1].tempoLevel, isNull);
      expect(f.phases[1].warnings.single, contains('판정하지'));
      expect(f.phases[2].deviations.single.zScore, 1);
      expect(f.items.first.features.single.phaseScores![2].score, 80);
      expect(f.speedMetrics[1].unit, 'body/s');
      expect(f.speedMetrics[1].user, 26.7);
      expect(f.speedMetrics[1].reference, 18);
      expect(f.speedMetrics[1].reliability, 'medium');
      expect(f.events.map((e) => e.key), [
        'foot_plant',
        'swing_start',
        'follow_end',
      ]);
      expect(f.events.first.msFromImpact, -300);
      expect(f.events.first.frame, 51);
      expect(f.previousTotalScore, isNull);
    },
  );

  for (final failure in ['unavailable', 'missing', 'low']) {
    test(
      'overall $failure never invents zero or drops partial results',
      () async {
        final body = v2();
        final overall = body['result']['overall'];
        if (failure == 'unavailable') overall['available'] = false;
        if (failure == 'missing') overall.remove('score');
        if (failure == 'low') overall['reliability'] = 'low';
        final f = await repository(body).fetchFeedback('model-v2-test');
        expect(f.totalScore, failure == 'low' ? 77.3 : isNull);
        expect(f.phases.length, 4);
        expect(f.speedMetrics.length, 3);
        expect(
          f.summary,
          contains(
            failure == 'low'
                ? '신뢰도'
                : failure == 'missing'
                ? '제공되지'
                : '확인하지 못',
          ),
        );
      },
    );
  }

  test(
    'unavailable groups keep their labels but suppress misleading scores',
    () async {
      final body = v2();
      body['result']['overall']['group_scores'][0]['available'] = false;
      final f = await repository(body).fetchFeedback('model-v2-test');
      expect(f.items.first.label, '왼쪽 팔');
      expect(f.items.first.currentScore, isNull);
      expect(f.items.first.features, isEmpty);
      expect(f.items.first.description, contains('분석할 수 없습니다'));
    },
  );

  test(
    'partial phases preserve measured reference scores and series nulls',
    () async {
      final body = v2();
      final joint = body['result']['joints'][0];
      joint['phases'][0]['available'] = false;
      joint['phases'][0]['z_score'] = 99;
      joint['phases'].removeAt(1);
      joint['phases'][2]['z_score'] = null;
      for (var i = 0; i < 40; i++) {
        joint['series']['user'][i] = null;
      }
      body['result']['phases']['phases'][0]['available'] = false;
      body['result']['phases']['phases'][0]['unavailable_reason'] =
          '앞발 들기를 찾지 못했습니다.';
      final f = await repository(body).fetchFeedback('model-v2-test');
      final feature = f.items.first.features.single;
      expect(feature.phaseScores!.map((p) => p.score), [null, null, 80, null]);
      expect(feature.series!.length, 80);
      expect(feature.series!.take(40).every((s) => s.user == null), isTrue);
      expect(feature.series![40].user, 114);
      expect(feature.series![20].reference, 110);
      expect(f.phases.first.score, isNull);
      expect(f.phases.first.userDurationMs, isNull);
      expect(f.phases.first.tempoLevel, isNull);
      expect(f.phases.first.unavailableReason, contains('찾지 못'));
    },
  );

  test('missing series values and standard deviations stay missing', () async {
    final body = v2();
    final series = body['result']['joints'][0]['series'];
    series['reference'][25] = null;
    series['reference_std'][26] = null;
    series['user'] = [10.0, null, 20.0];
    final feature = (await repository(
      body,
    ).fetchFeedback('model-v2-test')).items.first.features.single;
    expect(feature.series![1].user, isNull);
    expect(feature.series![3].user, isNull);
    expect(feature.series![25].reference, isNull);
    expect(feature.series![26].referenceStd, isNull);
    expect(feature.series![27].referenceStd, 3);
  });

  for (final leftHanded in [true, false]) {
    test(
      'uses server part names for ${leftHanded ? 'left' : 'right'} handed hitter',
      () async {
        final body = v2();
        if (leftHanded) {
          body['result']['overall']['group_scores'][0]['name'] = '오른쪽 팔';
          body['result']['overall']['group_scores'][1]['name'] = '왼쪽 팔';
        }
        final repo = repository(body);
        final f = await repo.fetchFeedback('model-v2-test');
        expect(f.items.first.label, leftHanded ? '오른쪽 팔' : '왼쪽 팔');
        expect(repo.buildPartAnalyses(f).first.isLeft, !leftHanded);
      },
    );
  }

  test('speed unavailable and null measurements never become zero', () async {
    final body = v2();
    body['result']['speed']['metrics'][0]['available'] = false;
    body['result']['speed']['metrics'][1]['user'] = null;
    final f = await repository(body).fetchFeedback('model-v2-test');
    expect(f.speedMetrics[0].user, isNull);
    expect(f.speedMetrics[0].available, isFalse);
    expect(f.speedMetrics[1].user, isNull);
    expect(f.speedMetrics[1].reference, 18);
  });

  test(
    '0.1 keeps its own phase keys and joint data without inventing part scores',
    () async {
      final body = v1();
      final f = await repository(body).fetchFeedback('model-v2-test');
      expect(f.modelVersion, '0.1');
      expect(f.items.first.currentScore, 70.5);
      expect(f.items.last.currentScore, isNull);
      expect(f.items.last.features.single.phaseScores!.single.key, 'stance');
      expect(f.items.last.features.single.eventBasedSeries, isFalse);
      expect(f.phases.single.key, 'stance');
      expect(f.events, isEmpty);
      expect(f.speedMetrics, isEmpty);
    },
  );

  test(
    'new upload polling and historical GET use identical 0.2 mapping',
    () async {
      var calls = 0;
      final repo = FeedbackRepository(
        api: AnalysisApi(
          client: MockClient((request) async {
            expect(request.url.queryParameters['include_series'], 'true');
            final body = v2();
            if (++calls == 1) {
              body['status'] = 'processing';
              body['result'] = null;
            }
            return http.Response(
              jsonEncode(body),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        ),
      );
      addTearDown(repo.dispose);
      final uploaded = await repo.fetchFeedback(
        'model-v2-test',
        firstTime: true,
      );
      expect(calls, 2);
      final historical = await repo.fetchFeedback('model-v2-test');
      expect(calls, 3);
      expect(uploaded.totalScore, historical.totalScore);
      expect(
        uploaded.phases.map((p) => p.score),
        historical.phases.map((p) => p.score),
      );
      expect(uploaded.speedMetrics[1].user, historical.speedMetrics[1].user);
    },
  );

  testWidgets(
    'overall keeps speed and opens actual phase feedback without another GET',
    (tester) async {
      smallView(tester);
      final requests = <Uri>[];
      final repo = repository(v2(), requests: requests);
      final router = GoRouter(
        routes: [
          GoRoute(
            path: '/',
            builder: (_, _) => OverallFeedbackScreen(
              analysisId: 'model-v2-test',
              repository: repo,
            ),
          ),
          GoRoute(
            path: '/phase-feedback',
            builder: (_, state) =>
                PhaseFeedbackScreen(feedback: state.extra as OverallFeedback),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.pumpAndSettle();
      expect(find.text('77.3'), findsOneWidget);
      expect(find.text('일부 관절이 가려져 있습니다.'), findsOneWidget);
      expect(find.text('탭하여 재생'), findsOneWidget);
      expect(find.byType(PhaseMetrics), findsNothing);
      await tester.ensureVisible(find.byType(SpeedFeedbackCard));
      expect(find.text('내 26.7 body/s / 기준 18 body/s'), findsOneWidget);
      expect(find.textContaining('체장 기준 상대속도'), findsOneWidget);
      await tester.tap(find.text('구간별 피드백 보기'));
      await tester.pumpAndSettle();
      expect(find.byType(PhaseFeedbackScreen), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const ValueKey('phase-card-transition')),
      );
      await tester.tap(find.byKey(const ValueKey('phase-card-transition')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.byType(PhaseMetrics), 200);
      expect(
        find.textContaining('0.8배 (소요 시간이 더 짧음) · 템포 판정 보류'),
        findsOneWidget,
      );
      expect(find.textContaining('구간이 짧아'), findsOneWidget);
      expect(find.text('75.1'), findsWidgets);
      await tester.scrollUntilVisible(find.byType(SwingEventsCard), 200);
      expect(find.textContaining('앞발 착지: 임팩트 전 300 ms'), findsOneWidget);
      expect(find.textContaining('팔로우 종료: 임팩트 후 300 ms'), findsOneWidget);
      expect(find.textContaining('로딩 시작:'), findsNothing);
      expect(find.byType(SpeedFeedbackCard), findsNothing);
      await tester.tap(find.byIcon(Icons.arrow_back_ios_new));
      await tester.pumpAndSettle();
      expect(find.byType(OverallFeedbackScreen), findsOneWidget);
      expect(requests.length, 1);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'unavailable overall and low group keep partial feedback on screen',
    (tester) async {
      smallView(tester);
      final body = v2();
      body['result']['overall']['available'] = false;
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'model-v2-test',
            repository: repository(body),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('77.3'), findsNothing);
      expect(find.text('-'), findsOneWidget);
      expect(find.text('참고용 · 분석 제한'), findsOneWidget);
      expect(find.textContaining('51.2점', findRichText: true), findsOneWidget);
      expect(find.byType(PhaseMetrics), findsNothing);
      expect(find.text('구간별 피드백 보기'), findsOneWidget);
      expect(find.textContaining('null'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    '0.1 feedback and joint screens work without 0.2 speed or events',
    (tester) async {
      smallView(tester);
      final repo = repository(v1());
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(analysisId: 'legacy', repository: repo),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('77.3'), findsOneWidget);
      expect(find.byType(PhaseMetrics), findsNothing);
      expect(find.byType(SpeedFeedbackCard), findsNothing);
      expect(tester.takeException(), isNull);
      final feedback = await repo.fetchFeedback('legacy');
      await tester.pumpWidget(
        MaterialApp(home: JointAnalysisScreen(feedback: feedback)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('팔'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('관절별 구간 참고 점수'), 250);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'plots preserve separate measured runs, missing bands and isolated points',
    (tester) async {
      smallView(tester);
      final body = v2();
      final joint = body['result']['joints'][0];
      joint['series']['user'] = [
        for (var i = 0; i < 80; i++)
          if (i < 10 || (i >= 20 && i < 30) || i == 50) 110.0 else null,
      ];
      joint['series']['reference'][25] = null;
      joint['series']['reference_std'][26] = null;
      joint['phases'][1]['available'] = false;
      joint['phases'][3]['z_score'] = null;
      final feedback = await repository(body).fetchFeedback('partial');
      await tester.pumpWidget(
        MaterialApp(home: JointAnalysisScreen(feedback: feedback)),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('관절별 구간 참고 점수'), 250);
      final series = tester.widget<CustomPaint>(
        find.byKey(const ValueKey('feature-series-lead_elbow_angle')),
      );
      final canvas = PlotCanvas();
      series.painter!.paint(canvas, const Size(300, 140));
      final userPaths = canvas.paths
          .where((p) => p.color.toARGB32() == AppColors.primary.toARGB32())
          .toList();
      expect(userPaths.length, 3);
      expect(
        userPaths[0].path.getBounds().right,
        lessThan(userPaths[1].path.getBounds().left),
      );
      expect(
        canvas.dots
            .where((d) => d.color.toARGB32() == AppColors.primary.toARGB32())
            .length,
        1,
      );
      final bands = canvas.paths
          .where((p) => p.style == PaintingStyle.fill)
          .toList();
      expect(bands.length, 2);
      expect(
        bands[0].path.getBounds().right,
        lessThan(bands[1].path.getBounds().left),
      );
      final referencePaths = canvas.paths
          .where(
            (p) =>
                p.style == PaintingStyle.stroke &&
                p.color.toARGB32() != AppColors.primary.toARGB32(),
          )
          .toList();
      expect(referencePaths.length, 2);
      expect(
        referencePaths[0].path.getBounds().right,
        lessThan(referencePaths[1].path.getBounds().left),
      );
      final phases = tester.widget<CustomPaint>(
        find.byKey(const ValueKey('feature-phase-scores-lead_elbow_angle')),
      );
      final phaseCanvas = PlotCanvas();
      phases.painter!.paint(phaseCanvas, const Size(300, 130));
      expect(phaseCanvas.dots.length, 2);
      expect(
        phaseCanvas.paths.every((p) => p.path.computeMetrics().isEmpty),
        isTrue,
        reason: '두 정상 구간 사이의 결측 구간을 선으로 잇지 않아야 한다.',
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'joint screen distinguishes reference scores and keeps low reliability group',
    (tester) async {
      smallView(tester);
      final feedback = await repository(v2()).fetchFeedback('model-v2-test');
      await tester.pumpWidget(
        MaterialApp(home: JointAnalysisScreen(feedback: feedback)),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('관절별 구간 참고 점수'), 250);
      expect(find.textContaining('구간 종합 점수와 다릅니다'), findsOneWidget);
      expect(find.text('스윙 단계별 점수'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.drag(find.byType(ListView), const Offset(0, 1600));
      await tester.pumpAndSettle();
      await tester.tap(find.text('오른쪽 팔'));
      await tester.pumpAndSettle();
      expect(find.text('51.2'), findsWidgets);
      expect(find.textContaining('참고용'), findsWidgets);
      expect(find.textContaining('다음 스윙을 촬영하면 이번 결과와 비교'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
