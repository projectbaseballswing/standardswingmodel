import '../api/auth_api.dart' show ApiException;
import '../api/swing_api.dart';
import '../models/swing.dart';
import 'session.dart';

/// 로그인한 사용자의 월별 스윙 기록을 가져온다.
class SwingRepository {
  SwingRepository({SwingApi? api}) : _api = api ?? SwingApi();

  final SwingApi _api;

  Future<List<Swing>> fetchMySwings({
    required int year,
    required int month,
  }) async {
    final userId = Session.instance.userId;
    if (userId == null || userId.trim().isEmpty) {
      throw ApiException('로그인한 뒤 스윙 기록을 확인해주세요.');
    }
    // 달력과 recordedAt 모두 기기 로컬 시간 기준. 조회 월의 오프셋을 전달한다.
    final items = await _api.fetchSwings(
      userId: userId,
      year: year,
      month: month,
      tzOffsetMinutes: DateTime(year, month).timeZoneOffset.inMinutes,
    );
    if (Session.instance.userId != userId) {
      throw ApiException('로그인 정보가 변경되었습니다. 다시 조회해주세요.');
    }
    try {
      return items.map(Swing.fromJson).toList();
    } on FormatException {
      throw ApiException('스윙 기록의 날짜 형식이 올바르지 않습니다.');
    } on TypeError {
      throw ApiException('스윙 목록 응답 형식이 올바르지 않습니다.');
    }
  }

  void dispose() => _api.dispose();
}
