import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api/auth_api.dart' show ApiException;
import '../data/session.dart';
import '../data/swing_repository.dart';
import '../models/swing.dart';
import '../route_observer.dart';
import '../theme/app_theme.dart';

/// 스윙 목록 화면 (로그인 후 첫 화면).
///
/// 달력에서 촬영한 날짜에 썸네일을 보여주고, 날짜를 선택하면 아래에 그날의
/// 스윙 영상들이 나온다. 과거 피드백 화면 연결은 다음 작업이다.
class SwingListScreen extends StatefulWidget {
  const SwingListScreen({super.key, this.repository});

  final SwingRepository? repository;

  @override
  State<SwingListScreen> createState() => _SwingListScreenState();
}

class _SwingListScreenState extends State<SwingListScreen> with RouteAware {
  late final SwingRepository _repository;
  ModalRoute<dynamic>? _route;
  int _requestId = 0;

  List<Swing> _swings = [];
  bool _loading = true;
  String? _error;

  // 달력에 표시할 기준 달과, 현재 선택된 날짜.
  late DateTime _month;
  DateTime? _selectedDay;

  // 우측 상단 프로필 아바타 hover 상태(웹/데스크톱에서 마우스 올렸을 때).
  bool _avatarHovering = false;

  @override
  void initState() {
    super.initState();
    _repository = widget.repository ?? SwingRepository();
    final now = DateTime.now();
    _month = DateTime(now.year, now.month);
    _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != _route) {
      swingRouteObserver.unsubscribe(this);
      _route = route;
      if (route != null) swingRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didPopNext() {
    // 카메라 push의 Future는 pushReplacement 시점에 끝날 수 있으므로,
    // 실제 결과 화면에서 목록으로 돌아왔을 때 다시 조회한다.
    _load();
  }

  @override
  void dispose() {
    swingRouteObserver.unsubscribe(this);
    if (widget.repository == null) _repository.dispose();
    super.dispose();
  }

  DateTime _defaultDay(DateTime month) {
    final now = DateTime.now();
    return now.year == month.year && now.month == month.month
        ? DateTime(now.year, now.month, now.day)
        : month;
  }

  Future<void> _load() async {
    final requestId = ++_requestId;
    final month = _month;
    setState(() {
      _loading = true;
      _error = null;
      _swings = [];
      _selectedDay = _defaultDay(month);
    });
    try {
      final swings = await _repository.fetchMySwings(
        year: month.year,
        month: month.month,
      );
      if (!mounted || requestId != _requestId) return;
      setState(() {
        _swings = swings;
        _loading = false;
        if (swings.isNotEmpty) {
          final latest = swings.first.recordedAt;
          if (latest.year == month.year && latest.month == month.month) {
            _selectedDay = DateTime(latest.year, latest.month, latest.day);
          }
        }
      });
    } on ApiException catch (e) {
      if (!mounted || requestId != _requestId) return;
      setState(() {
        _loading = false;
        _error = e.message;
      });
    }
  }

  // 이전/다음 달로 이동. delta: -1 = 이전 달, +1 = 다음 달.
  void _changeMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta);
    });
    _load();
  }

  List<Swing> _swingsOn(DateTime day) =>
      _swings.where((s) => s.isOnDay(day)).toList()
        ..sort((a, b) => b.recordedAt.compareTo(a.recordedAt));

  void _openFeedback(Swing swing) {
    final message = switch (swing.status) {
      'queued' || 'processing' => '분석이 진행 중입니다. 잠시 후 다시 확인해주세요.',
      'failed' => '분석에 실패한 기록입니다. 영상을 다시 업로드해주세요.',
      _ => '과거 스윙의 분석 결과 조회는 준비 중입니다.',
    };
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selectedDay ?? DateTime.now();
    final daySwings = _swingsOn(selected);
    final days = DateTime(_month.year, _month.month + 1, 0).day;
    final rows = ((_month.weekday % 7 + days) / 7).ceil();
    // 64px 달력 셀과 기존 배치를 유지하되 작은 화면에서도 상태/재시도를 볼 수 있게 한다.
    final minimumHeight = rows * 68.0 + 340;

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: SizedBox(
              height: constraints.maxHeight < minimumHeight
                  ? minimumHeight
                  : constraints.maxHeight,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _header(),
                  const SizedBox(height: 8),
                  _weekdayRow(),
                  const Divider(height: 1),
                  _calendarGrid(),
                  const Divider(height: 1),
                  Expanded(child: _listContent(selected, daySwings)),
                ],
              ),
            ),
          ),
        ),
      ),
      bottomNavigationBar: _bottomNav(),
    );
  }

  Widget _listContent(DateTime selected, List<Swing> daySwings) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, textAlign: TextAlign.center),
            TextButton(onPressed: _load, child: const Text('다시 시도')),
          ],
        ),
      );
    }
    return _daySection(selected, daySwings);
  }

  // 상단: 프로필 아바타 + "N월" + 목록/추가 아이콘.
  Widget _header() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: MouseRegion(
              cursor: SystemMouseCursors.click,
              onEnter: (_) => setState(() => _avatarHovering = true),
              onExit: (_) => setState(() => _avatarHovering = false),
              child: GestureDetector(
                onTap: _openProfile,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 120),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    // hover 시 테두리 강조 + 은은한 그림자로 눌리는 느낌.
                    border: Border.all(
                      color: _avatarHovering
                          ? AppColors.primary
                          : Colors.transparent,
                      width: 2,
                    ),
                    boxShadow: _avatarHovering
                        ? [
                            BoxShadow(
                              color: AppColors.primary.withValues(alpha: 0.25),
                              blurRadius: 8,
                            ),
                          ]
                        : null,
                  ),
                  child: Stack(
                    children: [
                      CircleAvatar(
                        radius: 20,
                        backgroundColor: AppColors.fieldFill,
                        backgroundImage: Session.instance.profileImage != null
                            ? MemoryImage(Session.instance.profileImage!)
                            : null,
                        child: Session.instance.profileImage == null
                            ? const Icon(Icons.person, color: AppColors.hint)
                            : null,
                      ),
                      // hover 시 살짝 어두운 오버레이로 클릭 가능함을 표시.
                      if (_avatarHovering)
                        Positioned.fill(
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: Colors.black.withValues(alpha: 0.06),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              // 연도는 올해가 아닐 때만 보조로 표시.
              if (_month.year != DateTime.now().year) ...[
                Text(
                  '${_month.year}년 ',
                  style: const TextStyle(fontSize: 15, color: AppColors.hint),
                ),
              ],
              Text(
                '${_month.month}월',
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                ),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_left),
                onPressed: () => _changeMonth(-1),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right),
                onPressed: () => _changeMonth(1),
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.view_list_outlined),
                onPressed: () {
                  // TODO(next): 리스트(목록형) 보기 전환.
                },
              ),
              IconButton(icon: const Icon(Icons.add), onPressed: _openCamera),
            ],
          ),
        ],
      ),
    );
  }

  Widget _weekdayRow() {
    const labels = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Row(
        children: labels
            .map(
              (d) => Expanded(
                child: Center(
                  child: Text(
                    d,
                    style: const TextStyle(
                      color: AppColors.hint,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            )
            .toList(),
      ),
    );
  }

  // 달력 그리드: 일요일 시작. 스윙이 있는 날은 썸네일 배경을 깐다.
  Widget _calendarGrid() {
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    // 이 달 1일의 요일(일=0 ~ 토=6)만큼 앞을 비운다.
    final leadingBlank = DateTime(_month.year, _month.month, 1).weekday % 7;
    final totalCells = leadingBlank + daysInMonth;
    final rows = (totalCells / 7).ceil();

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Column(
        children: List.generate(rows, (row) {
          return Row(
            children: List.generate(7, (col) {
              final cellIndex = row * 7 + col;
              final dayNum = cellIndex - leadingBlank + 1;
              if (dayNum < 1 || dayNum > daysInMonth) {
                return const Expanded(child: SizedBox(height: 64));
              }
              final date = DateTime(_month.year, _month.month, dayNum);
              return Expanded(child: _dayCell(date, dayNum));
            }),
          );
        }),
      ),
    );
  }

  Widget _dayCell(DateTime date, int dayNum) {
    final swings = _swingsOn(date);
    final hasSwing = swings.isNotEmpty;
    final isSelected =
        _selectedDay != null &&
        date.year == _selectedDay!.year &&
        date.month == _selectedDay!.month &&
        date.day == _selectedDay!.day;

    return GestureDetector(
      onTap: () => setState(() => _selectedDay = date),
      behavior: HitTestBehavior.opaque,
      child: Container(
        height: 64,
        margin: const EdgeInsets.all(2),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: isSelected
              ? Border.all(color: AppColors.primary, width: 1.5)
              : null,
        ),
        child: Stack(
          children: [
            // 스윙이 있으면 썸네일 자리(placeholder)를 깐다.
            if (hasSwing)
              Positioned.fill(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: Container(
                    color: AppColors.fieldFill,
                    child: const Icon(
                      Icons.sports_baseball,
                      color: AppColors.hint,
                      size: 20,
                    ),
                  ),
                ),
              ),
            // 날짜 숫자. 스윙이 있으면 가독성 위해 고정 크기 원 배지로.
            // (한 자리/두 자리 상관없이 원 크기·폰트가 동일하도록 고정 width/height 사용)
            Padding(
              padding: const EdgeInsets.all(4),
              child: Container(
                width: 22,
                height: 22,
                alignment: Alignment.center,
                decoration: hasSwing
                    ? const BoxDecoration(
                        color: AppColors.primary,
                        shape: BoxShape.circle,
                      )
                    : null,
                child: Text(
                  '$dayNum',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: hasSwing ? Colors.white : Colors.black87,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // 하단: 선택한 날짜 + 그날 스윙 썸네일 가로 목록.
  Widget _daySection(DateTime day, List<Swing> daySwings) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${day.month}월 ${day.day}일',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: daySwings.isEmpty
                ? Center(
                    child: Text(
                      _swings.isEmpty
                          ? '이번 달의 스윙 기록이 없습니다.'
                          : '이 날 촬영한 스윙이 없습니다.',
                      style: TextStyle(color: AppColors.hint),
                    ),
                  )
                : ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: daySwings.length,
                    separatorBuilder: (context, index) =>
                        const SizedBox(width: 12),
                    itemBuilder: (context, index) =>
                        _swingThumb(daySwings[index]),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _swingThumb(Swing swing) {
    return GestureDetector(
      onTap: () => _openFeedback(swing),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          // 남는 높이에 맞춰 썸네일이 줄어들도록 Expanded 로 감싼다.
          // (가로 리스트 높이가 가변이라 고정 높이면 몇 px 넘칠 수 있다.)
          Expanded(
            child: Container(
              width: 120,
              decoration: BoxDecoration(
                color: AppColors.fieldFill,
                borderRadius: BorderRadius.circular(8),
              ),
              child: swing.thumbnailUrl == null
                  ? _thumbnailPlaceholder()
                  : ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.network(
                        swing.thumbnailUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stackTrace) =>
                            _thumbnailPlaceholder(),
                      ),
                    ),
            ),
          ),
          const SizedBox(height: 6),
          Text(swing.timeLabel, style: const TextStyle(fontSize: 13)),
          Text(
            _statusLabel(swing),
            style: const TextStyle(fontSize: 12, color: AppColors.hint),
          ),
        ],
      ),
    );
  }

  Widget _thumbnailPlaceholder() =>
      const Icon(Icons.play_circle_outline, color: AppColors.hint, size: 32);

  String _statusLabel(Swing swing) => switch (swing.status) {
    'queued' => '분석 대기 중',
    'processing' => '분석 중',
    'failed' => '분석 실패',
    'done' =>
      swing.score == null
          ? '분석 완료'
          : '완료 · ${swing.score!.toStringAsFixed(1)}점',
    _ => '상태 확인 중',
  };

  // 스윙 촬영 화면으로 이동.
  void _openCamera() => context.push('/swings/camera');

  // 프로필 화면으로 이동(우측 상단 아바타 / 하단 "프로필" 탭).
  // 프로필에서 사진을 바꾸고 돌아오면 상단 아바타에 반영되도록 갱신한다.
  Future<void> _openProfile() async {
    await context.push('/profile');
    if (mounted) setState(() {});
  }

  Widget _bottomNav() {
    return BottomNavigationBar(
      currentIndex: 0,
      selectedItemColor: AppColors.primary,
      unselectedItemColor: AppColors.hint,
      type: BottomNavigationBarType.fixed,
      onTap: (index) {
        // 0: 스윙 촬영, 2: 프로필. 1(스윙 추이)은 다음 작업에서 연결.
        if (index == 0) _openCamera();
        if (index == 2) _openProfile();
      },
      items: const [
        BottomNavigationBarItem(
          icon: Icon(Icons.videocam_outlined),
          label: '스윙 촬영',
        ),
        BottomNavigationBarItem(icon: Icon(Icons.show_chart), label: '스윙 추이'),
        BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: '프로필'),
      ],
    );
  }
}
