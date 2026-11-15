import 'dart:async';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../api/pose_3d_api.dart';
import '../../api/analysis_api.dart';
import '../../data/session.dart';
import 'swing_3d_screen.dart';

/// A real analysis route owns status polling; rendering remains reusable.
class UserSwing3dScreen extends StatefulWidget {
  const UserSwing3dScreen({
    super.key,
    required this.analysisId,
    this.api,
    this.sceneBuilder,
    this.pollInterval = const Duration(seconds: 2),
  });
  final String analysisId;
  final Pose3dApi? api;
  final SwingSceneBuilder? sceneBuilder;
  final Duration pollInterval;
  @override
  State<UserSwing3dScreen> createState() => _UserSwing3dScreenState();
}

class _UserSwing3dScreenState extends State<UserSwing3dScreen> {
  late final Pose3dApi _api;
  final AnalysisApi _analysisApi = AnalysisApi();
  Pose3dResponse? _response;
  Pose3dException? _error;
  Timer? _poll;
  int _generation = 0, _pollCount = 0;
  bool _loading = true;
  // 품질 색뼈대용(선택). 분석 리포트에서 받는다.
  Map<String, List<int>>? _phaseFrames;
  Map<String, Map<String, String>>? _phasePartLevels;
  String _handedness = 'right';

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? Pose3dApi();
    Session.instance.addListener(_sessionChanged);
    _load();
  }

  // 분석 리포트에서 구간 프레임 경계 + 구간별·부위별 level 을 파싱한다.
  // 선택적 기능이라 실패/부재 시 조용히 넘어가고 3D는 그대로 보여준다.
  Future<void> _loadQuality() async {
    try {
      final data = await _analysisApi.getAnalysis(widget.analysisId);
      final result = data['result'];
      if (result is! Map) return;
      final input = data['input'];
      final hand = (input is Map ? input['handedness'] : null) ?? 'right';
      final pf = <String, List<int>>{};
      final rawPf = result['phase_frames'];
      if (rawPf is Map) {
        rawPf.forEach((k, v) {
          if (v is List && v.length >= 2) {
            pf['$k'] = [(v[0] as num).toInt(), (v[1] as num).toInt()];
          }
        });
      }
      const order = {'good': 0, 'caution': 1, 'warning': 2};
      final parts = <String, Map<String, String>>{};
      final joints = result['joints'];
      if (joints is List) {
        for (final j in joints) {
          if (j is! Map) continue;
          final bp = (j['body_part'] as String?) ?? 'other';
          final phases = j['phases'];
          if (phases is! List) continue;
          for (final ph in phases) {
            if (ph is! Map) continue;
            final k = ph['phase'] as String?;
            final lv = (ph['level'] as String?) ?? 'good';
            if (k == null) continue;
            final m = parts.putIfAbsent(k, () => {});
            if (!m.containsKey(bp) || (order[lv] ?? 0) > (order[m[bp]] ?? 0)) {
              m[bp] = lv;
            }
          }
        }
      }
      if (!mounted || pf.isEmpty || parts.isEmpty) return;
      setState(() {
        _phaseFrames = pf;
        _phasePartLevels = parts;
        _handedness = '$hand';
      });
    } catch (_) {
      // 품질 데이터는 선택적. 실패해도 3D는 그대로.
    }
  }

  @override
  void didUpdateWidget(covariant UserSwing3dScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.analysisId != widget.analysisId) _load();
  }

  void _sessionChanged() {
    if (mounted) _load();
  }

  Future<void> _load({bool polling = false}) async {
    _poll?.cancel();
    final generation = ++_generation;
    if (!polling) _pollCount = 0;
    setState(() {
      _error = null;
      if (!polling) {
        _response = null;
        _loading = true;
      }
    });
    try {
      final response = await _api.fetch(widget.analysisId);
      if (!mounted || generation != _generation) return;
      setState(() {
        _response = response;
        _loading = false;
      });
      if (response.pending && _pollCount++ < 90) {
        _poll = Timer(widget.pollInterval, () => _load(polling: true));
      } else if (!response.pending && _phasePartLevels == null) {
        _loadQuality(); // 분석 완료 시 1회 품질 로드(비차단)
      }
    } on Pose3dException catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _error = error;
        _loading = false;
        _response = null;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _error = const Pose3dException(
          'invalid_response',
          '3D 데이터를 표시할 수 없습니다.',
        );
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _generation++;
    _poll?.cancel();
    Session.instance.removeListener(_sessionChanged);
    if (widget.api == null) _api.dispose();
    _analysisApi.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final clip = _response?.clip;
    if (clip != null) {
      return Swing3dScreen(
        key: ValueKey('${widget.analysisId}:${Session.instance.userId}'),
        loader: () async => clip,
        sceneBuilder: widget.sceneBuilder,
        dataWarnings: _response!.warnings,
        phaseFrames: _phaseFrames,
        phasePartLevels: _phasePartLevels,
        handedness: _handedness,
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('내 스윙 3D'),
        leading: IconButton(
          tooltip: '피드백으로 돌아가기',
          icon: const Icon(Icons.arrow_back),
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/swings'),
        ),
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_loading) const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(
                _error?.message ??
                    (_loading
                        ? '이 분석의 3D 데이터를 확인하고 있습니다.'
                        : _pollCount > 90
                        ? '3D 생성이 오래 걸리고 있습니다. 잠시 후 상태를 다시 확인해주세요.'
                        : '3D 스윙을 생성하고 있습니다. 완료되면 자동으로 표시됩니다.'),
                key: const Key('user-pose-status'),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                '분석 ${widget.analysisId}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (!_loading)
                TextButton(onPressed: _load, child: const Text('상태 다시 확인')),
              if (_error?.code == 'unauthenticated' ||
                  _error?.code == 'session_changed')
                FilledButton(
                  onPressed: () => context.go('/login'),
                  child: const Text('로그인'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
