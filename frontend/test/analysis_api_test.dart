import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:swing_analysis/api/analysis_api.dart';

class _CapturingClient extends http.BaseClient {
  http.MultipartRequest? upload;
  List<int>? payload;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is! http.MultipartRequest) {
      throw StateError('Expected a multipart request');
    }
    upload = request;
    payload = await request.finalize().toBytes();
    return http.StreamedResponse(
      Stream.value(utf8.encode('{"analysis_id":"test123","status":"queued"}')),
      202,
      headers: {'content-type': 'application/json'},
    );
  }
}

void main() {
  for (final isLeft in [false, true]) {
    test('영상 업로드 시 사용자와 UTC 시각, ${isLeft ? '좌타' : '우타'} 정보를 보낸다', () async {
      final dir = await Directory.systemTemp.createTemp('swing_upload_test_');
      addTearDown(() async {
        await dir.delete(recursive: true);
      });
      final video = File('${dir.path}/test.mp4');
      final videoBytes = [0, 0, 0, 24, 102, 116, 121, 112];
      await video.writeAsBytes(videoBytes);

      final client = _CapturingClient();
      final api = AnalysisApi(client: client);
      addTearDown(api.dispose);
      // 화면이 전달하는 로컬 DateTime도 명시적인 UTC 시간대로 변환되어야 한다.
      final date = DateTime.utc(2026, 10, 10, 5, 30).toLocal();

      final result = await api.uploadSwingVideo(
        videoPath: video.path,
        isLeft: isLeft,
        userId: 'testuser01',
        recordedAt: date,
      );

      expect(result.analysisId, 'test123');
      expect(result.status, 'queued');
      final request = client.upload!;
      expect(request.method, 'POST');
      expect(request.url.path, '/api/analyses');
      expect(request.files.single.field, 'video');
      expect(request.files.single.filename, 'test.mp4');
      expect(request.files.single.length, videoBytes.length);
      expect(request.fields, {
        'handedness': isLeft ? 'left' : 'right',
        'user_id': 'testuser01',
        'recorded_at': '2026-10-10T05:30:00.000Z',
      });

      // 직렬화된 요청에도 파일 내용과 세 필드가 실제로 포함되는지 확인한다.
      final body = latin1.decode(client.payload!);
      expect(
        request.headers['content-type'],
        startsWith('multipart/form-data;'),
      );
      expect(body, contains('name="video"; filename="test.mp4"'));
      expect(body, contains(latin1.decode(videoBytes)));
      for (final field in request.fields.entries) {
        expect(body, contains('name="${field.key}"\r\n\r\n${field.value}\r\n'));
      }
    });
  }
}
