import 'package:flutter/material.dart';

import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../models/swing_timeline.dart';
import '../theme/app_theme.dart';
import '../widgets/body_part_art.dart';
import '../widgets/coaching_pending_note.dart';
import '../widgets/swing_video.dart';

/// 관절별 분석(상세 피드백) 화면.
///
/// 종합 피드백에서 "상세 피드백 보기" 를 누르면 들어온다.
/// 위쪽 인체 그림에서 부위(앞팔/뒷팔/몸통/앞다리/뒷다리)를 고르면, 그 부위의
/// 점수·상태와 내 스윙 영상, 세부 항목(팔꿈치 각도, 손 높이 등)별 각도 그래프를
/// 보여준다. 그래프의 세로선을 움직이면 영상도 그 시점으로 이동한다.
class JointAnalysisScreen extends StatefulWidget {
  const JointAnalysisScreen({
    super.key,
    required this.feedback,
    this.videoBuilder,
  });

  /// 종합 피드백. 이 값을 부위별로 펼쳐서 보여준다.
  final OverallFeedback feedback;

  /// 테스트에서 영상 위젯을 바꿔 끼울 때 쓴다. 없으면 [SwingVideo].
  final Widget Function(SwingVideoSync sync)? videoBuilder;

  @override
  State<JointAnalysisScreen> createState() => _JointAnalysisScreenState();
}

class _JointAnalysisScreenState extends State<JointAnalysisScreen> {
  late final FeedbackRepository _repo;
  late OverallFeedback _feedback;
  late List<PartAnalysis> _parts;
  int _selected = 0;

  /// 영상 ↔ 그래프 세로선 재생 위치 연결.
  final _videoSync = SwingVideoSync();

  /// 스윙 이벤트로 만든 영상 시간축. 이벤트가 부족하면 null(연동 안 함).
  SwingTimeline? get _timeline => SwingTimeline.fromEvents(_feedback.events);

  bool get _coachingPending => _feedback.coaching?.isExtendedPending ?? false;

  bool _refreshing = false;

  @override
  void initState() {
    super.initState();
    _repo = FeedbackRepository();
    _feedback = widget.feedback;
    _parts = _repo.buildPartAnalyses(_feedback);
    // 처음 들어오면 목록 맨 위 부위를 보여준다. (선택하면 그 부위로 바뀐다)
    // 관절 코칭이 아직 생성 중(pending)이면, 완성될 때까지 조용히 재조회해 채운다.
    if (_coachingPending) _refreshWhilePending();
  }

