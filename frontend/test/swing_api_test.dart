import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/api_config.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/api/swing_api.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/data/swing_repository.dart';
import 'package:swing_analysis/models/swing.dart';

Map<String, dynamic> record({Object? score = 77.3, String? thumbnail}) => {
  'analysis_id': 'analysis-1',
  'recorded_at': '2026-09-30T15:30:00Z',
  'status': 'done',
  'score': score,
  'thumbnail_url': thumbnail,
};

http.Response listing(List<Map<String, dynamic>> items) => http.Response(
  jsonEncode({
    'user_id': 'tester',
    'year_month': '2026-10',
    'count': items.length,
    'items': items,
  }),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void main() {
  tearDown(Session.instance.clear);

  test(
    'GET uses base URL, encoded user ID, month and explicit calendar offset',
    () async {
      final api = SwingApi(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.origin, Uri.parse(ApiConfig.baseUrl).origin);
          expect(request.url.pathSegments, [
            'api',
            'users',
            'user #/?한글',
            'swings',
          ]);
          expect(request.url.queryParameters, {
            'year': '2026',
            'month': '10',
            'tz_offset_minutes': '540',
          });
          expect(request.headers['Accept'], 'application/json');
          return listing([record()]);
        }),
      );
      addTearDown(api.dispose);
      final items = await api.fetchSwings(
        userId: 'user #/?한글',
        year: 2026,
        month: 10,
        tzOffsetMinutes: 540,
      );
      expect(items.single['score'], 77.3);
    },
  );

  test(
    'repository requests the active account on each call and maps local dates',
    () async {
      final requests = <http.Request>[];
      final repository = SwingRepository(
        api: SwingApi(
          client: MockClient((request) async {
            requests.add(request);
            return listing([record()]);
          }),
        ),
      );
      addTearDown(repository.dispose);
      Session.instance.signIn('first');
      final swings = await repository.fetchMySwings(year: 2026, month: 10);
      Session.instance.signIn('second');
      await repository.fetchMySwings(year: 2027, month: 1);
      expect(requests.map((r) => r.url.pathSegments[2]), ['first', 'second']);
      expect(requests.last.url.queryParameters, {
        'year': '2027',
        'month': '1',
        'tz_offset_minutes': '${DateTime(2027, 1).timeZoneOffset.inMinutes}',
      });
      final swing = swings.single;
      final local = DateTime.parse('2026-09-30T15:30:00Z').toLocal();
      expect(swing.recordedAt, local);
      expect(swing.recordedAt.isUtc, isFalse);
      expect(
        swing.isOnDay(DateTime(local.year, local.month, local.day)),
        isTrue,
      );
      expect(
        swing.isOnDay(DateTime(local.year, local.month, local.day + 1)),
        isFalse,
      );
      expect(swing.timeLabel, '${local.hour}시 ${local.minute}분');
      expect(swing.score, 77.3);
      expect(swing.status, 'done');
      expect(swing.thumbnailUrl, isNull);
    },
  );

  test('UTC boundary and offset notation map to the same local day', () {
    final utc = Swing.fromJson(record());
    final offset = Swing.fromJson({
      ...record(),
      'recorded_at': '2026-10-01T00:30:00+09:00',
    });
    expect(utc.recordedAt, offset.recordedAt);
    expect(utc.recordedAt.toUtc(), DateTime.utc(2026, 9, 30, 15, 30));
    // 한국시간 환경에서는 9월 UTC 기록이 10월 1일 달력에 표시된다.
    if (utc.recordedAt.timeZoneOffset == const Duration(hours: 9)) {
      expect(utc.isOnDay(DateTime(2026, 10, 1)), isTrue);
    }
  });

  test(
    'integer and null scores, nullable thumbnail and all statuses are preserved',
    () {
      expect(Swing.fromJson(record(score: 72)).score, 72.0);
      expect(
        Swing.fromJson(
          record(thumbnail: 'https://example.com/thumb.jpg'),
        ).thumbnailUrl,
        'https://example.com/thumb.jpg',
      );
      for (final status in ['queued', 'processing', 'done', 'failed']) {
        final swing = Swing.fromJson({
          ...record(score: null),
          'status': status,
        });
        expect(swing.score, isNull);
        expect(swing.thumbnailUrl, isNull);
        expect(swing.status, status);
      }
    },
  );

  for (final userId in <String?>[null, '', '   ']) {
    test('no HTTP request without a valid session ($userId)', () async {
      var calls = 0;
      final repository = SwingRepository(
        api: SwingApi(
          client: MockClient((_) async {
            calls++;
            return listing([]);
          }),
        ),
      );
      addTearDown(repository.dispose);
      Session.instance.userId = userId;
      await expectLater(
        repository.fetchMySwings(year: 2026, month: 10),
        throwsA(isA<ApiException>()),
      );
      expect(calls, 0);
    });
  }

  test('empty list stays empty', () async {
    Session.instance.signIn('tester');
    final repository = SwingRepository(
      api: SwingApi(client: MockClient((_) async => listing([]))),
    );
    addTearDown(repository.dispose);
    expect(await repository.fetchMySwings(year: 2026, month: 10), isEmpty);
  });

  test('network errors use the existing ApiException contract', () async {
    final api = SwingApi(
      client: MockClient((_) async => throw http.ClientException('offline')),
    );
    addTearDown(api.dispose);
    await expectLater(
      api.fetchSwings(
        userId: 'tester',
        year: 2026,
        month: 10,
        tzOffsetMinutes: 540,
      ),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          contains('네트워크'),
        ),
      ),
    );
  });

  for (final response in [
    http.Response(
      jsonEncode({'detail': '사용자를 찾을 수 없습니다.'}),
      404,
      headers: {'content-type': 'application/json; charset=utf-8'},
    ),
    http.Response(
      jsonEncode({
        'detail': [
          {'msg': 'invalid month'},
        ],
      }),
      422,
    ),
    http.Response('<html>Unavailable</html>', 503),
    http.Response('{', 200),
    http.Response('{"items":null}', 200),
  ]) {
    test(
      'HTTP or malformed response becomes ApiException (${response.statusCode}, ${response.body})',
      () async {
        final api = SwingApi(client: MockClient((_) async => response));
        addTearDown(api.dispose);
        await expectLater(
          api.fetchSwings(
            userId: 'tester',
            year: 2026,
            month: 10,
            tzOffsetMinutes: 540,
          ),
          throwsA(isA<ApiException>()),
        );
      },
    );
  }

  test('server detail is preserved', () async {
    final api = SwingApi(
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'detail': '사용자를 찾을 수 없습니다.'}),
          404,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    addTearDown(api.dispose);
    await expectLater(
      api.fetchSwings(
        userId: 'tester',
        year: 2026,
        month: 10,
        tzOffsetMinutes: 540,
      ),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'detail',
          '사용자를 찾을 수 없습니다.',
        ),
      ),
    );
  });

  test('a response from a previous session is rejected', () async {
    final response = Completer<http.Response>();
    final repository = SwingRepository(
      api: SwingApi(client: MockClient((_) => response.future)),
    );
    addTearDown(repository.dispose);
    Session.instance.signIn('first');
    final pending = repository.fetchMySwings(year: 2026, month: 10);
    Session.instance.signIn('second');
    final check = expectLater(pending, throwsA(isA<ApiException>()));
    response.complete(listing([record()]));
    await check;
  });

  test(
    'invalid record date is reported instead of silently dropping records',
    () async {
      Session.instance.signIn('tester');
      final repository = SwingRepository(
        api: SwingApi(
          client: MockClient(
            (_) async => listing([
              {...record(), 'recorded_at': 'invalid'},
            ]),
          ),
        ),
      );
      addTearDown(repository.dispose);
      await expectLater(
        repository.fetchMySwings(year: 2026, month: 10),
        throwsA(isA<ApiException>()),
      );
    },
  );
}
