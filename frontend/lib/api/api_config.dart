import 'package:flutter/foundation.dart';

/// API 서버 주소 설정.
///
/// 실행 대상마다 서버(127.0.0.1)를 가리키는 방법이 다르다.
/// - 웹(chrome), iOS 시뮬레이터, 데스크톱: `127.0.0.1`
/// - 안드로이드 에뮬레이터: 호스트 PC 를 `10.0.2.2` 로 봐야 한다.
///
/// 필요하면 실행 시 `--dart-define=API_BASE_URL=http://...` 로 덮어쓸 수 있다.
class ApiConfig {
  static const String _override =
      String.fromEnvironment('API_BASE_URL', defaultValue: '');

  static String get baseUrl {
    if (_override.isNotEmpty) return _override;
    // 안드로이드 에뮬레이터에서는 127.0.0.1 이 에뮬레이터 자신을 가리키므로 10.0.2.2 사용.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }
}
