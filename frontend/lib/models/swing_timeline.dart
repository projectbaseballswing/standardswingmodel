import 'feedback.dart';

/// 스윙 이벤트(프레임)로 만든 영상 시간축.
///
/// 0.2 관절 시계열은 4구간(스트라이드/착지 후 준비/스윙/팔로우스루)을 같은
/// 점 개수로 나눈 축이라 영상 시간과 1:1 이 아니다. 서버 이벤트의 프레임으로
/// 구간 경계를 영상 시간에 맞추고, 구간 안은 비례로 나눈다.
class SwingTimeline {
  SwingTimeline._(this._seconds);

  /// 이벤트 키 → 영상 시작부터의 시간(초).
  final Map<String, double> _seconds;

  /// 구간 순서대로 (시작 이벤트, 끝 이벤트). 백엔드 PHASE_EVENTS 와 같다.
  static const _phaseEvents = [
    ('foot_lift', 'foot_plant'),
    ('foot_plant', 'swing_start'),
    ('swing_start', 'impact'),
    ('impact', 'follow_end'),
  ];

  /// 이벤트에서 시간축을 만든다. 임팩트 기준 시간이 있는 이벤트가 2개 미만이면
  /// fps 를 알 수 없어 null.
  static SwingTimeline? fromEvents(List<SwingEvent> events) {
    final timed = events.where((e) => e.msFromImpact != null).toList()
      ..sort((a, b) => a.frame.compareTo(b.frame));
    if (timed.length < 2) return null;
    final first = timed.first;
    final last = timed.last;
    final frames = last.frame - first.frame;
    final ms = last.msFromImpact! - first.msFromImpact!;
    if (frames <= 0 || ms <= 0) return null;
    final fps = frames * 1000 / ms;

    final seconds = <String, double>{
      for (final e in events) e.key: e.frame / fps,
    };
    // 임팩트 프레임은 이벤트에 직접 없어서 각 이벤트의 "임팩트까지 ms" 로 구한다.
    final impacts = [for (final e in timed) e.frame / fps - e.msFromImpact! / 1000];
    seconds['impact'] = impacts.reduce((a, b) => a + b) / impacts.length;
    return SwingTimeline._(seconds);
  }

  /// 이벤트 시간(초). 없으면 null.
  double? secondsOf(String key) => _seconds[key];

  /// 길이 [length] 인 4구간 시계열의 인덱스 ↔ 영상 시간 변환기.
  /// 맞출 수 있는 경계가 2개 미만이면 null.
  SeriesClock? clockFor(int length) {
    final seg = length ~/ _phaseEvents.length;
    if (seg < 2) return null;
    final knots = <(double, double)>[];
    for (var s = 0; s < _phaseEvents.length; s++) {
      final start = _seconds[_phaseEvents[s].$1];
      final end = _seconds[_phaseEvents[s].$2];
      if (start != null) knots.add(((s * seg).toDouble(), start));
      if (end != null) knots.add((((s + 1) * seg - 1).toDouble(), end));
    }
    // 이벤트 검출이 어긋나 시간이 거꾸로 가는 지점은 버린다.
    final clean = <(double, double)>[];
    for (final k in knots) {
      if (clean.isEmpty || (k.$1 > clean.last.$1 && k.$2 >= clean.last.$2)) {
        clean.add(k);
      }
    }
    if (clean.length < 2) return null;
    return SeriesClock._(clean, length);
  }
}

/// 시계열 인덱스(실수) ↔ 영상 시간(초) 구간별 선형 변환.
class SeriesClock {
  SeriesClock._(this._knots, this.length);

  /// (인덱스, 초). 인덱스는 증가, 시간은 비감소.
  final List<(double, double)> _knots;
  final int length;

  /// 인덱스 → 영상 시간(초). 범위 밖은 양 끝 시간으로 고정.
  double secondsAt(double index) {
    if (index <= _knots.first.$1) return _knots.first.$2;
    for (var k = 1; k < _knots.length; k++) {
      final (i1, t1) = _knots[k];
      if (index <= i1) {
        final (i0, t0) = _knots[k - 1];
        return t0 + (t1 - t0) * (index - i0) / (i1 - i0);
      }
    }
    return _knots.last.$2;
  }

  /// 영상 시간(초) → 인덱스. 범위 밖은 그래프 양 끝으로 고정.
  double indexAt(double seconds) {
    if (seconds <= _knots.first.$2) return _knots.first.$1;
    for (var k = 1; k < _knots.length; k++) {
      final (i1, t1) = _knots[k];
      if (seconds <= t1) {
        final (i0, t0) = _knots[k - 1];
        if (t1 == t0) return i0;
        return i0 + (i1 - i0) * (seconds - t0) / (t1 - t0);
      }
    }
    return _knots.last.$1;
  }
}
