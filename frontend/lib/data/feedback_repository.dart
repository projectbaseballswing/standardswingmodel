import '../api/analysis_api.dart';
import '../models/feedback.dart';

/// 종합 피드백 데이터 공급.
///
/// ⚠️ 백엔드 연동 상태 ⚠️
///  - 첫 피드백([firstTime] == true): 실제로 GET /api/analyses/{id} 결과를
///    받아 매핑한다. 전체 점수·부위별 판정은 서버에서 온 진짜 값이다.
///  - 반복 피드백([firstTime] == false): "이전 대비 비교" 는 서버에 기록
///    저장(DB)·조회 API 가 생긴 뒤에야 가능하다. 그 전까지는 샘플을 쓴다.
///
/// 아직 백엔드가 주지 않아 프론트에서 임시로 채우는 값(교체 대상):
///  - 부위별 0~100 점수: z-score 로 환산한 임시값. [_scoreFromZ] 참고.
///  - summary / coachComment(AI 코치 문장): 규칙 기반 임시 문구.
class FeedbackRepository {
  FeedbackRepository({AnalysisApi? api}) : _api = api ?? AnalysisApi();

  final AnalysisApi _api;

  /// 분석 결과를 가져온다.
  ///
  /// [firstTime] 이 true 면 비교 대상이 없는 첫 피드백(실제 서버 결과)을,
  /// false 면 이전 스윙과 비교한 반복 피드백(아직 샘플)을 돌려준다.
  Future<OverallFeedback> fetchFeedback(
    String analysisId, {
    bool firstTime = false,
  }) async {
    if (firstTime) {
      final body = await _api.waitForReport(analysisId);
      return _mapReport(body);
    }
    // TODO(backend): 기록 저장(DB)·조회 API 가 생기면 이전 스윙과 비교해서 채운다.
    await Future<void>.delayed(const Duration(milliseconds: 200));
    return _sampleRepeat();
  }

  /// 서버 응답(GET /api/analyses/{id})을 첫 피드백 모델로 변환한다.
  OverallFeedback _mapReport(Map<String, dynamic> body) {
    final result = body['result'] as Map<String, dynamic>? ?? const {};
    final overall = result['overall'] as Map<String, dynamic>? ?? const {};
    final rawJoints = (result['joints'] as List?) ?? const [];

    final totalScore = _round(overall['score']);

    // 분석에 쓸 수 있는 관절만 추린다.
    final joints = rawJoints
        .whereType<Map<String, dynamic>>()
        .where((j) => j['available'] == true)
        .toList();

    final items = <FeedbackItem>[];
    for (final j in joints) {
      final impact = j['impact'] as Map<String, dynamic>? ?? const {};
      final z = (impact['z_score'] as num?)?.toDouble() ?? 0;
      items.add(FeedbackItem(
        label: (j['name'] as String?) ?? '관절',
        part: _partOf(j['body_part'] as String?),
        currentScore: _scoreFromZ(z),
        level: (j['level'] as String?) ?? 'good',
        description: (j['description'] as String?) ?? '',
      ));
    }

    return OverallFeedback(
      recordedAt: _parseTime(body['finished_at'] ?? body['created_at']),
      totalScore: totalScore,
      summary: _buildSummary(totalScore, items),
      coachComment: _buildCoach(items),
      items: items,
      // 첫 피드백이므로 previousTotalScore 는 주지 않는다.
    );
  }

  /// 서버의 body_part 를 화면 부위로 바꾼다.
  /// lead/rear 는 타석에서 투수 쪽/포수 쪽을 뜻하며, 좌우 구분이 필요해지면
  /// 서버가 함께 내려주는 body_part_name("왼쪽 팔" 등)을 쓰면 된다.
  BodyPart _partOf(String? bodyPart) {
    switch (bodyPart) {
      case 'leg':
      case 'lead_leg':
      case 'rear_leg':
        return BodyPart.leg;
      case 'arm':
      case 'lead_arm':
      case 'rear_arm':
        return BodyPart.arm;
      default:
        return BodyPart.torso;
    }
  }

