// dart:io는 네이티브 구현에만 포함한다. 웹은 선택한 Blob URL을 사용한다.
export 'selected_video_io.dart'
    if (dart.library.js_interop) 'selected_video_web.dart';
