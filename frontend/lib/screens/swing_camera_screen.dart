import 'dart:io';
import 'dart:math' show pi;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:video_player/video_player.dart';

import '../api/analysis_api.dart';
import '../api/auth_api.dart' show ApiException;
import '../theme/app_theme.dart';

/// 스윙 영상 촬영 화면.
///
/// 카메라 프리뷰를 세로로 꽉 채우고, 하단의 흰 원형 버튼으로 녹화를 시작/중지한다.
/// 녹화가 끝나면 미리보기 화면([_ReviewScreen])으로 넘어가 확인 후 업로드한다.
/// 왼쪽 아래 썸네일을 누르면 갤러리에서 기존 영상을 불러온다.
class SwingCameraScreen extends StatefulWidget {
  const SwingCameraScreen({super.key});

  @override
  State<SwingCameraScreen> createState() => _SwingCameraScreenState();
}

class _SwingCameraScreenState extends State<SwingCameraScreen>
    with WidgetsBindingObserver {
  CameraController? _controller;
  List<CameraDescription> _cameras = [];
  bool _initializing = true;
  bool _recording = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _setupCamera();
    // 화면에 들어오면 촬영 가이드를 한 번 보여준다.
    WidgetsBinding.instance.addPostFrameCallback((_) => _showGuide());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  // 앱이 백그라운드로 가면 카메라를 해제하고, 돌아오면 다시 초기화한다.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;
    if (state == AppLifecycleState.inactive) {
      controller.dispose();
    } else if (state == AppLifecycleState.resumed) {
      _setupCamera();
    }
  }

  Future<void> _setupCamera() async {
    try {
      _cameras = await availableCameras();
      if (_cameras.isEmpty) {
        setState(() {
          _error = '사용할 수 있는 카메라가 없습니다.';
          _initializing = false;
        });
        return;
      }
      // 후면 카메라 우선.
      final back = _cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => _cameras.first,
      );
      final controller = CameraController(
        back,
        ResolutionPreset.high,
        enableAudio: true,
      );
      await controller.initialize();
      if (!mounted) {
        controller.dispose();
        return;
      }
      setState(() {
        _controller = controller;
        _initializing = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '카메라를 열 수 없습니다. 권한을 확인해주세요.';
        _initializing = false;
      });
    }
  }

  Future<void> _toggleRecording() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;

    if (!_recording) {
      try {
        await controller.startVideoRecording();
        setState(() => _recording = true);
      } catch (_) {
        _showSnack('녹화를 시작할 수 없습니다.');
      }
    } else {
      try {
        final file = await controller.stopVideoRecording();
        setState(() => _recording = false);
        await _openReview(file.path);
      } catch (_) {
        setState(() => _recording = false);
        _showSnack('녹화를 저장할 수 없습니다.');
      }
    }
  }

  Future<void> _pickFromGallery() async {
    final picker = ImagePicker();
    final picked = await picker.pickVideo(source: ImageSource.gallery);
    if (picked != null) {
      await _openReview(picked.path);
    }
  }

  Future<void> _openReview(String videoPath) async {
    if (!mounted) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => _ReviewScreen(videoPath: videoPath)),
    );
  }

  void _showSnack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  // 촬영 가이드(측면 촬영 / 전신 촬영)를 단계별로 보여준다.
  Future<void> _showGuide() async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const CameraGuideDialog(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(),
            Expanded(child: _preview()),
            _bottomBar(),
          ],
        ),
      ),
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 12, 8),
      child: Row(
        children: [
          const Text('영상 촬영',
              style: TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.w600)),
          const Spacer(),
          // 촬영 가이드 다시 보기.
          IconButton(
            icon: const Icon(Icons.help_outline, color: Colors.white),
            onPressed: _showGuide,
          ),
        ],
      ),
    );
  }

  Widget _preview() {
    if (_initializing) {
      return const Center(child: CircularProgressIndicator(color: Colors.white));
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70)),
        ),
      );
    }
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      return const SizedBox.shrink();
    }
    return Stack(
      alignment: Alignment.center,
      children: [
        // 프리뷰를 세로 영역에 꽉 채운다(가운데 기준 크롭).
        ClipRect(
          child: OverflowBox(
            alignment: Alignment.center,
            child: FittedBox(
              fit: BoxFit.cover,
              child: SizedBox(
                width: controller.value.previewSize?.height ?? 1,
                height: controller.value.previewSize?.width ?? 1,
                child: CameraPreview(controller),
              ),
            ),
          ),
        ),
        if (_recording)
          Positioned(
            top: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.black54,
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.fiber_manual_record,
                      color: AppColors.primary, size: 12),
                  SizedBox(width: 6),
                  Text('녹화 중',
                      style: TextStyle(color: Colors.white, fontSize: 12)),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Widget _bottomBar() {
    return Container(
      color: Colors.black,
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          // 왼쪽: 갤러리에서 불러오기 썸네일.
          GestureDetector(
            onTap: _recording ? null : _pickFromGallery,
            child: Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: Colors.white12,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: Colors.white24),
              ),
              child: const Icon(Icons.photo_library_outlined,
                  color: Colors.white70, size: 20),
            ),
          ),
          // 가운데: 녹화 버튼.
          GestureDetector(
            onTap: _toggleRecording,
            child: Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 4),
              ),
              child: Center(
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  width: _recording ? 28 : 56,
                  height: _recording ? 28 : 56,
                  decoration: BoxDecoration(
                    color: _recording ? AppColors.primary : Colors.white,
                    borderRadius:
                        BorderRadius.circular(_recording ? 6 : 28),
                  ),
                ),
              ),
            ),
          ),
          // 오른쪽: 취소.
          SizedBox(
            width: 44,
            child: _recording
                ? const SizedBox.shrink()
                : GestureDetector(
                    onTap: () => Navigator.of(context).maybePop(),
                    child: const Text('취소',
                        textAlign: TextAlign.end,
                        style:
                            TextStyle(color: Colors.white, fontSize: 16)),
                  ),
          ),
        ],
      ),
    );
  }
}

