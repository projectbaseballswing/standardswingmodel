import 'dart:async';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../api/pose_3d_api.dart';
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
  Pose3dResponse? _response;
  Pose3dException? _error;
  Timer? _poll;
  int _generation = 0, _pollCount = 0;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? Pose3dApi();
    Session.instance.addListener(_sessionChanged);
    _load();
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
