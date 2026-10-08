import 'package:flutter/material.dart';

import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 관절별 분석(상세 피드백) 화면.
///
/// 종합 피드백에서 "상세 피드백 보기" 를 누르면 들어온다.
/// 위쪽 인체 그림에서 부위를 고르면 그 관절의 이전 대비 변화, 스윙 단계별
/// 점수 그래프, AI 코치 피드백을 보여준다.
class JointAnalysisScreen extends StatefulWidget {
  const JointAnalysisScreen({super.key, required this.feedback});

  /// 종합 피드백. 이 값을 관절별로 펼쳐서 보여준다.
  final OverallFeedback feedback;

  @override
  State<JointAnalysisScreen> createState() => _JointAnalysisScreenState();
}

class _JointAnalysisScreenState extends State<JointAnalysisScreen> {
  late final List<JointAnalysis> _joints;
  int _selected = 0;

  @override
  void initState() {
    super.initState();
    _joints = FeedbackRepository().buildJointAnalyses(widget.feedback);
    // 처음 들어오면 목록 맨 위 부위를 보여준다. (선택하면 그 부위로 바뀐다)
  }

  @override
  Widget build(BuildContext context) {
    final hasJoints = _joints.isNotEmpty;
    return Scaffold(
      backgroundColor: const Color(0xFFF7F7F7),
      appBar: AppBar(
        backgroundColor: const Color(0xFFF7F7F7),
        surfaceTintColor: const Color(0xFFF7F7F7),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
          onPressed: () => Navigator.of(context).maybePop(),
        ),
        title: const Text('관절별 분석'),
      ),
      body: !hasJoints
          ? const Center(child: Text('분석할 관절 정보가 없어요.'))
          : ListView(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
              children: [
                const Text(
                  '부위를 선택하면 상세 분석 결과를 확인할 수 있습니다.',
                  style: TextStyle(fontSize: 13, color: AppColors.hint),
                ),
                const SizedBox(height: 14),
                _SelectorCard(
                  joints: _joints,
                  selected: _selected,
                  onSelect: (i) => setState(() => _selected = i),
                ),
                const SizedBox(height: 14),
                _ScoreCard(joint: _joints[_selected]),
                const SizedBox(height: 14),
                _ChartCard(joint: _joints[_selected]),
                const SizedBox(height: 14),
                _CoachCard(joint: _joints[_selected]),
              ],
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// 부위 선택 카드 (인체 그림 + 목록)
// ---------------------------------------------------------------------------
class _SelectorCard extends StatelessWidget {
  const _SelectorCard({
    required this.joints,
    required this.selected,
    required this.onSelect,
  });

  final List<JointAnalysis> joints;
  final int selected;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              // 왼쪽: 인체 그림
              SizedBox(
                width: 96,
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: const [
                        Text('왼쪽',
                            style: TextStyle(
                                fontSize: 11, color: AppColors.hint)),
                        Text('오른쪽',
                            style: TextStyle(
                                fontSize: 11, color: AppColors.hint)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    SizedBox(
                      height: 180,
                      child: CustomPaint(
                        size: const Size(96, 180),
                        painter: _BodyFigurePainter(
                          regionColors: _regionColors(joints),
                          selectedRegion: _regionKeyOf(joints[selected]),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 14),
              // 오른쪽: 부위 목록
              Expanded(
                child: Column(
                  children: [
                    for (var i = 0; i < joints.length; i++) ...[
                      if (i > 0) const SizedBox(height: 8),
                      _PartRow(
                        joint: joints[i],
                        selected: i == selected,
                        onTap: () => onSelect(i),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _Legend(joints: joints),
        ],
      ),
    );
  }

  /// 인체 그림 영역별 색. 각 부위의 상태 색으로 칠한다.
  static Map<String, Color> _regionColors(List<JointAnalysis> joints) {
    final map = <String, Color>{};
    for (final j in joints) {
      map[_regionKeyOf(j)] = _statusStyle(j.status).color;
    }
    return map;
  }

  /// 부위 → 인체 그림 영역 키.
  ///
  /// 몸통은 관절이 3개(어깨 라인 / 상체 / 골반 라인)라 그림에서도
  /// 어깨선·척추·골반선 세 영역으로 나눠 매핑한다.
  static String _regionKeyOf(JointAnalysis j) {
    final left = j.label.contains('왼');
    switch (j.part) {
      case BodyPart.arm:
        return left ? 'leftArm' : 'rightArm';
      case BodyPart.leg:
        return left ? 'leftLeg' : 'rightLeg';
      case BodyPart.torso:
        if (j.label.contains('어깨')) return 'shoulderLine';
        if (j.label.contains('골반')) return 'pelvisLine';
        return 'spine'; // 상체 기울기
    }
  }
}

/// 목록의 부위 한 줄: 색 막대 + 이름 + 상태 배지 + 화살표.
class _PartRow extends StatelessWidget {
  const _PartRow({
    required this.joint,
    required this.selected,
    required this.onTap,
  });

  final JointAnalysis joint;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(joint.status);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
        decoration: BoxDecoration(
          color: selected ? style.soft : const Color(0xFFF7F7F7),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected ? style.color : Colors.transparent,
            width: 1.4,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 4,
              height: 18,
              decoration: BoxDecoration(
                color: style.color,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                joint.label,
                style: TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                  color: selected ? style.color : Colors.black87,
                ),
              ),
            ),
            Text(
              style.badge,
              style: TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w600,
                color: style.color,
              ),
            ),
            const Icon(Icons.chevron_right, size: 16, color: AppColors.hint),
          ],
        ),
      ),
    );
  }
}

/// 범례. 실제로 나타난 상태만 보여준다.
/// 반복 피드백은 개선됨/악화됨/변화없음/평가제한, 첫 피드백은 잘함/개선 필요.
class _Legend extends StatelessWidget {
  const _Legend({required this.joints});

  final List<JointAnalysis> joints;

  @override
  Widget build(BuildContext context) {
    // 표시 순서를 고정하고, 그중 실제로 존재하는 상태만 남긴다.
    const order = [
      JointStatus.proGood,
      JointStatus.proBad,
      JointStatus.improved,
      JointStatus.worsened,
      JointStatus.unchanged,
      JointStatus.limited,
    ];
    final present = joints.map((j) => j.status).toSet();
    final shown = order.where(present.contains);

    Widget dot(Color c, String label) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: c, shape: BoxShape.circle),
            ),
            const SizedBox(width: 4),
            Text(label,
                style: const TextStyle(fontSize: 11, color: AppColors.hint)),
          ],
        );
    return Wrap(
      alignment: WrapAlignment.center,
      spacing: 14,
      runSpacing: 6,
      children: [
        for (final s in shown)
          dot(_statusStyle(s).color, _statusStyle(s).legendLabel),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 점수 카드 (이전 / 현재 / 변화 + 설명)
// ---------------------------------------------------------------------------
class _ScoreCard extends StatelessWidget {
  const _ScoreCard({required this.joint});

  final JointAnalysis joint;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(joint.status);
    final delta = joint.delta;
    // 비교할 이전 점수가 있어야 이전/변화·비교 기간 선택을 보여준다.
    final hasComparison = joint.previousScore != null;
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 4,
                height: 16,
                decoration: BoxDecoration(
                  color: style.color,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 8),
              Text('${joint.label} 분석',
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const Spacer(),
              if (hasComparison)
                GestureDetector(
                  onTap: () {
                    // TODO(backend): 기록 저장·조회가 생기면 비교 기간 선택 연결.
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('비교 기간 선택은 준비 중이에요.')),
                    );
                  },
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: const [
                      Text('비교 기간 선택',
                          style:
                              TextStyle(fontSize: 12, color: AppColors.hint)),
                      Icon(Icons.chevron_right,
                          size: 16, color: AppColors.hint),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 14),
          if (hasComparison)
            Row(
              children: [
                _StatBox(
                    label: '이전 점수',
                    value: joint.previousScore?.toString() ?? '-'),
                const SizedBox(width: 10),
                _StatBox(
                    label: '현재 점수',
                    value: '${joint.currentScore}',
                    valueColor: style.color),
                const SizedBox(width: 10),
                _StatBox(
                  label: '점수 변화',
                  child: delta == null
                      ? const Text('-',
                          style: TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w800,
                              color: AppColors.hint))
                      : Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              delta > 0
                                  ? Icons.arrow_drop_up
                                  : (delta < 0
                                      ? Icons.arrow_drop_down
                                      : Icons.remove),
                              size: 22,
                              color: style.color,
                            ),
                            Text('${delta.abs()}',
                                style: TextStyle(
                                    fontSize: 22,
                                    fontWeight: FontWeight.w800,
                                    color: style.color)),
                          ],
                        ),
                ),
              ],
            )
          else
            // 첫 피드백(비교 없음): 현재 점수를 크게 + 상태 배지.
            _CurrentScoreOnly(joint: joint, style: style),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: style.soft,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(style.messageIcon, size: 16, color: style.color),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    joint.summary,
                    style: TextStyle(
                        fontSize: 12.5, height: 1.5, color: style.textOnSoft),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 이전/현재/변화 숫자 박스 하나.
