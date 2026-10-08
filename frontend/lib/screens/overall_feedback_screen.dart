import 'dart:io';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:video_player/video_player.dart';

import '../data/feedback_repository.dart';
import '../models/feedback.dart';
import '../theme/app_theme.dart';

/// 종합 피드백 화면.
///
/// 영상 분석이 끝나면 처음 보여주는 화면이다.
/// 첫 피드백([OverallFeedback.isFirst])과 반복 피드백을 같은 화면에서 그린다.
class OverallFeedbackScreen extends StatefulWidget {
  const OverallFeedbackScreen({
    super.key,
    required this.analysisId,
    this.firstTime = false,
    this.videoPath,
  });

  /// 조회할 분석 id.
  final String analysisId;

  /// 비교 대상이 없는 첫 피드백이면 true.
  final bool firstTime;

  /// 방금 촬영한 로컬 영상 경로. 있으면 "내 스윙 영상" 에 실제 영상을 보여준다.
  final String? videoPath;

  @override
  State<OverallFeedbackScreen> createState() => _OverallFeedbackScreenState();
}

class _OverallFeedbackScreenState extends State<OverallFeedbackScreen> {
  final _repo = FeedbackRepository();
  late Future<OverallFeedback> _future;

  @override
  void initState() {
    super.initState();
    _future = _repo.fetchFeedback(widget.analysisId, firstTime: widget.firstTime);
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
            child: _ShareButton(onTap: () {
              // TODO(next): 공유 기능 연결.
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('공유 기능은 준비 중이에요.')),
              );
            }),
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
            return const Center(child: Text('피드백을 불러오지 못했어요.'));
          }
          return _FeedbackBody(
            feedback: snapshot.data!,
            videoPath: widget.videoPath,
          );
        },
      ),
    );
  }
}

/// 스크롤되는 본문 + 하단 고정 버튼.
class _FeedbackBody extends StatelessWidget {
  const _FeedbackBody({required this.feedback, this.videoPath});

  final OverallFeedback feedback;
  final String? videoPath;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 16),
            children: [
              _dateLabel(feedback.recordedAt),
              const SizedBox(height: 12),
              _VideoRow(videoPath: videoPath),
              const SizedBox(height: 16),
              _ScoreCard(feedback: feedback),
              const SizedBox(height: 12),
              ..._buildCategorySections(feedback),
              const SizedBox(height: 12),
              _CoachCard(comment: feedback.coachComment),
            ],
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

  /// 첫/반복 피드백에 따라 분류 카드를 만든다.
  List<Widget> _buildCategorySections(OverallFeedback f) {
    final sections = <_CategorySpec>[];
    if (f.isFirst) {
      // 첫 피드백: 프로 기준 대비 level 로 나눈다.
      sections.add(_CategorySpec(
        title: '잘한 부분',
        tone: _Tone.good,
        items: f.items.where((i) => i.level == 'good').toList(),
      ));
      sections.add(_CategorySpec(
        title: '개선이 필요한 부분',
        tone: _Tone.bad,
        items: f.items.where((i) => i.level != 'good').toList(),
      ));
    } else {
      // 반복 피드백: 이전 대비 증감으로 나눈다.
      // |증감| 이 이 값 이하면 "큰 변화 없음" 으로 보고 유지로 분류한다.
      // TODO(backend): 기준 폭은 추후 실제 점수 분포에 맞춰 조정.
      const maintainBand = 2;
      sections.add(_CategorySpec(
        title: '개선된 부분',
        tone: _Tone.good,
        items: f.items.where((i) => (i.delta ?? 0) > maintainBand).toList(),
      ));
      sections.add(_CategorySpec(
        title: '개선이 필요한 부분',
        tone: _Tone.bad,
        items: f.items.where((i) => (i.delta ?? 0) < -maintainBand).toList(),
      ));
      sections.add(_CategorySpec(
        title: '유지된 부분',
        tone: _Tone.neutral,
        items:
            f.items.where((i) => (i.delta ?? 0).abs() <= maintainBand).toList(),
      ));
    }

    final widgets = <Widget>[];
    for (final spec in sections) {
      if (spec.items.isEmpty) continue;
      widgets.add(Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: _CategoryCard(spec: spec),
      ));
    }
    return widgets;
  }
}

// ---------------------------------------------------------------------------
// 상단: 날짜 아래 영상 2개
// ---------------------------------------------------------------------------
class _VideoRow extends StatelessWidget {
  const _VideoRow({this.videoPath});

