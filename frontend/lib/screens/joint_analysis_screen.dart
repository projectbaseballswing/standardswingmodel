import 'package:flutter/material.dart';

import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 관절별 분석(상세 피드백) 화면.
///
/// 종합 피드백에서 "상세 피드백 보기" 를 누르면 들어온다.
/// 위쪽 인체 그림에서 부위(앞팔/뒷팔/몸통/앞다리/뒷다리)를 고르면, 그 부위의
/// 점수·상태와 세부 항목(팔꿈치 각도, 손 높이 등)별 각도 그래프를 보여준다.
class JointAnalysisScreen extends StatefulWidget {
  const JointAnalysisScreen({super.key, required this.feedback});

  /// 종합 피드백. 이 값을 부위별로 펼쳐서 보여준다.
  final OverallFeedback feedback;

  @override
  State<JointAnalysisScreen> createState() => _JointAnalysisScreenState();
}

class _JointAnalysisScreenState extends State<JointAnalysisScreen> {
  late final List<PartAnalysis> _parts;
  int _selected = 0;

  @override
  void initState() {
    super.initState();
    _parts = FeedbackRepository().buildPartAnalyses(widget.feedback);
    // 처음 들어오면 목록 맨 위 부위를 보여준다. (선택하면 그 부위로 바뀐다)
  }

  @override
  Widget build(BuildContext context) {
    final hasParts = _parts.isNotEmpty;
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
      body: !hasParts
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
                  parts: _parts,
                  selected: _selected,
                  onSelect: (i) => setState(() => _selected = i),
                ),
                const SizedBox(height: 14),
                _ScoreCard(part: _parts[_selected]),
                const SizedBox(height: 14),
                if (_parts[_selected].features.isNotEmpty) ...[
                  _FeatureListCard(part: _parts[_selected]),
                  const SizedBox(height: 14),
                ],
                _CoachCard(part: _parts[_selected]),
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
    required this.parts,
    required this.selected,
    required this.onSelect,
  });

  final List<PartAnalysis> parts;
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
                          regionColors: _regionColors(parts),
                          selectedRegion: _regionKeyOf(parts[selected]),
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
                    for (var i = 0; i < parts.length; i++) ...[
                      if (i > 0) const SizedBox(height: 8),
                      _PartRow(
                        part: parts[i],
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
          _Legend(parts: parts),
        ],
      ),
    );
  }

  /// 인체 그림 영역별 색. 각 부위의 상태 색으로 칠한다.
  static Map<String, Color> _regionColors(List<PartAnalysis> parts) {
    final map = <String, Color>{};
    for (final p in parts) {
      map[_regionKeyOf(p)] = _statusStyle(p.status).color;
    }
    return map;
  }

  /// 부위 → 인체 그림 영역 키. 몸통은 통째로 하나의 영역으로 본다.
  static String _regionKeyOf(PartAnalysis p) {
    switch (p.part) {
      case BodyPart.arm:
        return p.isLeft ? 'leftArm' : 'rightArm';
      case BodyPart.leg:
        return p.isLeft ? 'leftLeg' : 'rightLeg';
      case BodyPart.torso:
        return 'torso';
    }
  }
}

/// 목록의 부위 한 줄: 색 막대 + 이름 + 점수 + 상태 배지 + 화살표.
class _PartRow extends StatelessWidget {
  const _PartRow({
    required this.part,
    required this.selected,
    required this.onTap,
  });