class _StatBox extends StatelessWidget {
  const _StatBox({
    required this.label,
    this.value,
    this.valueColor,
    this.child,
  });

  final String label;
  final String? value;
  final Color? valueColor;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFFF7F7F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          children: [
            Text(label,
                style: const TextStyle(fontSize: 11, color: AppColors.hint)),
            const SizedBox(height: 6),
            child ??
                Text(value ?? '-',
                    style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        color: valueColor ?? Colors.black87)),
          ],
        ),
      ),
    );
  }
}

/// 첫 피드백(비교 없음)용 점수 블록. 현재 점수를 크게 + 상태 배지.
class _CurrentScoreOnly extends StatelessWidget {
  const _CurrentScoreOnly({required this.joint, required this.style});

  final JointAnalysis joint;
  final _StatusStyle style;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F7),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('현재 점수',
                  style: TextStyle(fontSize: 11, color: AppColors.hint)),
              const SizedBox(height: 4),
              Row(
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  Text('${joint.currentScore}',
                      style: TextStyle(
                          fontSize: 40,
                          height: 1.0,
                          fontWeight: FontWeight.w800,
                          color: style.color)),
                  const Padding(
                    padding: EdgeInsets.only(left: 2),
                    child: Text('/ 100',
                        style: TextStyle(fontSize: 13, color: AppColors.hint)),
                  ),
                ],
              ),
            ],
          ),
          const Spacer(),
          // 프로 기준 대비 상태 배지(잘함 / 개선 필요).
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            decoration: BoxDecoration(
              color: style.soft,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(style.messageIcon, size: 14, color: style.color),
                const SizedBox(width: 5),
                Text(style.badge,
                    style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                        color: style.color)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 스윙 단계별 점수 그래프 카드
// ---------------------------------------------------------------------------
class _ChartCard extends StatelessWidget {
  const _ChartCard({required this.joint});

  final JointAnalysis joint;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(joint.status);
    final hasPrev = joint.previousPhaseScores != null;
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('스윙 단계별 ${joint.label} 점수',
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w700)),
              ),
              if (hasPrev) ...[
                _LegendDot(color: const Color(0xFFBDBDBD), label: '이전 스윙'),
                const SizedBox(width: 10),
              ],
              _LegendDot(color: style.color, label: '현재 스윙'),
            ],
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: 150,
            child: CustomPaint(
              size: Size.infinite,
              painter: _PhaseChartPainter(
                current: joint.currentPhaseScores,
                previous: joint.previousPhaseScores,
                currentColor: style.color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(label,
            style: const TextStyle(fontSize: 11, color: AppColors.hint)),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// AI 코치의 피드백 카드
// ---------------------------------------------------------------------------
class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.joint});

  final JointAnalysis joint;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(joint.status);
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.auto_awesome, size: 16, color: Color(0xFF8A6BEA)),
              SizedBox(width: 6),
              Text('AI 코치의 피드백',
                  style:
                      TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 10),
          Text(joint.coachComment,
              style: const TextStyle(
                  fontSize: 12.5, height: 1.5, color: AppColors.subtitle)),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: style.soft,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.lightbulb_outline, size: 15, color: style.color),
                    const SizedBox(width: 6),
                    Text(joint.pointsTitle,
                        style: TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w700,
                            color: style.color)),
                  ],
                ),
                const SizedBox(height: 8),
                for (final p in joint.points)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(top: 5, right: 7),
                          child: Container(
                            width: 4,
                            height: 4,
                            decoration: BoxDecoration(
                                color: style.color, shape: BoxShape.circle),
                          ),
                        ),
                        Expanded(
                          child: Text(p,
                              style: TextStyle(
                                  fontSize: 12.5,
                                  height: 1.4,
                                  color: style.textOnSoft)),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 인체 그림 Painter
// ---------------------------------------------------------------------------
class _BodyFigurePainter extends CustomPainter {
  _BodyFigurePainter({
    required this.regionColors,
    required this.selectedRegion,
  });

  /// 'leftArm','rightArm','shoulderLine','spine','pelvisLine',
  /// 'leftLeg','rightLeg' → 색.
  final Map<String, Color> regionColors;

  /// 지금 선택된 영역 키. 이 부위만 진하게, 나머지는 흐리게 그린다.
  final String selectedRegion;

  static const _neutral = Color(0xFFCCD0D6);

  /// 선택된 영역은 상태색 그대로, 나머지는 흐리게 표시한다.
  Color _c(String key) {
    final base = regionColors[key] ?? _neutral;
    if (key == selectedRegion) return base;
    return Color.lerp(base, Colors.white, 0.6)!;
  }

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final cx = w / 2;

    final fill = Paint()..style = PaintingStyle.fill;
    final limb = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    // 머리
    fill.color = _neutral;
    canvas.drawCircle(Offset(cx, h * 0.10), w * 0.13, fill);

    // 몸통 베이스(연한 회색 덩어리). 그 위에 어깨선·척추·골반선을 얹는다.
    fill.color = Color.lerp(_neutral, Colors.white, 0.45)!;
    final torso = RRect.fromRectAndRadius(
      Rect.fromLTRB(cx - w * 0.17, h * 0.21, cx + w * 0.17, h * 0.56),
      Radius.circular(w * 0.09),
    );
    canvas.drawRRect(torso, fill);

    // 몸통 3부위: 어깨선(상단 가로) / 척추(세로) / 골반선(하단 가로)
    limb.strokeWidth = w * 0.09;
    limb.color = _c('spine');
    canvas.drawLine(
        Offset(cx, h * 0.27), Offset(cx, h * 0.50), limb);
    limb.strokeWidth = w * 0.085;
    limb.color = _c('shoulderLine');
    canvas.drawLine(
        Offset(cx - w * 0.13, h * 0.25), Offset(cx + w * 0.13, h * 0.25), limb);
    limb.color = _c('pelvisLine');
    canvas.drawLine(
        Offset(cx - w * 0.11, h * 0.52), Offset(cx + w * 0.11, h * 0.52), limb);

    // 팔
    limb.strokeWidth = w * 0.11;
    limb.color = _c('leftArm');
    canvas.drawLine(
        Offset(cx - w * 0.16, h * 0.26), Offset(cx - w * 0.32, h * 0.55), limb);
    limb.color = _c('rightArm');
    canvas.drawLine(
        Offset(cx + w * 0.16, h * 0.26), Offset(cx + w * 0.32, h * 0.55), limb);

    // 다리
    limb.strokeWidth = w * 0.13;
    limb.color = _c('leftLeg');
    canvas.drawLine(
        Offset(cx - w * 0.08, h * 0.56), Offset(cx - w * 0.11, h * 0.92), limb);
    limb.color = _c('rightLeg');
    canvas.drawLine(
        Offset(cx + w * 0.08, h * 0.56), Offset(cx + w * 0.11, h * 0.92), limb);
  }

  @override
  bool shouldRepaint(_BodyFigurePainter old) =>
      old.regionColors != regionColors ||
      old.selectedRegion != selectedRegion;
}

