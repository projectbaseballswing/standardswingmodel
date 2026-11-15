import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/original_video_api.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/swing_list_screen.dart';
import 'package:swing_analysis/screens/swing_trend_screen.dart';
import 'package:swing_analysis/widgets/swing_trend_chart.dart';

void main() {
  testWidgets(
    'delete original, reopen trend, and retain the same scored record',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Session.instance.signIn('tester', accessToken: 'test-only');
      addTearDown(Session.instance.clear);
      final now = DateTime.now();
      var videoStatus = 'available';
      var deletes = 0;
      http.Response response(Object body) => http.Response(
        jsonEncode(body),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
      final repo = SwingRepository(
        api: SwingApi(
          client: MockClient(
            (_) async => response({
              'items': [
                {
                  'analysis_id': 'kept-analysis',
                  'recorded_at': now.toUtc().toIso8601String(),
                  'status': 'done',
                  'score': 82.4,
                  'video_status': videoStatus,
                },
              ],
            }),
          ),
        ),
      );
      final videoApi = OriginalVideoApi(
        client: MockClient((request) async {
          expect(request.method, 'DELETE');
          expect(request.url.path, '/api/analyses/kept-analysis/video');
          deletes++;
          videoStatus = 'deleted';
          return response({
            'analysis_id': 'kept-analysis',
            'video_status': videoStatus,
          });
        }),
      );
      addTearDown(repo.dispose);
      addTearDown(videoApi.dispose);
      final router = GoRouter(
        initialLocation: '/swings',
        observers: [swingRouteObserver],
        routes: [
          GoRoute(
            path: '/swings',
            builder: (_, _) =>
                SwingListScreen(repository: repo, videoApi: videoApi),
          ),
          GoRoute(
            path: '/swings/trend',
            builder: (_, _) =>
                SwingTrendScreen(repository: repo, clock: () => now),
          ),
          GoRoute(
            path: '/analyses/:id',
            builder: (_, s) =>
                Scaffold(body: Text('feedback:${s.pathParameters['id']}')),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.pumpAndSettle();
      Future<void> assertTrend() async {
        await tester.tap(find.text('스윙 추이'));
        await tester.pumpAndSettle();
        final points = tester
            .widget<SwingTrendChart>(find.byType(SwingTrendChart))
            .points;
        expect(points, hasLength(1));
        expect(points.single.analysisId, 'kept-analysis');
        expect(points.single.score, 82.4);
        expect(points.single.recordedAt.toUtc(), now.toUtc());
      }

      await assertTrend();
      await tester.tap(find.byTooltip('스윙 기록으로'));
      await tester.pumpAndSettle();
      final menu = find.byKey(const ValueKey('video-menu-kept-analysis'));
      await tester.ensureVisible(menu);
      await tester.pumpAndSettle();
      await tester.tap(menu);
      await tester.pumpAndSettle();
      await tester.tap(find.text('원본 영상 삭제'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('삭제'));
      await tester.pumpAndSettle();
      expect(deletes, 1);
      expect(find.text('원본 삭제됨'), findsOneWidget);
      await assertTrend();
      expect(
        tester
            .widget<SwingTrendChart>(find.byType(SwingTrendChart))
            .points
            .single
            .videoStatus,
        'deleted',
      );
      await tester.tap(find.byTooltip('스윙 기록으로'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('원본 삭제됨'));
      await tester.tap(find.text('원본 삭제됨'));
      await tester.pumpAndSettle();
      expect(find.text('feedback:kept-analysis'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
