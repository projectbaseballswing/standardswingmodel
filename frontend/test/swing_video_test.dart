import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/widgets/swing_video.dart';
import 'package:video_player/video_player.dart';

import 'fake_video_controller.dart';

http.Response signedResponse(
  String id, {
  int token = 1,
  int expiresIn = 900,
}) => http.Response(
  jsonEncode({
    'analysis_id': id,
    'url':
        'https://example.supabase.co/storage/v1/object/sign/video?token=$token',
    'expires_in': expiresIn,
  }),
  200,
);

class VideoHarness {
  VideoHarness({Future<http.Response> Function(http.Request)? handler}) {
    api = AnalysisApi(
      client: MockClient((request) async {
        requests.add(request.url);
        return handler != null
            ? handler(request)
            : signedResponse(
                request.url.pathSegments[2],
                token: requests.length,
              );
      }),
    );
    addTearDown(api.dispose);
  }

  late final AnalysisApi api;
  final requests = <Uri>[];
  final controllers = <FakeVideoController>[];
  final navigator = GlobalKey<NavigatorState>();
  DateTime now = DateTime.utc(2026, 10, 10);
  Completer<void>? initializeGate;
  bool failInitialize = false;

  Future<void> show(
    WidgetTester tester, {
    String id = 'saved-analysis',
    String? path,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        navigatorKey: navigator,
        navigatorObservers: [swingRouteObserver],
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 180,
              height: 172,
              child: SwingVideo(
                analysisId: id,
                videoPath: path,
                api: api,
                now: () => now,
                controllerFactory: ({videoPath, url}) {
                  final c = FakeVideoController(
                    localPath: videoPath,
                    url: url,
                    initializeGate: initializeGate,
                  )..failInitialize = failInitialize;
                  controllers.add(c);
                  return c;
                },
              ),
            ),
          ),
        ),
      ),
    );
  }
}

