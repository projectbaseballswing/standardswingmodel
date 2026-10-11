import 'package:flutter/material.dart';

import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 구간별 피드백 화면.
///
/// 종합 피드백에서 "구간별 피드백 보기" 를 누르면 들어온다.
/// 관절별 분석이 "어느 부위" 라면, 이 화면은 "스윙의 어느 타이밍(구간)" 이
/// 좋고 나쁜지를 보여준다. 들어오면 1번 구간이 기본 선택되고, 구간 카드를
/// 누르면 그 구간의 상세가 아래에 나온다.
///
/// 첫 피드백은 비교 없이 현재 점수만, 반복 피드백은 이전 대비 증감을 함께
/// 보여준다(이전 스윙·포즈 이미지는 아직 백엔드 전이라 샘플/자리표시자).
class PhaseFeedbackScreen extends StatefulWidget {
  const PhaseFeedbackScreen({super.key, required this.feedback});

  /// 종합 피드백. 이 값을 구간별로 펼쳐서 보여준다.
  final OverallFeedback feedback;

  @override
  State<PhaseFeedbackScreen> createState() => _PhaseFeedbackScreenState();
}

class _PhaseFeedbackScreenState extends State<PhaseFeedbackScreen> {
  late final List<PhaseAnalysis> _phases;
  int _selected = 0; // 처음엔 1번 구간 고정.

  @override
  void initState() {
    super.initState();
    _phases = FeedbackRepository().buildPhaseAnalyses(widget.feedback);
  }

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
                _AverageScoreCard(phases: _phases),
                const SizedBox(height: 14),
                _PhaseStepper(
                  phases: _phases,
                  selected: _selected,
                  onSelect: (i) => setState(() => _selected = i),
                ),
                const SizedBox(height: 14),
                _PhaseGrid(
                  phases: _phases,
                  selected: _selected,
                  onSelect: (i) => setState(() => _selected = i),
                ),
                const SizedBox(height: 14),
                _PhaseDetailCard(phase: _phases[_selected]),
              ],
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// 전체 평균 점수 카드
// ---------------------------------------------------------------------------
class _AverageScoreCard extends StatelessWidget {
  const _AverageScoreCard({required this.phases});

  final List<PhaseAnalysis> phases;

  @override
  Widget build(BuildContext context) {
    final avg = _avg(phases.map((p) => p.score));
    // 반복 피드백이면(이전 점수가 다 있으면) 평균 증감을 보여준다.
    final hasPrev = phases.every((p) => p.previousScore != null);
    final prevAvg = hasPrev ? _avg(phases.map((p) => p.previousScore!)) : null;
    final delta = prevAvg == null ? null : avg - prevAvg;

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('전체 평균 점수',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text('$avg',
                            style: const TextStyle(
                                fontSize: 44,
                                height: 1.0,
                                fontWeight: FontWeight.w800,
                                color: AppColors.primary)),
                        const Padding(
                          padding: EdgeInsets.only(bottom: 6, left: 2),
                          child: Text('/ 100',
                              style: TextStyle(
                                  fontSize: 14, color: AppColors.hint)),
                        ),
                      ],
                    ),
                    if (delta != null) ...[
                      const SizedBox(height: 6),
                      _DeltaText(delta: delta, suffix: ' 이전 스윙 대비'),
                    ],
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
                    _summary(phases, avg, delta),
                    style: const TextStyle(
                        fontSize: 12.5, height: 1.4, color: Color(0xFFC0514F)),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  int _avg(Iterable<int> xs) {
    final l = xs.toList();
    if (l.isEmpty) return 0;
    return (l.reduce((a, b) => a + b) / l.length).round();
  }

  String _summary(List<PhaseAnalysis> phases, int avg, int? delta) {
    final worst = phases.reduce((a, b) => a.score <= b.score ? a : b);
    if (delta != null) {
      final dir = delta > 0 ? '소폭 올랐어요' : (delta < 0 ? '소폭 하락했어요' : '비슷해요');
      return '지난 스윙보다 전체 점수가 $dir.\n특히 ${worst.phase.ko} 구간을 더 살펴보세요.';
    }
    return '프로 기준과 비교한 구간별 점수예요.\n특히 ${worst.phase.ko} 구간을 더 살펴보면 좋아요.';
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

  final List<PhaseAnalysis> phases;
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
                          phase: phases[i],
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
    required this.phase,
    required this.selected,
    required this.onTap,
  });

  final PhaseAnalysis phase;
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
            child: Text('${phase.number}',
                style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w700)),
          ),
          const SizedBox(height: 4),
          Text(
            phase.phase.en,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                fontSize: 9,
                height: 1.1,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                color: selected ? AppColors.primary : AppColors.hint),
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

  final List<PhaseAnalysis> phases;
  final int selected;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < phases.length; i += 2) {
      rows.add(IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: _PhaseCard(
                phase: phases[i],
                selected: selected == i,
                onTap: () => onSelect(i),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: i + 1 < phases.length
                  ? _PhaseCard(
                      phase: phases[i + 1],
                      selected: selected == i + 1,
                      onTap: () => onSelect(i + 1),
                    )
                  : const SizedBox.shrink(),
            ),
          ],
        ),
      ));
      if (i + 2 < phases.length) rows.add(const SizedBox(height: 12));
    }
    return Column(children: rows);
  }
}

class _PhaseCard extends StatelessWidget {
  const _PhaseCard({
    required this.phase,
    required this.selected,
    required this.onTap,
  });

