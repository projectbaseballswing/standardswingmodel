import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api/auth_api.dart';
import '../data/session.dart';
import '../theme/app_theme.dart';
import '../widgets/app_widgets.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _idController = TextEditingController();
  final _passwordController = TextEditingController();
  final _authApi = AuthApi();

  // 비밀번호 불일치 등 로그인 오류 메시지. null 이면 표시 안 함.
  String? _errorMessage;
  bool _loading = false;

  @override
  void dispose() {
    _idController.dispose();
    _passwordController.dispose();
    _authApi.dispose();
    super.dispose();
  }

  Future<void> _onLoginPressed() async {
    final id = _idController.text.trim();
    final password = _passwordController.text;

    if (id.isEmpty || password.isEmpty) {
      setState(() => _errorMessage = '아이디와 비밀번호를 입력해주세요.');
      return;
    }

    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      final result = await _authApi.login(id: id, password: password);
      if (!mounted) return;
      // 로그인한 사용자를 세션에 저장(프로필·서버 호출에서 참조).
      Session.instance.signIn(result.userId);
      // 로그인 성공 → 스윙 목록 화면으로 이동 (뒤로가기로 로그인에 못 돌아오게 go 사용).
      context.go('/swings');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            children: [
              const Spacer(flex: 22),
              // 타이틀
              const Text(
                'SWING\nANALYSIS',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 34,
                  height: 1.15,
                  fontWeight: FontWeight.w400,
                  color: Colors.black,
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                '당신의 스윙을 분석하세요',
                style: TextStyle(fontSize: 14, color: AppColors.subtitle),
              ),
              const Spacer(flex: 8),
              // 입력창
              AppTextField(
                hint: '아이디',
                controller: _idController,
              ),
              const SizedBox(height: 12),
              AppTextField(
                hint: '비밀번호',
                controller: _passwordController,
                obscureText: true,
              ),
              if (_errorMessage != null) ...[
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    _errorMessage!,
                    style: const TextStyle(
                        color: AppColors.error, fontSize: 13),
                  ),
                ),
              ],
              const Spacer(flex: 30),
              // 하단 링크
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  HoverLink(
                    label: '회원가입',
                    onTap: () => context.push('/signup'),
                  ),
                  const Text('  |  ',
                      style: TextStyle(color: AppColors.link, fontSize: 13)),
                  HoverLink(
                    label: '비밀번호 찾기',
                    onTap: () {
                      // TODO(backend): 비밀번호 찾기 화면/기능 필요.
                    },
                  ),
                ],
              ),
              const SizedBox(height: 12),
              PrimaryButton(
                label: _loading ? '로그인 중...' : '로그인',
                onPressed: _loading ? null : _onLoginPressed,
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }
}
