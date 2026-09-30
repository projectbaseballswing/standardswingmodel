import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_config.dart';

/// 서버 호출 중 발생한 오류. UI 에서 message 를 그대로 보여주면 된다.
class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// 로그인 성공 시 서버가 돌려주는 정보.
class LoginResult {
  const LoginResult({required this.userId});
  final String userId;
}

/// 회원가입 결과. registered 가 false 면 어느 항목이 중복인지 알 수 있다.
class RegisterResult {
  const RegisterResult({
    required this.registered,
    required this.idAvailable,
    required this.nicknameAvailable,
  });

  final bool registered;
  final bool idAvailable; // false = 아이디 중복
  final bool nicknameAvailable; // false = 닉네임 중복
}

/// 회원/로그인 관련 API 모음.
class AuthApi {
  AuthApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Uri _uri(String path, [Map<String, dynamic>? query]) =>
      Uri.parse('${ApiConfig.baseUrl}$path').replace(
        queryParameters: query?.map((k, v) => MapEntry(k, '$v')),
      );

  /// 이메일 중복확인. true = 사용 가능, false = 중복.
  ///
  /// [GET] /api/check-email?email=...  → {"email-uniqueness": 1|0}
  Future<bool> checkEmail(String email) async {
    final res = await _get(_uri('/api/check-email', {'email': email}));
    final body = _decode(res);
    return body['email-uniqueness'] == 1;
  }

  /// 회원가입.
  ///
  /// [POST] /api/register  {id, password, e-mail, nickname}
  ///   → {id-uniqueness, nickname-uniqueness, registered}
  Future<RegisterResult> register({
    required String id,
    required String password,
    required String email,
    required String nickname,
  }) async {
    final res = await _post('/api/register', {
      'id': id,
      'password': password,
      'e-mail': email,
      'nickname': nickname,
    });
    final body = _decode(res);
    return RegisterResult(
      registered: body['registered'] == true,
      idAvailable: body['id-uniqueness'] == 1,
      nicknameAvailable: body['nickname-uniqueness'] == 1,
    );
  }

  /// 로그인.
  ///
  /// [POST] /api/login  {e-mail, password}  → {success, user}
  /// 실패 시 서버가 401 을 주며, ApiException 으로 변환한다.
  Future<LoginResult> login({
    required String email,
    required String password,
  }) async {
    final res = await _post('/api/login', {
      'e-mail': email,
      'password': password,
    });
    final body = _decode(res);
    return LoginResult(userId: body['user'] as String);
  }

  Future<http.Response> _get(Uri uri) async {
    try {
      return await _client.get(uri, headers: {'Accept': 'application/json'});
    } catch (_) {
      throw ApiException('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.');
    }
  }

  Future<http.Response> _post(String path, Map<String, dynamic> body) async {
    try {
      return await _client.post(
        _uri(path),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
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
    // FastAPI 는 오류를 {"detail": "..."} 로 준다.
    final detail = body['detail'];
    throw ApiException(detail is String ? detail : '요청을 처리하지 못했습니다. (${res.statusCode})');
  }

  void dispose() => _client.close();
}
