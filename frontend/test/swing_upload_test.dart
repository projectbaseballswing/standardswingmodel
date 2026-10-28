import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:image_picker/image_picker.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/swing_camera_screen.dart';
import 'package:swing_analysis/video/selected_video.dart';
import 'package:swing_analysis/widgets/swing_video.dart';
import 'package:video_player/video_player.dart';

import 'fake_video_controller.dart';

/// Browser-like path; the uploader must consume the XFile, not open its path.
class StreamVideo extends XFile {
  StreamVideo({this.filename = 'swing.mp4', this.type, this.empty = false})
    : super('blob:https://example.com/selected-video');
  final String filename;
  final String? type;
  final bool empty;
  bool failLength = false;
  bool failStream = false;
  int reads = 0;
  int lengths = 0;
  static const bytes = [0, 1, 2, 3, 254, 255];

  @override
  String get name => filename;
  @override
  String? get mimeType => type;
  @override
  Future<int> length() async {
    lengths++;
    if (failLength) throw StateError('file unavailable');
    return empty ? 0 : bytes.length;
  }

  @override
  Stream<Uint8List> openRead([int? start, int? end]) async* {
    reads++;
    if (failStream) throw StateError('file unavailable');
    yield Uint8List.fromList(bytes.take(3).toList());
    yield Uint8List.fromList(bytes.skip(3).toList());
  }

  @override
  Future<Uint8List> readAsBytes() => throw StateError('Do not buffer the file');
}