  final PartAnalysis part;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(part.status);
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
                part.label,
                style: TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                  color: selected ? style.color : Colors.black87,
                ),
              ),
            ),
            Text(
              '${part.currentScore}',
              style: TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w800,
                color: style.color,
              ),
            ),
            const SizedBox(width: 8),
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
  const _Legend({required this.parts});

  final List<PartAnalysis> parts;

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
    final present = parts.map((j) => j.status).toSet();
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
  const _ScoreCard({required this.part});

  final PartAnalysis part;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(part.status);
    final delta = part.delta;
    // 비교할 이전 점수가 있어야 이전/변화·비교 기간 선택을 보여준다.
    final hasComparison = part.previousScore != null;
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
              Text('${part.label} 분석',
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
                    value: part.previousScore?.toString() ?? '-'),
                const SizedBox(width: 10),
                _StatBox(
                    label: '현재 점수',
                    value: '${part.currentScore}',
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
            _CurrentScoreOnly(part: part, style: style),
          // 검출 신뢰도가 높지 않으면 참고 문구를 덧붙인다.
          if (part.reliability != 'high') ...[
            const SizedBox(height: 10),
            _ReliabilityNote(reliability: part.reliability),
          ],
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
                    part.summary,
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

/// 검출 신뢰도 안내(보통/낮음일 때만).
class _ReliabilityNote extends StatelessWidget {
  const _ReliabilityNote({required this.reliability});

  final String reliability;

  @override
  Widget build(BuildContext context) {
    final text = reliability == 'low'
        ? '이 부위는 가려지기 쉬워 분석 신뢰도가 낮은 편이에요. 참고용으로 봐주세요.'
        : '이 부위는 분석 신뢰도가 보통이에요. 참고용으로 봐주세요.';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.info_outline, size: 14, color: AppColors.hint),
        const SizedBox(width: 6),
        Expanded(
          child: Text(text,
              style: const TextStyle(fontSize: 11.5, color: AppColors.hint)),
        ),
      ],
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
  const _CurrentScoreOnly({required this.part, required this.style});

  final PartAnalysis part;
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
                  Text('${part.currentScore}',
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
// 세부 항목(피처) 목록 카드
// ---------------------------------------------------------------------------
/// 부위를 이루는 세부 항목들을 펼쳐, 각 항목이 기준과 어떻게 다른지 보여준다.
/// 항목을 누르면 스윙 전체 각도 그래프(내 스윙 vs 기준)가 열린다.
class _FeatureListCard extends StatefulWidget {
  const _FeatureListCard({required this.part});

  final PartAnalysis part;

  @override
  State<_FeatureListCard> createState() => _FeatureListCardState();
}

class _FeatureListCardState extends State<_FeatureListCard> {
  // 부위가 바뀌면 다시 "가장 문제인 항목"을 펼친다.
  int? _expanded;
  String? _partKey;

  @override
  Widget build(BuildContext context) {
    final features = widget.part.features;
    if (_partKey != widget.part.key) {
      _partKey = widget.part.key;
      // 기본으로 기준과 차이가 큰 첫 항목을 펼친다. 없으면 접어 둔다.
      final idx = features.indexWhere((f) => f.level != 'good');
      _expanded = idx >= 0 ? idx : null;
    }

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${widget.part.label} 세부 항목',
              style:
                  const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          const Text('항목을 누르면 스윙 전체 변화를 볼 수 있어요.',
              style: TextStyle(fontSize: 11.5, color: AppColors.hint)),
          const SizedBox(height: 8),
          for (var i = 0; i < features.length; i++) ...[
            if (i > 0)
              const Divider(height: 1, thickness: 0.6, color: Color(0xFFEDEDED)),
            _FeatureTile(
              feature: features[i],
              expanded: _expanded == i,
              onTap: () => setState(() => _expanded = _expanded == i ? null : i),
            ),
          ],
        ],
      ),
    );
  }
}

/// 세부 항목 한 줄(접힘) + 그래프/수치(펼침).
class _FeatureTile extends StatelessWidget {
  const _FeatureTile({
    required this.feature,
    required this.expanded,
    required this.onTap,
  });

  final FeatureAnalysis feature;
  final bool expanded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final fstyle = _featureStyle(feature.level);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 11),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(feature.name,
                          style: const TextStyle(
                              fontSize: 13.5, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 2),
                      Text(_directionText(feature.direction),
                          style: const TextStyle(
                              fontSize: 11.5, color: AppColors.hint)),
                    ],
                  ),
                ),
                // level 배지
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: fstyle.soft,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(fstyle.label,
                      style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: fstyle.color)),
                ),
                Icon(expanded ? Icons.expand_less : Icons.expand_more,
                    size: 18, color: AppColors.hint),
              ],
            ),
          ),
        ),
        if (expanded) _FeatureDetail(feature: feature),
      ],
    );
  }
}

/// 펼쳤을 때: 각도 그래프 + 임팩트/움직임 폭 수치.
class _FeatureDetail extends StatelessWidget {
  const _FeatureDetail({required this.feature});

  final FeatureAnalysis feature;

