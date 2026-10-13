import 'dart:io';

import 'package:video_player/video_player.dart';

VideoPlayerController selectedVideoController(String path) =>
    VideoPlayerController.file(File(path));

// 파일은 image_picker/camera가 관리한다. 사용자의 원본을 삭제하지 않는다.
void releaseSelectedVideo(String? path) {}