  /// z-score → 0~100 임시 점수. 프로 기준에서 벗어날수록 낮아진다.
  /// TODO(backend): 서버가 부위별 점수를 직접 주면 그 값으로 교체.
  int _scoreFromZ(double z) {
    final score = (100 - z.abs() * 18).round();
    return score.clamp(0, 100);
  }

  int _round(dynamic v) => v is num ? v.round() : 0;

  DateTime _parseTime(dynamic v) {
    if (v is String) {
      final parsed = DateTime.tryParse(v);
      if (parsed != null) return parsed.toLocal();
    }
    return DateTime.now();
  }

  /// 점수 옆 분홍 박스 문구. (임시: 규칙 기반)
  String _buildSummary(int totalScore, List<FeedbackItem> items) {
    final worst = _worst(items);
    if (worst == null) {
      return '첫 스윙 분석 결과예요. 전체 점수는 $totalScore점이에요.';
    }
    return '첫 스윙 분석 결과예요. 프로 선수 기준과 비교했을 때 '
        '특히 ${worst.label} 부분을 더 살펴보면 좋아요.';
  }

  /// AI 코치의 한마디. (임시: 규칙 기반. 추후 LLM 문장으로 교체)
  String _buildCoach(List<FeedbackItem> items) {
    final goods = items.where((i) => i.level == 'good').toList();
    final worst = _worst(items);
    final sb = StringBuffer();
    if (goods.isNotEmpty) {
      sb.write('${goods.first.label}은(는) 프로 기준과 잘 맞아요. ');
    }
    if (worst != null) {
      sb.write('다음 스윙에서는 ${worst.label}에 더 집중해 보세요.');
    } else {
      sb.write('전반적으로 안정적인 스윙이에요.');
    }
    return sb.toString();
  }

  /// 프로 기준에서 가장 많이 벗어난(점수가 가장 낮은) 항목.
  FeedbackItem? _worst(List<FeedbackItem> items) {
    if (items.isEmpty) return null;
    return items
        .reduce((a, b) => a.currentScore <= b.currentScore ? a : b);
  }

  /// 반복 피드백 샘플(디자인 시안과 동일한 값).
  /// 이전 스윙과 비교해 증감(→, +8/-9)과 "개선 / 개선 필요 / 유지" 를 보여준다.
  OverallFeedback _sampleRepeat() {
    return OverallFeedback(
      recordedAt: DateTime(2024, 8, 8, 17, 30),
      totalScore: 61,
      previousTotalScore: 70,
      summary: '지난번보다 전체 점수가 소폭 하락했어요. 특히 오른쪽 팔의 움직임이 불안정해졌습니다.',
      coachComment:
          '전체적으로 하체의 안정성은 향상되었지만, 오른쪽 팔의 움직임이 이전보다 불안정해져 '
          '스윙 시 팔의 각도가 일찍 떨어지는 경향이 나타납니다. 다음 스윙에서는 오른쪽 팔의 '
          '각도를 일정하게 유지하는 데 집중해 보세요.',
      items: const [
        FeedbackItem(
          label: '왼쪽 다리',
          part: BodyPart.leg,
          currentScore: 80,
          previousScore: 72,
          description: '하체의 균형이 좋아지고, 체중 이동이 더 안정적으로 이루어졌습니다.',
        ),
        FeedbackItem(
          label: '왼쪽 팔',
          part: BodyPart.arm,
          currentScore: 74,
          previousScore: 65,
          description: '테이크백에서 임팩트까지 팔 궤도가 일정해져, 상체 회전과의 연결이 부드러워졌습니다.',
        ),
        FeedbackItem(
          label: '오른쪽 팔',
          part: BodyPart.arm,
          currentScore: 61,
          previousScore: 70,
          description: '스윙 시 오른쪽 팔의 움직임이 이전보다 다소 불안정해졌습니다.',
        ),
        FeedbackItem(
          label: '몸통',
          part: BodyPart.torso,
          currentScore: 76,
          previousScore: 75,
          description: '큰 변화 없이 안정적인 움직임을 유지하고 있습니다.',
        ),
      ],
    );
  }
}