  @override
  Widget build(BuildContext context) {
    final series = feature.series;
    final phaseScores = feature.phaseScores;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ① 스윙 단계별 실제 값 변화 (내 스윙 vs 기준 ±편차)
          if (series != null && series.isNotEmpty) ...[
            Row(
              children: [
                Text('스윙 단계별 ${feature.unit == 'deg' ? '각도' : '위치'} 변화',
                    style: const TextStyle(
                        fontSize: 12.5, fontWeight: FontWeight.w700)),
                const Spacer(),
                _LegendDot(color: const Color(0xFFBDBDBD), label: '기준 스윙'),
                const SizedBox(width: 10),
                _LegendDot(color: AppColors.primary, label: '내 스윙'),
              ],
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 140,
              child: CustomPaint(
                size: Size.infinite,
                painter: _FeatureChartPainter(
                  series: series,
                  unit: feature.unit,
                  userColor: AppColors.primary,
                ),
              ),
            ),
            const SizedBox(height: 14),
          ],
          // ② 스윙 단계별 점수 (구간 z_score 환산)
          if (phaseScores != null) ...[
            const Text('스윙 단계별 점수',
                style:
                    TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            SizedBox(
              height: 130,
              child: CustomPaint(
                size: Size.infinite,
                painter: _PhaseScoreChartPainter(
                  scores: phaseScores,
                  color: AppColors.primary,
                ),
              ),
            ),
            const SizedBox(height: 10),
          ],
          // 임팩트 순간 / 움직임 폭 수치
          Row(
            children: [
              if (feature.impact != null)
                _MeasureBox(
                    label: '임팩트 순간',
                    measure: feature.impact!,
                    unit: feature.unit),
              if (feature.impact != null && feature.rangeOfMotion != null)
                const SizedBox(width: 10),
              if (feature.rangeOfMotion != null)
                _MeasureBox(
                    label: '움직임 폭',
                    measure: feature.rangeOfMotion!,
                    unit: feature.unit),
            ],
          ),
          if (feature.description.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(feature.description,
                style: const TextStyle(
                    fontSize: 11.5, height: 1.4, color: AppColors.hint)),
          ],
        ],
      ),
    );
  }
}

/// 내 값 vs 기준 값 박스(임팩트 / 움직임 폭).
class _MeasureBox extends StatelessWidget {
  const _MeasureBox({
    required this.label,
    required this.measure,
    required this.unit,
  });

  final String label;
  final Measure measure;
  final String unit;

  @override
  Widget build(BuildContext context) {
    String fmt(double? v) => v == null ? '-' : '${v.toStringAsFixed(1)}$_u';
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
        decoration: BoxDecoration(
          color: const Color(0xFFF7F7F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(fontSize: 11, color: AppColors.hint)),
            const SizedBox(height: 6),
            Text('내 ${fmt(measure.user)}',
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700)),
            Text('기준 ${fmt(measure.reference)}',
                style: const TextStyle(fontSize: 12, color: AppColors.subtitle)),
          ],
        ),
      ),
    );
  }

  /// 각도는 °, 그 외 단위는 그대로 붙인다.
  String get _u => unit == 'deg' ? '°' : '';
}

// ---------------------------------------------------------------------------
// AI 코치의 피드백 카드
// ---------------------------------------------------------------------------
class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.part});

  final PartAnalysis part;

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(part.status);
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
          Text(part.coachComment,
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
                    Text(part.pointsTitle,
                        style: TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w700,
                            color: style.color)),
                  ],
                ),
                const SizedBox(height: 8),
                for (final p in part.points)
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
// 인체 그림 Painter
// ---------------------------------------------------------------------------
class _BodyFigurePainter extends CustomPainter {
  _BodyFigurePainter({
    required this.regionColors,
    required this.selectedRegion,
  });

  /// 'leftArm','rightArm','torso','leftLeg','rightLeg' → 색.
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

    // 몸통(어깨선·척추·골반선)은 하나의 영역으로 같은 색을 쓴다.
    final torsoColor = _c('torso');
    limb.strokeWidth = w * 0.09;
    limb.color = torsoColor;
    canvas.drawLine(Offset(cx, h * 0.27), Offset(cx, h * 0.50), limb);
    limb.strokeWidth = w * 0.085;
    canvas.drawLine(
        Offset(cx - w * 0.13, h * 0.25), Offset(cx + w * 0.13, h * 0.25), limb);
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
// 세부 항목 각도 시계열 Painter (내 스윙 vs 기준 ±편차)
// ---------------------------------------------------------------------------
class _FeatureChartPainter extends CustomPainter {
  _FeatureChartPainter({
    required this.series,
    required this.unit,
    required this.userColor,
  });

