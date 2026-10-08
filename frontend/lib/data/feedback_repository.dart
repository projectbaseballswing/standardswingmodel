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
        phaseScores: _phaseScoresFromServer(j['phases']),
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

  BodyPart _partOf(String? bodyPart) {
    switch (bodyPart) {
      case 'leg':
        return BodyPart.leg;
      case 'arm':
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

  /// 서버 `phases`(구간별 z_score)를 [SwingPhase] 순서의 0~100 점수로 환산한다.
  /// 4구간(준비·로딩·스윙·팔로우스루)이 모두 있어야 쓰고, 하나라도 없으면 null.
  List<int>? _phaseScoresFromServer(dynamic phasesRaw) {
    if (phasesRaw is! List) return null;
    final byKey = <String, double>{};
    for (final p in phasesRaw.whereType<Map<String, dynamic>>()) {
      final key = p['phase'] as String?;
      final z = (p['z_score'] as num?)?.toDouble();
      if (key != null && z != null) byKey[key] = z;
    }
    if (!SwingPhase.values.every((ph) => byKey.containsKey(ph.key))) {
      return null;
    }
    return [for (final ph in SwingPhase.values) _scoreFromZ(byKey[ph.key]!)];
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

  // -------------------------------------------------------------------------
  // 관절별 분석(상세 피드백)
  // -------------------------------------------------------------------------

  /// 종합 피드백을 관절별 상세 분석 목록으로 펼친다.
  ///
  /// ⚠️ 백엔드 연동 상태 ⚠️
  ///  - 이름·현재/이전 점수·변화 상태는 종합 피드백(실제 값)에서 그대로 온다.
  ///  - 단계별(스윙 4구간) 점수 그래프는 서버 phases(z_score)를 환산한 실제 값.
  ///    코치 문장·포인트는 아직 규칙 기반 임시 문구라, 백엔드 LLM 문장이
  ///    생기면 이 부분을 교체한다.
  List<JointAnalysis> buildJointAnalyses(OverallFeedback feedback) {
    final list = <JointAnalysis>[];
    for (var i = 0; i < feedback.items.length; i++) {
      final item = feedback.items[i];
      final status = _statusOf(item, isFirst: feedback.isFirst);
      final hasPrev = item.previousScore != null;
      final needWork =
          status == JointStatus.worsened || status == JointStatus.proBad;
      list.add(JointAnalysis(
        label: item.label,
        part: item.part,
        status: status,
        currentScore: item.currentScore,
        previousScore: item.previousScore,
        // 서버 구간 점수가 있으면 실제 값을, 없으면(샘플 등) 임시로 채운다.
        currentPhaseScores:
            item.phaseScores ?? _phaseScores(item.currentScore, seed: i),
        previousPhaseScores:
            hasPrev ? _phaseScores(item.previousScore!, seed: i + 7) : null,
        summary: _jointSummary(item, status),
        coachComment: _jointCoach(item, status),
        pointsTitle: needWork ? '개선 포인트' : '유지 포인트',
        points: _jointPoints(item, status),
      ));
    }
    return list;
  }

  /// 관절 상태를 정한다.
  ///  - 첫 피드백([isFirst]): 비교 대상이 없으니 프로 기준(level) 대비로
  ///    "잘함([proGood]) / 개선 필요([proBad])" 를 나눈다.
  ///  - 반복 피드백: 이전 대비 증감으로 개선/개선 필요/변화 없음을 나눈다.
  JointStatus _statusOf(FeedbackItem item, {required bool isFirst}) {
    if (isFirst) {
      return item.level == 'good' ? JointStatus.proGood : JointStatus.proBad;
    }
    final delta = item.delta;
    if (delta == null) return JointStatus.limited;
    const band = 2; // |증감| 이 이 값 이하면 "변화 없음".
    if (delta > band) return JointStatus.improved;
    if (delta < -band) return JointStatus.worsened;
    return JointStatus.unchanged;
  }

  /// 기준 점수 주변으로 구간별 점수를 만든다. (임시: 그래프 모양만 자연스럽게)
  /// 서버 구간 점수가 없는 경우(반복 피드백 샘플 등)에만 폴백으로 쓴다.
  List<int> _phaseScores(int base, {required int seed}) {
    // 구간마다 적용할 가감 패턴(준비·로딩·스윙·팔로우스루). 스윙 구간이 가장 높게.
    const wiggle = [-5, -2, 6, -4];
    return [
      for (var p = 0; p < wiggle.length; p++)
        (base + wiggle[p] + ((seed + p) % 3 - 1) * 2).clamp(0, 100),
    ];
  }

  String _jointSummary(FeedbackItem item, JointStatus status) {
    switch (status) {
      case JointStatus.improved:
        return '${item.label}의 움직임이 이전보다 안정적으로 개선되었습니다.\n'
            '특히 스윙 중 각도가 기준 스윙에 더 가까워졌습니다.';
      case JointStatus.worsened:
        return '${item.label}의 움직임이 이전보다 다소 불안정해졌습니다.\n'
            '특히 스윙 중 각도가 기준 스윙과 더 큰 차이를 보였습니다.';
      case JointStatus.unchanged:
        return '${item.label}의 움직임은 이전과 비슷하게 유지되고 있습니다.';
      case JointStatus.limited:
        return item.description.isNotEmpty
            ? item.description
            : '${item.label}은(는) 비교할 이전 스윙이 없어 이번 결과만 보여드려요.';
      case JointStatus.proGood:
        return '${item.label}의 움직임이 프로 선수 기준과 잘 맞는 편이에요.\n'
            '스윙 중 각도가 기준 스윙과 가깝게 유지되고 있습니다.';
      case JointStatus.proBad:
        return '${item.label}의 움직임이 프로 선수 기준과 다소 차이가 있어요.\n'
            '스윙 중 각도가 기준 스윙과 차이를 보이니 더 살펴보면 좋아요.';
    }
  }

  String _jointCoach(FeedbackItem item, JointStatus status) {
    switch (status) {
      case JointStatus.improved:
        return '이번 스윙에서 ${item.label}의 움직임이 이전보다 안정적으로 유지되었습니다.\n'
            '스윙 구간에서 각도가 끝까지 유지되어, 기준 스윙과의 차이가 줄었습니다.';
      case JointStatus.worsened:
        return '이번 스윙에서 ${item.label}의 움직임이 이전보다 다소 불안정해졌습니다.\n'
            '스윙 구간에서 각도가 일찍 무너지는 경향이 나타나며, 기준 스윙과의 차이가 커졌습니다.';
      case JointStatus.unchanged:
        return '이번 스윙에서 ${item.label}의 움직임은 이전과 큰 차이 없이 유지되었습니다.\n'
            '안정적인 흐름이니 지금 리듬을 그대로 이어가 보세요.';
      case JointStatus.limited:
        return '${item.label}은(는) 비교할 이전 스윙이 아직 없어 변화는 보여드릴 수 없어요.\n'
            '다음 스윙을 촬영하면 이번 결과와 비교해 변화를 알려드릴게요.';
      case JointStatus.proGood:
        return '${item.label}의 움직임이 프로 선수 기준과 잘 맞는 편이에요.\n'
            '지금의 안정적인 각도를 그대로 유지해 보세요.';
      case JointStatus.proBad:
        return '${item.label}의 움직임이 프로 선수 기준과 다소 차이가 있어요.\n'
            '스윙 구간에서 각도가 기준보다 일찍 무너지지 않도록 집중해 보세요.';
    }
  }

  List<String> _jointPoints(FeedbackItem item, JointStatus status) {
    switch (status) {
      case JointStatus.worsened:
        return [
          '스윙 구간까지 각도를 유지해 보세요.',
          '스윙 시 ${item.label}이(가) 몸에서 너무 일찍 떨어지지 않도록 주의하세요.',
          '다음 스윙에서는 하체와 상체의 회전에 맞춰 자연스럽게 따라오도록 연습해 보세요.',
        ];
      case JointStatus.improved:
        return [
          '지금의 각도 유지 흐름을 그대로 이어가 보세요.',
          '스윙 구간에서 ${item.label}과(와) 몸의 간격이 안정적으로 유지되고 있어요.',
          '다음 스윙에서도 하체 회전과 타이밍을 같은 리듬으로 가져가 보세요.',
        ];
      case JointStatus.unchanged:
        return [
          '현재의 안정적인 움직임을 유지해 보세요.',
          '무리하게 바꾸기보다 지금 리듬을 반복해 몸에 익혀 보세요.',
        ];
      case JointStatus.limited:
        return [
          '다음 스윙을 촬영하면 이번 결과와 비교해 변화를 확인할 수 있어요.',
        ];
      case JointStatus.proGood:
        return [
          '지금의 안정적인 각도 흐름을 그대로 유지해 보세요.',
          '${item.label}과(와) 몸의 간격이 기준 스윙과 잘 맞고 있어요.',
          '다음 스윙에서도 같은 리듬으로 가져가 보세요.',
        ];
      case JointStatus.proBad:
        return [
          '스윙 구간까지 ${item.label}의 각도를 유지해 보세요.',
          '스윙 시 ${item.label}이(가) 몸에서 너무 일찍 떨어지지 않도록 주의하세요.',
          '하체와 상체의 회전에 맞춰 자연스럽게 따라오도록 연습해 보세요.',
        ];
    }
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