  final String? videoPath;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: _ThumbFrame(
            label: '내 스윙 영상',
            child: videoPath != null
                ? _MySwingVideo(videoPath: videoPath!)
                : const _PlaceholderThumb(icon: Icons.sports_baseball),
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

/// 정사각 비율 썸네일 틀 + 아래 라벨.
class _ThumbFrame extends StatelessWidget {
  const _ThumbFrame({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        AspectRatio(
          aspectRatio: 1.05,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: child,
          ),
        ),
        const SizedBox(height: 6),
        Text(label,
            style: const TextStyle(fontSize: 12, color: AppColors.subtitle)),
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

/// 실제 촬영한 스윙 영상. 탭하면 재생/일시정지한다.
class _MySwingVideo extends StatefulWidget {
  const _MySwingVideo({required this.videoPath});

  final String videoPath;

  @override
  State<_MySwingVideo> createState() => _MySwingVideoState();
}

class _MySwingVideoState extends State<_MySwingVideo> {
  VideoPlayerController? _controller;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    final controller = VideoPlayerController.file(File(widget.videoPath));
    _controller = controller;
    controller.initialize().then((_) {
      if (!mounted) return;
      controller.setLooping(true);
      setState(() => _ready = true);
    }).catchError((_) {
      // 초기화 실패 시 자리표시자로 둔다.
    });
    controller.addListener(_onTick);
  }

  void _onTick() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _controller?.removeListener(_onTick);
    _controller?.dispose();
    super.dispose();
  }

  void _toggle() {
    final c = _controller;
    if (c == null || !_ready) return;
    setState(() => c.value.isPlaying ? c.pause() : c.play());
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    if (c == null || !_ready) {
      return const _PlaceholderThumb(icon: Icons.sports_baseball);
    }
    final playing = c.value.isPlaying;
    return GestureDetector(
      onTap: _toggle,
      child: Stack(
        fit: StackFit.expand,
        children: [
          FittedBox(
            fit: BoxFit.cover,
            clipBehavior: Clip.hardEdge,
            child: SizedBox(
              width: c.value.size.width,
              height: c.value.size.height,
              child: VideoPlayer(c),
            ),
          ),
          if (!playing)
            Container(
              width: 44,
              height: 44,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.35),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.play_arrow, color: Colors.white, size: 28),
            ),
          Positioned(
            left: 8,
            right: 8,
            bottom: 8,
            child: Row(
              children: [
                Text(_fmt(c.value.position),
                    style: const TextStyle(color: Colors.white, fontSize: 10)),
                const SizedBox(width: 4),
                Expanded(
                  child: VideoProgressIndicator(
                    c,
                    allowScrubbing: true,
                    padding: EdgeInsets.zero,
                    colors: const VideoProgressColors(
                      playedColor: Colors.white,
                      bufferedColor: Colors.white30,
                      backgroundColor: Colors.white24,
                    ),
                  ),
                ),
                const SizedBox(width: 4),
                Text(_fmt(c.value.duration),
                    style: const TextStyle(color: Colors.white, fontSize: 10)),
              ],
            ),
          ),
        ],
      ),
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
          const Text('전체 스윙 점수',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 점수
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text('${feedback.totalScore}',
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
                      _DeltaBadge(delta: delta),
                      const SizedBox(height: 2),
                      Text('(이전 ${feedback.previousTotalScore}점)',
                          style: const TextStyle(
                              fontSize: 11, color: AppColors.hint)),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 12),
              // 요약 분홍 박스
              Expanded(
                flex: 6,
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFDECEC),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    feedback.summary,
                    style: const TextStyle(
                        fontSize: 12.5,
                        height: 1.4,
                        color: Color(0xFFC0514F)),
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

/// ▼9 / ▲8 같은 증감 배지.
class _DeltaBadge extends StatelessWidget {
  const _DeltaBadge({required this.delta});

  final int delta;

  @override
  Widget build(BuildContext context) {
    final up = delta > 0;
    final color = up ? const Color(0xFF2E9E5B) : AppColors.primary;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(up ? Icons.arrow_drop_up : Icons.arrow_drop_down,
            size: 18, color: color),
        Text('${delta.abs()}',
            style: TextStyle(
                fontSize: 13, fontWeight: FontWeight.w700, color: color)),
      ],
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
    final visible =
        (_expanded || !hasMore) ? spec.items : spec.items.take(1).toList();

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더: 아이콘 + 제목 + (N곳 ▼/▲)
          Row(
            children: [
              Icon(tone.icon, size: 18, color: tone.color),
              const SizedBox(width: 6),
              Text(spec.title,
                  style: TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: tone.color)),
              const Spacer(),
              if (hasMore)
                GestureDetector(
                  onTap: () => setState(() => _expanded = !_expanded),
                  child: Row(
                    children: [
                      Text('${spec.items.length}곳',
                          style: const TextStyle(
                              fontSize: 12, color: AppColors.hint)),
                      Icon(
                          _expanded
                              ? Icons.keyboard_arrow_up
                              : Icons.keyboard_arrow_down,
                          size: 18,
                          color: AppColors.hint),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          for (var i = 0; i < visible.length; i++) ...[
            if (i > 0)
              const Divider(height: 20, thickness: 0.6, color: Color(0xFFEDEDED)),
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
        _PartIcon(part: item.part, tone: tone),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 이름 + 점수
              if (delta != null)
                // 반복 피드백: 이름  72 → 80  (+8)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(item.label,
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w700)),
                    const SizedBox(width: 6),
                    Text('${item.previousScore} → ${item.currentScore}점',
                        style: const TextStyle(
                            fontSize: 13, fontWeight: FontWeight.w600)),
                    const SizedBox(width: 4),
                    Text(
                      '(${delta > 0 ? '+' : ''}$delta)',
                      style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w700,
                          color: delta > 0
                              ? const Color(0xFF2E9E5B)
                              : (delta < 0
                                  ? AppColors.primary
                                  : AppColors.hint)),
                    ),
                  ],
                )
              else
                // 첫 피드백: 이름 - 81점 (길면 줄바꿈)
                Text.rich(
                  TextSpan(
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w700),
                    children: [
                      TextSpan(text: item.label),
                      TextSpan(
                        text: '  -  ${item.currentScore}점',
                        style: const TextStyle(
                            fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 3),
              Text(item.description,
                  style: const TextStyle(
                      fontSize: 12, height: 1.4, color: AppColors.subtitle)),
            ],
          ),
        ),
        const Padding(
          padding: EdgeInsets.only(left: 4, top: 2),
          child: Icon(Icons.chevron_right, size: 18, color: AppColors.hint),
        ),
      ],
    );
  }
}

/// 부위 아이콘(연한 색 알약 배경 + 아이콘). 실제 일러스트가 생기면 교체.
class _PartIcon extends StatelessWidget {
  const _PartIcon({required this.part, required this.tone});

