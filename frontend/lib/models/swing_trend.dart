import 'swing.dart';

enum SwingTrendPeriod {
  week('최근 1주', 7),
  month('최근 1개월', 30),
  all('전체', null);

  const SwingTrendPeriod(this.label, this.days);
  final String label;
  final int? days;
}

/// 표시 기간은 기기 로컬 날짜 기준, 오늘 포함 7/30일이다.
/// 날짜가 같은 별도 분석은 보존하고, 같은 ID의 모순된 기록은 제외한다.
class SwingTrend {
  SwingTrend.fromSwings(
    List<Swing> swings, {
    required SwingTrendPeriod period,
    required DateTime now,
  }) {
    final localNow = now.toLocal();
    final days = period.days;
    final start = days == null
        ? null
        : DateTime(localNow.year, localNow.month, localNow.day - days + 1);
    bool inRange(Swing swing) =>
        (start == null || !swing.recordedAt.isBefore(start)) &&
        !swing.recordedAt.isAfter(now);

    final groups = <String, List<Swing>>{};
    for (final swing in swings) {
      groups.putIfAbsent(swing.analysisId, () => []).add(swing);
    }
    for (final group in groups.values) {
      if (!group.any(inRange)) continue;
      recordCount++;
      final first = group.first;
      final conflicting = group
          .skip(1)
          .any(
            (s) =>
                s.recordedAt != first.recordedAt ||
                s.status != first.status ||
                s.score != first.score,
          );
      if (conflicting) {
        conflictingCount++;
        continue;
      }
      duplicateCount += group.length - 1;
      final score = first.score;
      if (first.analysisId.trim().isEmpty ||
          first.status != 'done' ||
          score == null ||
          !score.isFinite ||
          score < 0 ||
          score > 100) {
        excludedCount++;
        continue;
      }
      _points.add(first);
    }
    _points.sort((a, b) {
      final byDate = a.recordedAt.compareTo(b.recordedAt);
      return byDate != 0 ? byDate : a.analysisId.compareTo(b.analysisId);
    });
  }

  final List<Swing> _points = [];
  List<Swing> get points => List.unmodifiable(_points);
  int recordCount = 0;
  int excludedCount = 0;
  int conflictingCount = 0;
  int duplicateCount = 0;
  double? get average => _points.isEmpty
      ? null
      : _points.fold<double>(0, (total, s) => total + s.score!) /
            _points.length;
  double? get change =>
      _points.length < 2 ? null : _points.last.score! - _points.first.score!;
}
