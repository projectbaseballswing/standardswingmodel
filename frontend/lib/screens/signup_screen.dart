import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api/auth_api.dart';
import '../theme/app_theme.dart';
import '../widgets/app_widgets.dart';

class SignupScreen extends StatefulWidget {
  const SignupScreen({super.key});

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

/// 이메일 중복확인 결과 상태.
enum _EmailStatus { none, available, duplicated }

class _SignupScreenState extends State<SignupScreen> {
  final _idController = TextEditingController();
  final _nicknameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _passwordConfirmController = TextEditingController();
  final _authApi = AuthApi();

  _EmailStatus _emailStatus = _EmailStatus.none;
  bool _passwordMismatch = false;
  bool _checkingEmail = false;
  bool _submitting = false;

  // 가입 실패/오류 안내. null 이면 표시 안 함.
  String? _errorMessage;

  @override
  void dispose() {
    _idController.dispose();
    _nicknameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _passwordConfirmController.dispose();
    _authApi.dispose();
    super.dispose();
  }

  Future<void> _onCheckEmail() async {
    final email = _emailController.text.trim();
    if (email.isEmpty) {
      setState(() => _emailStatus = _EmailStatus.none);
      return;
    }

    setState(() {
      _checkingEmail = true;
      _errorMessage = null;
    });

    try {
      // GET /api/check-email?email=... → email-uniqueness 1(사용가능)/0(중복)
      final available = await _authApi.checkEmail(email);
      if (!mounted) return;
      setState(() {
        _emailStatus =
            available ? _EmailStatus.available : _EmailStatus.duplicated;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    } finally {
      if (mounted) setState(() => _checkingEmail = false);
    }
  }

  Future<void> _onSignupPressed() async {
    final id = _idController.text.trim();
    final nickname = _nicknameController.text.trim();
    final email = _emailController.text.trim();
    final password = _passwordController.text;
    final passwordConfirm = _passwordConfirmController.text;

    final mismatch = password != passwordConfirm;
    setState(() {
      _passwordMismatch = mismatch;
      _errorMessage = null;
    });
    if (mismatch) return;

    if (id.isEmpty ||
        nickname.isEmpty ||
        email.isEmpty ||
        password.isEmpty) {
      setState(() => _errorMessage = '모든 항목을 입력해주세요.');
      return;
    }

    setState(() => _submitting = true);
    try {
      // POST /api/register {id, password, e-mail, nickname}
      final result = await _authApi.register(
        id: id,
        password: password,
        email: email,
        nickname: nickname,
      );
      if (!mounted) return;

      if (result.registered) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('회원가입이 완료되었습니다. 로그인해주세요.')),
        );
        context.pop(); // 로그인 화면으로 복귀
        return;
      }

      // 등록 실패 — 어느 항목이 중복인지 안내한다.
      final reasons = <String>[
        if (!result.idAvailable) '아이디',
        if (!result.nicknameAvailable) '닉네임',
      ];
      setState(() {
        _errorMessage = reasons.isEmpty
            ? '회원가입에 실패했습니다. 입력값을 확인해주세요.'
            : '${reasons.join('과(와) ')}이(가) 이미 사용 중입니다.';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Widget? _emailStatusMessage() {
    switch (_emailStatus) {
      case _EmailStatus.available:
        return const Text('사용할 수 있는 이메일입니다.',
            style: TextStyle(color: AppColors.success, fontSize: 13));
      case _EmailStatus.duplicated:
        return const Text('중복된 이메일입니다.',
            style: TextStyle(color: AppColors.error, fontSize: 13));
      case _EmailStatus.none:
        return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final emailMessage = _emailStatusMessage();

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
          onPressed: () => context.pop(),
        ),
        title: const Text('회원가입'),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              // 아이디
              _label('아이디'),
              const SizedBox(height: 8),
              AppTextField(hint: '아이디 입력', controller: _idController),
              const SizedBox(height: 24),
              // 닉네임
              _label('닉네임'),
              const SizedBox(height: 8),
              AppTextField(hint: '닉네임 입력', controller: _nicknameController),
              const SizedBox(height: 24),
              // 이메일
              _label('이메일'),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: AppTextField(
                      hint: '이메일 입력',
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 52,
                    child: ElevatedButton(
                      onPressed: _checkingEmail ? null : _onCheckEmail,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                      child: Text(_checkingEmail ? '확인 중' : '중복확인',
                          style: const TextStyle(
                              fontSize: 14, fontWeight: FontWeight.w600)),
                    ),
                  ),
                ],
              ),
              if (emailMessage != null) ...[
                const SizedBox(height: 6),
                emailMessage,
              ],
              const SizedBox(height: 24),
              // 비밀번호
              _label('비밀번호'),
              const SizedBox(height: 8),
              AppTextField(
                hint: '비밀번호 입력',
                controller: _passwordController,
                obscureText: true,
              ),
              const SizedBox(height: 12),
              AppTextField(
                hint: '비밀번호 재입력',
                controller: _passwordConfirmController,
                obscureText: true,
              ),
              if (_passwordMismatch) ...[
                const SizedBox(height: 6),
                const Text('비밀번호가 일치하지 않습니다.',
                    style: TextStyle(color: AppColors.error, fontSize: 13)),
              ],
              if (_errorMessage != null) ...[
                const SizedBox(height: 6),
                Text(_errorMessage!,
                    style:
                        const TextStyle(color: AppColors.error, fontSize: 13)),
              ],
              const SizedBox(height: 40),
              PrimaryButton(
                label: _submitting ? '가입 중...' : '회원가입',
                onPressed: _submitting ? null : _onSignupPressed,
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }

  Widget _label(String text) => Text(text,
      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600));
}
