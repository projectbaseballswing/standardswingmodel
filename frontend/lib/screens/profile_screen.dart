import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../api/auth_api.dart';
import '../data/session.dart';
import '../theme/app_theme.dart';

/// 프로필 화면.
///
/// 스윙 목록의 우측 상단 아바타, 또는 하단 "프로필" 탭을 누르면 들어온다.
/// 세션에 저장된 아이디로 /api/me 를 호출해 이메일(과 추후 닉네임)을 보여준다.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _authApi = AuthApi();
  final _picker = ImagePicker();

  MyInfo? _info;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _authApi.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final userId = Session.instance.userId;
    // 세션이 없으면(직접 진입 등) 조회할 수 없다.
    if (userId == null) {
      setState(() => _loading = false);
      return;
    }
    try {
      final info = await _authApi.fetchMyInfo(userId);
      if (!mounted) return;
      setState(() {
        _info = info;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('프로필')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.symmetric(vertical: 24),
                children: [
                  _profileHeader(),
                  const SizedBox(height: 24),
                  const Divider(height: 1),
                  _menuItem(
                    icon: Icons.person_outline,
                    label: '계정 정보',
                    onTap: () {
                      // TODO(next): 계정 정보 상세/수정 화면.
                    },
                  ),
                  _menuItem(
                    icon: Icons.bar_chart_outlined,
                    label: '스윙 통계',
                    onTap: () {
                      // TODO(next): 스윙 통계 화면.
                    },
                  ),
                  _menuItem(
                    icon: Icons.settings_outlined,
                    label: '설정',
                    onTap: () {
                      // TODO(next): 설정 화면.
                    },
                  ),
                  const Divider(height: 1),
                  _menuItem(
                    icon: Icons.logout,
                    label: '로그아웃',
                    color: AppColors.error,
                    onTap: _logout,
                  ),
                ],
              ),
      ),
    );
  }

  // 아바타 + 닉네임(없으면 아이디) + 이메일.
  Widget _profileHeader() {
    final userId = _info?.id ?? Session.instance.userId;
    // 닉네임은 백엔드가 /api/me 에 추가하면 표시된다. 지금은 아이디로 대체.
    final displayName = _info?.nickname ?? userId ?? '사용자';
    final email = _info?.email ?? (_error ?? '정보를 불러오지 못했습니다.');

    return Column(
      children: [
        _avatar(),
        const SizedBox(height: 12),
        Text(
          displayName,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        Text(
          email,
          style: const TextStyle(fontSize: 14, color: AppColors.hint),
        ),
      ],
    );
  }

  // 프로필 사진. 탭하면 갤러리에서 사진을 골라 설정한다.
  // 우측 하단에 카메라 배지를 올려 "바꿀 수 있다"는 걸 표시.
  Widget _avatar() {
    final image = Session.instance.profileImage;
    return GestureDetector(
      onTap: _pickProfileImage,
      child: Stack(
        children: [
          CircleAvatar(
            radius: 44,
            backgroundColor: AppColors.fieldFill,
            backgroundImage: image != null ? MemoryImage(image) : null,
            child: image == null
                ? const Icon(Icons.person, size: 44, color: AppColors.hint)
                : null,
          ),
          Positioned(
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppColors.primary,
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 2),
              ),
              child: const Icon(Icons.photo_camera,
                  size: 16, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }

  // 갤러리에서 사진을 골라 프로필 사진으로 설정한다(앱 실행 동안 유지).
  Future<void> _pickProfileImage() async {
    final picked = await _picker.pickImage(source: ImageSource.gallery);
    if (picked == null) return; // 사용자가 취소.
    final bytes = await picked.readAsBytes();
    if (!mounted) return;
    setState(() => Session.instance.profileImage = bytes);
    // TODO(backend): 프로필 사진 업로드 API 가 생기면 여기서 서버에도 올린다.
  }

  Widget _menuItem({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
    Color? color,
  }) {
    return ListTile(
      leading: Icon(icon, color: color ?? Colors.black87),
      title: Text(
        label,
        style: TextStyle(fontSize: 15, color: color ?? Colors.black87),
      ),
      trailing: color == null
          ? const Icon(Icons.chevron_right, color: AppColors.hint)
          : null,
      onTap: onTap,
    );
  }

  // 로그아웃 → 세션 비우고 로그인 화면으로. 뒤로가기로 못 돌아오게 go 사용.
  void _logout() {
    Session.instance.clear();
    context.go('/login');
  }
}
