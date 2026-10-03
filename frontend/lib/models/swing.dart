/// 스윙 목록(달력)에서 쓰는 스윙 한 건의 정보.
class Swing {
  const Swing({
    required this.analysisId,
    required this.recordedAt,
    this.score,
    this.thumbnailUrl,
  });

  /// 분석 식별자. 영상을 클릭하면 GET /api/analyses/{analysisId} 로 피드백을 조회한다.
  final String analysisId;

  /// 촬영/분석 시각.
  final DateTime recordedAt;

  /// 종합 점수(없을 수 있음).
  final int? score;

  /// 썸네일 이미지 URL(없을 수 있음).
  final String? thumbnailUrl;

  /// 시:분 라벨. 예) "16시 30분"
  String get timeLabel => '${recordedAt.hour}시 ${recordedAt.minute}분';

  /// 같은 '날'인지 비교 (시각 무시).
  bool isOnDay(DateTime day) =>
      recordedAt.year == day.year &&
      recordedAt.month == day.month &&
      recordedAt.day == day.day;
}
