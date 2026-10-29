import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../api/analysis_api.dart';
import '../api/auth_api.dart' show ApiException;
import '../route_observer.dart';
import '../theme/app_theme.dart';
import '../video/selected_video.dart';

typedef SwingVideoControllerFactory =
    VideoPlayerController Function({String? videoPath, Uri? url});

/// 로컬 영상 우선. 과거 영상은 [preload]가 true면 화면 진입 시, 아니면 탭할 때
/// URL과 스트림을 요청한다.
/// URL은 이 위젯의 controller 안에서만 사용하며 영구 저장하지 않는다.
class SwingVideo extends StatefulWidget {
  const SwingVideo({
    super.key,
    required this.analysisId,
    this.videoPath,
    this.api,
    this.controllerFactory,
    this.now,
    this.fit = BoxFit.cover,
    this.autoplay = false,
    this.preload = false,
  });

  final String analysisId;
  final String? videoPath;
  final AnalysisApi? api;
  final SwingVideoControllerFactory? controllerFactory;
  final DateTime Function()? now;
  final BoxFit fit;
  final bool autoplay;

  /// 저장된 영상도 진입 즉시 불러와 첫 화면을 보여준다(재생은 하지 않음).
  final bool preload;

  @override
  State<SwingVideo> createState() => _SwingVideoState();
}

