import 'dart:async';
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

/// 메모리에서만 사용하는 영상 접근 URL. 사용자 소유권 인증을 의미하지 않는다.
class AnalysisVideoUrl {
  const AnalysisVideoUrl({required this.url, required this.expiresIn});

  final Uri url;
  final int expiresIn;
}

/// 스윙 업로드, 분석 결과 및 저장된 원본 영상 URL 조회 API.
class AnalysisApi {
  AnalysisApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Uri _uri(String path) => Uri.parse('${ApiConfig.baseUrl}$path');

  /// 녹화한 스윙 영상을 업로드해 분석 작업을 등록한다.
  ///
  /// [videoPath] 로컬 영상 파일 경로, [isLeft] 좌타 여부.
  /// [userId] 로그인한 계정 ID, [recordedAt] 등록 시각(현재는 업로드 시각).
  Future<AnalysisCreated> uploadSwingVideo({
    required String videoPath,
    required bool isLeft,
    required String userId,
    required DateTime recordedAt,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/api/analyses'))
      ..fields['handedness'] = isLeft ? 'left' : 'right'
      ..fields['user_id'] = userId
      ..fields['recorded_at'] = recordedAt.toUtc().toIso8601String()
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

  /// 분석 결과 1건을 조회한다.
  ///
  /// [GET] /api/analyses/{id}
  ///   → {analysis_id, status, stage, created_at, finished_at, input, error, result}
  /// status 는 queued / running / done / failed. result 는 done 일 때만 채워진다.
  ///
  /// [includeSeries] 가 true 면 관절 각도 80프레임 시계열(그래프용)도 함께 받는다.
  Future<Map<String, dynamic>> getAnalysis(
    String analysisId, {
    bool includeSeries = false,
  }) async {
    final query = includeSeries ? '?include_series=true' : '';
    final res = await _get(_uri('/api/analyses/$analysisId$query'));
    return _decode(res);
  }

  /// 저장된 원본 영상의 임시 URL. 오류에 서버 본문이나 토큰을 노출하지 않는다.
  Future<AnalysisVideoUrl> getVideoUrl(String analysisId) async {
    http.Response res;
    try {
      res = await _get(
        _uri('/api/analyses/${Uri.encodeComponent(analysisId)}/video'),
      ).timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw ApiException('영상 요청 시간이 초과됐습니다. 네트워크를 확인하고 다시 시도해주세요.');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(switch (res.statusCode) {
        404 => '저장된 영상이 없습니다.',
        409 => '영상 업로드 중입니다. 잠시 후 다시 시도해주세요.',
        502 => '영상 저장소에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.',
        503 => '영상 저장소 설정 문제로 재생할 수 없습니다.',
        _ => '영상 정보를 불러오지 못했습니다. 다시 시도해주세요.',
      });
    }
    try {
      final body = jsonDecode(utf8.decode(res.bodyBytes));
      if (body is! Map<String, dynamic> ||
          body['analysis_id'] != analysisId ||
          body['url'] is! String ||
          body['expires_in'] is! int) {
        throw const FormatException();
      }
      final url = Uri.tryParse(body['url'] as String);
      final expiresIn = body['expires_in'] as int;
      if (url == null ||
          url.scheme != 'https' ||
          url.host.isEmpty ||
          url.userInfo.isNotEmpty ||
          url.hasFragment ||
          expiresIn < 1 ||
          expiresIn > 604800) {
        throw const FormatException();
      }
      return AnalysisVideoUrl(url: url, expiresIn: expiresIn);
    } catch (_) {
      throw ApiException('영상 URL 응답이 올바르지 않습니다. 다시 시도해주세요.');
    }
  }

  /// 분석이 끝날 때까지(또는 실패/시간초과까지) 주기적으로 조회한다.
  ///
  /// 분석에는 수 초~십수 초가 걸리므로, status 가 done 이 될 때까지
  /// [interval] 간격으로 다시 조회한다. [timeout] 을 넘기면 예외를 던진다.
  Future<Map<String, dynamic>> waitForReport(
    String analysisId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 2),
    bool includeSeries = false,
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (true) {
      final body = await getAnalysis(analysisId, includeSeries: includeSeries);
      final status = body['status'] as String?;
      if (status == 'done') {
        if (body['result'] == null) {
          throw ApiException('저장된 분석 결과가 없습니다.');
        }
        return body;
      }
      if (status == 'failed') {
        final err = body['error'];
        final message = err is Map ? err['message'] : err;
        throw ApiException(
          message is String ? '분석에 실패했습니다. $message' : '분석에 실패했어요.',
        );
      }
      if (DateTime.now().isAfter(deadline)) {
        throw ApiException('분석이 예상보다 오래 걸려요. 잠시 후 다시 시도해주세요.');
      }
      await Future<void>.delayed(interval);
    }
  }

  Future<http.Response> _get(Uri uri) async {
    try {
      return await _client.get(uri, headers: {'Accept': 'application/json'});
    } catch (_) {
      throw ApiException('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.');
    }
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
      detail is String ? detail : '영상을 업로드하지 못했습니다. (${res.statusCode})',
    );
  }

  void dispose() => _client.close();
}
