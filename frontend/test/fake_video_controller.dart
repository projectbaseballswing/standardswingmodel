import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:video_player/video_player.dart';

/// 플랫폼/네트워크에 연결하지 않고 실제 VideoPlayer 위젯에 값을 공급한다.
class FakeVideoController extends VideoPlayerController {
  FakeVideoController({this.localPath, Uri? url, this.initializeGate})
    : super.networkUrl(url ?? Uri.parse('https://example.com/local-test'));

  final String? localPath;
  final Completer<void>? initializeGate;
  bool failInitialize = false;
  bool failPlay = false;
  bool failSeek = false;
  int plays = 0;
  int pauses = 0;
  int disposals = 0;

  @override
  Future<void> initialize() async {
    await initializeGate?.future;
    if (disposals > 0) return;
    if (failInitialize) throw StateError('https://example.com/?token=secret');
    value = const VideoPlayerValue(
      duration: Duration(minutes: 1),
      size: Size(1920, 1080),
      isInitialized: true,
    );
  }

  @override
  Future<void> setLooping(bool looping) async {
    value = value.copyWith(isLooping: looping);
  }

  @override
  Future<void> play() async {
    plays++;
    if (failPlay) throw StateError('https://example.com/?token=secret');
    value = value.copyWith(isPlaying: true);
  }

  @override
  Future<void> pause() async {
    pauses++;
    value = value.copyWith(isPlaying: false);
  }

  @override
  Future<void> seekTo(Duration position) async {
    if (failSeek) throw StateError('https://example.com/?token=secret');
    value = value.copyWith(position: position);
  }

  @override
  Future<void> dispose() async {
    disposals++;
    await super.dispose();
  }
}