class _SwingVideoState extends State<SwingVideo>
    with WidgetsBindingObserver, RouteAware {
  late final AnalysisApi _api;
  VideoPlayerController? _controller;
  ModalRoute<dynamic>? _route;
  Future<void> _cleanup = Future<void>.value();
  DateTime? _expiresAt;
  Duration _position = Duration.zero;
  bool _loading = false;
  bool _commandBusy = false;
  bool _visible = true;
  bool _foreground = true;
  String? _error;
  int _generation = 0;
  int _playIntent = 0;
  bool _useStoredVideo = false;

  bool get _local => widget.videoPath != null && !_useStoredVideo;
  DateTime get _now => (widget.now ?? DateTime.now)();
  bool get _expired =>
      !_local && (_expiresAt == null || !_now.isBefore(_expiresAt!));
  bool get _canPlay =>
      mounted && _visible && _foreground && (_route?.isCurrent ?? true);
  bool _current(int generation) => mounted && generation == _generation;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? AnalysisApi();
    WidgetsBinding.instance.addObserver(this);
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    _foreground = lifecycle == null || lifecycle == AppLifecycleState.resumed;
    if (_local || widget.preload) {
      unawaited(_load(play: widget.autoplay && !kIsWeb));
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (_route != route) {
      swingRouteObserver.unsubscribe(this);
      _route = route;
      if (route != null) swingRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didUpdateWidget(SwingVideo oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.analysisId != widget.analysisId ||
        oldWidget.videoPath != widget.videoPath) {
      _generation++;
      _playIntent++;
      unawaited(_detach());
      _loading = false;
      _commandBusy = false;
      _expiresAt = null;
      _position = Duration.zero;
      _error = null;
      _useStoredVideo = false;
      if (_local || widget.preload) {
        unawaited(_load(play: widget.autoplay && !kIsWeb));
      }
    }
  }

  @override
  void didPushNext() {
    _visible = false;
    unawaited(_pause());
  }

  @override
  void didPop() {
    _visible = false;
    unawaited(_pause());
  }

  @override
  void didPopNext() => _visible = true;

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (!_foreground) unawaited(_pause());
  }

  Future<void> _pause() async {
    _playIntent++;
    final c = _controller;
    if (c == null || !c.value.isPlaying) return;
    try {
      await c.pause();
    } catch (_) {
      _playerError(c);
    }
  }

  // 연결을 먼저 끊어 오래된 초기화/재생 콜백이 새 controller에 닿지 않게 한다.
  Future<void> _detach() {
    final c = _controller;
    _controller = null;
    if (c != null) {
      c.removeListener(_onTick);
      _cleanup = _cleanup.then((_) async {
        try {
          if (c.value.isPlaying) await c.pause();
        } catch (_) {
          // 플랫폼 오류의 URL/토큰을 출력하지 않는다.
        }
        try {
          await c.dispose();
        } catch (_) {
          // 오류가 난 controller도 한 번만 정리한다.
        }
      });
    }
    return _cleanup;
  }

  @override
  void dispose() {
    _generation++;
    _playIntent++;
    WidgetsBinding.instance.removeObserver(this);
    swingRouteObserver.unsubscribe(this);
    unawaited(_detach());
    if (widget.api == null) _api.dispose();
    super.dispose();
  }

  Future<void> _load({bool play = false, Duration? position}) async {
    if (_loading) return;
    final generation = ++_generation;
    final playIntent = _playIntent;
    final localPath = _local ? widget.videoPath : null;
    final analysisId = widget.analysisId;
    final resumeAt = position ?? _position;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await _detach();
      if (!_current(generation)) return;
      Uri? url;
      DateTime? expiresAt;
      if (localPath == null) {
        // 요청 시작부터 계산하여 네트워크 지연만큼 만료를 늦게 판단하지 않는다.
        final requestedAt = _now;
        final signed = await _api.getVideoUrl(analysisId);
        if (!_current(generation)) return;
        url = signed.url;
        expiresAt = requestedAt.add(Duration(seconds: signed.expiresIn));
        if (!_now.isBefore(expiresAt)) {
          throw ApiException('영상 주소가 만료됐습니다. 다시 시도해주세요.');
        }
      }
      final factory = widget.controllerFactory;
      final c = factory != null
          ? factory(videoPath: localPath, url: url)
          : localPath != null
          ? selectedVideoController(localPath)
          : VideoPlayerController.networkUrl(url!);
      _controller = c;
      _expiresAt = expiresAt;
      c.addListener(_onTick);
      await c.initialize().timeout(const Duration(seconds: 30));
      if (!_current(generation)) return;
      await c.setLooping(true);
      if (!_current(generation)) return;
      if (resumeAt > Duration.zero) {
        await c.seekTo(
          resumeAt > c.value.duration ? c.value.duration : resumeAt,
        );
        if (!_current(generation)) return;
      }
      if (c.value.hasError || !c.value.isInitialized) {
        throw StateError('Video initialization failed');
      }
      if (_expired) {
        throw ApiException('영상 주소가 만료됐습니다. 다시 시도해주세요.');
      }
      if (play && _canPlay && playIntent == _playIntent) {
        await c.play();
        if (!_current(generation)) return;
        if (!_canPlay || playIntent != _playIntent) await c.pause();
      }
    } catch (error) {
      if (!_current(generation)) return;
      _error = error is ApiException ? error.message : _playbackError;
      await _detach();
    } finally {
      if (_current(generation)) setState(() => _loading = false);
    }
  }

  String get _playbackError => _local
      ? kIsWeb
            ? '선택한 영상을 재생할 수 없습니다. 파일 형식과 코덱을 확인해주세요.'
            : '로컬 영상을 재생할 수 없습니다. 파일 형식과 코덱을 확인해주세요.'
      : '영상을 재생할 수 없습니다. 연결을 확인하고 다시 시도해주세요.';

  void _playerError(VideoPlayerController c) {
    if (!mounted || c != _controller) return;
    setState(() => _error = _playbackError);
    if (!_loading) {
      _generation++;
      _commandBusy = false;
      unawaited(_detach());
    }
  }

  void _onTick() {
    final c = _controller;
    if (!mounted || c == null) return;
    if (c.value.hasError) {
      if (_error == null) {
        _playerError(c);
        unawaited(_pause());
      }
    } else {
      _position = c.value.position;
      setState(() {});
    }
  }

  Future<void> _toggle() async {
    if (_loading || _commandBusy || !_canPlay) return;
    final c = _controller;
    if (c == null || _error != null || (!c.value.isPlaying && _expired)) {
      await _load(play: true);
      return;
    }
    final generation = _generation;
    final playIntent = _playIntent;
    _commandBusy = true;
    try {
      if (c.value.isPlaying) {
        await _pause();
      } else {
        await c.play();
        if (_current(generation) && (!_canPlay || playIntent != _playIntent)) {
          await c.pause();
        }
      }
    } catch (_) {
      _playerError(c);
    } finally {
      if (_current(generation)) _commandBusy = false;
    }
  }

  Future<void> _seek(double fraction) async {
    final c = _controller;
    if (_loading || _commandBusy || c == null || !_canPlay) return;
    final position = c.value.duration * fraction.clamp(0.0, 1.0);
    if (_expired) {
      await _load(play: c.value.isPlaying, position: position);
      return;
    }
    final generation = _generation;
    _commandBusy = true;
    try {
      await c.seekTo(position);
    } catch (_) {
      _playerError(c);
    } finally {
      if (_current(generation)) _commandBusy = false;
    }
  }

  String _fmt(Duration d) =>
      '${d.inMinutes.remainder(60).toString().padLeft(2, '0')}:'
      '${d.inSeconds.remainder(60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const ColoredBox(
        color: Color(0xFFE6E6E6),
        child: Center(
          child: SizedBox.square(
            dimension: 24,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              semanticsLabel: '영상을 불러오는 중',
            ),
          ),
        ),
      );
    }
    if (_error != null) {
      return ColoredBox(
        color: const Color(0xFFE6E6E6),
        child: Center(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    _error!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 11),
                  ),
                  TextButton(
                    onPressed: () {
                      // 웹 Blob이 사라졌거나 재생에 실패하면 저장된 원본으로
                      // 사용자가 명시적으로 재시도한다. 자동 재시도는 하지 않는다.
                      if (kIsWeb && _local && widget.analysisId.isNotEmpty) {
                        _useStoredVideo = true;
                      }
                      _toggle();
                    },
                    child: Text(
                      kIsWeb && _local && widget.analysisId.isNotEmpty
                          ? '저장된 영상으로 재시도'
                          : '다시 시도',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      return Semantics(
        button: true,
        label: '내 스윙 영상 재생',
        child: GestureDetector(
          onTap: _toggle,
          child: Container(
            color: const Color(0xFFE6E6E6),
            alignment: Alignment.center,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.sports_baseball,
                  size: 40,
                  color: Colors.grey.shade400,
                ),
                const SizedBox(height: 6),
                const Text('탭하여 재생', style: TextStyle(fontSize: 11)),
              ],
            ),
          ),
        ),
      );
    }
    return GestureDetector(
      key: const ValueKey('swing-video-playback'),
      behavior: HitTestBehavior.opaque,
      onTap: _toggle,
      child: Stack(
        fit: StackFit.expand,
        children: [
          FittedBox(
            fit: widget.fit,
            clipBehavior: Clip.hardEdge,
            child: SizedBox(
              width: c.value.size.width,
              height: c.value.size.height,
              // 웹에서는 영상이 HTML <video>라 탭을 가로챈다. 탭이 위의
              // GestureDetector로 가야 재생 중에도 눌러서 정지할 수 있다.
              child: IgnorePointer(child: VideoPlayer(c)),
            ),
          ),
          if (!c.value.isPlaying)
            // 피그마: 34px 흰 원(92% 불투명) 위 빨간 재생 삼각형.
            Center(
              child: Container(
                width: 34,
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.92),
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.play_arrow,
                  color: AppColors.primary,
                  size: 20,
                ),
              ),
            ),
          Positioned(
            left: 8,
            right: 8,
            bottom: 8,
            child: Row(
              children: [
                Text(
                  _fmt(c.value.position),
                  style: const TextStyle(color: Colors.white, fontSize: 10),
                ),
                const SizedBox(width: 4),
                Expanded(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      return GestureDetector(
                        key: const ValueKey('swing-video-progress'),
                        behavior: HitTestBehavior.opaque,
                        onTapUp: (details) => _seek(
                          details.localPosition.dx / constraints.maxWidth,
                        ),
                        onHorizontalDragUpdate: (details) => _seek(
                          details.localPosition.dx / constraints.maxWidth,
                        ),
                        child: VideoProgressIndicator(
                          c,
                          key: ObjectKey(c),
                          allowScrubbing: false,
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          colors: const VideoProgressColors(
                            playedColor: Colors.white,
                            bufferedColor: Colors.white30,
                            backgroundColor: Colors.white24,
                          ),
                        ),
                      );
                    },
                  ),
                ),
                const SizedBox(width: 4),
                Text(
                  _fmt(c.value.duration),
                  style: const TextStyle(color: Colors.white, fontSize: 10),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