  final List<SeriesSample> series;
  final String unit;
  final Color userColor;

  static const _grid = Color(0xFFEDEDED);
  static const _axisText = Color(0xFF9E9E9E);
  static const _refColor = Color(0xFFBDBDBD);

  @override
  void paint(Canvas canvas, Size size) {
    if (series.length < 2) return;
    const leftPad = 32.0;
    const bottomPad = 26.0;
    const topPad = 8.0;
    const rightPad = 6.0;
    final plot = Rect.fromLTRB(
        leftPad, topPad, size.width - rightPad, size.height - bottomPad);

    // y 범위: user / reference / ±std 를 모두 담는다.
    double? lo, hi;
    void acc(double? v) {
      if (v == null) return;
      lo = (lo == null || v < lo!) ? v : lo;
      hi = (hi == null || v > hi!) ? v : hi;
    }

    for (final s in series) {
      acc(s.user);
      acc(s.reference);
      if (s.reference != null && s.referenceStd != null) {
        acc(s.reference! + s.referenceStd!);
        acc(s.reference! - s.referenceStd!);
      }
    }
    lo ??= 0;
    hi ??= 1;
    if ((hi! - lo!).abs() < 1e-6) hi = lo! + 1;
    final margin = (hi! - lo!) * 0.12;
    lo = lo! - margin;
    hi = hi! + margin;

    double yOf(double v) => plot.bottom - (v - lo!) / (hi! - lo!) * plot.height;
    double xOf(int i) => plot.left + plot.width * (i / (series.length - 1));

    // 가로 눈금선 + y 라벨 (최소 / 중간 / 최대)
    final gridPaint = Paint()
      ..color = _grid
      ..strokeWidth = 1;
    for (var k = 0; k <= 2; k++) {
      final v = lo! + (hi! - lo!) * k / 2;
      final y = yOf(v);
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), gridPaint);
      _text(canvas, _fmtAxis(v), Offset(plot.left - 6, y),
          align: _Align.right, color: _axisText);
    }

    // 구간(4개) 경계선 + 라벨
    final seg = series.length ~/ SwingPhase.values.length;
    if (seg > 0) {
      for (var s = 0; s < SwingPhase.values.length; s++) {
        final centerIdx = (s * seg + seg ~/ 2).clamp(0, series.length - 1);
        final x = xOf(centerIdx);
        _text(canvas, SwingPhase.values[s].en, Offset(x, plot.bottom + 4),
            align: _Align.center, color: _axisText, size: 7.5);
        _text(canvas, SwingPhase.values[s].ko, Offset(x, plot.bottom + 14),
            align: _Align.center, color: _axisText, size: 7.5);
        if (s > 0) {
          final bx = xOf((s * seg).clamp(0, series.length - 1));
          canvas.drawLine(
              Offset(bx, plot.top), Offset(bx, plot.bottom), gridPaint);
        }
      }
    }

    // 기준 ±편차 밴드 (reference 가 모두 있을 때만)
    final allRef = series.every((s) => s.reference != null);
    if (allRef) {
      final band = Path();
      for (var i = 0; i < series.length; i++) {
        final r = series[i].reference!;
        final sd = series[i].referenceStd ?? 0;
        final p = Offset(xOf(i), yOf(r + sd));
        i == 0 ? band.moveTo(p.dx, p.dy) : band.lineTo(p.dx, p.dy);
      }
      for (var i = series.length - 1; i >= 0; i--) {
        final r = series[i].reference!;
        final sd = series[i].referenceStd ?? 0;
        band.lineTo(xOf(i), yOf(r - sd));
      }
      band.close();
      canvas.drawPath(
          band,
          Paint()
            ..color = _refColor.withValues(alpha: 0.18)
            ..style = PaintingStyle.fill);
    }

