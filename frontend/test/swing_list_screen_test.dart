import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/swing_list_screen.dart';

http.Response listing(List<Map<String, dynamic>> items) => http.Response(
  jsonEncode({'items': items}),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Map<String, dynamic> record(
  DateTime date, {
  String status = 'done',
  double? score = 77.3,
}) => {
  'analysis_id': 'analysis-${date.toIso8601String()}-$status',
  'recorded_at': date.toUtc().toIso8601String(),
  'status': status,
  'score': score,
  'thumbnail_url': null,
};

SwingRepository repositoryWith(
  Future<http.Response> Function(http.Request) handler,
) {
  final repository = SwingRepository(
    api: SwingApi(client: MockClient(handler)),
  );
  addTearDown(repository.dispose);
  return repository;
}

Future<void> showList(
  WidgetTester tester,
  SwingRepository repository, {
  Size size = const Size(430, 900),
}) async {
  configureView(tester, size: size);
  await tester.pumpWidget(
    MaterialApp(
      navigatorObservers: [swingRouteObserver],
      home: SwingListScreen(repository: repository),
    ),
  );
}

void configureView(WidgetTester tester, {Size size = const Size(430, 900)}) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
}

void main() {
  setUp(() => Session.instance.signIn('tester'));
  tearDown(Session.instance.clear);

  testWidgets('small screen can scroll to record status without overflow', (
    tester,
  ) async {
    final now = DateTime.now();
    final repository = repositoryWith(
      (_) async => listing([record(DateTime(now.year, now.month, 5, 10))]),
    );
    await showList(tester, repository, size: const Size(360, 600));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('완료 · 77.3점'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('10시 0분'));
    await tester.pump();
    expect(find.text('과거 스윙의 분석 결과 조회는 준비 중입니다.'), findsOneWidget);
  });

  testWidgets(
    'initial current month, empty month and navigation controls stay visible while loading',
    (tester) async {
      final pending = Completer<http.Response>();
      final requests = <http.Request>[];
      final repository = repositoryWith((request) {
        requests.add(request);
        return pending.future;
      });
      final now = DateTime.now();
      await showList(tester, repository);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byIcon(Icons.chevron_left), findsOneWidget);
      expect(find.byType(BottomNavigationBar), findsOneWidget);
      expect(requests.single.url.queryParameters['year'], '${now.year}');
      expect(requests.single.url.queryParameters['month'], '${now.month}');
      pending.complete(listing([]));
      await tester.pumpAndSettle();
      expect(find.text('이번 달의 스윙 기록이 없습니다.'), findsOneWidget);
      expect(find.text('${now.month}월 ${now.day}일'), findsOneWidget);
    },
  );

  testWidgets(
    'month movement requests the server and selects a date within that month',
    (tester) async {
      final requests = <http.Request>[];
      final repository = repositoryWith((request) async {
        requests.add(request);
        return listing([]);
      });
      final now = DateTime.now();
      await showList(tester, repository);
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.chevron_left));
      await tester.pumpAndSettle();
      final previous = DateTime(now.year, now.month - 1);
      expect(requests.last.url.queryParameters['year'], '${previous.year}');
      expect(requests.last.url.queryParameters['month'], '${previous.month}');
      expect(find.text('${previous.month}월 1일'), findsOneWidget);
      await tester.tap(find.byIcon(Icons.chevron_right));
      await tester.pumpAndSettle();
      expect(requests.length, 3);
      expect(find.text('${now.month}월 ${now.day}일'), findsOneWidget);
    },
  );

  testWidgets(
    'records are grouped by local day, decimals are visible, history shows guidance',
    (tester) async {
      final now = DateTime.now();
      final repository = repositoryWith(
        (_) async => listing([
          record(DateTime(now.year, now.month, 6, 16, 30)),
          record(DateTime(now.year, now.month, 2, 9, 5), score: null),
        ]),
      );
      await showList(tester, repository);
      await tester.pumpAndSettle();
      expect(find.text('${now.month}월 6일'), findsOneWidget);
      expect(find.text('16시 30분'), findsOneWidget);
      expect(find.text('9시 5분'), findsNothing);
      expect(find.text('완료 · 77.3점'), findsOneWidget);
      expect(find.byIcon(Icons.play_circle_outline), findsOneWidget);
      await tester.tap(find.text('16시 30분'));
      await tester.pump();
      expect(find.text('과거 스윙의 분석 결과 조회는 준비 중입니다.'), findsOneWidget);
      expect(find.byType(SwingListScreen), findsOneWidget);
      await tester.tap(find.text('2'));
      await tester.pump();
      expect(find.text('9시 5분'), findsOneWidget);
      expect(find.text('분석 완료'), findsOneWidget);
      await tester.tap(find.text('3'));
      await tester.pump();
      expect(find.text('이 날 촬영한 스윙이 없습니다.'), findsOneWidget);
    },
  );

  for (final entry in {
    'queued': '분석 대기 중',
    'processing': '분석 중',
    'failed': '분석 실패',
  }.entries) {
    testWidgets(
      '${entry.key} has an explicit status and never opens sample feedback',
      (tester) async {
        final now = DateTime.now();
        final repository = repositoryWith(
          (_) async => listing([
            record(
              DateTime(now.year, now.month, 5, 10),
              status: entry.key,
              score: null,
            ),
          ]),
        );
        await showList(tester, repository);
        await tester.pumpAndSettle();
        expect(find.text(entry.value), findsOneWidget);
        await tester.tap(find.text('10시 0분'));
        await tester.pump();
        expect(
          find.text(
            entry.key == 'failed'
                ? '분석에 실패한 기록입니다. 영상을 다시 업로드해주세요.'
                : '분석이 진행 중입니다. 잠시 후 다시 확인해주세요.',
          ),
          findsOneWidget,
        );
      },
    );
  }

  testWidgets('network error offers retry and recovers', (tester) async {
    var calls = 0;
    final repository = repositoryWith((_) async {
      if (++calls == 1) throw http.ClientException('offline');
      return listing([]);
    });
    await showList(tester, repository);
    await tester.pumpAndSettle();
    expect(find.textContaining('네트워크'), findsOneWidget);
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('이번 달의 스윙 기록이 없습니다.'), findsOneWidget);
  });

  for (final oldRequestFails in [false, true]) {
    testWidgets(
      'older ${oldRequestFails ? 'error' : 'success'} cannot replace the newest month',
      (tester) async {
        final requests = <http.Request>[];
        final responses = <Completer<http.Response>>[];
        final repository = repositoryWith((request) {
          requests.add(request);
          final response = Completer<http.Response>();
          responses.add(response);
          return response.future;
        });
        await showList(tester, repository);
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump();
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump();
        expect(responses.length, 3);
        final query = requests.last.url.queryParameters;
        final latest = DateTime(
          int.parse(query['year']!),
          int.parse(query['month']!),
          4,
          12,
        );
        responses[2].complete(listing([record(latest, score: 88.8)]));
        await tester.pumpAndSettle();
        if (oldRequestFails) {
          responses[1].completeError(http.ClientException('old error'));
        } else {
          responses[1].complete(listing([record(DateTime.now(), score: 11.1)]));
        }
        responses[0].complete(listing([]));
        await tester.pumpAndSettle();
        expect(find.text('${latest.month}월 4일'), findsOneWidget);
        expect(find.text('완료 · 88.8점'), findsOneWidget);
        expect(find.text('완료 · 11.1점'), findsNothing);
        expect(find.text('다시 시도'), findsNothing);
      },
    );
  }

  testWidgets('late response after disposal is ignored', (tester) async {
    final response = Completer<http.Response>();
    final repository = repositoryWith((_) => response.future);
    await showList(tester, repository);
    await tester.pumpWidget(const SizedBox());
    response.complete(listing([]));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('no session shows login guidance without HTTP', (tester) async {
    Session.instance.clear();
    var calls = 0;
    final repository = repositoryWith((_) async {
      calls++;
      return listing([]);
    });
    await showList(tester, repository);
    await tester.pumpAndSettle();
    expect(calls, 0);
    expect(find.text('로그인한 뒤 스윙 기록을 확인해주세요.'), findsOneWidget);
  });

  testWidgets(
    'camera replacement by feedback refreshes only when the list becomes visible',
    (tester) async {
      var calls = 0;
      final now = DateTime.now();
      final repository = repositoryWith(
        (_) async => ++calls == 1
            ? listing([])
            : listing([
                record(DateTime(now.year, now.month, now.day, 14), score: 91.2),
              ]),
      );
      final router = GoRouter(
        initialLocation: '/swings',
        observers: [swingRouteObserver],
        routes: [
          GoRoute(
            path: '/swings',
            builder: (_, _) => SwingListScreen(repository: repository),
          ),
          GoRoute(
            path: '/swings/camera',
            builder: (context, _) => Scaffold(
              body: TextButton(
                child: const Text('review'),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (context) => Scaffold(
                      body: TextButton(
                        child: const Text('upload success'),
                        onPressed: () {
                          final router = GoRouter.of(context);
                          Navigator.of(context).pop();
                          router.pushReplacement(
                            '/analyses/new?first=1',
                            extra: 'local.mp4',
                          );
                        },
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          GoRoute(
            path: '/analyses/:id',
            builder: (context, state) => Scaffold(
              body: Column(
                children: [
                  Text(
                    'feedback first=${state.uri.queryParameters['first']} ${state.extra}',
                  ),
                  TextButton(
                    onPressed: () => context.pop(),
                    child: const Text('back to list'),
                  ),
                ],
              ),
            ),
          ),
        ],
      );
      addTearDown(router.dispose);
      configureView(tester);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.pumpAndSettle();
      expect(calls, 1);
      await tester.tap(find.byIcon(Icons.add));
      await tester.pumpAndSettle();
      await tester.tap(find.text('review'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('upload success'));
      await tester.pumpAndSettle();
      expect(find.text('feedback first=1 local.mp4'), findsOneWidget);
      expect(calls, 1);
      await tester.tap(find.text('back to list'));
      await tester.pumpAndSettle();
      expect(calls, 2);
      expect(find.text('완료 · 91.2점'), findsOneWidget);
    },
  );
}
