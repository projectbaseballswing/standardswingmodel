import 'dart:typed_data';

/// 로그인한 사용자 정보를 앱 실행 동안 보관하는 간단한 세션 저장소.
///
/// 로그인 성공 시 [signIn] 으로 아이디를 채우고, 로그아웃 시 [clear] 로 비운다.
/// 프로필 화면 등에서 현재 사용자를 참조하거나, 서버 호출 시 아이디를 넘길 때 쓴다.
///
/// 백엔드가 할 일은 없다(로그인 응답이 이미 아이디를 준다). 세션 저장은 순수 프론트.
///
/// TODO(frontend): 앱을 껐다 켜도 로그인/프로필 사진이 유지되게 하려면
/// shared_preferences 같은 영구 저장소로 바꾼다. 지금은 인메모리라 앱 재시작 시 초기화된다.
class Session {
  Session._();
  static final Session instance = Session._();

  /// 로그인한 사용자의 아이디. 로그인 전/로그아웃 후에는 null.
  String? userId;

  /// 프로필 사진(갤러리에서 고른 이미지의 바이트). 설정 전에는 null.
  ///
  /// TODO(backend): 서버에 프로필 사진 업로드/조회 API 가 생기면, 이 값을 올리고
  /// 로그인/프로필 조회 시 내려받은 URL 로 바꾼다. 지금은 앱 실행 동안만 유지된다.
  Uint8List? profileImage;

  bool get isLoggedIn => userId != null;

  void signIn(String userId) {
    this.userId = userId;
  }

  void clear() {
    userId = null;
    profileImage = null;
  }
}