  @override
  void didUpdateWidget(JointAnalysisScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.feedback, widget.feedback)) {
      setState(() {
        _feedback = widget.feedback;
        _parts = _repo.buildPartAnalyses(_feedback);
      });
      if (_coachingPending) _refreshWhilePending();
    }
  }

  /// 관절·구간 코칭이 'pending' 인 동안 주기적으로 재조회해 코멘트를 채운다.
  /// 완료/실패(또는 화면 이탈·최대 시도 초과)면 멈춘다. 종합은 이미 보이는 상태다.
  Future<void> _refreshWhilePending() async {
    if (_refreshing) return; // 폴링 루프 중복 실행 방지
    final id = _feedback.analysisId;
    if (id.isEmpty) return;
    _refreshing = true;
    try {
      for (
        var attempt = 0;
        attempt < 20 && mounted && _coachingPending;
        attempt++
      ) {
        await Future<void>.delayed(const Duration(seconds: 2));
        if (!mounted) break;
        try {
          final fresh = await _repo.fetchFeedback(
            id,
          ); // firstTime:false → 단발 조회
          if (!mounted) break;
          setState(() {
            _feedback = fresh;
            _parts = _repo.buildPartAnalyses(fresh);
          });
        } catch (_) {
          // 일시적 실패는 무시하고 다음 시도. 종합 표시에는 영향 없다.
        }
      }
    } finally {
      _refreshing = false;
    }
  }

  @override
  void dispose() {
    _videoSync.dispose();
    _repo.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hasParts = _parts.isNotEmpty;
    final timeline = _timeline;
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
          : CustomScrollView(
              slivers: [
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
                  sliver: SliverList(
                    delegate: SliverChildListDelegate([
                      const Text(
                        '부위를 선택하면 상세 분석 결과를 확인할 수 있습니다.',
                        style: TextStyle(fontSize: 13, color: AppColors.hint),
                      ),
                      if (_coachingPending) ...[
                        const SizedBox(height: 12),
                        const CoachingPendingNote(
                          text: '서버에서 관절별 코멘트를 준비하고 있어요…',
                        ),
                      ],
                      const SizedBox(height: 14),
                      _SelectorCard(
                        parts: _parts,
                        selected: _selected,
                        onSelect: (i) => setState(() => _selected = i),
                      ),
                      const SizedBox(height: 14),
                      _ScoreCard(part: _parts[_selected]),
                      const SizedBox(height: 8),
                    ]),
                  ),
                ),
                // 점수 아래 영상. 스크롤해 화면 위에 닿으면 그 자리에 고정되어
                // 아래 그래프를 보면서도 영상을 함께 확인할 수 있다.
                SliverPersistentHeader(
                  pinned: true,
                  delegate: _PinnedVideoDelegate(
                    child: _VideoCard(
                      videoStatus: _feedback.videoStatus,
                      synced: timeline != null,
                      child:
                          widget.videoBuilder?.call(_videoSync) ??
                          SwingVideo(
                            key: ValueKey(_feedback.analysisId),
                            analysisId: _feedback.analysisId,
                            api: _repo.api,
                            fit: BoxFit.contain,
                            preload: true,
                            sync: _videoSync,
                          ),
                    ),
                  ),
                ),
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                  sliver: SliverList(
                    delegate: SliverChildListDelegate([
                      if (_parts[_selected].features.isNotEmpty) ...[
                        _FeatureListCard(
                          part: _parts[_selected],
                          sync: _videoSync,
                          timeline: timeline,
                        ),
                        const SizedBox(height: 14),
                      ],
                      _CoachCard(part: _parts[_selected]),
                    ]),
                  ),
                ),
              ],
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// 고정 영상 (점수 아래, 스크롤 시 화면 위에 고정)
// ---------------------------------------------------------------------------
class _PinnedVideoDelegate extends SliverPersistentHeaderDelegate {
  _PinnedVideoDelegate({required this.child});

  final Widget child;

  static const double _extent = 236;

  @override
  double get minExtent => _extent;

  @override
  double get maxExtent => _extent;

  @override
  Widget build(
    BuildContext context,
    double shrinkOffset,
    bool overlapsContent,
  ) {
    // 뒤로 지나가는 카드가 비치지 않도록 화면 배경색으로 덮는다.
    return Container(
      color: const Color(0xFFF7F7F7),
      padding: const EdgeInsets.fromLTRB(20, 6, 20, 6),
      child: child,
    );
  }

  @override
  bool shouldRebuild(_PinnedVideoDelegate old) => old.child != child;
}

class _VideoCard extends StatelessWidget {
  const _VideoCard({
    required this.videoStatus,
    required this.synced,
    required this.child,
  });

  final String videoStatus;

  /// 그래프 세로선과 시점 연동이 가능한지.
  final bool synced;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final deleted = videoStatus == 'deleted' || videoStatus == 'deleting';
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                '내 스윙 영상',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  synced
                      ? '그래프의 세로선을 움직이면 그 시점으로 이동해요.'
                      : '이 기록은 그래프와 시점 연동을 지원하지 않아요.',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 11, color: AppColors.hint),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: deleted
                  ? ColoredBox(
                      color: const Color(0xFFE6E6E6),
                      child: Center(
                        child: Text(
                          videoStatus == 'deleted'
                              ? '원본 영상이 삭제되었습니다'
                              : '원본 영상 삭제가 진행 중입니다.',
                          style: const TextStyle(fontSize: 12),
                        ),
                      ),
                    )
                  : ColoredBox(color: Colors.black, child: child),
            ),
          ),
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
                width: 120,
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: const [
                        Text(
                          '왼쪽',
                          style: TextStyle(fontSize: 11, color: AppColors.hint),
                        ),
                        Text(
                          '오른쪽',
                          style: TextStyle(fontSize: 11, color: AppColors.hint),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    BodyMap(colors: _regionColors(parts)),
                  ],
                ),
              ),
              const SizedBox(width: 10),
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
  /// 0.1의 pose/velocity 그룹이나 좌우 정보 없는 팔·다리는 칠하지 않는다.
  static Map<BodyRegion, Color> _regionColors(List<PartAnalysis> parts) {
    final map = <BodyRegion, Color>{};
    for (final p in parts) {
      final region = _regionOf(p);
      if (region != null) map[region] = bodyToneColor(_bodyTone(p.status));
    }
    return map;
  }
}

