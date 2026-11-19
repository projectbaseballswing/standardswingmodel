import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/models/swing_timeline.dart';

SwingEvent ev(String key, int frame, double? ms) =>
    SwingEvent(key: key, name: key, frame: frame, msFromImpact: ms);

void main() {
  // 30fps: 앞발 들기 1.0s, 착지 1.7s, 스윙 시작 1.8s, 임팩트 2.0s, 팔로우 종료 2.3s.
  final events = [
    ev('foot_lift', 30, -1000),
    ev('foot_plant', 51, -300),
    ev('swing_start', 54, -200),
    ev('follow_end', 69, 300),
  ];

  test('event frames map phase boundaries onto video time', () {
    final timeline = SwingTimeline.fromEvents(events)!;
    expect(timeline.secondsOf('impact'), closeTo(2.0, 1e-9));
    final clock = timeline.clockFor(80)!; // 4구간 × 20점
    expect(clock.secondsAt(0), closeTo(1.0, 1e-9));
    expect(clock.secondsAt(19), closeTo(1.7, 1e-9));
    expect(clock.secondsAt(59), closeTo(2.0, 1e-9));
    expect(clock.secondsAt(79), closeTo(2.3, 1e-9));
    // 구간 안은 비례 배분
    expect(clock.secondsAt(9.5), closeTo(1.35, 1e-9));
  });

  test('video time maps back to the series index and clamps outside', () {
    final clock = SwingTimeline.fromEvents(events)!.clockFor(80)!;
    expect(clock.indexAt(2.0), closeTo(59, 1e-9));
    expect(clock.indexAt(2.15), closeTo(69.5, 1e-9));
    expect(clock.indexAt(0.2), 0);
    expect(clock.indexAt(9.0), 79);
  });

  test('missing foot lift starts the clock at foot plant', () {
    final clock = SwingTimeline.fromEvents(events.skip(1).toList())!
        .clockFor(80)!;
    expect(clock.indexAt(0), 19);
    expect(clock.secondsAt(0), closeTo(1.7, 1e-9));
  });

  test('not enough timed events disables sync', () {
    expect(SwingTimeline.fromEvents([ev('foot_plant', 51, -300)]), isNull);
    expect(SwingTimeline.fromEvents(const []), isNull);
  });
}
