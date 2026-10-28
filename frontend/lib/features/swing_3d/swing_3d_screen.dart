import 'dart:math' as math;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:go_router/go_router.dart';
import '../../route_observer.dart';
import 'domain/pose.dart';
import 'domain/stabilizer.dart';
import 'rendering/integrated_mannequin_view.dart';
import 'diagnostics/scene_diagnostics.dart';

typedef SwingClipLoader = Future<SwingClip> Function();
typedef SwingSceneBuilder = Widget Function(BuildContext, SwingSceneState);

enum SwingDisplayMode { improved, p0, raw }

/// Rendering input is separate from the controls so widget tests can inspect
/// real coordinates without pretending a test canvas validates GPU rendering.
class SwingSceneState {
  const SwingSceneState({
    required this.positions,
    required this.warnings,
    required this.yaw,
    required this.pitch,
    required this.distance,
    required this.onReady,
    required this.onError,
    this.orientation,
    this.headPose,
    this.edgeVisible,
    this.torsoVisible = true,
    this.bodyScale = 1,
    this.cameraTargetY = -.1,
    this.mode = SwingDisplayMode.p0,
  });
  final List<List<double>?> positions;
  final List<bool> warnings;
  final double yaw, pitch, distance;
  final VoidCallback onReady;
  final ValueChanged<String> onError;
  final Map<String, dynamic>? orientation;
  final Map<String, dynamic>? headPose;
  final List<bool>? edgeVisible;
  final bool torsoVisible;
  final double bodyScale;
  final double cameraTargetY;
  final SwingDisplayMode mode;
}

class Swing3dScreen extends StatefulWidget {
  const Swing3dScreen({
    super.key,
    required this.loader,
    this.sceneBuilder,
    this.dataWarnings = const [],
  });
  final SwingClipLoader loader;
  final SwingSceneBuilder? sceneBuilder;
  final List<String> dataWarnings;

  @override
  State<Swing3dScreen> createState() => _Swing3dScreenState();
}

class _Swing3dScreenState extends State<Swing3dScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver, RouteAware {
  late final Ticker _ticker;
  SwingClip? _clip;
  PoseStabilizer? _p0;
  ModalRoute<dynamic>? _route;
  String? _loadError, _renderError;
  bool _loading = true, _ready = false, _playing = false;
  SwingDisplayMode _mode = SwingDisplayMode.p0;
  bool get _stable => _mode == SwingDisplayMode.p0;
  double _speed = 1;
  double _time = 0, _playStart = 0;
  double _yaw = .25, _pitch = .1, _distance = 3.6;
  final _pointers = <int, Offset>{};
  double _pinchSpan = 0, _pinchDistance = 3.6;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _ticker = createTicker(_tick);
    WidgetsBinding.instance.addObserver(this);
    _load();
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

  void _pause() {
    _ticker.stop();
    if (mounted && _playing) setState(() => _playing = false);
  }