BodyRegion? _regionOf(PartAnalysis p) =>
    bodyRegionOf(key: p.key, label: p.label, part: p.part);

BodyTone _bodyTone(JointStatus status) => switch (status) {
  JointStatus.improved || JointStatus.proGood => BodyTone.good,
  JointStatus.worsened || JointStatus.proBad => BodyTone.bad,
  JointStatus.unchanged || JointStatus.limited => BodyTone.neutral,
};

/// 목록의 부위 한 줄: 부위 아이콘 + 이름 + 점수 + 상태 배지 + 화살표.
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
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 11),
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
            BodyPartGlyph(
              part: part.part,
              region: _regionOf(part),
              color: bodyToneColor(_bodyTone(part.status)),
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
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
                        feedbackNumber(part.currentScore),
                        style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w800,
                          color: style.color,
                        ),
                      ),
                    ],
                  ),
                  Text(
                    style.badge,
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                      color: style.color,
                    ),
                  ),
                ],
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
        Text(
          label,
          style: const TextStyle(fontSize: 11, color: AppColors.hint),
        ),
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
              Text(
                '${part.label} 분석',
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
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
                      Text(
                        '비교 기간 선택',
                        style: TextStyle(fontSize: 12, color: AppColors.hint),
                      ),
                      Icon(
                        Icons.chevron_right,
                        size: 16,
                        color: AppColors.hint,
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          if (hasComparison)
            Row(
              children: [
                _StatBox(
                  label: '이전 점수',
                  value: part.previousScore?.toString() ?? '-',
                ),
                const SizedBox(width: 10),
                _StatBox(
                  label: '현재 점수',
                  value: feedbackNumber(part.currentScore),
                  valueColor: style.color,
                ),
                const SizedBox(width: 10),
                _StatBox(
                  label: '점수 변화',
                  child: delta == null
                      ? const Text(
                          '-',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w800,
                            color: AppColors.hint,
                          ),
                        )
                      : Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              delta > 0
                                  ? Icons.arrow_drop_up
                                  : (delta < 0
                                        ? Icons.arrow_drop_down
                                        : Icons.remove),
                              size: 18,
                              color: style.color,
                            ),
                            Text(
                              feedbackNumber(delta.abs()),
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                                color: style.color,
                              ),
                            ),
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
            const SizedBox(height: 6),
            _ReliabilityNote(reliability: part.reliability),
          ],
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
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
                      fontSize: 12.5,
                      height: 1.5,
                      color: style.textOnSoft,
                    ),
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
    final text = reliabilityLabel(reliability);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.info_outline, size: 14, color: AppColors.hint),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(fontSize: 11.5, color: AppColors.hint),
          ),
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
        padding: const EdgeInsets.symmetric(vertical: 7),
        decoration: BoxDecoration(
          color: const Color(0xFFF7F7F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: const TextStyle(fontSize: 11, color: AppColors.hint),
            ),
            const SizedBox(height: 2),
            child ??
                Text(
                  value ?? '-',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: valueColor ?? Colors.black87,
                  ),
                ),
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
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F7),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '현재 점수',
                    style: TextStyle(fontSize: 11, color: AppColors.hint),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Text(
                        feedbackNumber(part.currentScore),
                        style: TextStyle(
                          fontSize: 30,
                          height: 1.0,
                          fontWeight: FontWeight.w800,
                          color: style.color,
                        ),
                      ),
                      const Padding(
                        padding: EdgeInsets.only(left: 2),
                        child: Text(
                          '/ 100',
                          style: TextStyle(fontSize: 13, color: AppColors.hint),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 8),
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
                Text(
                  style.badge,
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: style.color,
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
// 세부 항목(피처) 목록 카드
// ---------------------------------------------------------------------------
/// 부위를 이루는 세부 항목들을 펼쳐, 각 항목이 기준과 어떻게 다른지 보여준다.
/// 항목을 누르면 스윙 전체 각도 그래프(내 스윙 vs 기준)가 열린다.
class _FeatureListCard extends StatefulWidget {
  const _FeatureListCard({
    required this.part,
    required this.sync,
    required this.timeline,
  });

  final PartAnalysis part;
  final SwingVideoSync sync;
  final SwingTimeline? timeline;

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
      final idx = features.indexWhere((f) => f.evidence?.isIssue == true);
      _expanded = idx >= 0 ? idx : null;
    }

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${widget.part.label} 세부 항목',
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          const Text(
            '항목을 누르면 스윙 전체 변화를 볼 수 있어요.',
            style: TextStyle(fontSize: 11.5, color: AppColors.hint),
          ),
          const SizedBox(height: 8),
          for (var i = 0; i < features.length; i++) ...[
            if (i > 0)
              const Divider(
                height: 1,
                thickness: 0.6,
                color: Color(0xFFEDEDED),
              ),
            _FeatureTile(
              feature: features[i],
              sync: widget.sync,
              timeline: widget.timeline,
              expanded: _expanded == i,
              onTap: () =>
                  setState(() => _expanded = _expanded == i ? null : i),
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
    required this.sync,
    required this.timeline,
    required this.expanded,
    required this.onTap,
  });

  final FeatureAnalysis feature;
  final SwingVideoSync sync;
  final SwingTimeline? timeline;
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
                      Text(
                        feature.name,
                        style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        feature.directionText != null
                            ? '${feature.directionText}.'
                            : _directionText(feature.direction),
                        style: const TextStyle(
                          fontSize: 11.5,
                          color: AppColors.hint,
                        ),
                      ),
                    ],
                  ),
                ),
                // level 배지
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: fstyle.soft,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    fstyle.label,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: fstyle.color,
                    ),
                  ),
                ),
                Icon(
                  expanded ? Icons.expand_less : Icons.expand_more,
                  size: 18,
                  color: AppColors.hint,
                ),
              ],
            ),
          ),
        ),
        if (expanded)
          _FeatureDetail(feature: feature, sync: sync, timeline: timeline),
      ],
    );
  }
}

