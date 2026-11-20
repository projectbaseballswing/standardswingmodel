import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api/analysis_api.dart';
import '../api/auth_api.dart' show ApiException;
import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../theme/app_theme.dart';
import '../video/selected_video.dart';
import '../widgets/body_part_art.dart';
import '../widgets/swing_video.dart';
import '../widgets/feedback_metrics.dart';

/// 종합 피드백 화면.
///
/// 영상 분석이 끝나면 처음 보여주는 화면이다.
/// 새 업로드 및 과거 기록의 실제 분석 결과를 같은 화면에서 그린다.
class OverallFeedbackScreen extends StatefulWidget {
  const OverallFeedbackScreen({
    super.key,
    required this.analysisId,
    this.firstTime = false,
    this.videoPath,
    this.repository,
  });

  /// 조회할 분석 id.
  final String analysisId;

  /// 새 업로드의 분석 완료를 기다릴 때 true. 과거 기록 조회는 false.
  final bool firstTime;

  /// 새 영상의 로컬 경로 또는 웹 Blob URL. 이 화면 종료 시 Blob을 해제한다.
  final String? videoPath;

  final FeedbackRepository? repository;

  @override
  State<OverallFeedbackScreen> createState() => _OverallFeedbackScreenState();
}

class _OverallFeedbackScreenState extends State<OverallFeedbackScreen> {
  late final FeedbackRepository _repo;
  late Future<OverallFeedback> _future;

  @override
  void initState() {
    super.initState();
    _repo = widget.repository ?? FeedbackRepository();
    _future = _repo.fetchFeedback(
      widget.analysisId,
      firstTime: widget.firstTime,
    );
  }

  @override
  void didUpdateWidget(OverallFeedbackScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.videoPath != widget.videoPath) {
      releaseSelectedVideo(oldWidget.videoPath);
    }
    if (oldWidget.analysisId != widget.analysisId ||
        oldWidget.firstTime != widget.firstTime) {
      _future = _repo.fetchFeedback(
        widget.analysisId,
        firstTime: widget.firstTime,
      );
    }
  }

  @override
  void dispose() {
    releaseSelectedVideo(widget.videoPath);
    if (widget.repository == null) _repo.dispose();
    super.dispose();
  }

  void _retry() {
    setState(() {
      _future = _repo.fetchFeedback(
        widget.analysisId,
        firstTime: widget.firstTime,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F7F7),
      appBar: AppBar(
        backgroundColor: const Color(0xFFF7F7F7),
        surfaceTintColor: const Color(0xFFF7F7F7),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
          onPressed: () => Navigator.of(context).maybePop(),
        ),
        title: const Text('종합 피드백'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: _ShareButton(
              onTap: () {
                // TODO(next): 공유 기능 연결.
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('공유 기능은 준비 중이에요.')),
                );
              },
            ),
          ),
        ],
      ),
      body: FutureBuilder<OverallFeedback>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError || !snapshot.hasData) {
            final error = snapshot.error;
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      error is ApiException ? error.message : '피드백을 불러오지 못했어요.',
                      textAlign: TextAlign.center,
                    ),
                    TextButton(onPressed: _retry, child: const Text('다시 시도')),
                  ],
                ),
              ),
            );
          }
          return _FeedbackBody(
            feedback: snapshot.data!,
            analysisId: widget.analysisId,
            videoPath: widget.videoPath,
            api: _repo.api,
          );
        },
      ),
    );
  }
}

/// 스크롤되는 본문 + 하단 고정 버튼.
class _FeedbackBody extends StatelessWidget {
  const _FeedbackBody({
    required this.feedback,
    required this.analysisId,
    required this.api,
    this.videoPath,
  });

