import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/api_config.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/api/original_video_api.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/swing_list_screen.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/widgets/swing_video.dart';

import 'feedback_fixture.dart';

http.Response jsonResponse(Object value, [int status = 200]) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);
http.Response deleted([String id = 'saved-analysis']) => jsonResponse({
  'analysis_id': id,
  'video_status': 'deleted',
  'already_deleted': false,
});

Future<void> showList(
  WidgetTester tester,
  OriginalVideoApi api, {
  String status = 'done',
  String videoStatus = 'available',
  Size size = const Size(390, 844),
  VoidCallback? onLoad,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final repo = SwingRepository(
    api: SwingApi(
      client: MockClient((_) async {
        onLoad?.call();
        return jsonResponse({
          'items': [
            {
              'analysis_id': 'saved-analysis',
              'recorded_at': DateTime.now().toUtc().toIso8601String(),
              'status': status,
              'score': 77.3,
              'video_status': videoStatus,
            },
          ],
        });
      }),
    ),
  );
  addTearDown(repo.dispose);
  final router = GoRouter(
    observers: [swingRouteObserver],
    initialLocation: '/swings',
    routes: [
      GoRoute(
        path: '/swings',
        builder: (_, _) => SwingListScreen(repository: repo, videoApi: api),
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
  await tester.ensureVisible(
    find.byKey(const ValueKey('video-menu-saved-analysis')),
  );
  await tester.pumpAndSettle();
}

Future<void> openDelete(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('video-menu-saved-analysis')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('원본 영상 삭제'));
  await tester.pumpAndSettle();
}

void main() {
  setUp(
    () => Session.instance.signIn('tester', accessToken: 'test-only-token'),
  );
  tearDown(Session.instance.clear);

  test(
    'DELETE accepts an encoded analysis ID only and sends Bearer auth',
    () async {
      final api = OriginalVideoApi(
        client: MockClient((r) async {
          expect(r.method, 'DELETE');
          expect(r.headers['Authorization'], 'Bearer test-only-token');
          expect(r.url.pathSegments, [
            'api',
            'analyses',
            'id/other?x=1',
            'video',
          ]);
          expect(r.url.query, isEmpty);
          expect(r.body, isEmpty);
          return deleted('id/other?x=1');
        }),
      );
      addTearDown(api.dispose);
      await api.delete('id/other?x=1');
    },
  );
  test('unauthenticated delete does not send a request', () async {
    Session.instance.clear();
    final api = OriginalVideoApi(
      client: MockClient((_) async => throw StateError('unexpected HTTP')),
    );
    addTearDown(api.dispose);
    await expectLater(
      api.delete('saved-analysis'),
      throwsA(isA<ApiException>()),
    );
  });
  for (final status in [401, 403, 404, 409, 502, 503]) {
    test(
      'delete $status is an error without exposing response secrets',
      () async {
        final api = OriginalVideoApi(
          client: MockClient(
            (_) async => jsonResponse({'detail': 'upstream secret'}, status),
          ),
        );
        addTearDown(api.dispose);
        await expectLater(
          api.delete('saved-analysis'),
          throwsA(
            isA<ApiException>().having(
              (e) => e.message,
              'message',
              isNot(contains('upstream secret')),
            ),
          ),
        );
      },
    );
  }
  test('wrong analysis ID in success response is rejected', () async {
    final api = OriginalVideoApi(
      client: MockClient((_) async => deleted('another')),
    );
    addTearDown(api.dispose);
    await expectLater(
      api.delete('saved-analysis'),
      throwsA(isA<ApiException>()),
    );
  });
  test(
    'local HTTP capability requires exact configured loopback origin',
    () async {
      final base = Uri.parse(ApiConfig.baseUrl);
      final localAllowed =
          base.scheme == 'http' &&
          ['localhost', '127.0.0.1', '::1'].contains(base.host);
      for (final link in [
        '${ApiConfig.baseUrl}/api/local-video?path=x&signature=test',
        'http://untrusted.invalid/api/local-video',
        'http://127.0.0.1:19999/api/local-video',
        '${ApiConfig.baseUrl}/other-path',
      ]) {
        final api = AnalysisApi(
          client: MockClient(
            (_) async => jsonResponse({
              'analysis_id': 'saved-analysis',
              'url': link,
              'expires_in': 60,
            }),
          ),
        );
        addTearDown(api.dispose);
        if (localAllowed && link.contains('?path=x')) {
          expect(
            (await api.getVideoUrl('saved-analysis')).url.toString(),
            link,
          );
        } else {
          await expectLater(
            api.getVideoUrl('saved-analysis'),
            throwsA(isA<ApiException>()),
          );
        }
      }
    },
  );

  testWidgets('cancel retains record and never deletes', (tester) async {
    var requests = 0;
    var loads = 0;
    final api = OriginalVideoApi(
      client: MockClient((_) async {
        requests++;
        return deleted();
      }),
    );
    addTearDown(api.dispose);
    await showList(tester, api, onLoad: () => loads++);
    await openDelete(tester);
    expect(
      find.textContaining('복구할 수 없지만 분석 점수와 3D 스윙 기록은 유지됩니다'),
      findsOneWidget,
    );
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(requests, 0);
    expect(loads, 1);
    expect(find.text('완료 · 77.3점'), findsOneWidget);
    expect(find.text('원본 삭제됨'), findsNothing);
  });
  testWidgets('confirmed delete keeps score and feedback navigation', (
    tester,
  ) async {
    var requests = 0;
    final api = OriginalVideoApi(
      client: MockClient((_) async {
        requests++;
        return deleted();
      }),
    );
    addTearDown(api.dispose);
    await showList(tester, api);
    await openDelete(tester);
    await tester.tap(
      find.byKey(const ValueKey('confirm-original-video-delete')),
    );
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(find.text('원본 삭제됨'), findsOneWidget);
    expect(find.text('완료 · 77.3점'), findsOneWidget);
    await tester.tap(find.text('원본 삭제됨'));
    await tester.pumpAndSettle();
    expect(find.text('feedback:saved-analysis'), findsOneWidget);
  });
  testWidgets('pending deletion disables duplicate requests', (tester) async {
    final pending = Completer<http.Response>();
    var requests = 0;
    final api = OriginalVideoApi(
      client: MockClient((_) {
        requests++;
        return pending.future;
      }),
    );
    addTearDown(api.dispose);
    await showList(tester, api);
    await openDelete(tester);
    await tester.tap(
      find.byKey(const ValueKey('confirm-original-video-delete')),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(
      find.byKey(const ValueKey('video-menu-saved-analysis')),
      findsNothing,
    );
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(requests, 1);
    pending.complete(deleted());
    await tester.pumpAndSettle();
    expect(find.text('원본 삭제됨'), findsOneWidget);
  });
  testWidgets('storage failure shows retry message and retains record', (
    tester,
  ) async {
    final api = OriginalVideoApi(
      client: MockClient((_) async => jsonResponse({}, 502)),
    );
    addTearDown(api.dispose);
    await showList(tester, api);
    await openDelete(tester);
    await tester.tap(
      find.byKey(const ValueKey('confirm-original-video-delete')),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('원본 영상 삭제를 완료하지 못했습니다'), findsOneWidget);
    expect(find.text('원본 삭제됨'), findsNothing);
    expect(find.text('완료 · 77.3점'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('video-menu-saved-analysis')),
      findsOneWidget,
    );
  });
  testWidgets('account change during confirmation prevents delete', (
    tester,
  ) async {
    var requests = 0;
    final api = OriginalVideoApi(
      client: MockClient((_) async {
        requests++;
        return deleted();
      }),
    );
    addTearDown(api.dispose);
    await showList(tester, api);
    await openDelete(tester);
    Session.instance.signIn('other', accessToken: 'other-token');
    await tester.tap(
      find.byKey(const ValueKey('confirm-original-video-delete')),
    );
    await tester.pumpAndSettle();
    expect(requests, 0);
  });
  for (final state in ['processing', 'deleted']) {
    testWidgets(
      '$state record cannot request deletion; small viewport remains usable',
      (tester) async {
        var requests = 0;
        final api = OriginalVideoApi(
          client: MockClient((_) async {
            requests++;
            return deleted();
          }),
        );
        addTearDown(api.dispose);
        await showList(
          tester,
          api,
          status: state == 'processing' ? state : 'done',
          videoStatus: state == 'deleted' ? state : 'available',
          size: const Size(320, 568),
        );
        await tester.tap(
          find.byKey(const ValueKey('video-menu-saved-analysis')),
        );
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<PopupMenuItem<String>>(find.byType(PopupMenuItem<String>))
              .enabled,
          false,
        );
        expect(requests, 0);
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'deleted feedback keeps score and 3D link without requesting video',
    (tester) async {
      final requests = <Uri>[];
      final api = AnalysisApi(
        client: MockClient((r) async {
          requests.add(r.url);
          if (r.url.path.contains('/comparison')) {
            return jsonResponse({'has_previous': false});
          }
          return jsonResponse({...storedAnalysis(), 'video_status': 'deleted'});
        }),
      );
      final repo = FeedbackRepository(api: api);
      addTearDown(repo.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: OverallFeedbackScreen(
            analysisId: 'saved-analysis',
            repository: repo,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('원본 영상이 삭제되었습니다'), findsOneWidget);
      expect(find.byType(SwingVideo), findsNothing);
      expect(find.text('3D 스윙 보기'), findsOneWidget);
      expect(requests.any((u) => u.path.endsWith('/video')), false);
    },
  );
  testWidgets(
    '410 after metadata load displays permanent notice without retry',
    (tester) async {
      var requests = 0;
      final api = AnalysisApi(
        client: MockClient((_) async {
          requests++;
          return jsonResponse({}, 410);
        }),
      );
      addTearDown(api.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 180,
              height: 172,
              child: SwingVideo(analysisId: 'gone', api: api, preload: true),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('원본 영상이 삭제되었습니다.'), findsOneWidget);
      expect(find.text('다시 시도'), findsNothing);
      expect(requests, 1);
    },
  );
}