/// 펼쳤을 때: 각도 그래프 + 임팩트/움직임 폭 수치.
class _FeatureDetail extends StatelessWidget {
  const _FeatureDetail({
    required this.feature,
    required this.sync,
    required this.timeline,
  });

  final FeatureAnalysis feature;
  final SwingVideoSync sync;
  final SwingTimeline? timeline;

  @override
  Widget build(BuildContext context) {
    final series = feature.series;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ① 스윙 단계별 실제 값 변화 (내 스윙 vs 기준 ±편차)
          Text(
            reliabilityLabel(feature.reliability),
            style: const TextStyle(fontSize: 11, color: AppColors.hint),
          ),
          if (series != null && series.isNotEmpty) ...[
            Text(
              '스윙 단계별 ${feature.unit == 'deg' ? '각도' : '위치'} 변화',
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            _SyncedSeriesChart(
              feature: feature,
              series: series,
              sync: sync,
              // 0.2 구간 시계열만 영상 시간축으로 옮길 수 있다.
              clock: feature.eventBasedSeries
                  ? timeline?.clockFor(series.length)
                  : null,
            ),
            const SizedBox(height: 14),
          ],
          // LLM 관절 코멘트(scope='full' 일 때만). 없으면 표시하지 않는다.
          // 임팩트 순간·움직임 폭은 숫자 카드 대신 이 코멘트가 말로 설명한다.
          if (feature.displayedComment.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              feature.commentSource,
              style: const TextStyle(fontSize: 11, color: AppColors.hint),
            ),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF3F0FB),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.auto_awesome,
                    size: 15,
                    color: Color(0xFF8A6BEA),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      feature.displayedComment,
                      style: const TextStyle(
                        fontSize: 12.5,
                        height: 1.5,
                        color: AppColors.subtitle,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
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
              Text(
                '분석 근거 안내 · 규칙 기반',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            part.coachComment,
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.5,
              color: AppColors.subtitle,
            ),
          ),
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
                    Expanded(
                      child: Text(
                        '${part.pointsTitle}\n${part.pointsSource}',
                        style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w700,
                          color: style.color,
                        ),
                      ),
                    ),
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
                              color: style.color,
                              shape: BoxShape.circle,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Text(
                            p,
                            style: TextStyle(
                              fontSize: 12.5,
                              height: 1.4,
                              color: style.textOnSoft,
                            ),
                          ),
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
// 영상과 연동되는 각도 그래프 (세로선 드래그 ↔ 영상 시점)
// ---------------------------------------------------------------------------
class _SyncedSeriesChart extends StatefulWidget {
  const _SyncedSeriesChart({
    required this.feature,
    required this.series,
    required this.sync,
    required this.clock,
  });

  final FeatureAnalysis feature;
  final List<SeriesSample> series;
  final SwingVideoSync sync;

  /// 인덱스 ↔ 영상 시간 변환. null 이면 세로선을 그리지 않는다.
  final SeriesClock? clock;