  final OverallFeedback feedback;
  final String analysisId;
  final String? videoPath;
  final AnalysisApi api;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _dateLabel(feedback.recordedAt),
                const SizedBox(height: 12),
                _VideoRow(
                  videoStatus: feedback.videoStatus,
                  analysisId: analysisId,
                  videoPath: videoPath,
                  api: api,
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    key: const Key('open-swing-3d'),
                    onPressed: () => context.push(
                      '/analyses/${Uri.encodeComponent(analysisId)}/pose-3d',
                    ),
                    icon: const Icon(Icons.view_in_ar),
                    label: const Text('3D 스윙 보기'),
                  ),
                ),
                const Text(
                  '이 영상에서 생성한 3D 추정 자세를 확인합니다.',
                  style: TextStyle(fontSize: 12, color: AppColors.hint),
                ),
                const SizedBox(height: 16),
                _ScoreCard(feedback: feedback),
                if (feedback.scoreExplanation.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  _Card(
                    child: Material(
                      color: Colors.transparent,
                      child: ExpansionTile(
                        key: const Key('score-evidence'),
                        title: const Text('점수가 산출된 이유'),
                        children: [
                          Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                if (feedback.postureScore != null ||
                                    feedback.speedScore != null) ...[
                                  Row(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Expanded(
                                        child: _SubScore(
                                          label: '자세',
                                          weight: feedback.confirmedComposite
                                              ? '70%'
                                              : '',
                                          score: feedback.postureScore,
                                          note: feedback.postureCapped
                                              ? '상한 40점 적용 · 몸통 회전 부족'
                                              : '프로 선수 자세와 얼마나 비슷한지',
                                          capped: feedback.postureCapped,
                                        ),
                                      ),
                                      const SizedBox(width: 10),
                                      Expanded(
                                        child: _SubScore(
                                          label: '속도',
                                          weight: feedback.confirmedComposite
                                              ? '30%'
                                              : '',
                                          score: feedback.speedScore,
                                          note: '임팩트 주변 최대 손 속도 · 프로 중앙값 80점',
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 12),
                                ],
                                Text(feedback.scoreExplanation),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
                if (feedback.scoreContributions.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  _ScoreContributionCard(
                    contributions: feedback.scoreContributions,
                  ),
                ],
                const SizedBox(height: 12),
                _CoachCard(feedback: feedback),
                const SizedBox(height: 12),
                ..._buildCategorySections(feedback),
                if (feedback.speedMetrics.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  SpeedFeedbackCard(metrics: feedback.speedMetrics),
                ],
              ],
            ),
          ),
        ),
        _BottomBar(feedback: feedback),
      ],
    );
  }

  Widget _dateLabel(DateTime at) {
    String two(int n) => n.toString().padLeft(2, '0');
    final text =
        '${at.year}. ${two(at.month)}. ${two(at.day)}  ${two(at.hour)}:${two(at.minute)}';
    return Text(
      text,
      style: const TextStyle(fontSize: 13, color: AppColors.hint),
    );
  }

  /// 실제 이전 스윙과의 비교 여부에 따라 분류 카드를 만든다.
  List<Widget> _buildCategorySections(OverallFeedback f) {
    final sections = <_CategorySpec>[];
    sections.add(
      _CategorySpec(
        title: '참고용 · 분석 제한',
        tone: _Tone.neutral,
        items: f.items.where((i) => i.limited).toList(),
      ),
    );
    if (!f.hasComparison) {
      // 이전 스윙과 비교하지 않은 결과: 프로 기준 대비 level로 나눈다.
      sections.add(
        _CategorySpec(
          title: '잘한 부분',
          tone: _Tone.good,
          items: f.items.where((i) => !i.limited && i.level == 'good').toList(),
        ),
      );
      sections.add(
        _CategorySpec(
          title: '개선이 필요한 부분',
          tone: _Tone.bad,
          items: f.items.where((i) => !i.limited && i.level != 'good').toList(),
        ),
      );
    } else {
      // 반복 피드백: 이전 대비 증감으로 나눈다.
      // |증감| 이 이 값 이하면 "큰 변화 없음" 으로 보고 유지로 분류한다.
      // TODO(backend): 기준 폭은 추후 실제 점수 분포에 맞춰 조정.
      const maintainBand = 2;
      sections.add(
        _CategorySpec(
          title: '개선된 부분',
          tone: _Tone.good,
          items: f.items.where((i) => (i.delta ?? 0) > maintainBand).toList(),
        ),
      );
      sections.add(
        _CategorySpec(
          title: '개선이 필요한 부분',
          tone: _Tone.bad,
          items: f.items.where((i) => (i.delta ?? 0) < -maintainBand).toList(),
        ),
      );
      sections.add(
        _CategorySpec(
          title: '유지된 부분',
          tone: _Tone.neutral,
          items: f.items
              .where((i) => (i.delta ?? 0).abs() <= maintainBand)
              .toList(),
        ),
      );
    }

    final widgets = <Widget>[];
    for (final spec in sections) {
      if (spec.items.isEmpty) continue;
      widgets.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _CategoryCard(spec: spec),
        ),
      );
    }
    return widgets;
  }
}

