import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../data/session.dart';
import '../features/swing_3d/domain/pose.dart';
import 'api_config.dart';

class Pose3dException implements Exception {
  const Pose3dException(this.code, this.message);
  final String code, message;
  @override
  String toString() => message;
}

class Pose3dResponse {
  const Pose3dResponse({
    required this.status,
    this.clip,
    this.warnings = const [],
  });
  final String status;
  final SwingClip? clip;
  final List<String> warnings;
  bool get pending => status == 'pending' || status == 'processing';
}

/// Authenticated analysis data only. Never resolves a bundled player asset.
class Pose3dApi {
  Pose3dApi({http.Client? client}) : _client = client ?? http.Client();
  final http.Client _client;

  Future<Pose3dResponse> fetch(String analysisId) async {
    final token = Session.instance.accessToken;
    final owner = Session.instance.userId;
    if (token == null || owner == null) {
      throw const Pose3dException(
        'unauthenticated',
        '로그인 세션이 없습니다. 다시 로그인해주세요.',
      );
    }
    if (analysisId.trim().isEmpty) {
      throw const Pose3dException(
        'invalid_analysis',
        '분석 ID가 없습니다. 분석 기록에서 다시 열어주세요.',
      );
    }
    late http.Response response;
    try {
      response = await _client
          .get(
            Uri.parse(
              '${ApiConfig.baseUrl}/api/analyses/${Uri.encodeComponent(analysisId)}/pose-3d',
            ),
            headers: {
              'Accept': 'application/json',
              'Authorization': 'Bearer $token',
            },
          )
          .timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw const Pose3dException(
        'timeout',
        '3D 데이터 요청 시간이 초과됐습니다. 다시 시도해주세요.',
      );
    } catch (_) {
      throw const Pose3dException('network', '3D 데이터 서버에 연결할 수 없습니다.');
    }
    if (Session.instance.userId != owner ||
        Session.instance.accessToken != token) {
      throw const Pose3dException(
        'session_changed',
        '로그인 계정이 변경됐습니다. 현재 계정의 분석을 다시 열어주세요.',
      );
    }
    const errors = {
      401: ('unauthenticated', '인증이 만료되었거나 유효하지 않습니다. 다시 로그인해주세요.'),
      403: ('forbidden', '다른 사용자의 3D 분석에는 접근할 수 없습니다.'),
      404: ('not_found', '해당 분석 또는 3D 데이터가 없습니다.'),
      422: ('failed', '이 영상의 3D 데이터를 생성하지 못했습니다. 기존 점수와 피드백은 별도로 확인할 수 있습니다.'),
      503: ('unavailable', '3D 저장소 또는 인증 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.'),
    };
    if (errors.containsKey(response.statusCode)) {
      final error = errors[response.statusCode]!;
      throw Pose3dException(error.$1, error.$2);
    }
    if (response.statusCode != 200 && response.statusCode != 202) {
      throw const Pose3dException('server', '3D 데이터를 불러오지 못했습니다.');
    }
    if (response.bodyBytes.length > 32 * 1024 * 1024) {
      throw const Pose3dException(
        'invalid_response',
        '3D 데이터가 표시 가능한 크기를 초과했습니다.',
      );
    }
    try {
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map<String, dynamic> ||
          body['analysis_id'] != analysisId ||
          body['user_id'] != owner ||
          body['contract_version'] != 'EXP008-pose3d-v1') {
        throw const FormatException('Analysis identity or contract mismatch');
      }
      final status = body['status'];
      final warnings = body['warnings'] == null
          ? <String>[]
          : (body['warnings'] as List).cast<String>();
      if (response.statusCode == 202 &&
          (status == 'pending' || status == 'processing') &&
          body['clip'] == null) {
        return Pose3dResponse(status: status, warnings: warnings);
      }
      if (response.statusCode != 200 || status != 'ready') {
        throw const FormatException('Unexpected status');
      }
      final raw = body['clip'];
      if (raw is! Map<String, dynamic> ||
          raw['data_kind'] != 'analysis' ||
          raw['analysis_id'] != analysisId ||
          raw['id'] != analysisId) {
        throw const FormatException(
          'Actual analysis must not contain a sample',
        );
      }
      final clip = SwingClip.fromJson(raw);
      if (clip.finalMotion == null ||
          clip.frameCount != body['frame_count'] ||
          clip.handedness != body['handedness']) {
        throw const FormatException('Incomplete final display');
      }
      return Pose3dResponse(status: status, clip: clip, warnings: warnings);
    } catch (_) {
      throw const Pose3dException(
        'invalid_response',
        '분석 ID 또는 3D 데이터 형식이 일치하지 않습니다. 샘플 영상으로 대체하지 않습니다.',
      );
    }
  }

  void dispose() => _client.close();
}
