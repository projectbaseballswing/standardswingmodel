/// Display/coaching support only. Never edits stored scores or reliability.
String? feedbackPhaseSupportNotice(Map<String, dynamic> phase, {double? fps}) {
  final frames = phase['user_frames'];
  if (frames is! List || frames.length != 2) {
    return '구간의 원본 프레임 범위를 확인할 수 없어 동작 판단과 연습 안내를 보류해요.';
  }
  if (frames.any((x) => x is! int || x < 0) ||
      (frames[1] as int) <= (frames[0] as int)) {
    return '구간의 프레임 경계를 확인해야 해요. 점수는 참고용이며 동작 판단과 연습 안내를 보류해요.';
  }
  final count = (frames[1] as int) - (frames[0] as int);
  if (count <= 2) {
    return '구간이 매우 짧아요($count프레임 간격·경계 포함 관측값 ${count + 1}개). 점수는 참고용으로 유지하고 동작 판단·연습 안내는 보류해요.';
  }
  if (fps != null) {
    if (!fps.isFinite || fps <= 0) return '구간의 FPS를 확인해야 해 동작 판단과 연습 안내를 보류해요.';
    final duration = phase['user_duration_ms'];
    if (duration != null) {
      final expected = count / fps * 1000;
      final tolerance = expected * .001 > 1.1 ? expected * .001 : 1.1;
      if (duration is! num ||
          !duration.isFinite ||
          (duration - expected).abs() > tolerance) {
        return '구간의 프레임 수와 시간 정보가 맞지 않아 동작 판단과 연습 안내를 보류해요.';
      }
    }
  }
  return null;
}