// ---------------------------------------------------------------------------
// 상단: 날짜 아래 영상 2개
// ---------------------------------------------------------------------------
class _VideoRow extends StatelessWidget {
  const _VideoRow({
    required this.analysisId,
    required this.api,
    this.videoPath,
    this.videoStatus = 'unknown',
  });

  final String analysisId;

  final String? videoPath;

  final AnalysisApi api;
  final String videoStatus;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: _ThumbFrame(
            label: '내 스윙 영상',
            child: videoStatus == 'deleted' || videoStatus == 'deleting'
                ? ColoredBox(
                    color: const Color(0xFFE6E6E6),
                    child: Center(
                      child: Padding(
                        padding: const EdgeInsets.all(8),
                        child: Text(
                          videoStatus == 'deleted'
                              ? '원본 영상이 삭제되었습니다'
                              : '원본 영상 삭제가 진행 중입니다.\n목록에서 삭제를 다시 요청해주세요.',
                          textAlign: TextAlign.center,
                          style: const TextStyle(fontSize: 12),
                        ),
                      ),
                    ),
                  )
                : SwingVideo(
                    key: ValueKey((analysisId, videoPath)),
                    analysisId: analysisId,
                    videoPath: videoPath,
                    api: api,
                    preload: true,
                  ),
          ),
        ),
        const SizedBox(width: 12),
        const Expanded(
          child: _ThumbFrame(
            label: '분석 결과',
            // TODO(backend): 분석 결과(포즈 오버레이) 이미지를 서버가 주면 교체.
            child: _PlaceholderThumb(icon: Icons.accessibility_new),
          ),
        ),
      ],
    );
  }
}

/// 5:7(가로:세로) 비율 썸네일 틀 + 아래 라벨.
class _ThumbFrame extends StatelessWidget {
  const _ThumbFrame({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        AspectRatio(
          aspectRatio: 5 / 7,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: child,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          label,
          style: const TextStyle(fontSize: 12, color: AppColors.subtitle),
        ),
      ],
    );
  }
}

/// 영상/이미지가 없을 때 보여주는 회색 자리표시자.
class _PlaceholderThumb extends StatelessWidget {
  const _PlaceholderThumb({required this.icon});

  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFFE6E6E6),
      alignment: Alignment.center,
      child: Icon(icon, size: 40, color: Colors.grey.shade400),
    );
  }
}

// ---------------------------------------------------------------------------
// 전체 스윙 점수 카드
// ---------------------------------------------------------------------------
class _ScoreCard extends StatelessWidget {
  const _ScoreCard({required this.feedback});

  final OverallFeedback feedback;

  @override
  Widget build(BuildContext context) {
    final delta = feedback.totalDelta;
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '전체 스윙 점수',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 10),
          Text(
            reliabilityLabel(feedback.reliability),
            style: const TextStyle(fontSize: 11.5, color: AppColors.hint),
          ),
          for (final warning in feedback.warnings)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                warning,
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.subtitle,
                ),
              ),
            ),
          const SizedBox(height: 4),
          // 점수  / 100  [▼ 9]  (이전 70점)
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  feedbackNumber(feedback.totalScore),
                  style: const TextStyle(
                    fontSize: 30,
                    height: 1.0,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primary,
                  ),
                ),
                const SizedBox(width: 4),
                const Text(
                  '/ 100',
                  style: TextStyle(fontSize: 12, color: _gray),
                ),
                if (delta != null) ...[
                  const SizedBox(width: 8),
                  _DeltaBadge(delta: delta),
                  const SizedBox(width: 8),
                  Text(
                    '(이전 ${feedback.previousTotalScore}점)',
                    style: const TextStyle(fontSize: 10, color: _gray),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 10),
          // 요약 분홍 박스
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF1F1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              '${feedback.summarySource}\n${feedback.summary}',
              style: const TextStyle(
                fontSize: 13,
                height: 15 / 13,
                color: Color(0xFFD9534F),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 종합 점수를 이루는 자세/속도 점수 한 칸.
class _SubScore extends StatelessWidget {
  const _SubScore({
    required this.label,
    required this.weight,
    required this.score,
    required this.note,
    this.capped = false,
  });

  final String label;
  final String weight;
  final double? score;
  final String note;
  final bool capped;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: capped ? const Color(0xFFFDECEC) : AppColors.fieldFill,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            weight.isEmpty ? '$label 점수' : '$label 점수 · 반영 $weight',
            style: const TextStyle(fontSize: 11.5, color: AppColors.hint),
          ),
          const SizedBox(height: 4),
          Text(
            score == null ? '-' : feedbackNumber(score),
            style: TextStyle(
              fontSize: 22,
              height: 1.1,
              fontWeight: FontWeight.w800,
              color: capped ? AppColors.primary : AppColors.subtitle,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            score == null ? '측정하지 못했어요' : note,
            style: TextStyle(
              fontSize: 11,
              height: 1.35,
              color: capped ? const Color(0xFFC0514F) : AppColors.hint,
            ),
          ),
        ],
      ),
    );
  }
}

