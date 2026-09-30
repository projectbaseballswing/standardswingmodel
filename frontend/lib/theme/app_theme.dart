import 'package:flutter/material.dart';

/// 앱 전체에서 쓰는 색상과 테마.
class AppColors {
  static const Color primary = Color(0xFFEA5C5C); // 로그인/회원가입 버튼의 빨강
  static const Color fieldFill = Color(0xFFF4F4F4); // 입력창 배경 (연한 회색)
  static const Color hint = Color(0xFF9E9E9E); // placeholder 글자색
  static const Color subtitle = Color(0xFF444444); // 부제 글자색
  static const Color link = Color(0xFF9E9E9E); // 하단 링크 글자색
  static const Color error = Color(0xFFEA5C5C); // 오류 메시지
  static const Color success = Color(0xFF9E9E9E); // "사용할 수 있는 이메일입니다." 안내
}

ThemeData buildAppTheme() {
  return ThemeData(
    useMaterial3: true,
    scaffoldBackgroundColor: Colors.white,
    fontFamily: 'Roboto',
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.white,
      elevation: 0,
      centerTitle: true,
      foregroundColor: Colors.black,
      titleTextStyle: TextStyle(
        color: Colors.black,
        fontSize: 18,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}
