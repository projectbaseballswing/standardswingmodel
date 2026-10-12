import 'package:flutter/material.dart';

import '../models/feedback.dart';
import '../theme/app_theme.dart';
import '../widgets/feedback_metrics.dart';

/// 구간별 피드백 화면.
///
/// 종합 피드백에서 "구간별 피드백 보기" 를 누르면 들어온다.
/// 관절별 분석이 "어느 부위" 라면, 이 화면은 "스윙의 어느 타이밍(구간)" 이
/// 어떻게 측정했는지 보여준다. 들어오면 첫 구간이 기본 선택되고, 구간 카드를
/// 누르면 그 구간의 상세가 아래에 나온다.
///
/// 새 업로드와 과거 기록 모두 서버 구간 점수를 사용한다. 이전 비교는 만들지 않는다.
/// 포즈 이미지는 서버가 제공하지 않아 기존 자리표시자를 유지한다.
class PhaseFeedbackScreen extends StatefulWidget {
  const PhaseFeedbackScreen({super.key, required this.feedback});

  /// 종합 피드백. 이 값을 구간별로 펼쳐서 보여준다.
  final OverallFeedback feedback;

  @override
  State<PhaseFeedbackScreen> createState() => _PhaseFeedbackScreenState();
}

class _PhaseFeedbackScreenState extends State<PhaseFeedbackScreen> {
  List<AnalysisPhase> get _phases => widget.feedback.phases;
  String? _selectedKey;
  int get _selected {
    final index = _phases.indexWhere((p) => p.key == _selectedKey);
    return index < 0 ? 0 : index;
  }

  void _select(int index) => setState(() => _selectedKey = _phases[index].key);