/// 피그마 보조 글자색.
const Color _gray = Color(0xFF8E8E93);

// ---------------------------------------------------------------------------
// 점수 영향도: 어느 부위가 점수를 얼마나 깎았는지(기준과 벌어진 비중) 막대로.
// ---------------------------------------------------------------------------
class _ScoreContributionCard extends StatelessWidget {
  const _ScoreContributionCard({required this.contributions});

  final List<ScoreContribution> contributions;

  // 막대는 '점수를 깎은 비중'(길이)만 나타낸다. 잘함/개선필요 같은 상태는 아래 부위 카드에
  // 이미 색으로 보이므로, 여기서는 상태색을 쓰지 않고 중립 단색으로 둔다(색=상태로 오해 방지).
  static const Color _bar = Color(0xFF6B7FB3);

  @override
  Widget build(BuildContext context) {
    final hasLow = contributions.any((c) => c.isLowReliability);
    // 막대 길이는 비중 그대로(트랙 전체=100%). "전체 중 이만큼"으로 읽히게.
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '점수 영향도',
            style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 4),
          const Text(
            '자세 점수 계산에 쓰인 기준과의 차이를 부위별 비중으로 보여줘요. '
            '표시된 부위 안에서 비교한 비율이며, 종합점수가 몇 점 낮아졌다는 뜻은 아니에요.',
            style: TextStyle(fontSize: 12, color: AppColors.hint, height: 1.4),
          ),
          const SizedBox(height: 13),
          for (final c in contributions)
            Padding(
              padding: const EdgeInsets.only(bottom: 11),
              child: Opacity(
                opacity: c.isLowReliability ? 0.5 : 1,
                child: Row(
                  children: [
                    SizedBox(
                      width: 84,
                      child: Text(
                        c.isLowReliability ? '${c.name} *' : c.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.subtitle,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(5),
                        child: LinearProgressIndicator(
                          value: c.share.clamp(0.0, 1.0),
                          minHeight: 9,
                          backgroundColor: const Color(0xFFEEF0F2),
                          valueColor: const AlwaysStoppedAnimation(_bar),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    SizedBox(
                      width: 38,
                      child: Text(
                        '${(c.share * 100).round()}%',
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          if (hasLow)
            const Padding(
              padding: EdgeInsets.only(top: 1),
              child: Text(
                '* 몸에 가려 검출 신뢰도가 낮아 참고용이에요. 비중 계산에는 포함돼 있어요.',
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.hint,
                  height: 1.5,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// ▼9 / ▲8 같은 증감 배지.
class _DeltaBadge extends StatelessWidget {
  const _DeltaBadge({required this.delta});

  final double delta;

  @override
  Widget build(BuildContext context) {
    final up = delta > 0;
    final style = _toneStyle(up ? _Tone.good : _Tone.bad);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: style.soft,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        '${up ? '▲' : '▼'} ${feedbackNumber(delta.abs())}',
        style: TextStyle(
          fontSize: 10.5,
          fontWeight: FontWeight.w700,
          color: style.color,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 분류 카드 (개선된 / 개선 필요 / 유지된 / 잘한 부분)
// ---------------------------------------------------------------------------
enum _Tone { good, bad, neutral }

class _CategorySpec {
  _CategorySpec({required this.title, required this.tone, required this.items});

  final String title;
  final _Tone tone;
  final List<FeedbackItem> items;
}

class _CategoryCard extends StatefulWidget {
  const _CategoryCard({required this.spec});

  final _CategorySpec spec;

  @override
  State<_CategoryCard> createState() => _CategoryCardState();
}

class _CategoryCardState extends State<_CategoryCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final spec = widget.spec;
    final tone = _toneStyle(spec.tone);
    final hasMore = spec.items.length > 1;
    final visible = (_expanded || !hasMore)
        ? spec.items
        : spec.items.take(1).toList();

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더: 아이콘 + 제목 + (N곳 ▼/▲)
          Row(
            children: [
              Icon(tone.icon, size: 18, color: tone.color),
              const SizedBox(width: 6),
              Text(
                spec.title,
                style: TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                  color: tone.color,
                ),
              ),
              const Spacer(),
              if (hasMore)
                GestureDetector(
                  onTap: () => setState(() => _expanded = !_expanded),
                  child: Row(
                    children: [
                      Text(
                        '${spec.items.length}곳',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                          color: tone.color,
                        ),
                      ),
                      Icon(
                        _expanded
                            ? Icons.keyboard_arrow_up
                            : Icons.keyboard_arrow_down,
                        size: 18,
                        color: tone.color,
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          for (var i = 0; i < visible.length; i++) ...[
            if (i > 0)
              const Divider(
                height: 20,
                thickness: 0.6,
                color: Color(0xFFEDEDED),
              ),
            _ItemRow(item: visible[i], tone: spec.tone),
          ],
        ],
      ),
    );
  }
}

class _ItemRow extends StatelessWidget {
  const _ItemRow({required this.item, required this.tone});

  final FeedbackItem item;
  final _Tone tone;

  @override
  Widget build(BuildContext context) {
    final delta = item.delta;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        BodyPartThumb(
          part: item.part,
          region: bodyRegionOf(
            key: item.key,
            label: item.label,
            part: item.part,
          ),
          tone: switch (tone) {
            _Tone.good => BodyTone.good,
            _Tone.bad => BodyTone.bad,
            _Tone.neutral => BodyTone.neutral,
          },
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 이름 + 점수
              if (delta != null)
                // 반복 피드백: 이름  72 → 80점  (+8) — 길면 줄바꿈된다.
                Text.rich(
                  TextSpan(
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                    children: [
                      TextSpan(text: item.label),
                      TextSpan(
                        text:
                            '  ${feedbackNumber(item.previousScore)} → ${feedbackNumber(item.currentScore)}점',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      TextSpan(
                        text:
                            '  (${delta > 0 ? '+' : ''}${feedbackNumber(delta)})',
                        style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w700,
                          color: delta > 0
                              ? const Color(0xFF2E9E5B)
                              : (delta < 0
                                    ? AppColors.primary
                                    : AppColors.hint),
                        ),
                      ),
                    ],
                  ),
                )
              else
                // 이전 비교 없음: 이름 - 81점 (길면 줄바꿈)
                Text.rich(
                  TextSpan(
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                    children: [
                      TextSpan(text: item.label),
                      TextSpan(
                        text: '  -  ${feedbackNumber(item.currentScore)}점',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 3),
              Text(
                reliabilityLabel(item.reliability),
                style: const TextStyle(fontSize: 11, color: AppColors.hint),
              ),
              Text(
                item.description,
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.4,
                  color: AppColors.subtitle,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// AI 코치의 한마디
// ---------------------------------------------------------------------------
class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.feedback});
  final OverallFeedback feedback;

  static const _accent = Color(0xFF8A6BEA);

  @override
  Widget build(BuildContext context) {
    final cf = feedback.coaching?.coachFeedback;
    final first = feedback.priorities.firstOrNull;
    final strength = feedback.strengths.firstOrNull;
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.info_outline, size: 16, color: _accent),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  feedback.coachSource,
                  style: const TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            feedback.coachingReview.notice,
            key: const Key('coaching-review-notice'),
            style: const TextStyle(fontSize: 11.5, color: AppColors.hint),
          ),
          const SizedBox(height: 14),
          if (strength != null)
            _CoachStep(
              icon: Icons.check_circle_outline,
              label: '잘한 점 · 기준과 가까운 구간',
              text: '${strength.observation}\n다른 구간에서는 결과가 달라질 수 있어요.',
            ),
          if (feedback.coaching != null)
            _CoachStep(
              icon: Icons.flag_outlined,
              label: '가장 먼저 확인할 동작',
              text: feedback.coachComment,
            )
          else if (first != null) ...[
            _CoachStep(
              icon: Icons.flag_outlined,
              label: '가장 먼저 확인할 동작',
              text: first.observation,
            ),
            _CoachStep(
              icon: Icons.search,
              label: '원본에서 먼저 확인',
              text:
                  '${first.action}\n이 설명은 구간의 평균을 비교한 것이에요. '
                  '한순간의 자세를 이 값에 맞추라는 뜻은 아니에요.',
            ),
            const _CoachStep(
              icon: Icons.sports_baseball_outlined,
              label: '원본을 보는 방법',
              text:
                  '해당 구간의 처음·중간·끝 장면을 천천히 비교해 보세요. '
                  '어떤 동작을 얼마나 바꿀지는 이 결과만으로 정하기 어려워요.',
              isLast: true,
            ),
          ] else
            Text(feedback.coachComment),
          if (cf != null) ...[
            _CoachStep(icon: Icons.search, label: '기준과의 차이', text: cf.problem),
            _CoachStep(
              icon: Icons.help_outline,
              label: '원인과 확인 범위',
              text: cf.cause,
            ),
            _CoachStep(
              icon: Icons.build_outlined,
              label: '확인 후 시도할 작은 조절',
              text: cf.fix,
            ),
            _CoachStep(
              icon: Icons.sports_baseball_outlined,
              label: '추천 연습 · 효과 검증과 구분',
              text: cf.drill,
              isLast: true,
            ),
          ],
        ],
      ),
    );
  }
}

/// AI 코치 4단 중 한 단계. 아이콘 + 라벨 + 본문.
class _CoachStep extends StatelessWidget {
  const _CoachStep({
    required this.icon,
    required this.label,
    required this.text,
    this.isLast = false,
  });

  final IconData icon;
  final String label;
  final String text;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: isLast ? 0 : 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 15, color: _CoachCard._accent),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: _CoachCard._accent,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    fontSize: 12.5,
                    height: 1.5,
                    color: AppColors.subtitle,
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
// 하단 버튼 2개
// ---------------------------------------------------------------------------
class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.feedback});

  final OverallFeedback feedback;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
        child: Row(
          children: [
            Expanded(
              child: SizedBox(
                height: 50,
                child: OutlinedButton(
                  onPressed: () {
                    // 관절별 분석(상세 피드백) 화면으로 이동.
                    context.push('/joint-analysis', extra: feedback);
                  },
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    backgroundColor: const Color(0xFFFDECEC),
                    side: BorderSide.none,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: const Text(
                    '상세 피드백 보기',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: SizedBox(
                height: 50,
                child: ElevatedButton(
                  onPressed: () {
                    // 구간별 피드백 화면으로 이동.
                    context.push('/phase-feedback', extra: feedback);
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: const Text(
                    '구간별 피드백 보기',
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
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

// ---------------------------------------------------------------------------
// 공통 위젯
// ---------------------------------------------------------------------------
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

class _ShareButton extends StatelessWidget {
  const _ShareButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFE0E0E0)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: const [
            Icon(Icons.ios_share, size: 14, color: Colors.black87),
            SizedBox(width: 4),
            Text('공유하기', style: TextStyle(fontSize: 12, color: Colors.black87)),
          ],
        ),
      ),
    );
  }
}

class _ToneStyle {
  const _ToneStyle({
    required this.color,
    required this.soft,
    required this.icon,
  });
  final Color color;
  final Color soft;
  final IconData icon;
}

_ToneStyle _toneStyle(_Tone tone) {
  switch (tone) {
    case _Tone.good:
      return const _ToneStyle(
        color: Color(0xFF2E9E5B),
        soft: Color(0xFFE7F5EC),
        icon: Icons.trending_up,
      );
    case _Tone.bad:
      return const _ToneStyle(
        color: AppColors.primary,
        soft: Color(0xFFFDECEC),
        icon: Icons.trending_down,
      );
    case _Tone.neutral:
      return const _ToneStyle(
        color: Color(0xFF9E9E9E),
        soft: Color(0xFFEFEFEF),
        icon: Icons.remove,
      );
  }
}
