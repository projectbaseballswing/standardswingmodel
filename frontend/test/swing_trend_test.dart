import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/models/swing.dart';
import 'package:swing_analysis/models/swing_trend.dart';

final now = DateTime(2026, 11, 11, 15);
Swing row(
  String id,
  DateTime date, {
  double? score = 70,
  String status = 'done',
}) => Swing(analysisId: id, recordedAt: date, status: status, score: score);
SwingTrend trend(
  List<Swing> rows, [
  SwingTrendPeriod period = SwingTrendPeriod.all,
]) => SwingTrend.fromSwings(rows, period: period, now: now);

void main() {
  tearDown(Session.instance.clear);
  test(
    'all-history request omits year/month and carries current Bearer token',
    () async {
      Session.instance.signIn('user /한글', accessToken: 'test-token');
      final repository = SwingRepository(
        api: SwingApi(
          client: MockClient((request) async {
            expect(request.url.pathSegments[2], 'user /한글');
            expect(request.url.queryParameters.keys, ['tz_offset_minutes']);
            expect(request.headers['Authorization'], 'Bearer test-token');
            return http.Response(
              jsonEncode({
                'items': [
                  {
                    'analysis_id': 'a',
                    'recorded_at': '2026-11-01T12:00:00Z',
                    'status': 'done',
                    'score': 72,
                  },
                ],
              }),
              200,
            );
          }),
        ),
      );
      addTearDown(repository.dispose);
      expect((await repository.fetchAllMySwings()).single.score, 72);
    },
  );
  test(
    'all-history never sends request without authenticated session',
    () async {
      var requests = 0;
      final repository = SwingRepository(
        api: SwingApi(
          client: MockClient((_) async {
            requests++;
            return http.Response('{"items":[]}', 200);
          }),
        ),
      );
      addTearDown(repository.dispose);
      for (final hasUser in [false, true]) {
        if (hasUser) Session.instance.signIn('user');
        await expectLater(
          repository.fetchAllMySwings(),
          throwsA(isA<ApiException>()),
        );
      }
      expect(requests, 0);
    },
  );
  test('same-account token change rejects previous response', () async {
    final response = Completer<http.Response>();
    final repository = SwingRepository(
      api: SwingApi(client: MockClient((_) => response.future)),
    );
    addTearDown(repository.dispose);
    Session.instance.signIn('u', accessToken: 'old');
    final pending = repository.fetchAllMySwings();
    Session.instance.signIn('u', accessToken: 'new');
    final expectation = expectLater(pending, throwsA(isA<ApiException>()));
    response.complete(http.Response('{"items":[]}', 200));
    await expectation;
  });
  test('partial month filter is rejected before HTTP', () async {
    final api = SwingApi(
      client: MockClient((_) async => throw StateError('must not call')),
    );
    addTearDown(api.dispose);
    await expectLater(
      api.fetchSwings(userId: 'u', year: 2026, tzOffsetMinutes: 0),
      throwsArgumentError,
    );
  });
  test(
    '7 and30 local calendar days include start boundary, exclude future',
    () {
      final rows = [
        row('week-start', DateTime(2026, 11, 5)),
        row('before-week', DateTime(2026, 11, 4, 23, 59)),
        row('month-start', DateTime(2026, 10, 13)),
        row('before-month', DateTime(2026, 10, 12, 23, 59)),
        row('now', now),
        row('future', now.add(const Duration(seconds: 1))),
      ];
      expect(
        trend(rows, SwingTrendPeriod.week).points.map((s) => s.analysisId),
        ['week-start', 'now'],
      );
      expect(
        trend(rows, SwingTrendPeriod.month).points.map((s) => s.analysisId),
        ['month-start', 'before-week', 'week-start', 'now'],
      );
      expect(trend(rows).points.length, 5);
    },
  );
  test(
    'calendar month/year rollover keeps30days, not calendar month subtraction',
    () {
      final t = SwingTrend.fromSwings(
        [
          row('included', DateTime(2025, 12, 3)),
          row('excluded', DateTime(2025, 12, 2, 23, 59)),
        ],
        period: SwingTrendPeriod.month,
        now: DateTime(2026, 1, 1, 8),
      );
      expect(t.points.single.analysisId, 'included');
    },
  );
  test('only done finite0..100 scores included, zero remains actual zero', () {
    final rows = [
      row('zero', now, score: 0),
      row('100', now, score: 100),
      for (final status in ['queued', 'processing', 'failed', 'unknown'])
        row(status, now, status: status),
      row('null', now, score: null),
      row('nan', now, score: double.nan),
      row('inf', now, score: double.infinity),
      row('negative', now, score: -1),
      row('too-high', now, score: 101),
      row('', now),
    ];
    final t = trend(rows);
    expect(t.points.map((s) => s.score), [100, 0]);
    expect(t.average, 50);
    expect(t.excludedCount, 10);
    expect(t.conflictingCount, 0);
  });
  test(
    'duplicate same ID counted once; distinct simultaneous analyses remain',
    () {
      final r = row('a', now, score: 20);
      final t = trend([r, r, row('b', now, score: 80)]);
      expect(t.points.length, 2);
      expect(t.duplicateCount, 1);
      expect(t.average, 50);
    },
  );
  for (final field in ['score', 'date', 'status']) {
    test(
      'conflicting duplicate $field excluded, not arbitrarily corrected',
      () {
        final a = row('a', now);
        final b = row(
          'a',
          field == 'date' ? now.subtract(const Duration(days: 1)) : now,
          score: field == 'score' ? 80 : 70,
          status: field == 'status' ? 'failed' : 'done',
        );
        final t = trend([a, b, row('safe', now, score: 50)]);
        expect(t.points.single.analysisId, 'safe');
        expect(t.conflictingCount, 1);
        expect(t.average, 50);
      },
    );
  }
  test('empty and single point never invent a change or zero mean', () {
    expect(trend([]).average, isNull);
    expect(trend([]).change, isNull);
    final t = trend([row('one', now, score: 81)]);
    expect(t.average, 81);
    expect(t.change, isNull);
  });
  test(
    'sort ascending without modifying original and compute first/last actual points',
    () {
      final rows = [
        row('last', now, score: 89),
        row('first', now.subtract(const Duration(days: 2)), score: 62),
        row('mid', now.subtract(const Duration(days: 1)), score: 71),
      ];
      final t = trend(rows);
      expect(t.points.map((s) => s.analysisId), ['first', 'mid', 'last']);
      expect(t.change, 27);
      expect(rows.first.analysisId, 'last');
    },
  );
}
