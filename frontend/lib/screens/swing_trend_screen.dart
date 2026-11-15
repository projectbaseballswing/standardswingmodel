import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api/auth_api.dart' show ApiException;
import '../data/session.dart';
import '../data/swing_repository.dart';
import '../models/swing.dart';
import '../models/swing_trend.dart';
import '../route_observer.dart';
import '../theme/app_theme.dart';
import '../widgets/swing_trend_chart.dart';

class SwingTrendScreen extends StatefulWidget {
  const SwingTrendScreen({super.key, this.repository, this.clock});
  final SwingRepository? repository;
  final DateTime Function()? clock;

  @override
  State<SwingTrendScreen> createState() => _SwingTrendScreenState();
}

class _SwingTrendScreenState extends State<SwingTrendScreen> with RouteAware {
  late final SwingRepository _repository;
  ModalRoute<dynamic>? _route;
  List<Swing> _swings = [];
  SwingTrendPeriod _period = SwingTrendPeriod.month;
  String? _selectedId, _error, _userId, _token;
  bool _loading = true;
  int _requestId = 0;

  @override
  void initState() {
    super.initState();
    _repository = widget.repository ?? SwingRepository();
    _userId = Session.instance.userId;
    _token = Session.instance.accessToken;
    Session.instance.addListener(_sessionChanged);
    _load();
  }

