import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/models/feedback.dart';

import 'feedback_fixture.dart';

http.Response response(Map<String, dynamic> body, [int status = 200]) =>
    http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

FeedbackRepository repositoryFor(
  Future<http.Response> Function(http.Request) handler,
) {
  final repo = FeedbackRepository(
    api: AnalysisApi(client: MockClient(handler)),
  );
  addTearDown(repo.dispose);
  return repo;
}

void main() {
  test(
    'historical report uses one GET with series and maps only actual data',
    () async {
      var calls = 0;
      final repo = repositoryFor((request) async {
        calls++;
        expect(request.method, 'GET');
        expect(request.url.path, '/api/analyses/saved-analysis');
        expect(request.url.queryParameters, {'include_series': 'true'});
        return response(storedAnalysis());
      });
      final feedback = await repo.fetchFeedback('saved-analysis');
      expect(calls, 1);
      expect(feedback.totalScore, 77); // 기존 UI의 정수 반올림 유지.
      expect(
        feedback.recordedAt,
        DateTime.parse('2026-10-09T09:30:00Z').toLocal(),
      );
      expect(feedback.recordedAt.isUtc, isFalse);
      expect(feedback.previousTotalScore, isNull);
      expect(feedback.totalDelta, isNull);
      expect(feedback.hasComparison, isFalse);
      expect(feedback.summary, isNot(contains('첫')));
      final item = feedback.items.single;
      expect(item.currentScore, 64);
      expect(item.previousScore, isNull);
      expect(item.delta, isNull);
      final feature = item.features.single;
      expect(feature.key, 'lead_elbow_angle');
      expect(feature.impact!.user, 123.4);
      expect(feature.rangeOfMotion!.user, 20.5);
      expect(feature.series!.map((sample) => sample.user), [
        110.0,
        null,
        123.4,
      ]);
      expect(feature.phaseScores, isNull); // 누락된 구간은 합성하지 않는다.
      final part = repo.buildPartAnalyses(feedback).single;
      expect(part.status, JointStatus.proBad);
      expect(part.previousScore, isNull);
      expect(part.delta, isNull);
    },
  );

  for (final status in ['queued', 'processing', 'failed', 'unknown']) {
    test(
      '$status is reported with one GET even if result is present',
      () async {
        var calls = 0;
        final repo = repositoryFor((_) async {
          calls++;
          return response({
            ...storedAnalysis(),
            'status': status,
            'error': {'message': '영상 품질 부족'},
          });
        });
        final message = switch (status) {
          'queued' => '대기',
          'processing' => '진행',
          'failed' => '영상 품질 부족',
          _ => '상태',
        };
        await expectLater(
          repo.fetchFeedback('saved-analysis'),
          throwsA(
            isA<ApiException>().having(
              (e) => e.message,
              'message',
              contains(message),
            ),
          ),
        );
        expect(calls, 1);
      },
    );
  }

  test('404 keeps server message', () async {
    final repo = repositoryFor(
      (_) async => response({'detail': '분석 결과를 찾을 수 없습니다.'}, 404),
    );
    await expectLater(
      repo.fetchFeedback('missing'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          '분석 결과를 찾을 수 없습니다.',
        ),
      ),
    );
  });

  test('network errors use ApiException', () async {
    final repo = repositoryFor(
      (_) async => throw http.ClientException('offline'),
    );
    await expectLater(
      repo.fetchFeedback('saved-analysis'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          contains('네트워크'),
        ),
      ),
    );
  });

  for (final result in [
    null,
    <String, dynamic>{},
    {'overall': <String, dynamic>{}},
    {
      'overall': {'score': null},
    },
  ]) {
    test(
      'missing result or required score reports unavailable ($result)',
      () async {
        final repo = repositoryFor(
          (_) async => response({...storedAnalysis(), 'result': result}),
        );
        await expectLater(
          repo.fetchFeedback('saved-analysis'),
          throwsA(isA<ApiException>()),
        );
      },
    );
  }

  test(
    'missing group score is omitted, while legitimate zero is preserved',
    () async {
      final body = storedAnalysis();
      body['result']['overall']['score'] = 0;
      body['result']['overall']['group_scores'][0]['score'] = null;
      final repo = repositoryFor((_) async => response(body));
      final feedback = await repo.fetchFeedback('saved-analysis');
      expect(feedback.totalScore, 0);
      expect(feedback.items, isEmpty);
      expect(feedback.coachComment, contains('정보가 없습니다'));
    },
  );

  test(
    'recorded_at falls back to server created_at, then finished_at',
    () async {
      final body = storedAnalysis()..remove('recorded_at');
      final repo = repositoryFor((_) async => response(body));
      expect(
        (await repo.fetchFeedback('saved-analysis')).recordedAt,
        DateTime.parse(body['created_at']).toLocal(),
      );
      body.remove('created_at');
      expect(
        (await repo.fetchFeedback('saved-analysis')).recordedAt,
        DateTime.parse(body['finished_at']).toLocal(),
      );
      body.remove('finished_at');
      await expectLater(
        repo.fetchFeedback('saved-analysis'),
        throwsA(isA<ApiException>()),
      );
    },
  );

  test(
    'new upload continues queued/processing polling with series until done',
    () async {
      var calls = 0;
      final repo = repositoryFor((request) async {
        expect(request.url.queryParameters['include_series'], 'true');
        final status = ['queued', 'processing', 'done'][calls++];
        return response({
          ...storedAnalysis(),
          'status': status,
          if (status != 'done') 'result': null,
        });
      });
      final feedback = await repo.fetchFeedback(
        'saved-analysis',
        firstTime: true,
      );
      expect(feedback.totalScore, 77);
      expect(calls, 3);
    },
  );

  for (final status in ['done', 'failed']) {
    test(
      'new upload terminal $status without result stops without fake feedback',
      () async {
        var calls = 0;
        final repo = repositoryFor((_) async {
          calls++;
          return response({
            ...storedAnalysis(),
            'status': status,
            'result': null,
          });
        });
        await expectLater(
          repo.fetchFeedback('saved-analysis', firstTime: true),
          throwsA(isA<ApiException>()),
        );
        expect(calls, 1);
      },
    );
  }
}