class UploadClient extends http.BaseClient {
  final requests = <http.MultipartRequest>[];
  List<int>? payload;
  int status = 202;
  String body = '{"analysis_id":"uploaded","status":"queued"}';
  bool failNetwork = false;
  Completer<void>? gate;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final upload = request as http.MultipartRequest;
    requests.add(upload);
    payload = await upload.finalize().toBytes();
    await gate?.future;
    if (failNetwork) throw http.ClientException('mock offline');
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

Future<void> upload(
  AnalysisApi api,
  XFile video, {
  String user = 'testuser01',
}) => api.uploadSwingVideo(
  video: video,
  isLeft: true,
  userId: user,
  recordedAt: DateTime.parse('2026-10-12T18:30:00+09:00'),
);

Future<void> showReview(
  WidgetTester tester,
  AnalysisApi api, {
  XFile? video,
  bool failPreview = false,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      navigatorObservers: [swingRouteObserver],
      home: SwingVideoReviewScreen(
        video: video ?? StreamVideo(),
        api: api,
        controllerFactory: ({videoPath, url}) =>
            FakeVideoController(localPath: videoPath)
              ..failInitialize = failPreview,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  tearDown(Session.instance.clear);

  test(
    'XFile stream preserves bytes, filename, MIME and all multipart fields',
    () async {
      final client = UploadClient();
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      final video = StreamVideo(filename: 'swing.MOV', type: 'video/quicktime');
      await upload(api, video);
      final request = client.requests.single;
      expect(request.method, 'POST');
      expect(request.url.path, '/api/analyses');
      expect(request.fields, {
        'handedness': 'left',
        'user_id': 'testuser01',
        'recorded_at': '2026-10-12T09:30:00.000Z',
      });
      expect(request.files.single.field, 'video');
      expect(request.files.single.filename, 'swing.MOV');
      expect(request.files.single.contentType.toString(), 'video/quicktime');
      expect(request.files.single.length, StreamVideo.bytes.length);
      expect(
        latin1.decode(client.payload!),
        contains(latin1.decode(StreamVideo.bytes)),
      );
      expect(video.reads, 1);
      expect(video.lengths, 1);
    },
  );

  for (final entry in {
    'mp4': 'video/mp4',
    'mov': 'video/quicktime',
    'm4v': 'video/x-m4v',
    'avi': 'video/x-msvideo',
    'mkv': 'video/x-matroska',
    'webm': 'video/webm',
  }.entries) {
    test('missing MIME falls back to .${entry.key}', () async {
      final client = UploadClient();
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      await upload(api, StreamVideo(filename: 'swing.${entry.key}'));
      expect(
        client.requests.single.files.single.contentType.toString(),
        entry.value,
      );
    });
  }

  test('blank user is rejected before file reads or HTTP', () async {
    final client = UploadClient();
    final api = AnalysisApi(client: client);
    addTearDown(api.dispose);
    final file = StreamVideo();
    await expectLater(
      upload(api, file, user: '  '),
      throwsA(isA<ApiException>()),
    );
    expect(client.requests, isEmpty);
    expect(file.lengths, 0);
    expect(file.reads, 0);
  });

  for (final problem in ['empty', 'length', 'stream', 'network']) {
    test('$problem failure becomes a handled ApiException', () async {
      final client = UploadClient()..failNetwork = problem == 'network';
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      final file = StreamVideo(empty: problem == 'empty')
        ..failLength = problem == 'length'
        ..failStream = problem == 'stream';
      await expectLater(upload(api, file), throwsA(isA<ApiException>()));
      if (problem == 'empty' || problem == 'length') {
        expect(client.requests, isEmpty);
      }
    });
  }

  for (final status in [413, 415, 500]) {
    test('HTTP $status shows the server error', () async {
      final client = UploadClient()
        ..status = status
        ..body = '{"detail":"업로드 거절"}';
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      await expectLater(
        upload(api, StreamVideo()),
        throwsA(
          isA<ApiException>().having((e) => e.message, 'message', '업로드 거절'),
        ),
      );
    });
  }
  for (final body in [
    'not JSON',
    '{}',
    '{"analysis_id":null}',
    '{"analysis_id":"uploaded","status":3}',
  ]) {
    test('invalid upload response $body is handled', () async {
      final api = AnalysisApi(client: UploadClient()..body = body);
      addTearDown(api.dispose);
      await expectLater(
        upload(api, StreamVideo()),
        throwsA(isA<ApiException>()),
      );
    });
  }

  test('selected video controller uses native file or browser URL', () async {
    final source = kIsWeb ? 'blob:https://example.com/video' : 'test.mp4';
    final controller = selectedVideoController(source);
    expect(
      controller.dataSourceType,
      kIsWeb ? DataSourceType.network : DataSourceType.file,
    );
    if (kIsWeb) expect(controller.dataSource, source);
    await controller.dispose();
  });

  testWidgets('signed out review blocks upload without reading the video', (
    tester,
  ) async {
    Session.instance.clear();
    final client = UploadClient();
    final api = AnalysisApi(client: client);
    addTearDown(api.dispose);
    final video = StreamVideo();
    await showReview(tester, api, video: video);
    await tester.tap(find.text('분석 요청'));
    await tester.pump();
    expect(find.text('로그인한 뒤 영상을 업로드해주세요.'), findsOneWidget);
    expect(client.requests, isEmpty);
    expect(video.reads, 0);
  });

  testWidgets(
    'preview failure stops loading but still permits upload and retry',
    (tester) async {
      Session.instance.signIn('testuser01');
      final client = UploadClient()
        ..status = 415
        ..body = '{"detail":"지원하지 않는 영상"}';
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      await showReview(tester, api, failPreview: true);
      expect(find.textContaining('파일 형식과 코덱'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await tester.tap(find.text('분석 요청'));
      await tester.pumpAndSettle();
      expect(find.text('지원하지 않는 영상'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '분석 요청'))
            .onPressed,
        isNotNull,
      );
      await tester.pump(const Duration(seconds: 5)); // 오류 SnackBar가 닫힌 뒤 재시도.
      await tester.pumpAndSettle();
      await tester.tap(find.text('분석 요청'));
      await tester.pumpAndSettle();
      expect(client.requests.length, 2);
    },
  );

  testWidgets('rapid submit sends once and blocks back until network error', (
    tester,
  ) async {
    Session.instance.signIn('testuser01');
    final gate = Completer<void>();
    final client = UploadClient()
      ..gate = gate
      ..failNetwork = true;
    final api = AnalysisApi(client: client);
    addTearDown(api.dispose);
    await showReview(tester, api);
    await tester.tap(find.text('좌타'));
    await tester.pump();
    await tester.tap(find.text('분석 요청'));
    await tester.tap(find.text('분석 요청'));
    await tester.pump();
    expect(client.requests.length, 1);
    expect(client.requests.single.fields['handedness'], 'left');
    expect(tester.widget<PopScope>(find.byType(PopScope)).canPop, isFalse);
    gate.complete();
    await tester.pumpAndSettle();
    expect(find.textContaining('네트워크를 확인'), findsOneWidget);
    expect(tester.widget<PopScope>(find.byType(PopScope)).canPop, isTrue);
  });

  testWidgets(
    'upload replaces camera with first=1 result and keeps the selected source',
    (tester) async {
      Session.instance.signIn('testuser01');
      final client = UploadClient();
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      final source = StreamVideo();
      final players = <FakeVideoController>[];
      VideoPlayerController factory({String? videoPath, Uri? url}) {
        final player = FakeVideoController(localPath: videoPath, url: url);
        players.add(player);
        return player;
      }

      final router = GoRouter(
        routes: [
          GoRoute(
            path: '/',
            builder: (context, _) => Scaffold(
              body: TextButton(
                onPressed: () => context.push('/camera'),
                child: const Text('목록에서 촬영'),
              ),
            ),
          ),
          GoRoute(
            path: '/camera',
            builder: (context, _) => Scaffold(
              body: TextButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => SwingVideoReviewScreen(
                      video: source,
                      api: api,
                      controllerFactory: factory,
                    ),
                  ),
                ),
                child: const Text('선택 완료'),
              ),
            ),
          ),
          GoRoute(
            path: '/analyses/:id',
            builder: (_, state) => Scaffold(
              body: Column(
                children: [
                  Text(
                    '${state.pathParameters['id']} first=${state.uri.queryParameters['first']}',
                  ),
                  Expanded(
                    child: SwingVideo(
                      analysisId: state.pathParameters['id']!,
                      videoPath: state.extra as String?,
                      api: api,
                      controllerFactory: factory,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        observers: [swingRouteObserver],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.tap(find.text('목록에서 촬영'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('선택 완료'));
      await tester.pumpAndSettle();
      expect(players.single.plays, kIsWeb ? 0 : 1);
      await tester.tap(find.text('분석 요청'));
      await tester.pumpAndSettle();
      expect(find.text('uploaded first=1'), findsOneWidget);
      expect(find.byType(SwingVideoReviewScreen), findsNothing);
      expect(players.first.disposals, 1);
      expect(players.last.localPath, source.path);
      expect(players.last.plays, 0);
      await tester.tap(find.byIcon(Icons.play_arrow));
      await tester.pumpAndSettle();
      expect(players.last.value.isPlaying, isTrue);
      expect(client.requests.length, 1);
      expect(client.requests.single.fields['handedness'], 'right');
      router.pop();
      await tester.pumpAndSettle();
      expect(find.text('목록에서 촬영'), findsOneWidget);
      expect(players.last.disposals, 1);
    },
  );

  testWidgets('web Blob failure offers an explicit stored-video fallback', (
    tester,
  ) async {
    final calls = <Uri>[];
    final api = AnalysisApi(
      client: MockClient((request) async {
        calls.add(request.url);
        return http.Response(
          '{"analysis_id":"saved","url":"https://example.com/video","expires_in":900}',
          200,
        );
      }),
    );
    addTearDown(api.dispose);
    final players = <FakeVideoController>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SwingVideo(
            analysisId: 'saved',
            videoPath: 'blob:https://example.com/missing',
            api: api,
            controllerFactory: ({videoPath, url}) {
              final c = FakeVideoController(localPath: videoPath, url: url)
                ..failInitialize = videoPath != null;
              players.add(c);
              return c;
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(calls, isEmpty);
    await tester.tap(find.text('저장된 영상으로 재시도'));
    await tester.pumpAndSettle();
    expect(calls.single.path, '/api/analyses/saved/video');
    expect(players.first.disposals, 1);
    expect(players.last.localPath, isNull);
    expect(players.last.value.isPlaying, isTrue);
  }, skip: !kIsWeb);

  testWidgets('web Blob is released when review is cancelled', (tester) async {
    final file = XFile.fromData(
      Uint8List.fromList([1, 2, 3]),
      mimeType: 'video/mp4',
      name: 'test.mp4',
    );
    final path = file.path;
    final api = AnalysisApi(client: UploadClient());
    addTearDown(api.dispose);
    await showReview(tester, api, video: file);
    // Browser Blob reads complete through real DOM tasks, outside the widget
    // fake clock. Keep the fixture bytes and actual object-URL lifetime check.
    expect(await tester.runAsync(() => XFile(path).readAsBytes()), [1, 2, 3]);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.runAsync(
      () => expectLater(XFile(path).readAsBytes(), throwsException),
    );
  }, skip: !kIsWeb);

  testWidgets('result error still releases its Blob on exit', (tester) async {
    final file = XFile.fromData(
      Uint8List.fromList([1, 2, 3]),
      mimeType: 'video/mp4',
      name: 'test.mp4',
    );
    final path = file.path;
    final repo = FeedbackRepository(
      api: AnalysisApi(
        client: MockClient((_) async => http.Response('{}', 404)),
      ),
    );
    addTearDown(repo.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: OverallFeedbackScreen(
          analysisId: 'missing',
          videoPath: path,
          repository: repo,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(await tester.runAsync(() => XFile(path).readAsBytes()), [1, 2, 3]);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.runAsync(
      () => expectLater(XFile(path).readAsBytes(), throwsException),
    );
  }, skip: !kIsWeb);
}
