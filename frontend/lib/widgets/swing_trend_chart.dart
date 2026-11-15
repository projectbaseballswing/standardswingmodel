import 'package:flutter/material.dart';

import '../models/swing.dart';
import '../theme/app_theme.dart';

/// 실제 기록 시각을 X축에 사용한다. 보간 점수나 빈 날짜의 0점을 생성하지 않는다.
class SwingTrendChart extends StatelessWidget {
  const SwingTrendChart({
    super.key,
    required this.points,
    required this.selectedId,
    required this.onSelect,
  });

  final List<Swing> points;
  final String? selectedId;
  final ValueChanged<Swing> onSelect;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 230,
    child: LayoutBuilder(
      builder: (context, constraints) {
        final size = Size(constraints.maxWidth, 230);
        final positions = _positions(points, size);
        return Semantics(
          label:
              '종합 점수 그래프, 0점부터 100점. ${points.length}건. 아래 기록 목록에서도 선택할 수 있습니다.',
          child: GestureDetector(
            key: const ValueKey('swing-trend-chart'),
            behavior: HitTestBehavior.opaque,
            onTapDown: (details) {
              if (positions.isEmpty) return;
              var closest = 0;
              for (var i = 1; i < positions.length; i++) {
                if ((positions[i] - details.localPosition).distanceSquared <
                    (positions[closest] - details.localPosition)
                        .distanceSquared) {
                  closest = i;
                }
              }
              onSelect(points[closest]);
            },
            child: CustomPaint(
              painter: _TrendPainter(
                points,
                selectedId,
                Directionality.of(context),
              ),
              size: size,
            ),
          ),
        );
      },
    ),
  );
}

List<Offset> _positions(List<Swing> points, Size size) {
  if (points.isEmpty) return [];
  const left = 36.0, top = 12.0, bottom = 36.0;
  final width = (size.width - left - 14).clamp(1.0, double.infinity);
  final height = size.height - top - bottom;
  final first = points.first.recordedAt.microsecondsSinceEpoch;
  final span = points.last.recordedAt.microsecondsSinceEpoch - first;
  return points
      .map(
        (s) => Offset(
          left +
              width *
                  (span == 0
                      ? .5
                      : (s.recordedAt.microsecondsSinceEpoch - first) / span),
          top + height * (1 - s.score! / 100),
        ),
      )
      .toList();
}

class _TrendPainter extends CustomPainter {
  _TrendPainter(this.points, this.selectedId, this.direction);
  final List<Swing> points;
  final String? selectedId;
  final TextDirection direction;

  void _text(Canvas canvas, String text, Offset at, {double alignment = 0}) {
    final painter = TextPainter(
      text: TextSpan(
        text: text,
        style: const TextStyle(fontSize: 11, color: AppColors.gray600),
      ),
      textDirection: direction,
    )..layout();
    painter.paint(canvas, at - Offset(painter.width * alignment, 0));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = AppColors.line.withValues(alpha: .55)
      ..strokeWidth = 1;
    for (var score = 0; score <= 100; score += 25) {
      final y = 12 + (size.height - 48) * (1 - score / 100);
      canvas.drawLine(Offset(36, y), Offset(size.width - 14, y), grid);
      _text(canvas, '$score', Offset(28, y - 7), alignment: 1);
    }
    final locations = _positions(points, size);
    if (locations.isEmpty) return;
    if (locations.length > 1) {
      final path = Path()..moveTo(locations.first.dx, locations.first.dy);
      for (final point in locations.skip(1)) {
        path.lineTo(point.dx, point.dy);
      }
      canvas.drawPath(
        path,
        Paint()
          ..color = AppColors.primary
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5
          ..strokeJoin = StrokeJoin.round,
      );
    }
    for (var i = 0; i < locations.length; i++) {
      final selected = points[i].analysisId == selectedId;
      if (selected) {
        canvas.drawCircle(
          locations[i],
          9,
          Paint()..color = AppColors.primary.withValues(alpha: .16),
        );
      }
      canvas.drawCircle(
        locations[i],
        selected ? 5 : 3.5,
        Paint()..color = AppColors.primary,
      );
      canvas.drawCircle(
        locations[i],
        selected ? 2.5 : 1.5,
        Paint()..color = Colors.white,
      );
    }
    String date(Swing s) =>
        '${s.recordedAt.year}.${s.recordedAt.month}.${s.recordedAt.day}';
    if (points.first.recordedAt == points.last.recordedAt) {
      _text(
        canvas,
        date(points.first),
        Offset(locations.first.dx, size.height - 22),
        alignment: .5,
      );
    } else {
      _text(canvas, date(points.first), Offset(36, size.height - 22));
      _text(
        canvas,
        date(points.last),
        Offset(size.width - 14, size.height - 22),
        alignment: 1,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _TrendPainter old) =>
      old.points != points ||
      old.selectedId != selectedId ||
      old.direction != direction;
}
