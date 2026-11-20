import 'package:flutter/material.dart';

import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 선택된 구간의 실제 시간·템포·신뢰도. 점수는 구간 화면의 점수 카드에 표시한다.
class PhaseMetrics extends StatelessWidget {
  const PhaseMetrics({super.key, required this.phase});
  final AnalysisPhase phase;

  @override
  Widget build(BuildContext context) {
    // '주요 관절 차이'만 보여준다. (시간/신뢰도/템포/몸통 회전 등은 표시하지 않는다.)
    if (!phase.available) {
      return _note(phase.unavailableReason ?? '이 구간은 분석할 수 없습니다.');
    }
    if (phase.deviations.isEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _note('신뢰 가능한 측정값에서 표시할 주요 관절 차이가 없어요.'),
          for (final warning in phase.warnings) _hint(warning),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '주요 관절 차이',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        ),
        _hint(
          '프로 기준 스윙과 비교한 차이예요. 막대가 길수록 기준에서 많이 벗어난 거예요(색: 초록 양호·주황 주의·빨강 경고).',
        ),
        for (final deviation in phase.deviations)
          _DeviationRow(deviation: deviation),
        _hint('차이 크기는 기준 분포와의 비교이며 실제 자세 정확도나 점수 기여도가 아닙니다.'),
        for (final warning in phase.warnings) _hint(warning),
      ],
    );
  }
}

/// '주요 관절 차이' 한 줄: 관절 이름 + 방향(색) + 뭘 재는지 설명 + 양방향 막대.
/// 가운데가 기준(0). 막대는 z 부호 방향으로, |z| 가 클수록 길게. 숫자는 보여주지 않는다.
class _DeviationRow extends StatelessWidget {
  const _DeviationRow({required this.deviation});
  final PhaseDeviation deviation;

  @override
  Widget build(BuildContext context) {
    final color = _devColor(deviation.level, deviation.zScore);
    final label =
        deviation.directionText ?? _directionLabel(deviation.direction);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            deviation.name,
            style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
          ),
          if (deviation.description.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                deviation.description,
                style: const TextStyle(fontSize: 10.5, color: AppColors.hint),
              ),
            ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 10,
                  child: CustomPaint(
                    size: Size.infinite,
                    painter: _DeviationBarPainter(
                      magnitude: (deviation.zScore ?? 0).abs(),
                      color: color,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

String _directionLabel(String direction) => switch (direction) {
  'higher' => '기준보다 큼',
  'lower' => '기준보다 작음',
  'similar' => '기준과 비슷',
  _ => '',
};

/// 레벨(없으면 |z|)로 막대·라벨 색을 정한다. 양호=초록, 주의=주황, 경고=빨강.
Color _devColor(String level, double? z) {
  final lv = level.isNotEmpty
      ? level
      : z == null
      ? 'good'
      : z.abs() >= 2
      ? 'warning'
      : z.abs() >= 1
      ? 'caution'
      : 'good';
  return switch (lv) {
    'warning' => AppColors.primary,
    'caution' => const Color(0xFFF5A623),
    _ => const Color(0xFF4CC38A),
  };
}

/// 왼쪽(기준과 같음) → 오른쪽으로 '벗어난 정도(|z|)'만큼 차는 막대.
/// 좌우에 방향 의미는 없다. 길수록 많이 벗어난 것이고, 색이 심각도를 나타낸다.
class _DeviationBarPainter extends CustomPainter {
  _DeviationBarPainter({required this.magnitude, required this.color});

  /// 기준에서 벗어난 크기(|z|). 0 이면 기준과 같음.
  final double magnitude;
  final Color color;

  /// |z| 가 이 값 이상이면 막대가 끝까지 찬다.
  static const double _zMax = 2.5;

  @override
  void paint(Canvas canvas, Size size) {
    final cy = size.height / 2;
    final r = size.height / 2; // 둥근 끝 반지름
    final left = r;
    final right = size.width - r;
    final track = Paint()
      ..color = const Color(0xFFECECEF)
      ..strokeCap = StrokeCap.round
      ..strokeWidth = size.height;
    canvas.drawLine(Offset(left, cy), Offset(right, cy), track);

    final frac = (magnitude / _zMax).clamp(0.0, 1.0);
    final fill = Paint()
      ..color = color
      ..strokeCap = StrokeCap.round
      ..strokeWidth = size.height;
    if (frac <= 0) {
      canvas.drawCircle(Offset(left, cy), r, fill);
    } else {
      canvas.drawLine(
        Offset(left, cy),
        Offset(left + frac * (right - left), cy),
        fill,
      );
    }
  }

  @override
  bool shouldRepaint(_DeviationBarPainter old) =>
      old.magnitude != magnitude || old.color != color;
}

class SwingEventsCard extends StatelessWidget {
  const SwingEventsCard({super.key, required this.events});
  final List<SwingEvent> events;

  @override
  Widget build(BuildContext context) {
    final shown = events
        .where(
          (e) =>
              const ['foot_plant', 'swing_start', 'follow_end'].contains(e.key),
        )
        .toList();
    if (shown.isEmpty) return const SizedBox.shrink();
    return _MetricCard(
      title: '주요 동작 시점 · 임팩트 기준',
      children: [
        for (final e in shown)
          _note(
            '${e.name}: ${e.msFromImpact == null
                ? '시간 정보 없음'
                : e.msFromImpact == 0
                ? '임팩트 시점'
                : '임팩트 ${e.msFromImpact! < 0 ? '전' : '후'} ${feedbackNumber(e.msFromImpact!.abs())} ms'} · 프레임 ${e.frame}',
          ),
      ],
    );
  }
}

class SpeedFeedbackCard extends StatelessWidget {
  const SpeedFeedbackCard({super.key, required this.metrics});
  final List<SpeedMetric> metrics;

  @override
  Widget build(BuildContext context) => _MetricCard(
    title: '속도와 타이밍',
    children: [
      for (final metric in metrics) ...[
        const SizedBox(height: 10),
        Text(
          metric.name,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        _note(
          '내 ${_value(metric.user, metric.unit)} / 기준 ${_value(metric.reference, metric.unit)}',
        ),
        if (!metric.available)
          _note('분석 불가')
        else if (metric.user == null)
          _note('측정값이 제공되지 않았습니다.'),
        _note(reliabilityLabel(metric.reliability)),
      ],
      if (metrics.any((m) => m.unit == 'body/s')) ...[
        const SizedBox(height: 10),
        _note('body/s는 체장 기준 상대속도입니다. 실제 이동 속도(m/s, km/h)가 아닙니다.'),
      ],
    ],
  );
}

String _value(double? value, String unit) =>
    value == null ? '-' : '${feedbackNumber(value)} $unit';

Widget _note(String text) => Padding(
  padding: const EdgeInsets.only(top: 4),
  child: Text(
    text,
    style: const TextStyle(
      fontSize: 11.5,
      color: AppColors.subtitle,
      height: 1.4,
    ),
  ),
);

/// 설명용 더 옅은 회색 줄.
Widget _hint(String text) => Padding(
  padding: const EdgeInsets.only(top: 2),
  child: Text(
    text,
    style: const TextStyle(fontSize: 11, color: AppColors.hint, height: 1.4),
  ),
);

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.title, required this.children});
  final String title;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(14),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: SizedBox(
        width: double.infinity,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
            ),
            ...children,
          ],
        ),
      ),
    ),
  );
}
