import 'package:flutter/material.dart';

import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 선택된 구간의 실제 시간·템포·신뢰도. 점수는 구간 화면의 점수 카드에 표시한다.
class PhaseMetrics extends StatelessWidget {
  const PhaseMetrics({super.key, required this.phase});
  final AnalysisPhase phase;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      _note(
        '내 시간 ${_value(phase.available ? phase.userDurationMs : null, 'ms')} / 기준 ${_value(phase.referenceDurationMs, 'ms')}',
      ),
      _note(reliabilityLabel(phase.reliability)),
      if (!phase.available)
        _note(phase.unavailableReason ?? '이 구간은 분석할 수 없습니다.')
      else ...[
        _note(_tempo(phase)),
        if (phase.score == null) _note('구간 점수가 제공되지 않았습니다.'),
      ],
      for (final warning in phase.warnings) _note(warning),
      if (phase.available && phase.deviations.isNotEmpty) ...[
        _note('주요 관절 차이 (기준 스윙 대비)'),
        for (final deviation in phase.deviations)
          _note(
            '${deviation.name}: ${_direction(deviation.direction)}'
            '${deviation.zScore == null ? '' : ' · z ${feedbackNumber(deviation.zScore)}'}',
          ),
      ],
    ],
  );

  String _tempo(AnalysisPhase phase) {
    final ratio = phase.tempoRatio;
    final ratioText = ratio
        ?.toStringAsFixed(3)
        .replaceFirst(RegExp(r'\.?0+$'), '');
    final comparison = ratio == null
        ? '소요 시간 비율 미제공'
        : '기준의 $ratioText배'
              ' (${ratio > 1
                  ? '소요 시간이 더 김'
                  : ratio < 1
                  ? '소요 시간이 더 짧음'
                  : '소요 시간이 같음'})';
    final verdict = switch (phase.tempoLevel) {
      'good' => '기준 범위',
      'caution' => '기준과 차이 있음',
      'warning' => '기준과 차이 큼',
      _ => '판정 보류',
    };
    return '$comparison · 템포 $verdict';
  }

  String _direction(String direction) => switch (direction) {
    'higher' => '기준보다 높음',
    'lower' => '기준보다 낮음',
    'similar' => '기준과 유사',
    _ => '방향 정보 없음',
  };
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
