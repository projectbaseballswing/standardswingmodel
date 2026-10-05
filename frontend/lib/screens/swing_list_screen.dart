import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../data/swing_repository.dart';
import '../models/swing.dart';
import '../theme/app_theme.dart';

/// 스윙 목록 화면 (로그인 후 첫 화면).
///
/// 달력에서 촬영한 날짜에 썸네일을 보여주고, 날짜를 선택하면 아래에 그날의
/// 스윙 영상들이 나온다. 영상을 누르면 피드백 화면으로 이동한다(다음 작업).
class SwingListScreen extends StatefulWidget {
  const SwingListScreen({super.key});

  @override
  State<SwingListScreen> createState() => _SwingListScreenState();
}

class _SwingListScreenState extends State<SwingListScreen> {
  final _repository = SwingRepository();

  List<Swing> _swings = [];
  bool _loading = true;

  // 달력에 표시할 기준 달과, 현재 선택된 날짜.
  late DateTime _month;
  DateTime? _selectedDay;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _month = DateTime(now.year, now.month);
    _load();
  }

  Future<void> _load() async {
    final swings = await _repository.fetchMySwings();
    if (!mounted) return;
    setState(() {
      _swings = swings;
      _loading = false;
      // 스윙이 있는 첫 날짜를 기본 선택(없으면 오늘).
      _selectedDay = swings.isNotEmpty
          ? DateTime(swings.first.recordedAt.year,
              swings.first.recordedAt.month, swings.first.recordedAt.day)
          : DateTime.now();
    });
  }

  // 이전/다음 달로 이동. delta: -1 = 이전 달, +1 = 다음 달.
  void _changeMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta);
    });
  }

  List<Swing> _swingsOn(DateTime day) =>
      _swings.where((s) => s.isOnDay(day)).toList()
        ..sort((a, b) => b.recordedAt.compareTo(a.recordedAt));

  void _openFeedback(Swing swing) {
    // 목록에서 연 스윙은 이전 스윙과 비교하는 반복 피드백으로 본다.
    context.push('/analyses/${swing.analysisId}');
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selectedDay ?? DateTime.now();
    final daySwings = _swingsOn(selected);

    return Scaffold(
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _header(),
                  const SizedBox(height: 8),
                  _weekdayRow(),
                  const Divider(height: 1),
                  _calendarGrid(),
                  const Divider(height: 1),
                  Expanded(child: _daySection(selected, daySwings)),
                ],
              ),
      ),
      bottomNavigationBar: _bottomNav(),
    );
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
            child: CircleAvatar(
              radius: 20,
              backgroundColor: AppColors.fieldFill,
              child: const Icon(Icons.person, color: AppColors.hint),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              // 연도는 올해가 아닐 때만 보조로 표시.
              if (_month.year != DateTime.now().year) ...[
                Text('${_month.year}년 ',
                    style: const TextStyle(
                        fontSize: 15, color: AppColors.hint)),
              ],
              Text(
                '${_month.month}월',
                style: const TextStyle(
                    fontSize: 24, fontWeight: FontWeight.w700),
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
              IconButton(
                icon: const Icon(Icons.add),
                onPressed: _openCamera,
              ),
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
            .map((d) => Expanded(
                  child: Center(
                    child: Text(d,
                        style: const TextStyle(
                            color: AppColors.hint,
                            fontWeight: FontWeight.w600)),
                  ),
                ))
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
    final isSelected = _selectedDay != null &&
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
                    child: const Icon(Icons.sports_baseball,
                        color: AppColors.hint, size: 20),
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
                        color: AppColors.primary, shape: BoxShape.circle)
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
          Text('${day.month}월 ${day.day}일',
              style:
                  const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          Expanded(
            child: daySwings.isEmpty
                ? const Center(
                    child: Text('이 날 촬영한 스윙이 없습니다.',
                        style: TextStyle(color: AppColors.hint)),
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
              child: const Icon(Icons.play_circle_outline,
                  color: AppColors.hint, size: 32),
            ),
          ),
          const SizedBox(height: 6),
          Text(swing.timeLabel, style: const TextStyle(fontSize: 13)),
        ],
      ),
    );
  }

  // 스윙 촬영 화면으로 이동.
  void _openCamera() => context.push('/swings/camera');

  Widget _bottomNav() {
    return BottomNavigationBar(
      currentIndex: 0,
      selectedItemColor: AppColors.primary,
      unselectedItemColor: AppColors.hint,
      type: BottomNavigationBarType.fixed,
      onTap: (index) {
        // 0: 스윙 촬영. 1·2 는 다음 작업에서 연결.
        if (index == 0) _openCamera();
      },
      items: const [
        BottomNavigationBarItem(
            icon: Icon(Icons.videocam_outlined), label: '스윙 촬영'),
        BottomNavigationBarItem(
            icon: Icon(Icons.show_chart), label: '스윙 추이'),
        BottomNavigationBarItem(
            icon: Icon(Icons.person_outline), label: '프로필'),
      ],
    );
  }
}