// ---------------------------------------------------------------------------
// 단계별 점수 꺾은선 Painter
// ---------------------------------------------------------------------------
class _PhaseChartPainter extends CustomPainter {
  _PhaseChartPainter({
    required this.current,
    required this.currentColor,
    this.previous,
  });

  final List<int> current;
  final List<int>? previous;
  final Color currentColor;

  static const _grid = Color(0xFFEDEDED);
  static const _axisText = Color(0xFF9E9E9E);
  static const _prevColor = Color(0xFFBDBDBD);

  @override
  void paint(Canvas canvas, Size size) {
    const leftPad = 26.0; // y축 숫자 자리
    const bottomPad = 26.0; // x축 라벨 자리
    const topPad = 6.0;
    final plot = Rect.fromLTRB(
        leftPad, topPad, size.width, size.height - bottomPad);

    double yOf(num score) =>
        plot.bottom - (score.clamp(0, 100) / 100) * plot.height;
    double xOf(int i) =>
        plot.left + (plot.width) * (i / (current.length - 1));

    final gridPaint = Paint()
      ..color = _grid
      ..strokeWidth = 1;

    // 가로 눈금선 + y 라벨 (0 / 50 / 100)
    for (final v in [0, 50, 100]) {
      final y = yOf(v);
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), gridPaint);
      _text(canvas, '$v', Offset(plot.left - 6, y),
          align: _Align.right, color: _axisText);
    }

    // x 라벨 (영문 + 국문 두 줄)
    for (var i = 0; i < SwingPhase.values.length && i < current.length; i++) {
      final phase = SwingPhase.values[i];
      final x = xOf(i);
      _text(canvas, phase.en, Offset(x, plot.bottom + 4),
          align: _Align.center, color: _axisText, size: 7.5);
      _text(canvas, phase.ko, Offset(x, plot.bottom + 14),
          align: _Align.center, color: _axisText, size: 7.5);
    }

    // 이전 스윙 선
    if (previous != null) {
      _drawLine(canvas, previous!, _prevColor, xOf, yOf);
    }
    // 현재 스윙 선
    _drawLine(canvas, current, currentColor, xOf, yOf);
  }

  void _drawLine(Canvas canvas, List<int> scores, Color color,
      double Function(int) xOf, double Function(num) yOf) {
    final linePaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final dotPaint = Paint()
      ..color = color
      ..style = PaintingStyle.fill;

    final path = Path();
    for (var i = 0; i < scores.length; i++) {
      final p = Offset(xOf(i), yOf(scores[i]));
      if (i == 0) {
        path.moveTo(p.dx, p.dy);
      } else {
        path.lineTo(p.dx, p.dy);
      }
    }
    canvas.drawPath(path, linePaint);
    for (var i = 0; i < scores.length; i++) {
      canvas.drawCircle(Offset(xOf(i), yOf(scores[i])), 2.6, dotPaint);
    }
  }

  void _text(Canvas canvas, String s, Offset at,
      {required _Align align, required Color color, double size = 10}) {
    final tp = TextPainter(
      text: TextSpan(
          text: s, style: TextStyle(color: color, fontSize: size)),
      textDirection: TextDirection.ltr,
    )..layout();
    double dx;
    switch (align) {
      case _Align.center:
        dx = at.dx - tp.width / 2;
        break;
      case _Align.right:
        dx = at.dx - tp.width;
        break;
      case _Align.left:
        dx = at.dx;
        break;
    }
    // y 라벨은 선 중앙에 오도록 살짝 올린다.
    final dy = align == _Align.right ? at.dy - tp.height / 2 : at.dy;
    tp.paint(canvas, Offset(dx, dy));
  }

  @override
  bool shouldRepaint(_PhaseChartPainter old) =>
      old.current != current ||
      old.previous != previous ||
      old.currentColor != currentColor;
}

