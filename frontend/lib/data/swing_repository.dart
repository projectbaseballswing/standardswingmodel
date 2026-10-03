import '../models/swing.dart';

/// 스윙 목록 데이터 공급.
///
/// ⚠️ 백엔드 교체 지점 ⚠️
/// 아직 "내 스윙 목록" 조회 API 가 없어서 지금은 임시 데이터를 돌려준다.
/// 백엔드에 목록 API(예: GET /api/me/analyses)가 생기면
/// [fetchMySwings] 의 내용만 실제 호출로 바꾸면 되고, 화면 코드는 건드릴 필요 없다.
/// 그때 아래 [_buildSampleSwings] 임시 데이터는 삭제한다.
class SwingRepository {
  /// 내 스윙 전체 목록을 가져온다.
  Future<List<Swing>> fetchMySwings() async {
    // TODO(backend): 아래 임시 데이터를 실제 API 호출로 교체.
    //   final res = await _authApi.fetchMySwings(userId);
    //   return res;
    await Future<void>.delayed(const Duration(milliseconds: 200)); // 로딩 느낌용
    return _buildSampleSwings();
  }

  /// 이번 달의 2·6·10·11일에 스윙이 있는 것으로 꾸민 임시 데이터.
  /// TODO(backend): 실제 연동 후 이 메서드는 통째로 삭제.
  List<Swing> _buildSampleSwings() {
    final now = DateTime.now();
    DateTime at(int day, int hour, int minute) =>
        DateTime(now.year, now.month, day, hour, minute);

    return [
      Swing(analysisId: 's-2-1', recordedAt: at(2, 14, 5), score: 78),
      Swing(analysisId: 's-6-1', recordedAt: at(6, 16, 30), score: 82),
      Swing(analysisId: 's-6-2', recordedAt: at(6, 15, 3), score: 75),
      Swing(analysisId: 's-6-3', recordedAt: at(6, 11, 20), score: 70),
      Swing(analysisId: 's-10-1', recordedAt: at(10, 9, 40), score: 69),
      Swing(analysisId: 's-11-1', recordedAt: at(11, 18, 12), score: 73),
    ];
  }
}