  @override
  Widget build(BuildContext context) {
    final hasPhases = _phases.isNotEmpty;
    return Scaffold(
      backgroundColor: const Color(0xFFF7F7F7),
      appBar: AppBar(
        backgroundColor: const Color(0xFFF7F7F7),
        surfaceTintColor: const Color(0xFFF7F7F7),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
          onPressed: () => Navigator.of(context).maybePop(),
        ),
        title: const Text('구간별 피드백'),
      ),
      body: !hasPhases
          ? const Center(child: Text('분석할 구간 정보가 없어요.'))
          : ListView(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
              children: [
                const Text(
                  '각 스윙 구간의 점수를 확인해보세요.',
                  style: TextStyle(fontSize: 13, color: AppColors.hint),
                ),
                const SizedBox(height: 14),
                _OverallScoreCard(feedback: widget.feedback),
                const SizedBox(height: 14),
                _PhaseStepper(
                  phases: _phases,
                  selected: _selected,
                  onSelect: _select,
                ),
                const SizedBox(height: 14),
                _PhaseGrid(
                  phases: _phases,
                  selected: _selected,
                  onSelect: _select,
                ),
                const SizedBox(height: 14),
                _PhaseDetailCard(
                  key: ValueKey('phase-detail-${_phases[_selected].key}'),
                  phase: _phases[_selected],
                  number: _selected + 1,
                ),
                if (widget.feedback.events.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  SwingEventsCard(events: widget.feedback.events),
                ],
              ],
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// 서버가 제공한 전체 스윙 점수 카드 (구간 점수를 평균 내지 않는다)
// ---------------------------------------------------------------------------
class _OverallScoreCard extends StatelessWidget {
  const _OverallScoreCard({required this.feedback});

  final OverallFeedback feedback;

  @override
  Widget build(BuildContext context) {
    final measured = feedback.phases
        .where((p) => p.available && p.score != null)
        .length;

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '전체 스윙 점수',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            feedbackNumber(
                              feedback.available ? feedback.totalScore : null,
                            ),
                            style: const TextStyle(
                              fontSize: 44,
                              height: 1.0,
                              fontWeight: FontWeight.w800,
                              color: AppColors.primary,
                            ),
                          ),
                          const Padding(
                            padding: EdgeInsets.only(bottom: 6, left: 2),
                            child: Text(
                              '/ 100',
                              style: TextStyle(
                                fontSize: 14,
                                color: AppColors.hint,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      reliabilityLabel(feedback.reliability),
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.hint,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 6,
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFDECEC),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '점수 제공 구간 $measured / ${feedback.phases.length}\n'
                    '구간을 선택해 실제 점수와 소요 시간을 확인하세요.',
                    style: const TextStyle(
                      fontSize: 12.5,
                      height: 1.4,
                      color: Color(0xFFC0514F),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 구간 스텝퍼 (번호 + 연결선)
// ---------------------------------------------------------------------------
class _PhaseStepper extends StatelessWidget {
  const _PhaseStepper({
    required this.phases,
    required this.selected,
    required this.onSelect,
  });

  final List<AnalysisPhase> phases;
  final int selected;
  final ValueChanged<int> onSelect;

  static const _circle = 28.0;

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: LayoutBuilder(
        builder: (context, c) {
          final nodeW = c.maxWidth / phases.length;
          final inset = nodeW / 2;
          return SizedBox(
            height: 62,
            child: Stack(
              children: [
                // 노드 중심을 잇는 연결선.
                Positioned(
                  left: inset,
                  right: inset,
                  top: _circle / 2 - 1,
                  child: Container(height: 2, color: const Color(0xFFE6E6E6)),
                ),
                Row(
                  children: [
                    for (var i = 0; i < phases.length; i++)
                      SizedBox(
                        width: nodeW,
                        child: _StepNode(
                          key: ValueKey('phase-step-${phases[i].key}'),
                          phase: phases[i],
                          number: i + 1,
                          selected: selected == i,
                          onTap: () => onSelect(i),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _StepNode extends StatelessWidget {
  const _StepNode({
    super.key,
    required this.phase,
    required this.number,
    required this.selected,
    required this.onTap,
  });

  final AnalysisPhase phase;
  final int number;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = _accentColor(phase);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Column(
        children: [
          Container(
            width: _PhaseStepper._circle,
            height: _PhaseStepper._circle,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              border: selected
                  ? Border.all(color: AppColors.primary, width: 2.5)
                  : null,
            ),
            child: Text(
              '$number',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            phase.name,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 9,
              height: 1.1,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              color: selected ? AppColors.primary : AppColors.hint,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 구간 카드 그리드 (2열)
// ---------------------------------------------------------------------------
class _PhaseGrid extends StatelessWidget {
  const _PhaseGrid({
    required this.phases,
    required this.selected,
    required this.onSelect,
  });

  final List<AnalysisPhase> phases;
  final int selected;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < phases.length; i += 2) {
      rows.add(
        IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: _PhaseCard(
                  key: ValueKey('phase-card-${phases[i].key}'),
                  phase: phases[i],
                  number: i + 1,
                  selected: selected == i,
                  onTap: () => onSelect(i),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: i + 1 < phases.length
                    ? _PhaseCard(
                        key: ValueKey('phase-card-${phases[i + 1].key}'),
                        phase: phases[i + 1],
                        number: i + 2,
                        selected: selected == i + 1,
                        onTap: () => onSelect(i + 1),
                      )
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      );
      if (i + 2 < phases.length) rows.add(const SizedBox(height: 12));
    }
    return Column(children: rows);
  }
}

class _PhaseCard extends StatelessWidget {
  const _PhaseCard({
    super.key,
    required this.phase,
    required this.number,
    required this.selected,
    required this.onTap,
  });

  final AnalysisPhase phase;
  final int number;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final accent = _accentColor(phase);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFFFEF4F4) : Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: selected ? AppColors.primary : const Color(0xFFEDEDED),
            width: selected ? 1.6 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 번호 + 구간명
            Row(
              children: [
                _NumberBadge(number: number, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    phase.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // 포즈 자리표시자 + 실제 구간 점수
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const _PosePlaceholder(width: 46, height: 58),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(
                          _scoreText(phase),
                          style: const TextStyle(
                            fontSize: 30,
                            height: 1.0,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              _statusText(phase),
              style: const TextStyle(
                fontSize: 11.5,
                height: 1.35,
                color: AppColors.hint,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 선택 구간 상세 카드
// ---------------------------------------------------------------------------
class _PhaseDetailCard extends StatelessWidget {
  const _PhaseDetailCard({
    super.key,
    required this.phase,
    required this.number,
  });

  final AnalysisPhase phase;
  final int number;

  @override
  Widget build(BuildContext context) {
    final accent = _accentColor(phase);
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더: 번호 + "구간 분석" + 수준 배지
          Row(
            children: [
              _NumberBadge(number: number, color: accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${phase.name} 구간 분석',
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              _MeasurementBadge(phase: phase),
            ],
          ),
          const SizedBox(height: 14),
          // 포즈 자리표시자 + 점수
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const _PosePlaceholder(width: 92, height: 116, label: '현재 스윙'),
              const SizedBox(width: 16),
              Expanded(child: _ScoreBlock(phase: phase)),
            ],
          ),
          const SizedBox(height: 14),
          PhaseMetrics(phase: phase),
          const SizedBox(height: 14),
          _TipBox(
            tip: !phase.available
                ? '분석되지 않은 구간의 자세는 판정하지 않습니다.'
                : phase.reliability == 'low'
                ? '검출 신뢰도가 낮습니다. 측정값은 참고용으로 확인하세요.'
                : '구간 점수와 소요 시간은 서로 다른 지표입니다. 템포 판정이 보류된 구간은 수치만 참고하세요.',
          ),
        ],
      ),
    );
  }
}

/// 실제 서버 구간 점수. 비교 데이터가 없으므로 이전 점수나 증감을 만들지 않는다.
class _ScoreBlock extends StatelessWidget {
  const _ScoreBlock({required this.phase});
  final AnalysisPhase phase;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Text(
          _scoreText(phase),
          style: const TextStyle(
            fontSize: 40,
            height: 1.0,
            fontWeight: FontWeight.w800,
            color: AppColors.primary,
          ),
        ),
      ),
      const SizedBox(height: 4),
      const Text(
        '구간 점수',
        style: TextStyle(fontSize: 12, color: AppColors.hint),
      ),
    ],
  );
}

// ---------------------------------------------------------------------------
// 코칭 팁 박스
// ---------------------------------------------------------------------------
class _TipBox extends StatelessWidget {
  const _TipBox({required this.tip});

  final String tip;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFEF6EC),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Text('💡', style: TextStyle(fontSize: 14)),
              SizedBox(width: 6),
              Text(
                '확인 안내',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            tip,
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.5,
              color: AppColors.subtitle,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 공통 위젯
// ---------------------------------------------------------------------------

/// 번호 동그라미 배지.
class _NumberBadge extends StatelessWidget {
  const _NumberBadge({required this.number, required this.color});

  final int number;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 24,
      height: 24,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      child: Text(
        '$number',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// 점수의 좋고 나쁨 대신 실제 측정 상태를 표시한다.
class _MeasurementBadge extends StatelessWidget {
  const _MeasurementBadge({required this.phase});

  final AnalysisPhase phase;

  @override
  Widget build(BuildContext context) {
    final color = _accentColor(phase);
    final soft = color == AppColors.hint
        ? const Color(0xFFF4F4F4)
        : const Color(0xFFE7F5EC);
    final text = _statusText(phase);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: soft,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

/// 포즈 이미지 자리표시자(회색 박스 + 사람 아이콘). 하단에 라벨 칩(선택).
///
/// TODO(backend): 포즈 오버레이 이미지가 생기면 교체.
class _PosePlaceholder extends StatelessWidget {
  const _PosePlaceholder({
    required this.width,
    required this.height,
    this.label,
  });

  final double width;
  final double height;
  final String? label;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Container(
        width: width,
        height: height,
        color: const Color(0xFFE9E9E9),
        alignment: Alignment.center,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Icon(
              Icons.sports_baseball,
              size: width * 0.42,
              color: Colors.grey.shade400,
            ),
            if (label != null)
              Positioned(
                bottom: 6,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    label!,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 흰 배경 둥근 카드.
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

/// 기존 색상은 측정 상태를 구분한다. 임의의 점수 기준이나 비교 증감으로 평가하지 않는다.
Color _accentColor(AnalysisPhase p) =>
    !p.available ||
        p.score == null ||
        !const ['high', 'medium'].contains(p.reliability)
    ? AppColors.hint
    : const Color(0xFF2E9E5B);

String _scoreText(AnalysisPhase p) =>
    feedbackNumber(p.available ? p.score : null);

String _statusText(AnalysisPhase p) => !p.available
    ? '분석 불가'
    : p.score == null
    ? '점수 미제공'
    : p.reliability == 'low'
    ? '참고용'
    : const ['high', 'medium'].contains(p.reliability)
    ? '측정 완료'
    : '신뢰도 미제공';