enum _Align { left, center, right }

// ---------------------------------------------------------------------------
// 공통 위젯 / 상태 스타일
// ---------------------------------------------------------------------------
class _Card extends StatelessWidget {
  const _Card({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
      ),
      child: child,
    );
  }
}

class _StatusStyle {
  const _StatusStyle({
    required this.color,
    required this.soft,
    required this.textOnSoft,
    required this.badge,
    required this.messageIcon,
    String? legendLabel,
  }) : legendLabel = legendLabel ?? badge;

  final Color color;
  final Color soft;
  final Color textOnSoft;

  /// 목록 행에 쓰는 배지 글자. 예) 개선됨 / 개선 필요 / 잘함.
  final String badge;

  /// 범례에 쓰는 글자. 대개 배지와 같지만, 악화됨처럼 다를 수 있다.
  final String legendLabel;

  final IconData messageIcon;
}

_StatusStyle _statusStyle(JointStatus status) {
  switch (status) {
    case JointStatus.improved:
      return const _StatusStyle(
        color: Color(0xFF2E9E5B),
        soft: Color(0xFFE7F5EC),
        textOnSoft: Color(0xFF2B7A49),
        badge: '개선됨',
        messageIcon: Icons.arrow_upward,
      );
    case JointStatus.worsened:
      return const _StatusStyle(
        color: AppColors.primary,
        soft: Color(0xFFFDECEC),
        textOnSoft: Color(0xFFC0514F),
        badge: '개선 필요',
        legendLabel: '악화됨',
        messageIcon: Icons.error_outline,
      );
    case JointStatus.unchanged:
      return const _StatusStyle(
        color: Color(0xFF9E9E9E),
        soft: Color(0xFFF0F0F0),
        textOnSoft: Color(0xFF616161),
        badge: '변화 없음',
        messageIcon: Icons.remove,
      );
    case JointStatus.limited:
      return const _StatusStyle(
        color: Color(0xFFBDBDBD),
        soft: Color(0xFFF4F4F4),
        textOnSoft: Color(0xFF757575),
        badge: '평가 제한',
        messageIcon: Icons.info_outline,
      );
    case JointStatus.proGood:
      return const _StatusStyle(
        color: Color(0xFF2E9E5B),
        soft: Color(0xFFE7F5EC),
        textOnSoft: Color(0xFF2B7A49),
        badge: '잘함',
        messageIcon: Icons.check_circle_outline,
      );
    case JointStatus.proBad:
      return const _StatusStyle(
        color: AppColors.primary,
        soft: Color(0xFFFDECEC),
        textOnSoft: Color(0xFFC0514F),
        badge: '개선 필요',
        messageIcon: Icons.error_outline,
      );
  }
}