Future<void> play(WidgetTester tester) async {
  await tester.tap(find.text('탭하여 재생'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('request timeout stops loading and a late response is ignored', (
    tester,
  ) async {
    final pending = Completer<http.Response>();
    final h = VideoHarness(handler: (_) => pending.future);
    await h.show(tester);
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 31));
    await tester.pump();
    expect(find.textContaining('시간이 초과'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    pending.complete(signedResponse('saved-analysis'));
    await tester.pumpAndSettle();
    expect(h.controllers, isEmpty);
    expect(h.requests.length, 1);
  });

  testWidgets(
    'initialization timeout releases player without automatic retry',
    (tester) async {
      final gate = Completer<void>();
      final h = VideoHarness()..initializeGate = gate;
      await h.show(tester);
      await tester.tap(find.text('탭하여 재생'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 31));
      await tester.pump();
      expect(find.textContaining('재생할 수 없습니다'), findsOneWidget);
      expect(h.controllers.single.disposals, 1);
      gate.complete();
      await tester.pumpAndSettle();
      expect(h.controllers.single.plays, 0);
      expect(h.requests.length, 1);
    },
  );

  testWidgets('a URL already expired during issuance never starts a stream', (
    tester,
  ) async {
    final pending = Completer<http.Response>();
    final h = VideoHarness(handler: (_) => pending.future);
    await h.show(tester);
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    h.now = h.now.add(const Duration(seconds: 2));
    pending.complete(signedResponse('saved-analysis', expiresIn: 1));
    await tester.pumpAndSettle();
    expect(find.textContaining('만료'), findsOneWidget);
    expect(h.controllers, isEmpty);
    expect(h.requests.length, 1);
  });

  testWidgets(
    'changing a loaded analysis releases its player and waits for a new tap',
    (tester) async {
      final h = VideoHarness();
      await h.show(tester, id: 'old');
      await play(tester);
      final old = h.controllers.single;
      await h.show(tester, id: 'new');
      await tester.pumpAndSettle();
      expect(old.disposals, 1);
      expect(old.value.isPlaying, isFalse);
      expect(find.byType(VideoPlayer), findsNothing);
      expect(h.requests.length, 1);
      await play(tester);
      expect(h.requests.last.path, '/api/analyses/new/video');
      expect(h.controllers.last.value.position, Duration.zero);
    },
  );

  testWidgets('failed local video retries the file without requesting a URL', (
    tester,
  ) async {
    final h = VideoHarness()..failInitialize = true;
    await h.show(tester, path: 'C:/videos/local.mp4');
    await tester.pumpAndSettle();
    expect(find.textContaining('로컬 영상'), findsOneWidget);
    h.failInitialize = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(h.requests, isEmpty);
    expect(h.controllers.last.localPath, 'C:/videos/local.mp4');
    expect(h.controllers.last.value.isPlaying, isTrue);
  });

  testWidgets(
    'remote video is lazy and duplicate taps share one pending request',
    (tester) async {
      final pending = Completer<http.Response>();
      final h = VideoHarness(handler: (_) => pending.future);
      await h.show(tester);
      expect(h.requests, isEmpty);
      expect(h.controllers, isEmpty);
      await tester.tap(find.text('탭하여 재생'));
      await tester.tap(find.text('탭하여 재생'));
      await tester.pump();
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(h.requests.length, 1);
      expect(h.controllers, isEmpty);
      pending.complete(signedResponse('saved-analysis'));
      await tester.pumpAndSettle();
      expect(h.controllers.single.value.isPlaying, isTrue);
      expect(h.controllers.single.value.isLooping, isTrue);
      expect(find.byType(VideoPlayer), findsOneWidget);
      expect(find.text('01:00'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
      await tester.pump();
      expect(h.controllers.single.value.isPlaying, isFalse);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      expect(h.controllers.single.disposals, 1);
    },
  );

  testWidgets('local file takes precedence and keeps play pause and seeking', (
    tester,
  ) async {
    final h = VideoHarness();
    await h.show(tester, path: 'C:/videos/new-swing.mp4');
    await tester.pumpAndSettle();
    expect(h.requests, isEmpty);
    final c = h.controllers.single;
    expect(c.localPath, 'C:/videos/new-swing.mp4');
    expect(c.value.isPlaying, isFalse);
    await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
    await tester.pumpAndSettle();
    expect(c.value.isPlaying, isTrue);
    await tester.tap(find.byKey(const ValueKey('swing-video-progress')));
    await tester.pumpAndSettle();
    expect(c.value.position.inSeconds, closeTo(30, 1));
    h.now = h.now.add(const Duration(days: 1));
    await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
    await tester.pumpAndSettle();
    expect(c.value.isPlaying, isFalse);
    await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
    await tester.pumpAndSettle();
    expect(h.controllers.length, 1);
    expect(h.requests, isEmpty);
  });

  for (final seek in [false, true]) {
    testWidgets(
      'expired URL refreshes on ${seek ? 'seek' : 'play'} and disposes old player',
      (tester) async {
        final h = VideoHarness();
        await h.show(tester);
        await play(tester);
        final old = h.controllers.single;
        await old.seekTo(const Duration(seconds: 12));
        await old.pause();
        await tester.pump();
        h.now = h.now.add(const Duration(seconds: 900));
        await tester.tap(
          find.byKey(
            ValueKey(seek ? 'swing-video-progress' : 'swing-video-playback'),
          ),
        );
        await tester.pumpAndSettle();
        expect(h.requests.length, 2);
        expect(old.disposals, 1);
        final renewed = h.controllers.last;
        expect(renewed.dataSource, contains('token=2'));
        expect(renewed.value.position.inSeconds, closeTo(seek ? 30 : 12, 1));
        expect(renewed.value.isPlaying, !seek);
      },
    );
  }

  for (final entry in {
    404: '없습니다',
    409: '업로드 중',
    502: '연결하지 못',
    503: '설정 문제',
  }.entries) {
    testWidgets(
      'HTTP ${entry.key} shows video guidance and allows a manual retry',
      (tester) async {
        var attempts = 0;
        final h = VideoHarness(
          handler: (_) async => ++attempts == 1
              ? http.Response('{"detail":"token=secret"}', entry.key)
              : signedResponse('saved-analysis'),
        );
        await h.show(tester);
        await play(tester);
        expect(find.textContaining(entry.value), findsOneWidget);
        expect(find.textContaining('secret'), findsNothing);
        expect(h.controllers, isEmpty);
        await tester.pump(const Duration(minutes: 2));
        expect(attempts, 1);
        await tester.tap(find.text('다시 시도'));
        await tester.pumpAndSettle();
        expect(attempts, 2);
        expect(h.controllers.single.value.isPlaying, isTrue);
      },
    );
  }

  testWidgets('network error is distinct and retry requests a fresh URL', (
    tester,
  ) async {
    var attempts = 0;
    final h = VideoHarness(
      handler: (_) async {
        if (++attempts == 1) throw http.ClientException('token=secret');
        return signedResponse('saved-analysis');
      },
    );
    await h.show(tester);
    await play(tester);
    expect(find.textContaining('네트워크'), findsOneWidget);
    expect(find.textContaining('secret'), findsNothing);
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(h.controllers.single.value.isPlaying, isTrue);
  });

  testWidgets(
    'initialization failure releases controller and retries with a new URL',
    (tester) async {
      final h = VideoHarness()..failInitialize = true;
      await h.show(tester);
      await play(tester);
      expect(find.textContaining('재생할 수 없습니다'), findsOneWidget);
      expect(find.textContaining('secret'), findsNothing);
      expect(h.controllers.single.disposals, 1);
      await tester.pump(const Duration(minutes: 1));
      expect(h.requests.length, 1);
      h.failInitialize = false;
      await tester.tap(find.text('다시 시도'));
      await tester.pumpAndSettle();
      expect(h.requests.length, 2);
      expect(h.controllers.last.value.isPlaying, isTrue);
    },
  );

  for (final failure in ['event', 'play', 'seek']) {
    testWidgets(
      'player $failure error is sanitized and offers manual renewal',
      (tester) async {
        final h = VideoHarness();
        await h.show(tester);
        await play(tester);
        final c = h.controllers.single;
        if (failure == 'event') {
          c.value = c.value.copyWith(
            errorDescription: 'https://example.com/?token=secret',
          );
        } else if (failure == 'play') {
          await c.pause();
          c.failPlay = true;
          await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
        } else {
          c.failSeek = true;
          await tester.tap(find.byKey(const ValueKey('swing-video-progress')));
        }
        await tester.pumpAndSettle();
        expect(find.textContaining('재생할 수 없습니다'), findsOneWidget);
        expect(find.textContaining('secret'), findsNothing);
        expect(c.disposals, 1);
        await tester.tap(find.text('다시 시도'));
        await tester.pumpAndSettle();
        expect(h.requests.length, 2);
        expect(h.controllers.last.value.isPlaying, isTrue);
      },
    );
  }

  testWidgets(
    'background and route changes pause without automatic resumption',
    (tester) async {
      final h = VideoHarness();
      await h.show(tester);
      await play(tester);
      final c = h.controllers.single;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await tester.pump();
      expect(c.value.isPlaying, isFalse);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(c.plays, 1);
      await tester.tap(find.byKey(const ValueKey('swing-video-playback')));
      await tester.pump();
      expect(c.value.isPlaying, isTrue);
      unawaited(
        h.navigator.currentState!.push(
          MaterialPageRoute<void>(
            builder: (_) => const Scaffold(body: Text('joint analysis')),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(c.value.isPlaying, isFalse);
      h.navigator.currentState!.pop();
      await tester.pumpAndSettle();
      expect(c.value.isPlaying, isFalse);
    },
  );

  testWidgets('late URL from a different analysis is ignored', (tester) async {
    final pending = Completer<http.Response>();
    final h = VideoHarness(
      handler: (request) => request.url.pathSegments[2] == 'old'
          ? pending.future
          : Future.value(signedResponse('new')),
    );
    await h.show(tester, id: 'old');
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    await h.show(tester, id: 'new');
    await play(tester);
    pending.complete(signedResponse('old'));
    await tester.pumpAndSettle();
    expect(h.controllers.length, 1);
    expect(h.requests.last.path, '/api/analyses/new/video');
    expect(tester.takeException(), isNull);
  });

  testWidgets('URL completing after dispose does not create a player', (
    tester,
  ) async {
    final pending = Completer<http.Response>();
    final h = VideoHarness(handler: (_) => pending.future);
    await h.show(tester);
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    pending.complete(signedResponse('saved-analysis'));
    await tester.pumpAndSettle();
    expect(h.controllers, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('initialization completing after dispose cannot play', (
    tester,
  ) async {
    final gate = Completer<void>();
    final h = VideoHarness()..initializeGate = gate;
    await h.show(tester);
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    expect(h.controllers.length, 1);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    gate.complete();
    await tester.pumpAndSettle();
    expect(h.controllers.single.disposals, 1);
    expect(h.controllers.single.plays, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('leaving route during initialization cancels autoplay intent', (
    tester,
  ) async {
    final gate = Completer<void>();
    final h = VideoHarness()..initializeGate = gate;
    await h.show(tester);
    await tester.tap(find.text('탭하여 재생'));
    await tester.pump();
    unawaited(
      h.navigator.currentState!.push(
        MaterialPageRoute<void>(
          builder: (_) => const Scaffold(body: Text('another screen')),
        ),
      ),
    );
    await tester.pump();
    gate.complete();
    await tester.pumpAndSettle();
    expect(h.controllers.single.plays, 0);
    h.navigator.currentState!.pop();
    await tester.pumpAndSettle();
    expect(h.controllers.single.plays, 0);
  });
}