  final BodyPart part;
  final _Tone tone;

  @override
  Widget build(BuildContext context) {
    final style = _toneStyle(tone);
    IconData icon;
    switch (part) {
      case BodyPart.leg:
        icon = Icons.directions_walk;
        break;
      case BodyPart.arm:
        icon = Icons.sports_handball;
        break;
      case BodyPart.torso:
        icon = Icons.accessibility_new;
        break;
    }
    return Container(
      width: 40,
      height: 48,
      decoration: BoxDecoration(
        color: style.soft,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(icon, size: 22, color: style.color),
    );
  }
}

// ---------------------------------------------------------------------------
// AI 코치의 한마디
// ---------------------------------------------------------------------------
class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.comment});

  final String comment;

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.auto_awesome, size: 16, color: Color(0xFF8A6BEA)),
              SizedBox(width: 6),
              Text('AI 코치의 한마디',
                  style:
                      TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 8),
          Text(comment,
              style: const TextStyle(
                  fontSize: 12.5, height: 1.5, color: AppColors.subtitle)),
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
                        borderRadius: BorderRadius.circular(10)),
                  ),
                  child: const Text('상세 피드백 보기',
                      style: TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w700)),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: SizedBox(
                height: 50,
                child: ElevatedButton(
                  onPressed: () {
                    // TODO(next): 구간별 피드백 화면으로 이동.
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10)),
                  ),
                  child: const Text('구간별 피드백 보기',
                      style: TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w700)),
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
            Text('공유하기',
                style: TextStyle(fontSize: 12, color: Colors.black87)),
          ],
        ),
      ),
    );
  }
}

class _ToneStyle {
  const _ToneStyle({required this.color, required this.soft, required this.icon});
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
          icon: Icons.trending_up);
    case _Tone.bad:
      return const _ToneStyle(
          color: AppColors.primary,
          soft: Color(0xFFFDECEC),
          icon: Icons.trending_down);
    case _Tone.neutral:
      return const _ToneStyle(
          color: Color(0xFF9E9E9E),
          soft: Color(0xFFEFEFEF),
          icon: Icons.remove);
  }
}
