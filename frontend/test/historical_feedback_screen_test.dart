import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/swing_list_screen.dart';

import 'feedback_fixture.dart';

http.Response jsonResponse(Object body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void setView(WidgetTester tester) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(430, 1000);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
}

void main() {
  tearDown(Session.instance.clear);

  testWidgets(
    'completed list entry opens actual saved feedback and joint series without video requests',
    (tester) async {
      setView(tester);
      Session.instance.signIn('tester');
      final calls = <Uri>[];
      final now = DateTime.now();
      final client = MockClient((request) async {
        calls.add(request.url);
        if (request.url.path == '/api/users/tester/swings') {
          return jsonResponse({
            'items': [
              {
                'analysis_id': 'saved-analysis',
                'recorded_at': DateTime(
                  now.year,
                  now.month,
                  now.day,
                  10,
                ).toUtc().toIso8601String(),
                'status': 'done',
                'score': 77.3,
                'thumbnail_url': null,
              },
            ],
          });
        }
        expect(request.url.path, '/api/analyses/saved-analysis');
        expect(request.url.queryParameters, {'include_series': 'true'});
        return jsonResponse(storedAnalysis());
      });
      final listRepository = SwingRepository(api: SwingApi(client: client));
      final feedbackRepository = FeedbackRepository(
        api: AnalysisApi(client: client),
      );
      addTearDown(client.close);
      final router = GoRouter(
        initialLocation: '/swings',
        observers: [swingRouteObserver],
        routes: [
          GoRoute(
            path: '/swings',
            builder: (_, _) => SwingListScreen(repository: listRepository),
          ),
          GoRoute(
            path: '/analyses/:id',
            builder: (_, state) => OverallFeedbackScreen(
              analysisId: state.pathParameters['id']!,
              repository: feedbackRepository,
            ),
          ),
          GoRoute(
            path: '/joint-analysis',
            builder: (_, state) =>
                JointAnalysisScreen(feedback: state.extra as OverallFeedback),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.pumpAndSettle();
      await tester.tap(find.text('10시 0분'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<OverallFeedbackScreen>(find.byType(OverallFeedbackScreen))
            .analysisId,
        'saved-analysis',
      );
      expect(find.text('종합 피드백'), findsOneWidget);
      expect(find.text('77'), findsOneWidget);
      expect(find.textContaining('첫 스윙'), findsNothing);
      expect(find.textContaining('이전 70'), findsNothing);
      expect(find.text('개선된 부분'), findsNothing);
      expect(find.text('유지된 부분'), findsNothing);
      final at = DateTime.parse('2026-10-09T09:30:00Z').toLocal();
      String two(int value) => value.toString().padLeft(2, '0');
      expect(
        find.text(
          '${at.year}. ${two(at.month)}. ${two(at.day)}  ${two(at.hour)}:${two(at.minute)}',
        ),
        findsOneWidget,
      );
      expect(
        find.byIcon(Icons.sports_baseball),
        findsOneWidget,
      ); // 과거 영상 placeholder.
      await tester.tap(find.text('상세 피드백 보기'));
      await tester.pumpAndSettle();
      expect(find.text('관절별 분석'), findsOneWidget);
      expect(find.text('이전 점수'), findsNothing);
      expect(find.text('점수 변화'), findsNothing);
      final screen = tester.widget<JointAnalysisScreen>(
        find.byType(JointAnalysisScreen),
      );
      expect(screen.feedback.items.single.currentScore, 64);
      expect(
        screen.feedback.items.single.features.single.series!.last.user,
        123.4,
      );
      expect(
        calls.where((uri) => uri.path == '/api/analyses/saved-analysis').length,
        1,
      );
      expect(calls.any((uri) => uri.path.endsWith('/video')), isFalse);
      expect(tester.takeException(), isNull);
    },
  );

  for (final failure in [
    'queued',
    'processing',
    'failed',
    '404',
    'network',
    'result',
    'score',
  ]) {
    testWidgets(
      '$failure shows a specific error and retry loads real feedback',
      (tester) async {
        setView(tester);
        var calls = 0;
        final api = AnalysisApi(
          client: MockClient((_) async {
            if (++calls > 1) return jsonResponse(storedAnalysis());
            if (failure == 'network') throw http.ClientException('offline');
            if (failure == '404') {
              return jsonResponse({'detail': '분석 결과를 찾을 수 없습니다.'}, 404);
            }
            final body = storedAnalysis();
            if (failure == 'result') {
              body['result'] = null;
            } else if (failure == 'score') {
              body['result']['overall']['score'] = null;
            } else {
              body['status'] = failure;
            }
            return jsonResponse(body);
          }),
        );
        final repository = FeedbackRepository(api: api);
        addTearDown(repository.dispose);
        await tester.pumpWidget(
          MaterialApp(
            home: OverallFeedbackScreen(
              analysisId: 'saved-analysis',
              repository: repository,
            ),
          ),
        );
        await tester.pumpAndSettle();
        final expected = switch (failure) {
          'queued' => '대기',
          'processing' => '진행',
          'failed' => '실패',
          '404' => '찾을 수 없습니다',
          'network' => '네트워크',
          'result' => '결과가 없습니다',
          _ => '종합 점수',
        };
        expect(find.textContaining(expected), findsOneWidget);
        expect(find.text('전체 스윙 점수'), findsNothing);
        expect(calls, 1);
        await tester.tap(find.text('다시 시도'));
        await tester.pumpAndSettle();
        expect(calls, 2);
        expect(find.text('전체 스윙 점수'), findsOneWidget);
        expect(find.text('77'), findsOneWidget);
      },
    );
  }
}
