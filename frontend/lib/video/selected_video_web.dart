import 'dart:js_interop';

import 'package:video_player/video_player.dart';

VideoPlayerController selectedVideoController(String path) =>
    VideoPlayerController.networkUrl(Uri.parse(path));

@JS('URL.revokeObjectURL')
external void _revokeObjectUrl(JSString url);

// 선택 화면이 소유하며, 업로드 성공 시 결과 화면으로 소유권을 넘긴다.
void releaseSelectedVideo(String? path) {
  if (path != null && Uri.tryParse(path)?.scheme == 'blob') {
    _revokeObjectUrl(path.toJS);
  }
}