  final PhaseAnalysis phase;
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
                _NumberBadge(number: phase.number, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(phase.phase.en,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 13.5, fontWeight: FontWeight.w700)),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // 포즈 자리표시자 + 점수/증감
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const _PosePlaceholder(width: 46, height: 58),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${phase.score}',
                          style: const TextStyle(
                              fontSize: 30,
                              height: 1.0,
                              fontWeight: FontWeight.w800)),
                      if (phase.delta != null) ...[
                        const SizedBox(height: 4),
                        _DeltaText(delta: phase.delta!),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(phase.shortComment,
                style: const TextStyle(
                    fontSize: 11.5, height: 1.35, color: AppColors.hint)),
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
  const _PhaseDetailCard({required this.phase});

  final PhaseAnalysis phase;

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
              _NumberBadge(number: phase.number, color: accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text('${phase.phase.en} 구간 분석',
                    style: const TextStyle(
                        fontSize: 15, fontWeight: FontWeight.w700)),
              ),
              _LevelBadge(needWork: phase.needWork),
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
          Text(phase.detailComment,
              style: const TextStyle(
                  fontSize: 12.5, height: 1.5, color: AppColors.subtitle)),
          const SizedBox(height: 14),
          _TipBox(tip: phase.tip),
        ],
      ),
    );
  }
}

/// 상세 점수 블록. 반복이면 이전→현재, 첫 피드백이면 현재만.
class _ScoreBlock extends StatelessWidget {
  const _ScoreBlock({required this.phase});

  final PhaseAnalysis phase;

  @override
  Widget build(BuildContext context) {
    final prev = phase.previousScore;
    if (prev == null) {
      // 첫 피드백: 현재 점수만.
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${phase.score}',
              style: const TextStyle(
                  fontSize: 40,
                  height: 1.0,
                  fontWeight: FontWeight.w800,
                  color: AppColors.primary)),
          const SizedBox(height: 4),
          const Text('현재 점수',
              style: TextStyle(fontSize: 12, color: AppColors.hint)),
        ],
      );
    }
    // 반복 피드백: 이전 → 현재 (+증감).
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text('$prev',
                style: const TextStyle(
                    fontSize: 20, fontWeight: FontWeight.w700)),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 6),
              child: Icon(Icons.arrow_forward, size: 16, color: AppColors.hint),
            ),
            Text('${phase.score}',
                style: const TextStyle(
                    fontSize: 34,
                    height: 1.0,
                    fontWeight: FontWeight.w800,
                    color: AppColors.primary)),
            const SizedBox(width: 6),
            _DeltaText(delta: phase.delta!),
          ],
        ),
        const SizedBox(height: 4),
        const Text('이전 점수      현재 점수',
            style: TextStyle(fontSize: 11, color: AppColors.hint)),
      ],
    );
  }
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
              Text('코칭 팁',
                  style:
                      TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 8),
          Text(tip,
              style: const TextStyle(
                  fontSize: 12.5, height: 1.5, color: AppColors.subtitle)),
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
      child: Text('$number',
          style: const TextStyle(
              color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}

/// 수준 배지. 개선 필요(빨강) / 안정적(초록).
class _LevelBadge extends StatelessWidget {
  const _LevelBadge({required this.needWork});

  final bool needWork;

  @override
  Widget build(BuildContext context) {
    final color = needWork ? AppColors.primary : const Color(0xFF2E9E5B);
    final soft = needWork ? const Color(0xFFFDECEC) : const Color(0xFFE7F5EC);
    final text = needWork ? '주요 개선 필요' : '안정적';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: soft,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(text,
          style: TextStyle(
              fontSize: 11, fontWeight: FontWeight.w700, color: color)),
    );
  }
}

/// 증감 텍스트. ▲+5(초록) / ▼5(빨강) / – 0(회색). 뒤에 [suffix] 를 붙일 수 있다.
class _DeltaText extends StatelessWidget {
  const _DeltaText({required this.delta, this.suffix});

  final int delta;
  final String? suffix;

  @override
  Widget build(BuildContext context) {
    final Color color;
    final String mark;
    if (delta > 0) {
      color = const Color(0xFF2E9E5B);
      mark = '▲ $delta';
    } else if (delta < 0) {
      color = AppColors.primary;
      mark = '▼ ${delta.abs()}';
    } else {
      color = AppColors.hint;
      mark = '– 0';
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(mark,
            style: TextStyle(
                fontSize: 13, fontWeight: FontWeight.w700, color: color)),
        if (suffix != null)
          Text(suffix!,
              style: const TextStyle(fontSize: 11, color: AppColors.hint)),
      ],
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
            Icon(Icons.sports_baseball,
                size: width * 0.42, color: Colors.grey.shade400),
            if (label != null)
              Positioned(
                bottom: 6,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(label!,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 9,
                          fontWeight: FontWeight.w700)),
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

/// 구간 상태 대표색.
///  - 반복 피드백(증감 있음): ▲초록 / ▼빨강 / –회색
///  - 첫 피드백: good 초록 / 개선 필요 빨강
Color _accentColor(PhaseAnalysis p) {
  final d = p.delta;
  if (d != null) {
    if (d > 2) return const Color(0xFF2E9E5B);
    if (d < -2) return AppColors.primary;
    return AppColors.hint;
  }
  return p.level == 'good' ? const Color(0xFF2E9E5B) : AppColors.primary;
}
