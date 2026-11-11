import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
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
      expect(feedback.totalScore, 77.3); // 서버의 소수점 점수 보존.
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
      expect(item.currentScore, 63.8);
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
      expect(feature.phaseScores!.single.key, 'swing');
      expect(feature.phaseScores!.single.score, 80); // 있는 구간만 참고 점수로 표시.
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

  for (final result in [null, <String, dynamic>{}]) {
    test('missing result reports unavailable ($result)', () async {
      final repo = repositoryFor(
        (_) async => response({...storedAnalysis(), 'result': result}),
      );
      await expectLater(
        repo.fetchFeedback('saved-analysis'),
        throwsA(isA<ApiException>()),
      );
    });
  }

  test(
    'missing group score stays null, while legitimate zero is preserved',
    () async {
      final body = storedAnalysis();
      body['result']['overall']['score'] = 0;
      body['result']['overall']['group_scores'][0]['score'] = null;
      final repo = repositoryFor((_) async => response(body));
      final feedback = await repo.fetchFeedback('saved-analysis');
      expect(feedback.totalScore, 0);
      expect(feedback.items.single.currentScore, isNull);
      expect(feedback.items.single.limited, isTrue);
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
      expect(feedback.totalScore, 77.3);
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

  test('LLM coaching overrides rule-based summary/coach and part points', () async {
    final body = storedAnalysis();
    (body['result'] as Map<String, dynamic>)['coaching'] = {
      'overall_summary': 'LLM 종합 요약입니다.',
      'overall_coach': 'LLM 코치 한마디입니다.',
      'parts': [
        {
          'key': 'lead_arm',
          'summary': 'LLM 앞팔 요약.',
          'keep_points': <String>[],
          'improve_points': ['앞팔 팔꿈치를 더 펴 보세요.'],
        },
      ],
    };
    final repo = repositoryFor((_) async => response(body));

    final feedback = await repo.fetchFeedback('saved-analysis');
    expect(feedback.summary, 'LLM 종합 요약입니다.');
    expect(feedback.coachComment, 'LLM 코치 한마디입니다.');
    expect(feedback.coaching, isNotNull);

    final part = repo.buildPartAnalyses(feedback).single;
    expect(part.summary, 'LLM 앞팔 요약.');
    expect(part.points, ['앞팔 팔꿈치를 더 펴 보세요.']);
  });

  test('full-scope coaching maps joint comment and phase coaching', () async {
    final body = storedAnalysis();
    final result = body['result'] as Map<String, dynamic>;
    result['phases'] = {
      'phases': [
        {
          'key': 'swing',
          'name': '스윙',
          'available': true,
          'score': 70.0,
          'reliability': 'high',
        },
      ],
    };
    result['coaching'] = {
      'overall_summary': 'LLM 종합 요약입니다.',
      'overall_coach': 'LLM 코치 한마디입니다.',
      'parts': <Map<String, dynamic>>[],
      'joints': [
        {'key': 'lead_elbow_angle', 'comment': '팔꿈치가 기준보다 큽니다.'},
      ],
      'phases': [
        {
          'key': 'swing',
          'card_line': '스윙이 조금 빨라요.',
          'comment': '스윙 구간 템포가 기준보다 빠릅니다.',
          'tip': '천천히 끝까지 밀어 보세요.',
        },
      ],
    };
    final repo = repositoryFor((_) async => response(body));

    final feedback = await repo.fetchFeedback('saved-analysis');
    // 피처(관절) 코멘트가 붙었는지.
    expect(feedback.items.single.features.single.comment, '팔꿈치가 기준보다 큽니다.');
    expect(feedback.coaching!.joints['lead_elbow_angle'], '팔꿈치가 기준보다 큽니다.');
    // 구간 코칭이 붙었는지.
    final phase = feedback.phases.single;
    expect(phase.coachCardLine, '스윙이 조금 빨라요.');
    expect(phase.coachComment, '스윙 구간 템포가 기준보다 빠릅니다.');
    expect(phase.coachTip, '천천히 끝까지 밀어 보세요.');
    expect(feedback.coaching!.phases['swing']!.tip, '천천히 끝까지 밀어 보세요.');
  });

  test('overall-scope coaching leaves joint/phase coaching empty', () async {
    final body = storedAnalysis();
    final result = body['result'] as Map<String, dynamic>;
    result['phases'] = {
      'phases': [
        {
          'key': 'swing',
          'name': '스윙',
          'available': true,
          'score': 70.0,
          'reliability': 'high',
        },
      ],
    };
    result['coaching'] = {
      'overall_summary': 'LLM 종합 요약입니다.',
      'overall_coach': 'LLM 코치 한마디입니다.',
      'parts': <Map<String, dynamic>>[],
    };
    final repo = repositoryFor((_) async => response(body));

    final feedback = await repo.fetchFeedback('saved-analysis');
    // joints/phases 가 없으면 피처/구간 코칭은 빈 문자열로 폴백.
    expect(feedback.items.single.features.single.comment, '');
    expect(feedback.phases.single.coachCardLine, '');
    expect(feedback.phases.single.coachTip, '');
    expect(feedback.coaching!.joints, isEmpty);
    expect(feedback.coaching!.phases, isEmpty);
  });

  test('missing coaching falls back to rule-based text', () async {
    // 픽스처엔 coaching 키가 없다 → 규칙 기반 문구 유지.
    final repo = repositoryFor((_) async => response(storedAnalysis()));
    final feedback = await repo.fetchFeedback('saved-analysis');
    expect(feedback.coaching, isNull);
    expect(feedback.summary, contains('스윙 분석 결과')); // _buildSummary 문구.
  });

  test('malformed coaching (missing overall fields) is ignored', () async {
    final body = storedAnalysis();
    (body['result'] as Map<String, dynamic>)['coaching'] = {
      'parts': [
        {'key': 'lead_arm', 'summary': 'x'},
      ],
    };
    final repo = repositoryFor((_) async => response(body));
    final feedback = await repo.fetchFeedback('saved-analysis');
    // overall_summary/overall_coach 가 없으면 통째로 무시 → 규칙 기반.
    expect(feedback.coaching, isNull);
    expect(feedback.summary, contains('스윙 분석 결과'));
  });

  group('comparison (반복 피드백)', () {
    setUp(() => Session.instance.userId = 'user-1');
    tearDown(() => Session.instance.clear());

    Map<String, dynamic> comparisonBody() => {
      'has_previous': true,
      'previous_analysis_id': 'prev-1',
      'overall_previous_score': 70.0,
      'overall_delta': 7.3,
      'parts': [
        {'key': 'lead_arm', 'previous_score': 60.0, 'delta': 3.8},
      ],
      'phases': <dynamic>[],
      'joints': <dynamic>[],
      'coaching': {
        'overall_summary': '지난 스윙보다 전체적으로 좋아졌어요.',
        'overall_coach': '앞팔 안정감을 계속 유지하세요.',
        'parts': [
          {
            'key': 'lead_arm',
            'summary': '앞팔이 지난번보다 안정됐어요.',
            'keep_points': ['지금 리듬을 유지해 보세요.'],
            'improve_points': <String>[],
          },
        ],
      },
    };

    // 분석 조회와 comparison 조회를 경로로 구분해 응답한다.
    FeedbackRepository repoWithComparison(Map<String, dynamic> comparison) =>
        repositoryFor((request) async {
          if (request.url.path.endsWith('/comparison')) {
            return response(comparison);
          }
          return response(storedAnalysis());
        });

    test('previous scores and 이전 대비 LLM coaching are applied', () async {
      final repo = repoWithComparison(comparisonBody());
      final feedback = await repo.fetchFeedback('saved-analysis');

      // 전체: 이전 점수·증감 활성화.
      expect(feedback.hasComparison, isTrue);
      expect(feedback.previousTotalScore, 70.0);
      expect(feedback.totalDelta, closeTo(7.3, 1e-9));
      // 부위: 이전 점수 매칭.
      final item = feedback.items.single;
      expect(item.previousScore, 60.0);
      expect(item.delta, closeTo(3.8, 1e-9));
      // 코칭: '이전 대비' 문장이 요약·부위에 반영.
      expect(feedback.summary, '지난 스윙보다 전체적으로 좋아졌어요.');
      expect(feedback.coaching!.parts['lead_arm']!.summary, '앞팔이 지난번보다 안정됐어요.');

      // 부위 상세: 개선(improved) 상태 + 이전 대비 LLM 포인트.
      final part = repo.buildPartAnalyses(feedback).single;
      expect(part.status, JointStatus.improved);
      expect(part.summary, '앞팔이 지난번보다 안정됐어요.');
      expect(part.points, ['지금 리듬을 유지해 보세요.']);
    });

    test('has_previous=false falls back to first-feedback (no comparison)',
        () async {
      final repo = repoWithComparison({'has_previous': false});
      final feedback = await repo.fetchFeedback('saved-analysis');
      expect(feedback.hasComparison, isFalse);
      expect(feedback.previousTotalScore, isNull);
      expect(feedback.items.single.previousScore, isNull);
    });

    test('comparison fetch failure is swallowed (still shows first feedback)',
        () async {
      final repo = repositoryFor((request) async {
        if (request.url.path.endsWith('/comparison')) {
          return response({'detail': 'nope'}, 500);
        }
        return response(storedAnalysis());
      });
      final feedback = await repo.fetchFeedback('saved-analysis');
      expect(feedback.hasComparison, isFalse);
      expect(feedback.totalScore, 77.3);
    });
  });
}
