import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_config.dart';
import 'auth_api.dart' show ApiException;

/// 스윙 영상 업로드 결과. 등록된 분석 작업의 id 와 상태.
class AnalysisCreated {
  const AnalysisCreated({required this.analysisId, required this.status});
  final String analysisId;
  final String status; // queued / running 등
}

/// 스윙 영상 분석 관련 API.
///
/// 백엔드는 이미 아래 엔드포인트를 제공한다(백엔드 수정 불필요):
///   POST /api/analyses        (multipart: video, handedness) → {analysis_id, status}
///   GET  /api/analyses/{id}   → 분석 결과(피드백)
class AnalysisApi {
  AnalysisApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Uri _uri(String path) => Uri.parse('${ApiConfig.baseUrl}$path');

  /// 녹화한 스윙 영상을 업로드해 분석 작업을 등록한다.
  ///
  /// [videoPath] 로컬 영상 파일 경로, [isLeft] 좌타 여부.
  Future<AnalysisCreated> uploadSwingVideo({
    required String videoPath,
    required bool isLeft,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/api/analyses'))
      ..fields['handedness'] = isLeft ? 'left' : 'right'
      ..files.add(await http.MultipartFile.fromPath('video', videoPath));

    http.Response res;
    try {
      final streamed = await _client.send(request);
      res = await http.Response.fromStream(streamed);
    } catch (_) {
      throw ApiException('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.');
    }

    final body = _decode(res);
    return AnalysisCreated(
      analysisId: body['analysis_id'] as String,
      status: (body['status'] as String?) ?? 'queued',
    );
  }

  /// 정상(2xx) 응답이면 JSON 을 반환하고, 아니면 서버 메시지로 예외를 던진다.
  Map<String, dynamic> _decode(http.Response res) {
    Map<String, dynamic> body;
    try {
      body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      body = {};
    }
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return body;
    }
    final detail = body['detail'];
    throw ApiException(
        detail is String ? detail : '영상을 업로드하지 못했습니다. (${res.statusCode})');
  }

  void dispose() => _client.close();
}
