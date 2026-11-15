import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../data/session.dart';
import 'api_config.dart';
import 'auth_api.dart';

/// Only an analysis ID is accepted; Storage paths never come from the app.
class OriginalVideoApi {
  OriginalVideoApi({http.Client? client}) : _client = client ?? http.Client();
  final http.Client _client;

  Future<void> delete(String analysisId) async {
    if (!Session.instance.isLoggedIn) {
      throw ApiException('로그인한 뒤 원본 영상을 삭제해주세요.');
    }
    http.Response response;
    try {
      response = await _client
          .delete(
            Uri.parse(
              '${ApiConfig.baseUrl}/api/analyses/${Uri.encodeComponent(analysisId)}/video',
            ),
            headers: {
              'Accept': 'application/json',
              ...Session.instance.authorizationHeaders,
            },
          )
          .timeout(const Duration(seconds: 35));
    } on TimeoutException {
      throw ApiException('삭제 결과를 확인하지 못했습니다. 목록을 확인하고 필요하면 다시 삭제를 요청해주세요.');
    } catch (_) {
      throw ApiException('서버에 연결할 수 없습니다. 목록을 확인한 뒤 다시 시도해주세요.');
    }
    if (response.statusCode != 200) {
      throw ApiException(switch (response.statusCode) {
        401 => '로그인이 만료되었습니다. 다시 로그인해주세요.',
        403 => '본인의 원본 영상만 삭제할 수 있습니다.',
        404 => '삭제할 원본 영상이나 분석 기록을 찾을 수 없습니다.',
        409 => '분석·3D 생성 중이거나 영상 상태를 확인할 수 없어 삭제할 수 없습니다. 잠시 후 다시 확인해주세요.',
        502 || 503 => '원본 영상 삭제를 완료하지 못했습니다. 다시 삭제를 요청해주세요. 분석 기록은 유지됩니다.',
        _ => '원본 영상 삭제에 실패했습니다. 목록을 확인하고 다시 시도해주세요.',
      });
    }
    try {
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map ||
          body['analysis_id'] != analysisId ||
          body['video_status'] != 'deleted') {
        throw const FormatException();
      }
    } catch (_) {
      throw ApiException('삭제 응답을 확인할 수 없습니다. 목록을 다시 확인해주세요.');
    }
  }

  void dispose() => _client.close();
}