  void _sessionChanged() {
    if (_userId == Session.instance.userId &&
        _token == Session.instance.accessToken) {
      return;
    }
    _userId = Session.instance.userId;
    _token = Session.instance.accessToken;
    _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (_route != route) {
      swingRouteObserver.unsubscribe(this);
      _route = route;
      if (route != null) swingRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didPopNext() => _load();

  @override
  void dispose() {
    Session.instance.removeListener(_sessionChanged);
    swingRouteObserver.unsubscribe(this);
    if (widget.repository == null) _repository.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final request = ++_requestId;
    setState(() {
      _loading = true;
      _error = null;
      _swings = [];
    });
    try {
      final records = await _repository.fetchAllMySwings();
      if (!mounted || request != _requestId) return;
      setState(() {
        _swings = records;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || request != _requestId) return;
      setState(() {
        _loading = false;
        _error = e is ApiException
            ? e.message
            : '스윙 기록을 불러오지 못했습니다. 다시 시도해주세요.';
      });
    }
  }

  void _backToList() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go('/swings');
    }
  }

  void _openFeedback(Swing swing) =>
      context.push('/analyses/${Uri.encodeComponent(swing.analysisId)}');

  String _date(Swing s) {
    final d = s.recordedAt;
    String two(int v) => '$v'.padLeft(2, '0');
    return '${d.year}.${two(d.month)}.${two(d.day)}  ${two(d.hour)}:${two(d.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    final trend = SwingTrend.fromSwings(
      _swings,
      period: _period,
      now: widget.clock?.call() ?? DateTime.now(),
    );
    final points = trend.points;
    final selected =
        points.where((s) => s.analysisId == _selectedId).firstOrNull ??
        points.lastOrNull;
    final descending = points.reversed.toList();
    return Scaffold(
      backgroundColor: const Color(0xFFF7F7F7),
      appBar: AppBar(
        title: const Text('스윙 추이'),
        leading: IconButton(
          tooltip: '스윙 기록으로',
          onPressed: _backToList,
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
        ),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 840),
            child: RefreshIndicator(
              onRefresh: _load,
              child: CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(20, 24, 20, 16),
                    sliver: SliverToBoxAdapter(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            '나의 스윙 점수 변화',
                            style: TextStyle(
                              fontSize: 23,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 8),
                          const Text(
                            '기록을 쌓으며 종합 점수의 변화를 확인해보세요.',
                            style: TextStyle(
                              fontSize: 13,
                              color: AppColors.subtitle,
                            ),
                          ),
                          const SizedBox(height: 20),
                          Wrap(
                            spacing: 8,
                            runSpacing: 6,
                            children: [
                              for (final period in SwingTrendPeriod.values)
                                ChoiceChip(
                                  key: ValueKey('trend-period-${period.name}'),
                                  label: Text(period.label),
                                  selected: _period == period,
                                  selectedColor: AppColors.primary.withValues(
                                    alpha: .10,
                                  ),
                                  labelStyle: TextStyle(
                                    color: _period == period
                                        ? AppColors.primary
                                        : AppColors.gray600,
                                  ),
                                  side: BorderSide(
                                    color: _period == period
                                        ? AppColors.primary
                                        : AppColors.line,
                                  ),
                                  showCheckmark: false,
                                  onSelected: (_) => setState(() {
                                    _period = period;
                                    _selectedId = null;
                                  }),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text(
                            _period.days == null
                                ? '전체 기록 · 기기 현지 날짜 기준'
                                : '오늘 포함 ${_period.days}일 · 기기 현지 날짜 기준',
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.subtitle,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (_loading)
                    const SliverFillRemaining(
                      hasScrollBody: false,
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_error != null)
                    _message(
                      Icons.cloud_off_outlined,
                      '기록을 불러오지 못했어요',
                      _error!,
                      action: TextButton(
                        onPressed: Session.instance.isLoggedIn
                            ? _load
                            : () => context.go('/login'),
                        child: Text(
                          Session.instance.isLoggedIn ? '다시 시도' : '로그인하기',
                        ),
                      ),
                    )
                  else if (points.isEmpty)
                    _message(
                      Icons.show_chart,
                      _swings.isEmpty
                          ? '아직 스윙 기록이 없어요'
                          : trend.recordCount == 0
                          ? '선택한 기간에 기록이 없어요'
                          : '표시할 종합 점수가 없어요',
                      trend.recordCount == 0
                          ? '기간을 바꾸거나 스윙을 촬영해보세요.'
                          : '분석이 완료되고 유효한 점수가 있는 기록만 표시합니다.\n중복 ID의 내용이 서로 다르면 추이에서 제외합니다.',
                    )
                  else ...[
                    SliverPadding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      sliver: SliverToBoxAdapter(
                        child: Column(
                          children: [
                            _card(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      _metric('분석 기록', '${points.length}건'),
                                      _metric(
                                        '평균 점수',
                                        '${trend.average!.toStringAsFixed(1)}점',
                                      ),
                                      _metric(
                                        '첫 기록 대비',
                                        trend.change == null
                                            ? '비교 전'
                                            : '${trend.change! > 0 ? '+' : ''}${trend.change!.toStringAsFixed(1)}점',
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 22),
                                  const Text(
                                    '종합 점수',
                                    style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 10),
                                  SwingTrendChart(
                                    points: points,
                                    selectedId: selected!.analysisId,
                                    onSelect: (s) => setState(
                                      () => _selectedId = s.analysisId,
                                    ),
                                  ),
                                  Text(
                                    points.length == 1
                                        ? '기록이 1건이에요. 다음 점수가 쌓이면 변화를 비교할 수 있어요.'
                                        : '점을 누르면 기록을 선택할 수 있어요. 선은 실제 기록 사이의 변화만 연결합니다.',
                                    style: const TextStyle(
                                      fontSize: 12,
                                      color: AppColors.subtitle,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(height: 12),
                            Material(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(16),
                              child: InkWell(
                                key: const ValueKey('trend-selected-feedback'),
                                borderRadius: BorderRadius.circular(16),
                                onTap: () => _openFeedback(selected),
                                child: Padding(
                                  padding: const EdgeInsets.all(16),
                                  child: Row(
                                    children: [
                                      const Icon(
                                        Icons.insights_outlined,
                                        color: AppColors.primary,
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              '선택한 기록 · ${selected.score!.toStringAsFixed(1)}점',
                                              style: const TextStyle(
                                                fontWeight: FontWeight.w600,
                                              ),
                                            ),
                                            const SizedBox(height: 5),
                                            Text(
                                              _date(selected),
                                              style: const TextStyle(
                                                fontSize: 12,
                                                color: AppColors.subtitle,
                                              ),
                                            ),
                                            const SizedBox(height: 5),
                                            const Text(
                                              '종합 피드백 보기',
                                              style: TextStyle(
                                                fontSize: 13,
                                                color: AppColors.primary,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                      const Icon(
                                        Icons.chevron_right,
                                        color: AppColors.hint,
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                            if (trend.excludedCount +
                                    trend.conflictingCount +
                                    trend.duplicateCount >
                                0)
                              Padding(
                                padding: const EdgeInsets.only(top: 12),
                                child: Text(
                                  '집계 제외: 미완료·점수 없음/범위 오류 ${trend.excludedCount}건, 내용이 다른 중복 ID ${trend.conflictingCount}건. 동일한 중복 행 ${trend.duplicateCount}개는 한 번만 반영했습니다.',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: AppColors.subtitle,
                                  ),
                                ),
                              ),
                            const SizedBox(height: 24),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: Text(
                                '기간 내 기록 ${points.length}건',
                                style: const TextStyle(
                                  fontSize: 17,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            const SizedBox(height: 10),
                          ],
                        ),
                      ),
                    ),
                    SliverPadding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                      sliver: SliverList.builder(
                        itemCount: descending.length,
                        itemBuilder: (context, index) {
                          final swing = descending[index];
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Material(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(12),
                              child: ListTile(
                                key: ValueKey(
                                  'trend-record-${swing.analysisId}',
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                selected:
                                    swing.analysisId == selected.analysisId,
                                selectedTileColor: AppColors.primary.withValues(
                                  alpha: .05,
                                ),
                                title: Text(
                                  _date(swing),
                                  style: const TextStyle(fontSize: 13),
                                ),
                                subtitle: const Text(
                                  '분석 완료 · 종합 피드백',
                                  style: TextStyle(fontSize: 12),
                                ),
                                trailing: Text(
                                  '${swing.score!.toStringAsFixed(1)}점',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: AppColors.primary,
                                  ),
                                ),
                                onTap: () => _openFeedback(swing),
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: 1,
        selectedItemColor: AppColors.primary,
        unselectedItemColor: AppColors.hint,
        type: BottomNavigationBarType.fixed,
        onTap: (index) {
          if (index == 0) context.push('/swings/camera');
          if (index == 2) context.push('/profile');
        },
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.videocam_outlined),
            label: '스윙 촬영',
          ),
          BottomNavigationBarItem(icon: Icon(Icons.show_chart), label: '스윙 추이'),
          BottomNavigationBarItem(
            icon: Icon(Icons.person_outline),
            label: '프로필',
          ),
        ],
      ),
    );
  }

  Widget _card({required Widget child}) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
    ),
    child: child,
  );

  Widget _metric(String label, String value) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 12, color: AppColors.subtitle),
        ),
        const SizedBox(height: 6),
        Text(
          value,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );

  Widget _message(
    IconData icon,
    String title,
    String message, {
    Widget? action,
  }) => SliverFillRemaining(
    hasScrollBody: false,
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 46, color: AppColors.hint),
          const SizedBox(height: 16),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.subtitle),
          ),
          if (action != null) ...[const SizedBox(height: 12), action],
        ],
      ),
    ),
  );
}
