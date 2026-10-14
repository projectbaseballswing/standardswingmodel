import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/api/auth_api.dart';

void main() {
  const valid = {
    'analysis_id': 'saved-analysis',
    'url':
        'https://example.supabase.co/storage/v1/object/sign/video?token=secret',
    'expires_in': 900,
  };

  AnalysisApi apiFor(Future<http.Response> Function(http.Request) handler) {
    final api = AnalysisApi(client: MockClient(handler));
    addTearDown(api.dispose);
    return api;
  }

  test('GET video uses the analysis ID and parses URL and expiry', () async {
    final api = apiFor((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/api/analyses/saved-analysis/video');
      expect(request.url.query, isEmpty);
      expect(request.headers['Accept'], 'application/json');
      return http.Response(jsonEncode(valid), 200);
    });
    final video = await api.getVideoUrl('saved-analysis');
    expect(video.url, Uri.parse(valid['url'] as String));
    expect(video.expiresIn, 900);
  });

  test('analysis ID is encoded as a single path segment', () async {
    const id = 'id/with?query#fragment';
    final api = apiFor((request) async {
      expect(request.url.pathSegments, ['api', 'analyses', id, 'video']);
      expect(request.url.query, isEmpty);
      return http.Response(jsonEncode({...valid, 'analysis_id': id}), 200);
    });
    await api.getVideoUrl(id);
  });

  final invalid = <String, Object?>{
    'not JSON': 'invalid',
    'array': [],
    'empty': {},
    'different analysis': {...valid, 'analysis_id': 'other'},
    'missing URL': {...valid}..remove('url'),
    'relative URL': {...valid, 'url': '/video?token=secret'},
    'invalid URL': {...valid, 'url': 'https://'},
    'insecure URL': {...valid, 'url': 'http://example.com/video'},
    'embedded credentials': {
      ...valid,
      'url': 'https://user:secret@example.com/video',
    },
    'missing expiry': {...valid}..remove('expires_in'),
    'string expiry': {...valid, 'expires_in': '900'},
    'zero expiry': {...valid, 'expires_in': 0},
    'excessive expiry': {...valid, 'expires_in': 604801},
  };
  for (final entry in invalid.entries) {
    test('rejects ${entry.key} without leaking the response', () async {
      final api = apiFor(
        (_) async => http.Response(jsonEncode(entry.value), 200),
      );
      await expectLater(
        api.getVideoUrl('saved-analysis'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            allOf(contains('응답'), isNot(contains('secret'))),
          ),
        ),
      );
    });
  }

  for (final entry in {
    404: '없습니다',
    409: '업로드 중',
    502: '연결하지 못',
    503: '설정 문제',
    500: '불러오지 못',
  }.entries) {
    test('HTTP ${entry.key} has safe specific guidance', () async {
      final api = apiFor(
        (_) async =>
            http.Response(jsonEncode({'detail': valid['url']}), entry.key),
      );
      await expectLater(
        api.getVideoUrl('saved-analysis'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            allOf(
              contains(entry.value),
              isNot(contains('secret')),
              isNot(contains('https')),
            ),
          ),
        ),
      );
    });
  }

  test('network failure is sanitized', () async {
    final api = apiFor((_) async => throw http.ClientException('token=secret'));
    await expectLater(
      api.getVideoUrl('saved-analysis'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          allOf(contains('네트워크'), isNot(contains('secret'))),
        ),
      ),
    );
  });
}