/// 녹화/선택한 영상을 미리 보고, 좌타·우타를 고른 뒤 업로드하는 화면.
class _ReviewScreen extends StatefulWidget {
  const _ReviewScreen({required this.videoPath});
  final String videoPath;

  @override
  State<_ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<_ReviewScreen> {
  late final VideoPlayerController _video;
  final _api = AnalysisApi();
  bool _isLeft = false; // 기본: 우타
  bool _uploading = false;

  @override
  void initState() {
    super.initState();
    _video = VideoPlayerController.file(File(widget.videoPath))
      ..initialize().then((_) {
        if (!mounted) return;
        setState(() {});
        _video
          ..setLooping(true)
          ..play();
      });
  }

  @override
  void dispose() {
    _video.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _upload() async {
    setState(() => _uploading = true);
    try {
      final created = await _api.uploadSwingVideo(
        videoPath: widget.videoPath,
        isLeft: _isLeft,
      );
      if (!mounted) return;
      // 리뷰(중첩 MaterialPageRoute)만 닫고, 촬영 화면은 GoRouter 로 피드백으로
      // 교체한다. GoRoute 페이지를 Navigator.pop 으로 직접 닫으면 GoRouter 상태와
      // 어긋나 push 가 무시되므로, 교체는 반드시 router 로 한다.
      // 갓 촬영한 스윙이므로 비교 대상이 없는 첫 피드백(first=1)으로 연다.
      // TODO(backend): 실제로는 이 유저의 이전 기록 유무로 first 여부를 정한다.
      final router = GoRouter.of(context);
      Navigator.of(context).pop(); // review 닫기
      // 방금 촬영한 영상 경로를 함께 넘겨 "내 스윙 영상" 에 실제 영상을 보여준다.
      router.pushReplacement(
        '/analyses/${created.analysisId}?first=1',
        extra: widget.videoPath,
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _uploading = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: const Text('촬영 확인'),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: Center(
                child: _video.value.isInitialized
                    ? AspectRatio(
                        aspectRatio: _video.value.aspectRatio,
                        child: VideoPlayer(_video),
                      )
                    : const CircularProgressIndicator(color: Colors.white),
              ),
            ),
            _handednessSelector(),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _uploading
                          ? null
                          : () => Navigator.of(context).pop(),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.white,
                        side: const BorderSide(color: Colors.white54),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: const Text('다시 촬영'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      onPressed: _uploading ? null : _upload,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: _uploading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                  color: Colors.white, strokeWidth: 2),
                            )
                          : const Text('분석 요청'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _handednessSelector() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      child: Row(
        children: [
          const Text('타격', style: TextStyle(color: Colors.white70)),
          const SizedBox(width: 16),
          _choice('우타', !_isLeft, () => setState(() => _isLeft = false)),
          const SizedBox(width: 8),
          _choice('좌타', _isLeft, () => setState(() => _isLeft = true)),
        ],
      ),
    );
  }

  Widget _choice(String label, bool selected, VoidCallback onTap) {
    return ChoiceChip(
      label: Text(label),
      selected: selected,
      onSelected: (_) => onTap(),
      selectedColor: AppColors.primary,
      backgroundColor: Colors.white12,
      labelStyle: TextStyle(color: selected ? Colors.white : Colors.white70),
    );
  }
}

// ----------------------------------------------------------------------
// 촬영 가이드 (단계별 안내)
// ----------------------------------------------------------------------

/// 촬영 전 보여주는 2단계 가이드 팝업.
/// 1/2: 측면에서 촬영 → 2/2: 전신이 나오도록 촬영.
/// 상단 X 를 누르면 종료 확인 팝업을 띄우고, 확인 시 가이드를 닫는다.
class CameraGuideDialog extends StatefulWidget {
  const CameraGuideDialog({super.key});

  @override
  State<CameraGuideDialog> createState() => _CameraGuideDialogState();
}

class _CameraGuideDialogState extends State<CameraGuideDialog> {
  final _controller = PageController();
  int _page = 0;
  static const _pageCount = 2;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _next() {
    if (_page < _pageCount - 1) {
      _controller.nextPage(
          duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    } else {
      Navigator.of(context).pop(); // 촬영 시작하기 → 가이드 닫기
    }
  }

  void _back() {
    if (_page > 0) {
      _controller.previousPage(
          duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    }
  }

  // X: 종료할지 한 번 더 확인.
  Future<void> _confirmExit() async {
    final exit = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: const [
            Icon(Icons.sports_baseball, color: AppColors.primary, size: 36),
            SizedBox(height: 12),
            Text('촬영 가이드를 종료할까요?',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            SizedBox(height: 8),
            Text('가이드를 종료하면 정확한 분석이\n어려울 수 있어요.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.hint, fontSize: 13)),
          ],
        ),
        actionsAlignment: MainAxisAlignment.spaceBetween,
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('취소', style: TextStyle(color: AppColors.hint)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
            child: const Text('종료하기'),
          ),
        ],
      ),
    );
    if (exit == true && mounted) {
      Navigator.of(context).pop(); // 가이드 자체를 닫는다.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: SizedBox(
        height: 560,
        child: Column(
          children: [
            _topRow(),
            Expanded(
              child: PageView(
                controller: _controller,
                onPageChanged: (i) => setState(() => _page = i),
                children: const [_GuidePageOne(), _GuidePageTwo()],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _next,
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(_page == _pageCount - 1 ? '촬영 시작하기' : '다음'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topRow() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Row(
        children: [
          SizedBox(
            width: 32,
            child: _page > 0
                ? IconButton(
                    padding: EdgeInsets.zero,
                    icon: const Icon(Icons.chevron_left),
                    onPressed: _back,
                  )
                : null,
          ),
          const SizedBox(width: 4),
          Expanded(child: _progress()),
          const SizedBox(width: 4),
          SizedBox(
            width: 32,
            child: IconButton(
              padding: EdgeInsets.zero,
              icon: const Icon(Icons.close),
              onPressed: _confirmExit,
            ),
          ),
        ],
      ),
    );
  }

  Widget _progress() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: (_page + 1) / _pageCount,
            minHeight: 6,
            backgroundColor: AppColors.fieldFill,
            valueColor: const AlwaysStoppedAnimation(AppColors.primary),
          ),
        ),
        const SizedBox(height: 4),
        Text('${_page + 1}/$_pageCount',
            style: const TextStyle(fontSize: 11, color: AppColors.hint)),
      ],
    );
  }
}

/// 1/2 페이지: 측면에서 촬영.
class _GuidePageOne extends StatelessWidget {
  const _GuidePageOne();

  @override
  Widget build(BuildContext context) {
    return _GuideBody(
      highlight: '측면',
      rest: '에서 촬영해 주세요',
      subtitle: '스윙 동작이 잘 보이도록\n옆에서 촬영해 주세요.',
      tip: '정면이 아닌, 옆(측면)에서 촬영해야\n스윙 자세를 정확하게 분석할 수 있어요.',
      illustration: SizedBox(
        width: 180,
        height: 190,
        child: Stack(
          alignment: Alignment.center,
          children: [
            const CustomPaint(size: Size(150, 180), painter: _BatterPainter()),
            // "측면" 배지.
            Positioned(
              top: 16,
              right: 0,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Text('측면',
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w700)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 2/2 페이지: 전신이 나오도록 촬영.
class _GuidePageTwo extends StatelessWidget {
  const _GuidePageTwo();

  @override
  Widget build(BuildContext context) {
    return _GuideBody(
      highlight: '전신',
      rest: '이 나오도록 촬영해 주세요',
      subtitle: '머리부터 발끝까지\n모두 화면에 들어오게 해주세요.',
      tip: '전신이 보여야 관절 움직임을\n정확하게 분석할 수 있어요.',
      illustration: SizedBox(
        width: 180,
        height: 190,
        child: CustomPaint(
          foregroundPainter: const _FramePainter(),
          child: const Center(
            child: CustomPaint(
                size: Size(130, 160), painter: _BatterPainter()),
          ),
        ),
      ),
    );
  }
}

/// 가이드 한 페이지 공통 레이아웃(제목·부제·그림·팁).
class _GuideBody extends StatelessWidget {
  const _GuideBody({
    required this.highlight,
    required this.rest,
    required this.subtitle,
    required this.illustration,
    required this.tip,
  });

  final String highlight; // 빨강으로 강조할 앞 단어
  final String rest; // 나머지 제목
  final String subtitle;
  final Widget illustration;
  final String tip;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(
        children: [
          const SizedBox(height: 8),
          RichText(
            textAlign: TextAlign.center,
            text: TextSpan(
              style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: Colors.black),
              children: [
                TextSpan(
                    text: highlight,
                    style: const TextStyle(color: AppColors.primary)),
                TextSpan(text: rest),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Text(subtitle,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.subtitle, fontSize: 13)),
          Expanded(child: Center(child: illustration)),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.fieldFill,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.lightbulb_outline,
                    color: AppColors.primary, size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(tip,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.subtitle, height: 1.4)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }
}

/// 측면 타자 실루엣(이미지 참고). 머리/모자·상의는 짙은색, 바지는 밝은색.
class _BatterPainter extends CustomPainter {
  const _BatterPainter();

  static const _dark = Color(0xFF2E333D);
  static const _pants = Color(0xFFD9DBDE);
  static const _skin = Color(0xFFC89B6E);
  static const _bat = Color(0xFFC19A64);

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    Offset p(double x, double y) => Offset(x * w, y * h);

    final darkFill = Paint()..color = _dark;
    final pantsFill = Paint()..color = _pants;
    final skinFill = Paint()..color = _skin;

    // 다리(스탠스): 앞/뒤로 벌린 모양.
    final legs = Path()
      ..moveTo(w * 0.40, h * 0.55)
      ..lineTo(w * 0.24, h * 0.94)
      ..lineTo(w * 0.37, h * 0.94)
      ..lineTo(w * 0.50, h * 0.66)
      ..lineTo(w * 0.64, h * 0.94)
      ..lineTo(w * 0.77, h * 0.94)
      ..lineTo(w * 0.60, h * 0.55)
      ..close();
    canvas.drawPath(legs, pantsFill);

    // 상체(짙은 유니폼), 약간 앞으로 기울임.
    final torso = Path()
      ..moveTo(w * 0.39, h * 0.33)
      ..lineTo(w * 0.61, h * 0.33)
      ..lineTo(w * 0.65, h * 0.60)
      ..lineTo(w * 0.37, h * 0.60)
      ..close();
    canvas.drawPath(torso, darkFill);

    // 머리(피부).
    final headCenter = p(0.55, 0.22);
    final headR = w * 0.095;
    canvas.drawCircle(headCenter, headR, skinFill);
    // 모자: 머리 위쪽 반원 + 왼쪽 챙.
    canvas.drawArc(
      Rect.fromCircle(center: headCenter, radius: headR * 1.08),
      pi,
      pi,
      true,
      darkFill,
    );
    final brim = Path()
      ..moveTo(headCenter.dx - headR * 0.6, headCenter.dy - headR * 0.1)
      ..lineTo(headCenter.dx - headR * 1.9, headCenter.dy + headR * 0.15)
      ..lineTo(headCenter.dx - headR * 0.6, headCenter.dy + headR * 0.4)
      ..close();
    canvas.drawPath(brim, darkFill);

    // 팔(짙은색, 굵은 선) — 어깨에서 손까지.
    final arm = Paint()
      ..color = _dark
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.085;
    final hands = p(0.70, 0.30);
    canvas.drawLine(p(0.57, 0.37), hands, arm);

    // 배트 — 손에서 위로.
    final batPaint = Paint()
      ..color = _bat
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.05;
    canvas.drawLine(hands, p(0.44, 0.04), batPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// 전신 안내용 점선 프레임(네 모서리 빨간 브래킷).
class _FramePainter extends CustomPainter {
  const _FramePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.primary
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;

    const inset = 10.0;
    final len = size.width * 0.18; // 브래킷 길이
    final l = inset, t = inset;
    final r = size.width - inset, b = size.height - inset;

    // 좌상
    canvas.drawLine(Offset(l, t), Offset(l + len, t), paint);
    canvas.drawLine(Offset(l, t), Offset(l, t + len), paint);
    // 우상
    canvas.drawLine(Offset(r, t), Offset(r - len, t), paint);
    canvas.drawLine(Offset(r, t), Offset(r, t + len), paint);
    // 좌하
    canvas.drawLine(Offset(l, b), Offset(l + len, b), paint);
    canvas.drawLine(Offset(l, b), Offset(l, b - len), paint);
    // 우하
    canvas.drawLine(Offset(r, b), Offset(r - len, b), paint);
    canvas.drawLine(Offset(r, b), Offset(r, b - len), paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
