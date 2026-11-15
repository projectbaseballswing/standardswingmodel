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
import 'package:swing_analysis/screens/swing_trend_screen.dart';
import 'package:swing_analysis/theme/app_theme.dart';

final now = DateTime(2026, 11, 11, 15);
Map<String, Object?> record(
  String id,
  int days,
  double? score, {
  String status = 'done',
}) => {
  'analysis_id': id,
  'recorded_at': now.subtract(Duration(days: days)).toUtc().toIso8601String(),
  'status': status,
  'score': score,
};
http.Response listing(List<Map<String, Object?>> rows) => http.Response(
  jsonEncode({'items': rows}),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Future<void> show(
  WidgetTester tester,
  Future<http.Response> Function(http.Request) handler, {
  Size size = const Size(390, 844),
  bool fromList = false,
  double textScale = 1,
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final repo = SwingRepository(api: SwingApi(client: MockClient(handler)));
  addTearDown(repo.dispose);
  final router = GoRouter(
    initialLocation: fromList ? '/swings' : '/swings/trend',
    observers: [swingRouteObserver],
    routes: [
      GoRoute(
        path: '/swings',
        builder: (_, _) => SwingListScreen(repository: repo),
      ),
      GoRoute(
        path: '/swings/trend',
        builder: (_, _) => SwingTrendScreen(repository: repo, clock: () => now),
      ),
      GoRoute(
        path: '/analyses/:id',
        builder: (context, state) => Scaffold(
          body: Column(
            children: [
              Text('feedback:${state.pathParameters['id']}'),
              TextButton(
                onPressed: () => context.pop(),
                child: const Text('back'),
              ),
            ],
          ),
        ),
      ),
      GoRoute(
        path: '/login',
        builder: (_, _) => const Scaffold(body: Text('login destination')),
      ),
      GoRoute(
        path: '/swings/camera',
        builder: (_, _) => const Scaffold(body: Text('camera destination')),
      ),
      GoRoute(
        path: '/profile',
        builder: (_, _) => const Scaffold(body: Text('profile destination')),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    MaterialApp.router(
      theme: buildAppTheme(),
      routerConfig: router,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
    ),
  );
}

void main() {
  setUp(
    () => Session.instance.signIn('tester', accessToken: 'test-only-token'),
  );
  tearDown(Session.instance.clear);
  testWidgets('calendar bottom tab opens trend and back keeps calendar route', (
    tester,
  ) async {
    await show(tester, (_) async => listing([]), fromList: true);
    await tester.pumpAndSettle();
    await tester.tap(find.text('스윙 추이'));
    await tester.pumpAndSettle();
    expect(find.text('나의 스윙 점수 변화'), findsOneWidget);
    await tester.tap(find.byTooltip('스윙 기록으로'));
    await tester.pumpAndSettle();
    expect(find.byType(SwingListScreen), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('loading then empty records, period controls remain visible', (
    tester,
  ) async {
    final pending = Completer<http.Response>();
    await show(tester, (_) => pending.future);
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('전체'), findsOneWidget);
    pending.complete(listing([]));
    await tester.pumpAndSettle();
    expect(find.text('아직 스윙 기록이 없어요'), findsOneWidget);
  });
  testWidgets('network error retry succeeds without manufacturing scores', (
    tester,
  ) async {
    var calls = 0;
    await show(tester, (_) async {
      if (++calls == 1) throw http.ClientException('offline');
      return listing([record('one', 1, 81)]);
    });
    await tester.pumpAndSettle();
    expect(find.text('기록을 불러오지 못했어요'), findsOneWidget);
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(find.text('비교 전'), findsOneWidget);
    expect(calls, 2);
  });
  testWidgets('invalid/missing scores have a separate empty message', (
    tester,
  ) async {
    await show(
      tester,
      (_) async => listing([
        record('none', 1, null),
        record('working', 2, 88, status: 'processing'),
      ]),
    );
    await tester.pumpAndSettle();
    expect(find.text('표시할 종합 점수가 없어요'), findsOneWidget);
    expect(find.byKey(const ValueKey('swing-trend-chart')), findsNothing);
  });
  testWidgets(
    'period filters use same fetched records and duplicate does not add count',
    (tester) async {
      var calls = 0;
      final one = record('recent', 1, 80);
      await show(tester, (_) async {
        calls++;
        return listing([
          one,
          one,
          record('month', 20, 60),
          record('older', 50, 40),
        ]);
      });
      await tester.pumpAndSettle();
      expect(find.text('2건'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('trend-period-week')));
      await tester.pumpAndSettle();
      expect(find.text('1건'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('trend-period-all')));
      await tester.pumpAndSettle();
      expect(find.text('3건'), findsOneWidget);
      expect(calls, 1);
    },
  );
  testWidgets(
    'selected chart record and list record open existing analysis ID route; return refreshes',
    (tester) async {
      var calls = 0;
      await show(tester, (_) async {
        calls++;
        return listing([record('latest', 1, 80), record('earlier', 2, 60)]);
      });
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const ValueKey('trend-selected-feedback')),
      );
      await tester.tap(find.byKey(const ValueKey('trend-selected-feedback')));
      await tester.pumpAndSettle();
      expect(find.text('feedback:latest'), findsOneWidget);
      await tester.tap(find.text('back'));
      await tester.pumpAndSettle();
      expect(calls, 2);
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('trend-record-earlier')),
        150,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.byKey(const ValueKey('trend-record-earlier')));
      await tester.pumpAndSettle();
      expect(find.text('feedback:earlier'), findsOneWidget);
    },
  );
  testWidgets('chart point selection changes actual feedback target', (
    tester,
  ) async {
    await show(
      tester,
      (_) async => listing([record('latest', 1, 80), record('earlier', 2, 60)]),
    );
    await tester.pumpAndSettle();
    final chart = find.byKey(const ValueKey('swing-trend-chart'));
    await tester.ensureVisible(chart);
    final box = tester.getRect(chart);
    await tester.tapAt(Offset(box.left + 36, box.top + 89));
    await tester.pump();
    await tester.ensureVisible(
      find.byKey(const ValueKey('trend-selected-feedback')),
    );
    await tester.tap(find.byKey(const ValueKey('trend-selected-feedback')));
    await tester.pumpAndSettle();
    expect(find.text('feedback:earlier'), findsOneWidget);
  });
  testWidgets(
    'sign-out removes cached chart, blocks subsequent request and offers login',
    (tester) async {
      var calls = 0;
      await show(tester, (_) async {
        calls++;
        return listing([record('private', 1, 81)]);
      });
      await tester.pumpAndSettle();
      Session.instance.clear();
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('swing-trend-chart')), findsNothing);
      expect(calls, 1);
      await tester.tap(find.text('로그인하기'));
      await tester.pumpAndSettle();
      expect(find.text('login destination'), findsOneWidget);
    },
  );
  testWidgets('stale old-account response cannot replace new-account records', (
    tester,
  ) async {
    final old = Completer<http.Response>();
    await show(
      tester,
      (r) async => r.url.pathSegments[2] == 'tester'
          ? old.future
          : listing([record('new', 1, 90)]),
    );
    await tester.pump();
    Session.instance.signIn('new-user', accessToken: 'new-token');
    await tester.pumpAndSettle();
    old.complete(listing([record('old', 1, 10)]));
    await tester.pumpAndSettle();
    expect(find.text('선택한 기록 · 90.0점'), findsOneWidget);
    expect(find.text('선택한 기록 · 10.0점'), findsNothing);
  });
  for (final size in [const Size(320, 568), const Size(1280, 900)]) {
    testWidgets('responsive scroll layout without overflow at$size', (
      tester,
    ) async {
      await show(
        tester,
        (_) async => listing([
          for (var i = 0; i < 40; i++) record('a$i', i, 55 + i.toDouble()),
        ]),
        size: size,
        textScale: 1.3,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('trend-period-all')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('trend-record-a39')),
        350,
        scrollable: find.byType(Scrollable).first,
        maxScrolls: 30,
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  }
}
