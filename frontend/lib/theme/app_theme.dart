import 'package:flutter/material.dart';

/// 앱 전체에서 쓰는 색상과 테마.
class AppColors {
  static const Color primary = Color(0xFFFF4A4A); // 피그마 Red-400
  static const Color fieldFill = Color(0xFFFAFAFA); // 입력창 배경 (Gray-100)
  static const Color hint = Color(0xFF989898); // placeholder 글자색 (Gray-400)
  static const Color subtitle = Color(0xFF444444); // 부제 글자색
  static const Color link = Color(0xFF989898); // 하단 링크 글자색 (Gray-400)
  static const Color error = Color(0xFFFF4A4A); // 오류 메시지 (Red-400)
  static const Color success = Color(0xFF989898); // "사용할 수 있는 이메일입니다." 안내
  static const Color gray600 = Color(0xFF474747); // 달력 요일/날짜 글자색 (Gray-600)
  static const Color line = Color(0xFFD7D7D7); // 달력 구분선
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
