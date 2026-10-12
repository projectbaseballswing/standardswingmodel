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
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/phase_feedback_screen.dart';
import 'package:swing_analysis/widgets/feedback_metrics.dart';
import 'package:swing_analysis/widgets/swing_video.dart';

import 'fake_video_controller.dart';

Map<String, dynamic> report() =>
    jsonDecode(File('test/fixtures/analysis_v2.json').readAsStringSync())
        as Map<String, dynamic>;

Future<OverallFeedback> feedback(Map<String, dynamic> body) async {
  final repo = FeedbackRepository(
    api: AnalysisApi(
      client: MockClient(
        (_) async => http.Response(
          jsonEncode(body),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    ),
  );
  try {
    return await repo.fetchFeedback('model-v2-test');
  } finally {
    repo.dispose();
  }
}

void smallView(WidgetTester tester) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(360, 800);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> show(WidgetTester tester, OverallFeedback f) async {
  await tester.pumpWidget(MaterialApp(home: PhaseFeedbackScreen(feedback: f)));
  await tester.pumpAndSettle();
}

Future<void> selectPhase(
  WidgetTester tester,
  String key, {
  bool step = false,
}) async {
  await tester.drag(find.byType(ListView), const Offset(0, 3000));
  await tester.pumpAndSettle();
  final selector = find.byKey(ValueKey('phase-${step ? 'step' : 'card'}-$key'));
  await tester.scrollUntilVisible(selector, 180);
  await tester.tap(selector);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(find.byType(PhaseMetrics), 180);
}

Finder detailText(String key, String text) => find.descendant(
  of: find.byKey(ValueKey('phase-detail-$key')),
  matching: find.text(text),
);

void main() {
  testWidgets(
    'server phase score survives missing joints and uses selected deviations',
    (tester) async {
      smallView(tester);
      final body = report();
      final original = await feedback(body);
      expect(original.items.first.features.single.phaseScores![2].score, 80);
      body['result']['joints'] = [];
      final f = await feedback(body);
      expect(f.items.every((i) => i.features.isEmpty), isTrue);
      await show(tester, f);
      expect(find.text('전체 스윙 점수'), findsOneWidget);
      expect(find.text('77.3'), findsOneWidget);
      expect(find.text('전체 평균 점수'), findsNothing);
      await selectPhase(tester, 'swing');
      expect(detailText('swing', '71.4'), findsOneWidget);
      expect(find.text('80'), findsNothing);
      expect(find.text('내 시간 200 ms / 기준 200 ms'), findsOneWidget);
      expect(find.textContaining('소요 시간이 같음'), findsOneWidget);
      expect(find.textContaining('템포 기준 범위'), findsOneWidget);
      expect(find.textContaining('앞팔 팔꿈치 각도: 기준보다 높음'), findsOneWidget);
      expect(find.textContaining('이전 점수'), findsNothing);
      expect(find.textContaining('이전 스윙 대비'), findsNothing);
      expect(find.text('점수 변화'), findsNothing);
      await selectPhase(tester, 'stride', step: true);
      expect(detailText('stride', '82.5'), findsOneWidget);
      expect(find.text('내 시간 600 ms / 기준 500 ms'), findsOneWidget);
      expect(find.textContaining('앞팔 팔꿈치 각도:'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  for (final state in ['unavailable', 'missing-score', 'low']) {
    testWidgets(
      'phase $state keeps partial measurements without invented grades',
      (tester) async {
        smallView(tester);
        final body = report();
        body['result']['overall']['available'] = false;
        final phase = body['result']['phases']['phases'][0];
        if (state == 'unavailable') {
          phase['available'] = false;
          phase['unavailable_reason'] = '앞발 들기를 찾지 못했습니다.';
        } else if (state == 'missing-score') {
          phase['score'] = null;
        } else {
          phase['reliability'] = 'low';
        }
        await show(tester, await feedback(body));
        expect(find.text('77.3'), findsNothing);
        await selectPhase(tester, 'stride');
        expect(
          detailText('stride', state == 'low' ? '82.5' : '-'),
          findsOneWidget,
        );
        expect(find.text('안정적'), findsNothing);
        expect(find.text('주요 개선 필요'), findsNothing);
        if (state == 'unavailable') {
          expect(find.text('분석 불가'), findsWidgets);
          expect(find.text('앞발 들기를 찾지 못했습니다.'), findsOneWidget);
          expect(find.text('내 시간 - / 기준 500 ms'), findsOneWidget);
        } else if (state == 'low') {
          expect(find.text('신뢰도 낮음 · 참고용'), findsOneWidget);
        } else {
          expect(find.text('구간 점수가 제공되지 않았습니다.'), findsOneWidget);
          expect(find.text('내 시간 600 ms / 기준 500 ms'), findsOneWidget);
        }
        await selectPhase(tester, 'swing');
        expect(detailText('swing', '71.4'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('missing and deferred tempo never receive an invented verdict', (
    tester,
  ) async {
    smallView(tester);
    final body = report();
    final phase = body['result']['phases']['phases'][1];
    phase['tempo_ratio'] = 1.025;
    phase['tempo_level'] = null;
    await show(tester, await feedback(body));
    await selectPhase(tester, 'transition');
    expect(
      find.textContaining('1.025배 (소요 시간이 더 김) · 템포 판정 보류'),
      findsOneWidget,
    );
    expect(find.textContaining('구간이 짧아'), findsOneWidget);
    expect(find.textContaining('템포 기준 범위'), findsNothing);
    phase['tempo_ratio'] = null;
    phase['user_duration_ms'] = null;
    await show(tester, await feedback(body));
    await selectPhase(tester, 'transition');
    expect(find.text('소요 시간 비율 미제공 · 템포 판정 보류'), findsOneWidget);
    expect(find.text('내 시간 - / 기준 125 ms'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'partial phase order and selection follow server keys across updates',
    (tester) async {
      smallView(tester);
      final body = report();
      final phases = List<dynamic>.of(body['result']['phases']['phases']);
      phases[2]['name'] = '서버 스윙 구간';
      body['result']['phases']['phases'] = [phases[3], phases[2], phases[0]];
      await show(tester, await feedback(body));
      expect(find.byKey(const ValueKey('phase-step-transition')), findsNothing);
      await selectPhase(tester, 'swing');
      expect(find.text('서버 스윙 구간 구간 분석'), findsOneWidget);
      expect(detailText('swing', '71.4'), findsOneWidget);
      body['result']['phases']['phases'] = [phases[2], phases[0]];
      await show(tester, await feedback(body));
      await tester.scrollUntilVisible(find.byType(PhaseMetrics), 180);
      expect(detailText('swing', '71.4'), findsOneWidget);
      body['result']['phases']['phases'] = [phases[3]];
      await show(tester, await feedback(body));
      await tester.scrollUntilVisible(find.byType(PhaseMetrics), 180);
      expect(detailText('follow', '89.9'), findsOneWidget);
      expect(find.byKey(const ValueKey('phase-detail-swing')), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('0.1 server names and keys work without 0.2 events or speed', (
    tester,
  ) async {
    smallView(tester);
    final body = report();
    final result = body['result'];
    result['model_version'] = '0.1';
    result['phases'] = {
      'model_version': '0.1',
      'phases': [
        {'key': 'stance', 'name': '준비 자세', 'score': 60.3},
        {'key': 'load', 'name': '로딩(테이크백·스트라이드)', 'score': 70.2},
        {'key': 'swing', 'name': '스윙', 'score': 80.1},
        {'key': 'follow_through', 'name': '팔로우스루', 'score': null},
      ],
    };
    result['speed'] = {'available': false, 'metrics': []};
    await show(tester, await feedback(body));
    expect(find.text('준비 자세'), findsWidgets);
    await selectPhase(tester, 'load');
    expect(detailText('load', '70.2'), findsOneWidget);
    expect(find.text('로딩(테이크백·스트라이드) 구간 분석'), findsOneWidget);
    await selectPhase(tester, 'follow_through');
    expect(detailText('follow_through', '-'), findsOneWidget);
    expect(find.byType(SwingEventsCard), findsNothing);
    expect(find.byType(SpeedFeedbackCard), findsNothing);
    expect(find.text('착지 후 준비'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty phase response has an empty state', (tester) async {
    final body = report();
    body['result']['phases']['phases'] = [];
    await show(tester, await feedback(body));
    expect(find.text('분석할 구간 정보가 없어요.'), findsOneWidget);
    expect(find.text('0'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  for (final local in [true, false]) {
    testWidgets(
      '${local ? 'local' : 'signed URL'} video pauses on phase route and survives return',
      (tester) async {
        smallView(tester);
        final f = await feedback(report());
        final requests = <Uri>[];
        final api = AnalysisApi(
          client: MockClient((request) async {
            requests.add(request.url);
            return http.Response(
              jsonEncode({
                'analysis_id': 'model-v2-test',
                'url': 'https://example.com/video?token=mock',
                'expires_in': 900,
              }),
              200,
            );
          }),
        );
        addTearDown(api.dispose);
        late FakeVideoController controller;
        final router = GoRouter(
          observers: [swingRouteObserver],
          routes: [
            GoRoute(
              path: '/',
              builder: (context, _) => Scaffold(
                body: Column(
                  children: [
                    SizedBox(
                      width: 180,
                      height: 172,
                      child: SwingVideo(
                        analysisId: 'model-v2-test',
                        videoPath: local ? 'swing.mp4' : null,
                        api: api,
                        controllerFactory: ({videoPath, url}) => controller =
                            FakeVideoController(localPath: videoPath, url: url),
                      ),
                    ),
                    TextButton(
                      onPressed: () =>
                          context.push('/phase-feedback', extra: f),
                      child: const Text('구간 화면'),
                    ),
                  ],
                ),
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
        await tester.tap(
          local ? find.byIcon(Icons.play_arrow) : find.text('탭하여 재생'),
        );
        await tester.pumpAndSettle();
        expect(controller.value.isPlaying, isTrue);
        expect(controller.localPath, local ? 'swing.mp4' : isNull);
        expect(requests.length, local ? 0 : 1);
        if (!local) {
          expect(requests.single.path, '/api/analyses/model-v2-test/video');
        }
        await tester.tap(find.text('구간 화면'));
        await tester.pumpAndSettle();
        expect(find.byType(PhaseFeedbackScreen), findsOneWidget);
        expect(controller.value.isPlaying, isFalse);
        expect(controller.disposals, 0);
        await tester.tap(find.byIcon(Icons.arrow_back_ios_new));
        await tester.pumpAndSettle();
        expect(find.byType(SwingVideo), findsOneWidget);
        expect(controller.value.isPlaying, isFalse);
        expect(requests.length, local ? 0 : 1);
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpAndSettle();
        expect(controller.disposals, 1);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
