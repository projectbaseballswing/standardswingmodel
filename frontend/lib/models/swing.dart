/// 스윙 목록(달력)에서 쓰는 스윙 한 건의 정보.
class Swing {
  const Swing({
    required this.analysisId,
    required this.recordedAt,
    required this.status,
    this.score,
    this.thumbnailUrl,
  });

  factory Swing.fromJson(Map<String, dynamic> json) => Swing(
    analysisId: json['analysis_id'] as String,
    recordedAt: DateTime.parse(json['recorded_at'] as String).toLocal(),
    status: json['status'] as String,
    score: (json['score'] as num?)?.toDouble(),
    thumbnailUrl: json['thumbnail_url'] as String?,
  );

  /// 분석 식별자. 과거 결과 조회는 다음 단계에서 연결한다.
  final String analysisId;

  /// 기기 로컬 시간대로 변환한 촬영/분석 시각.
  final DateTime recordedAt;

  /// queued / processing / done / failed.
  final String status;

  /// 종합 점수(없을 수 있음).
  final double? score;

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