  @override
  void didPushNext() => _pause();

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) _pause();
  }

  Future<void> _load() async {
    final generation = ++_generation;
    _ticker.stop();
    setState(() {
      _loading = true;
      _ready = false;
      _playing = false;
      _time = 0;
      _clip = null;
      _p0 = null;
      _loadError = null;
      _renderError = null;
      _pointers.clear();
    });
    try {
      final clip = await widget.loader();
      final p0 = PoseStabilizer(clip);
      if (!mounted || generation != _generation) return;
      setState(() {
        _clip = clip;
        _p0 = p0;
        _mode = clip.directional == null && clip.finalMotion == null
            ? SwingDisplayMode.p0
            : SwingDisplayMode.improved;
        _loading = false;
      });
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _loading = false;
        _loadError = error.toString();
      });
    }
  }

  void _tick(Duration elapsed) {
    final clip = _clip;
    if (clip == null) return;
    final next = _playStart + elapsed.inMicroseconds / 1000000 * _speed;
    setState(() {
      _time = math.min(next, clip.duration);
      if (next >= clip.duration) {
        _ticker.stop();
        _playing = false;
      }
    });
  }

  void _playPause() {
    if (!_ready || _renderError != null || _clip == null) return;
    if (_playing) {
      _pause();
      return;
    }
    setState(() {
      if (_time >= _clip!.duration) _time = 0;
      _playStart = _time;
      _playing = true;
    });
    _ticker.start();
  }

  void _seek(double value) {
    _ticker.stop();
    setState(() {
      _playing = false;
      _time = value.clamp(0, _clip!.duration);
    });
  }

  void _setSpeed(double speed) {
    final resume = _playing;
    _pause();
    setState(() => _speed = speed);
    if (resume) _playPause();
  }

  void _step(int delta) {
    final clip = _clip!;
    final index = (clip.frameIndexAt(_time) + delta).clamp(
      0,
      clip.frameCount - 1,
    );
    _seek(clip.timestamps[index]);
  }

  void _zoom(double delta) =>
      setState(() => _distance = (_distance + delta).clamp(1.6, 7.0));

  void _pointerDown(PointerDownEvent event) {
    _pointers[event.pointer] = event.localPosition;
    if (_pointers.length == 2) {
      _pinchSpan = (_pointers.values.first - _pointers.values.last).distance;
      _pinchDistance = _distance;
    }
  }

  void _pointerMove(PointerMoveEvent event) {
    final previous = _pointers[event.pointer];
    if (previous == null) return;
    _pointers[event.pointer] = event.localPosition;
    if (_pointers.length == 1) {
      final delta = event.localPosition - previous;
      setState(() {
        _yaw += delta.dx * .008;
        _pitch = (_pitch + delta.dy * .006).clamp(-1.2, 1.2);
      });
    } else if (_pointers.length == 2 && _pinchSpan > 0) {
      final span = (_pointers.values.first - _pointers.values.last).distance;
      if (span > 1) {
        setState(
          () =>
              _distance = (_pinchDistance * _pinchSpan / span).clamp(1.6, 7.0),
        );
      }
    }
  }

  void _renderFailed(String error) {
    if (!mounted) return;
    _ticker.stop();
    setState(() {
      _renderError = error;
      _ready = false;
      _playing = false;
    });
  }

  String? _emptyReason(StabilizedFrame frame, List<Vec3?> positions) {
    if (positions.any((point) => point != null)) return null;
    if (frame.source.finiteJointCount == 0) {
      return '원시 관절 좌표가 없어 이 프레임을 표시할 수 없습니다.';
    }
    if (!frame.source.hasValidRoot) return '골반 기준점이 없어 이 프레임을 표시할 수 없습니다.';
    return '안정화 표시 정책이 모든 관절을 생략했습니다. 원본 좌표로 전환해 비교할 수 있습니다.';
  }

  Widget _scene(StabilizedFrame frame, List<Vec3?> positions, double height) {
    final finalMotion = _mode == SwingDisplayMode.improved
        ? _clip!.finalMotion
        : null;
    final motion = _mode == SwingDisplayMode.improved
        ? finalMotion?.directional ?? _clip!.directional
        : null;
    final index = frame.source.index;
    // Keep the same world camera when comparing raw/P0 with final display.
    // Clips without the new display contract retain their legacy camera.
    final referenceScale = _clip!.finalMotion?.referenceScale ?? 1.0;
    final scene = SwingSceneState(
      positions: positions.map((point) => point?.toList()).toList(),
      warnings:
          motion?.warningsAt(index) ??
          frame.jointRisks.map((risks) => risks.isNotEmpty).toList(),
      yaw: _yaw,
      pitch: _pitch,
      distance: _distance * referenceScale,
      onReady: () {
        if (mounted && !_ready && _renderError == null) {
          setState(() => _ready = true);
        }
      },
      onError: _renderFailed,
      orientation: motion?.frameAt(index),
      headPose: finalMotion?.headAt(index),
      edgeVisible: motion?.edgesAt(index),
      torsoVisible: motion?.torsoAt(index) ?? true,
      bodyScale: finalMotion?.referenceScale ?? motion?.bodyScale ?? 1,
      cameraTargetY: -.1 * referenceScale,
      mode: _mode,
    );
    final empty = _emptyReason(frame, positions);
    return SizedBox(
      height: height,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Listener(
          key: const Key('swing-3d-orbit'),
          behavior: HitTestBehavior.opaque,
          onPointerDown: _pointerDown,
          onPointerMove: _pointerMove,
          onPointerUp: (event) => _pointers.remove(event.pointer),
          onPointerCancel: (event) => _pointers.remove(event.pointer),
          onPointerSignal: (event) {
            if (event is PointerScrollEvent) {
              GestureBinding.instance.pointerSignalResolver.register(
                event,
                (_) => _zoom(event.scrollDelta.dy * .004),
              );
            }
          },
          child: GestureDetector(
            // Claim pan/pinch in the scene so the surrounding page cannot
            // cancel a camera gesture when the longer guidance is scrollable.
            behavior: HitTestBehavior.opaque,
            onScaleStart: (_) {},
            onScaleUpdate: (_) {},
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (widget.sceneBuilder != null)
                  widget.sceneBuilder!(context, scene)
                else
                  MannequinView(
                    key: ValueKey(_generation),
                    positions: scene.positions,
                    jointWarnings: scene.warnings,
                    orientation: scene.orientation,
                    headPose: scene.headPose,
                    edgeVisible: scene.edgeVisible,
                    torsoVisible: scene.torsoVisible,
                    bodyScale: scene.bodyScale,
                    yaw: _yaw,
                    pitch: _pitch,
                    distance: scene.distance,
                    cameraTargetY: scene.cameraTargetY,
                    onDiagnostics: sceneDiagnosticsEnabled
                        ? (mesh) => publishSceneDiagnostics({
                            'frame_index': index,
                            'timestamp_s': frame.source.timestamp,
                            'playback_time_s': _time,
                            'playing': _playing,
                            'speed': _speed,
                            'mode': _mode.name,
                            'clip_id': _clip!.id,
                            'sample': _clip!.isSample,
                            'frame_count': _clip!.frameCount,
                            'body_scale': scene.bodyScale,
                            'head_pose': scene.headPose,
                            'orientation': scene.orientation,
                            'mesh': mesh,
                          })
                        : null,
                    onReady: scene.onReady,
                    onError: scene.onError,
                  ),
                if (empty != null && _renderError == null)
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: Container(
                      key: const Key('swing-3d-empty'),
                      margin: const EdgeInsets.all(12),
                      padding: const EdgeInsets.all(12),
                      color: const Color(0xEEFFF0D4),
                      child: Text(
                        empty,
                        style: const TextStyle(color: Color(0xFF663D00)),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('3D 스윙 상세'),
        leading: IconButton(
          tooltip: '피드백으로 돌아가기',
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/swings');
            }
          },
        ),
      ),
      body: SafeArea(
        top: false,
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1080),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFFF0D4),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _clip == null
                                  ? '3D 스윙 데이터 준비 중'
                                  : '${_clip!.isSample ? '샘플 시연' : '분석 좌표'} · ${_clip!.title}',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 17,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              _clip == null
                                  ? '좌표 데이터를 확인하고 있습니다.'
                                  : _clip?.isSample == false
                                  ? '분석 ${_clip!.analysisId}의 추정 좌표입니다. 실제 3D 정확도를 보장하지 않습니다.'
                                  : '현재 선택한 내 스윙의 분석 결과가 아닙니다. 기존 샘플 좌표를 재생합니다.',
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),
                      if (_loading)
                        const Padding(
                          padding: EdgeInsets.all(60),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      else if (_loadError != null) ...[
                        const Text(
                          '3D 데이터를 읽을 수 없습니다.',
                          key: Key('swing-3d-load-error'),
                        ),
                        Text(_loadError!),
                        TextButton(
                          onPressed: _load,
                          child: const Text('다시 시도'),
                        ),
                      ] else if (_clip != null)
                        ..._content(constraints),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  List<Widget> _content(BoxConstraints constraints) {
    final clip = _clip!;
    final index = clip.frameIndexAt(_time);
    final frame = _p0!.frameAt(index);
    final improved = _mode == SwingDisplayMode.improved;
    final finalMotion = improved ? clip.finalMotion : null;
    final motion = improved
        ? finalMotion?.directional ?? clip.directional
        : null;
    final orientation = motion?.frameAt(index);
    final positions = improved
        ? finalMotion?.positionsAt(index) ?? frame.source.positions
        : _stable
        ? frame.positions
        : frame.rawPositions;
    final visible = positions.where((point) => point != null).length;
    final warnings = <String>{
      ...widget.dataWarnings,
      ...clip.warnings,
      ...?motion?.reasonsAt(index),
      if (motion == null) ...frame.warnings,
    }.toList();
    final torsoShown =
        orientation != null &&
        motion != null &&
        motion.torsoAt(index) &&
        orientation['shoulder'] != null &&
        orientation['pelvis'] != null;
    return [
      SegmentedButton<SwingDisplayMode>(
        key: const Key('swing-3d-mode'),
        segments: [
          if (clip.directional != null || clip.finalMotion != null)
            const ButtonSegment(
              value: SwingDisplayMode.improved,
              label: Text('개선 시연'),
            ),
          const ButtonSegment(
            value: SwingDisplayMode.p0,
            label: Text('안정화 P0'),
          ),
          const ButtonSegment(
            value: SwingDisplayMode.raw,
            label: Text('원본 좌표'),
          ),
        ],
        selected: {_mode},
        onSelectionChanged: (values) => setState(() => _mode = values.single),
      ),
      const SizedBox(height: 12),
      _scene(
        frame,
        positions,
        (constraints.maxHeight * .48).clamp(240.0, 480.0),
      ),
      const SizedBox(height: 8),
      Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 16,
        children: [
          Text(
            '프레임 $index / ${clip.frameCount - 1} · ${_time.toStringAsFixed(2)} s',
            key: const Key('swing-3d-frame'),
          ),
          Text(
            '표시 $visible/12 · ${improved
                ? (finalMotion != null
                      ? "개선 P2 + O1 + F1 + S2 + H4"
                      : motion!.hasP2
                      ? "개선 P2 + O1"
                      : "방향 O1 · P2 없음")
                : _stable
                ? "안정화 P0"
                : "원본 좌표"}',
            key: const Key('swing-3d-count'),
          ),
        ],
      ),
      Slider(
        key: const Key('swing-3d-timeline'),
        value: _time,
        max: clip.duration,
        label: '${_time.toStringAsFixed(2)}초',
        semanticFormatterCallback: (value) => '${value.toStringAsFixed(2)}초',
        onChanged: _seek,
      ),
      Wrap(
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 8,
        children: [
          IconButton(
            tooltip: '이전 프레임',
            onPressed: () => _step(-1),
            icon: const Icon(Icons.skip_previous),
          ),
          FilledButton.icon(
            key: const Key('swing-3d-play'),
            onPressed: _ready && _renderError == null ? _playPause : null,
            icon: Icon(_playing ? Icons.pause : Icons.play_arrow),
            label: Text(_playing ? '일시정지' : '재생'),
          ),
          DropdownButton<double>(
            key: const Key('swing-3d-speed'),
            value: _speed,
            items: const [
              DropdownMenuItem(value: .25, child: Text('0.25×')),
              DropdownMenuItem(value: .5, child: Text('0.5×')),
              DropdownMenuItem(value: 1, child: Text('1×')),
            ],
            onChanged: (value) {
              if (value != null) _setSpeed(value);
            },
          ),
          IconButton(
            tooltip: '다음 프레임',
            onPressed: () => _step(1),
            icon: const Icon(Icons.skip_next),
          ),
          IconButton(
            tooltip: '확대',
            onPressed: () => _zoom(-.3),
            icon: const Icon(Icons.zoom_in),
          ),
          IconButton(
            tooltip: '축소',
            onPressed: () => _zoom(.3),
            icon: const Icon(Icons.zoom_out),
          ),
          IconButton(
            tooltip: '카메라 초기화',
            onPressed: () => setState(() {
              _yaw = .25;
              _pitch = .1;
              _distance = 3.6;
            }),
            icon: const Icon(Icons.restart_alt),
          ),
        ],
      ),
      const Center(
        child: Text(
          '드래그로 회전 · 휠 또는 두 손가락으로 확대/축소',
          style: TextStyle(fontSize: 12),
        ),
      ),
      const Padding(
        padding: EdgeInsets.only(top: 8),
        child: Text(
          '청록: 신체 · 주황: 발 방향 · 회색: 불확실/중립 표시 · 결측 관절은 생략',
          style: TextStyle(fontSize: 12),
        ),
      ),
      if (_renderError != null) ...[
        const Text(
          '3D 렌더링을 시작하지 못했습니다. 데이터 생략과는 별개의 표시 오류입니다.',
          key: Key('swing-3d-render-error'),
        ),
        TextButton(onPressed: _load, child: const Text('다시 시도')),
      ],
      const SizedBox(height: 12),
      Text(
        finalMotion != null
            ? '단안 영상의 추정 자세를 재생합니다. 머리 방향은 타자의 측면 자세를 보수적으로 표현한 표시 정책이며 실제 얼굴 추적 결과가 아닙니다. 머리·손·발 모양도 시각화용 추정입니다.'
            : '단안 영상에서 추정한 자세이며 실제 모션 캡처 정답이 아닙니다. 얼굴은 몸통 기반 추정 방향이며, 실제 머리의 독립 회전이 아닙니다. 머리·손·발 모양은 시각화용 추정입니다.',
        style: const TextStyle(fontSize: 12, color: Color(0xFF555555)),
      ),
      if (motion != null && orientation != null) ...[
        const SizedBox(height: 6),
        Text(
          motion.hasP2
              ? finalMotion != null
                    ? '표시용 좌표의 떨림을 줄이고 의심스러운 연결은 제한합니다. 원본 좌표와 결측 상태를 별도로 보존하며, 추정 자세의 정확도 개선을 뜻하지 않습니다.'
                    : '관절 위치는 유지하고 의심스러운 연결을 제한합니다. 개선 시연은 정확도가 독립 검증된 서비스 정책이 아닙니다.'
              : 'P2 표시 마스크가 없어 유한 관절을 연결합니다. P2 안정화 결과로 해석하지 마세요.',
          style: const TextStyle(fontSize: 12),
        ),
        if (finalMotion != null &&
            torsoShown &&
            finalMotion.headAt(index)['display_features'] != true)
          const Text(
            '머리 방향을 표시할 근거가 부족해 얼굴 표식 없는 중립 머리로 표시합니다.',
            key: Key('swing-3d-head-neutral'),
            style: TextStyle(fontSize: 12, color: Color(0xFF9A6000)),
          ),
        if (!motion.torsoAt(index) ||
            orientation['shoulder'] == null ||
            orientation['pelvis'] == null)
          const Text(
            '관절 점이 있어도 몸통·머리 연결은 표시할 수 없습니다. P2 표시 제한 또는 방향 계산 불가 상태입니다.',
            key: Key('swing-3d-torso-omitted'),
            style: TextStyle(color: Color(0xFF9A6000)),
          ),
        Text(
          '몸통 ${!torsoShown
              ? '표시 생략'
              : orientation['body_mode'] == 'directional'
              ? '방향 표시'
              : '방향 보류'} · '
          '왼발 ${orientation['feet'][0]['mode'] == 'directional'
              ? 'heel/toe 방향'
              : orientation['feet'][0]['mode'] == 'missing'
              ? '표시 불가'
              : '둥근 중립 표시'} · '
          '오른발 ${orientation['feet'][1]['mode'] == 'directional'
              ? 'heel/toe 방향'
              : orientation['feet'][1]['mode'] == 'missing'
              ? '표시 불가'
              : '둥근 중립 표시'}',
          key: const Key('swing-3d-direction-state'),
          style: const TextStyle(fontSize: 12),
        ),
      ],
      if (_stable)
        const Padding(
          padding: EdgeInsets.only(top: 4),
          child: Text(
            '기존 P0 정책은 뼈 길이를 조정하고 위험 관절을 숨깁니다. 더 정확한 자세를 보장하지 않습니다.',
            style: TextStyle(fontSize: 12),
          ),
        ),
      if (warnings.isNotEmpty)
        ExpansionTile(
          key: const Key('swing-3d-warnings'),
          tilePadding: EdgeInsets.zero,
          leading: const Icon(Icons.warning_amber, color: Color(0xFF9A6000)),
          title: Text('이 프레임의 주의 사항 ${warnings.length}개'),
          children: [
            for (final warning in warnings)
              ListTile(dense: true, title: Text(warning)),
          ],
        ),
    ];
  }

  @override
  void dispose() {
    clearSceneDiagnostics();
    _generation++;
    _ticker.dispose();
    swingRouteObserver.unsubscribe(this);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }
}