  @override
  State<_SyncedSeriesChart> createState() => _SyncedSeriesChartState();
}

class _SyncedSeriesChartState extends State<_SyncedSeriesChart> {
  /// 드래그 중인 위치. 영상 이동이 따라오기 전에도 손가락 위치를 바로 보여준다.
  double? _dragIndex;

  double _indexFromDx(double dx, double width) {
    final plotW =
        width - _FeatureChartPainter.leftPad - _FeatureChartPainter.rightPad;
    final f = ((dx - _FeatureChartPainter.leftPad) / plotW).clamp(0.0, 1.0);
    return f * (widget.series.length - 1);
  }

  void _moveTo(double dx, double width) {
    final clock = widget.clock;
    if (clock == null) return;
    final index = _indexFromDx(dx, width);
    setState(() => _dragIndex = index);
    final ms = (clock.secondsAt(index) * 1000).round();
    widget.sync.seekTo(Duration(milliseconds: ms));
  }

  void _release() {
    if (_dragIndex != null) setState(() => _dragIndex = null);
  }

  @override
  Widget build(BuildContext context) {
    final clock = widget.clock;
    return ListenableBuilder(
      listenable: widget.sync,
      builder: (context, _) {
        final cursor = clock == null
            ? null
            : _dragIndex ??
                  clock.indexAt(widget.sync.position.inMilliseconds / 1000);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              height: 140,
              child: LayoutBuilder(
                builder: (context, box) => GestureDetector(
                  key: ValueKey('feature-series-scrub-${widget.feature.key}'),
                  behavior: HitTestBehavior.opaque,
                  onTapDown: clock == null
                      ? null
                      : (d) => _moveTo(d.localPosition.dx, box.maxWidth),
                  onTapUp: clock == null ? null : (_) => _release(),
                  onHorizontalDragStart: clock == null
                      ? null
                      : (d) => _moveTo(d.localPosition.dx, box.maxWidth),
                  onHorizontalDragUpdate: clock == null
                      ? null
                      : (d) => _moveTo(d.localPosition.dx, box.maxWidth),
                  onHorizontalDragEnd: clock == null ? null : (_) => _release(),
                  onHorizontalDragCancel: clock == null ? null : _release,
                  child: CustomPaint(
                    key: ValueKey('feature-series-${widget.feature.key}'),
                    size: Size.infinite,
                    painter: _FeatureChartPainter(
                      series: widget.series,
                      eventBased: widget.feature.eventBasedSeries,
                      unit: widget.feature.unit,
                      userColor: AppColors.primary,
                      cursor: cursor,
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 세부 항목 각도 시계열 Painter (내 스윙 vs 기준 ±편차)
// ---------------------------------------------------------------------------
class _FeatureChartPainter extends CustomPainter {
  _FeatureChartPainter({
    required this.series,
    required this.eventBased,
    required this.unit,
    required this.userColor,
    this.cursor,
  });

  final List<SeriesSample> series;
  final bool eventBased;
  final String unit;
  final Color userColor;

  /// 영상 현재 시점의 시계열 인덱스(실수). null 이면 세로선을 그리지 않는다.
  final double? cursor;

  static const _grid = Color(0xFFEDEDED);
  static const _axisText = Color(0xFF9E9E9E);
  static const _refColor = Color(0xFFBDBDBD);

  static const leftPad = 32.0;
  static const rightPad = 6.0;

  @override
  void paint(Canvas canvas, Size size) {
    if (series.length < 2) return;
    const bottomPad = 26.0;
    const topPad = 8.0;
    final plot = Rect.fromLTRB(
      leftPad,
      topPad,
      size.width - rightPad,
      size.height - bottomPad,
    );

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
      _text(
        canvas,
        _fmtAxis(v),
        Offset(plot.left - 6, y),
        align: _Align.right,
        color: _axisText,
      );
    }

    // 구간(4개) 경계선 + 라벨
    final seg = series.length ~/ SwingPhase.values.length;
    if (eventBased && seg > 0) {
      for (var s = 0; s < SwingPhase.values.length; s++) {
        final centerIdx = (s * seg + seg ~/ 2).clamp(0, series.length - 1);
        final x = xOf(centerIdx);
        _text(
          canvas,
          SwingPhase.values[s].en,
          Offset(x, plot.bottom + 4),
          align: _Align.center,
          color: _axisText,
          size: 7.5,
        );
        _text(
          canvas,
          SwingPhase.values[s].ko,
          Offset(x, plot.bottom + 14),
          align: _Align.center,
          color: _axisText,
          size: 7.5,
        );
        if (s > 0) {
          final bx = xOf((s * seg).clamp(0, series.length - 1));
          canvas.drawLine(
            Offset(bx, plot.top),
            Offset(bx, plot.bottom),
            gridPaint,
          );
        }
      }
    }

    // 기준과 편차가 함께 있는 연속 구간만 밴드로 그린다. 결측 구간을 잇지 않는다.
    var start = 0;
    while (start < series.length) {
      if (series[start].reference == null ||
          series[start].referenceStd == null) {
        start++;
        continue;
      }
      var end = start + 1;
      while (end < series.length &&
          series[end].reference != null &&
          series[end].referenceStd != null) {
        end++;
      }
      if (end - start >= 2) {
        final band = Path();
        for (var i = start; i < end; i++) {
          final y = yOf(series[i].reference! + series[i].referenceStd!);
          i == start ? band.moveTo(xOf(i), y) : band.lineTo(xOf(i), y);
        }
        for (var i = end - 1; i >= start; i--) {
          band.lineTo(
            xOf(i),
            yOf(series[i].reference! - series[i].referenceStd!),
          );
        }
        band.close();
        canvas.drawPath(
          band,
          Paint()..color = _refColor.withValues(alpha: 0.18),
        );
      }
      start = end;
    }

    // 기준 선 → 내 스윙 선 순서로.
    _drawCurve(
      canvas,
      [for (final s in series) s.reference],
      _refColor,
      xOf,
      yOf,
      width: 1.6,
    );
    _drawCurve(
      canvas,
      [for (final s in series) s.user],
      userColor,
      xOf,
      yOf,
      width: 2.2,
    );

    // 영상 현재 시점 세로선 + 내 스윙 선 위의 점.
    final c = cursor;
    if (c != null) {
      final x = plot.left + plot.width * (c / (series.length - 1));
      canvas.drawLine(
        Offset(x, plot.top),
        Offset(x, plot.bottom),
        Paint()
          ..color = userColor.withValues(alpha: 0.8)
          ..strokeWidth = 1.4,
      );
      final i0 = c.floor().clamp(0, series.length - 1);
      final i1 = c.ceil().clamp(0, series.length - 1);
      final v0 = series[i0].user;
      final v1 = series[i1].user;
      final v = v0 != null && v1 != null
          ? v0 + (v1 - v0) * (c - i0)
          : (v0 ?? v1);
      if (v != null) {
        final p = Offset(x, yOf(v));
        canvas.drawCircle(p, 5, Paint()..color = Colors.white);
        canvas.drawCircle(
          p,
          5,
          Paint()
            ..color = userColor
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2,
        );
        canvas.drawCircle(p, 2.2, Paint()..color = userColor);
      }
    }
  }

  /// null 지점에서는 선을 끊어 그린다(영상에 없는 구간).
  void _drawCurve(
    Canvas canvas,
    List<double?> ys,
    Color color,
    double Function(int) xOf,
    double Function(double) yOf, {
    required double width,
  }) {
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
      if ((i == 0 || ys[i - 1] == null) &&
          (i == ys.length - 1 || ys[i + 1] == null)) {
        canvas.drawCircle(p, width / 2, Paint()..color = color);
      }
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

  void _text(
    Canvas canvas,
    String s,
    Offset at, {
    required _Align align,
    required Color color,
    double size = 10,
  }) {
    final tp = TextPainter(
      text: TextSpan(
        text: s,
        style: TextStyle(color: color, fontSize: size),
      ),
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
      old.eventBased != eventBased ||
      old.unit != unit ||
      old.userColor != userColor ||
      old.cursor != cursor;
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
  const _FeatureStyle({
    required this.color,
    required this.soft,
    required this.label,
  });
  final Color color;
  final Color soft;
  final String label;
}

_FeatureStyle _featureStyle(String level) {
  switch (level) {
    case 'warning':
      return const _FeatureStyle(
        color: AppColors.primary,
        soft: Color(0xFFFDECEC),
        label: '개선 필요',
      );
    case 'caution':
      return const _FeatureStyle(
        color: Color(0xFFD9892B),
        soft: Color(0xFFFBF0DE),
        label: '주의',
      );
    default:
      return const _FeatureStyle(
        color: Color(0xFF2E9E5B),
        soft: Color(0xFFE7F5EC),
        label: '양호',
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