    // 기준 선 → 내 스윙 선 순서로.
    _drawCurve(canvas, [for (final s in series) s.reference], _refColor, xOf,
        yOf, width: 1.6);
    _drawCurve(canvas, [for (final s in series) s.user], userColor, xOf, yOf,
        width: 2.2);
  }

  /// null 지점에서는 선을 끊어 그린다(영상에 없는 구간).
  void _drawCurve(Canvas canvas, List<double?> ys, Color color,
      double Function(int) xOf, double Function(double) yOf,
      {required double width}) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = width
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    Path? path;
    for (var i = 0; i < ys.length; i++) {
      final v = ys[i];
      if (v == null) {
        if (path != null) {
          canvas.drawPath(path, paint);
          path = null;
        }
        continue;
      }
      final p = Offset(xOf(i), yOf(v));
      if (path == null) {
        path = Path()..moveTo(p.dx, p.dy);
      } else {
        path.lineTo(p.dx, p.dy);
      }
    }
    if (path != null) canvas.drawPath(path, paint);
  }

  String _fmtAxis(double v) =>
      unit == 'deg' ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

  void _text(Canvas canvas, String s, Offset at,
      {required _Align align, required Color color, double size = 10}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(color: color, fontSize: size)),
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
  bool shouldRepaint(_FeatureChartPainter old) =>
      old.series != series ||
      old.unit != unit ||
      old.userColor != userColor;
}

// ---------------------------------------------------------------------------
// 스윙 단계별 점수 꺾은선 Painter (4구간 × 0~100 점수)
// ---------------------------------------------------------------------------
class _PhaseScoreChartPainter extends CustomPainter {
  _PhaseScoreChartPainter({required this.scores, required this.color});

  /// SwingPhase 순서(4개)의 0~100 점수.
  final List<int> scores;
  final Color color;

  static const _grid = Color(0xFFEDEDED);
  static const _axisText = Color(0xFF9E9E9E);

  @override
  void paint(Canvas canvas, Size size) {
    if (scores.length < 2) return;
    const leftPad = 26.0;
    const bottomPad = 26.0;
    const topPad = 6.0;
    final plot =
        Rect.fromLTRB(leftPad, topPad, size.width, size.height - bottomPad);

    double yOf(num s) =>
        plot.bottom - (s.clamp(0, 100) / 100) * plot.height;
    double xOf(int i) => plot.left + plot.width * (i / (scores.length - 1));

    final gridPaint = Paint()
      ..color = _grid
      ..strokeWidth = 1;

    // 가로 눈금 + y 라벨 (0 / 50 / 100)
    for (final v in [0, 50, 100]) {
      final y = yOf(v);
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), gridPaint);
      _text(canvas, '$v', Offset(plot.left - 6, y),
          align: _Align.right, color: _axisText);
    }

    // x 라벨(영문 + 국문)
    for (var i = 0; i < SwingPhase.values.length && i < scores.length; i++) {
      final phase = SwingPhase.values[i];
      final x = xOf(i);
      _text(canvas, phase.en, Offset(x, plot.bottom + 4),
          align: _Align.center, color: _axisText, size: 7.5);
      _text(canvas, phase.ko, Offset(x, plot.bottom + 14),
          align: _Align.center, color: _axisText, size: 7.5);
    }

    // 점수 선 + 점
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
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    canvas.drawPath(path, linePaint);
    for (var i = 0; i < scores.length; i++) {
      canvas.drawCircle(Offset(xOf(i), yOf(scores[i])), 2.6, dotPaint);
    }
  }

  void _text(Canvas canvas, String s, Offset at,
      {required _Align align, required Color color, double size = 10}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(color: color, fontSize: size)),
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
    final dy = align == _Align.right ? at.dy - tp.height / 2 : at.dy;
    tp.paint(canvas, Offset(dx, dy));
  }

  @override
  bool shouldRepaint(_PhaseScoreChartPainter old) =>
      old.scores != scores || old.color != color;
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

/// 기준 대비 방향 → 사람이 읽는 문구.
String _directionText(String direction) {
  switch (direction) {
    case 'higher':
      return '기준보다 높은 편이에요.';
    case 'lower':
      return '기준보다 낮은 편이에요.';
    default:
      return '기준과 비슷해요.';
  }
}

/// 세부 항목 level(양호/주의/개선 필요) 스타일.
class _FeatureStyle {
  const _FeatureStyle(
      {required this.color, required this.soft, required this.label});
  final Color color;
  final Color soft;
  final String label;
}

_FeatureStyle _featureStyle(String level) {
  switch (level) {
    case 'warning':
      return const _FeatureStyle(
          color: AppColors.primary, soft: Color(0xFFFDECEC), label: '개선 필요');
    case 'caution':
      return const _FeatureStyle(
          color: Color(0xFFD9892B), soft: Color(0xFFFBF0DE), label: '주의');
    default:
      return const _FeatureStyle(
          color: Color(0xFF2E9E5B), soft: Color(0xFFE7F5EC), label: '양호');
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
