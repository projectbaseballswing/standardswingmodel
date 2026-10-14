import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_config.dart';
import 'auth_api.dart' show ApiException;

/// 사용자별 스윙 목록. userId는 조회 필터이며 인증 토큰이 아니다.
class SwingApi {
  SwingApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Future<List<Map<String, dynamic>>> fetchSwings({
    required String userId,
    required int year,
    required int month,
    required int tzOffsetMinutes,
  }) async {
    final uri =
        Uri.parse(
          '${ApiConfig.baseUrl}/api/users/${Uri.encodeComponent(userId)}/swings',
        ).replace(
          queryParameters: {
            'year': '$year',
            'month': '$month',
            'tz_offset_minutes': '$tzOffsetMinutes',
          },
        );

    http.Response response;
    try {
      response = await _client
          .get(uri, headers: {'Accept': 'application/json'})
          .timeout(const Duration(seconds: 15));
    } catch (_) {
      throw ApiException('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.');
    }

    Map<String, dynamic> body;
    try {
      body =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      throw ApiException('스윙 목록 응답을 읽을 수 없습니다. 잠시 후 다시 시도해주세요.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = body['detail'];
      throw ApiException(
        detail is String
            ? detail
            : '스윙 목록을 불러오지 못했습니다. (${response.statusCode})',
      );
    }
    try {
      return (body['items'] as List)
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
    } catch (_) {
      throw ApiException('스윙 목록 응답 형식이 올바르지 않습니다.');
    }
  }

  void dispose() => _client.close();
}
