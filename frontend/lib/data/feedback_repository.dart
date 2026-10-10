import 'dart:math';

import '../api/analysis_api.dart';
import '../models/feedback.dart';

/// 종합 피드백 데이터 공급.
///
/// ⚠️ 백엔드 연동 상태 ⚠️
///  - 첫 피드백([firstTime] == true): 실제로 GET /api/analyses/{id} 결과를
///    받아 매핑한다. 전체 점수·부위별 점수·세부 항목은 서버에서 온 진짜 값이다.
///  - 반복 피드백([firstTime] == false): "이전 대비 비교" 는 서버에 기록
///    저장(DB)·조회 API 가 생긴 뒤에야 가능하다. 그 전까지는 샘플을 쓴다.
///
/// 아직 백엔드가 주지 않아 프론트에서 임시로 채우는 값(교체 대상):
///  - summary / coachComment / 포인트(AI 코치 문장): 규칙 기반 임시 문구.
///
/// ★ 부위별 0~100 점수는 서버 overall.group_scores 의 실제 score 를 쓴다.
class FeedbackRepository {
  FeedbackRepository({AnalysisApi? api}) : _api = api ?? AnalysisApi();

  final AnalysisApi _api;

  /// 부위 점수가 이 값 이상이면 "잘함", 미만이면 "개선 필요" 로 본다.
  /// distance_to_score 가 "프로 평균 거리 = 80점" 이라, 프로 평균 수준을 기준선으로 둔다.
  static const int _goodScore = 80;

  /// 분석 결과를 가져온다.
  ///
  /// [firstTime] 이 true 면 비교 대상이 없는 첫 피드백(실제 서버 결과)을,
  /// false 면 이전 스윙과 비교한 반복 피드백(아직 샘플)을 돌려준다.
  Future<OverallFeedback> fetchFeedback(
    String analysisId, {
    bool firstTime = false,
  }) async {
    if (firstTime) {
      // 상세 그래프용 80점 시계열이 필요하므로 series 를 포함해 받는다.
      final body = await _api.waitForReport(analysisId, includeSeries: true);
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
    final rawGroups = (overall['group_scores'] as List?) ?? const [];

    final totalScore = _round(overall['score']);

    // 부위별 세부 항목(피처)을 모은다.
    // 신뢰도 낮음(뒷팔 팔꿈치 등)과 미측정 항목은 뺀다 — 서버도 종합/상세에서 제외한다.
    final featuresByPart = <String, List<FeatureAnalysis>>{};
    for (final j in rawJoints.whereType<Map<String, dynamic>>()) {
      if (j['available'] != true || j['reliability'] == 'low') continue;
      final part = (j['body_part'] as String?) ?? 'other';
      (featuresByPart[part] ??= []).add(_mapFeature(j));
    }

    // 부위(그룹) 단위로 묶는다. 점수는 group_scores.score 실제값.
    final items = <FeedbackItem>[];
    for (final g in rawGroups.whereType<Map<String, dynamic>>()) {
      if (g['available'] != true) continue;
      final key = (g['key'] as String?) ?? '';
      final features = featuresByPart[key] ?? const <FeatureAnalysis>[];
      // 믿을 만한 세부 항목이 하나도 없는 부위(뒷팔 등)는 보여주지 않는다.
      if (features.isEmpty) continue;
      final score = _round(g['score']);
      items.add(FeedbackItem(
        key: key,
        label: (g['name'] as String?) ?? '부위',
        part: _partOf(key),
        currentScore: score,
        level: score >= _goodScore ? 'good' : 'caution',
        description: _partDescription(features),
        reliability: (g['reliability'] as String?) ?? 'high',
        features: features,
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

  /// 서버 joints[] 한 건을 세부 항목으로 변환한다.
  FeatureAnalysis _mapFeature(Map<String, dynamic> j) {
    return FeatureAnalysis(
      key: (j['key'] as String?) ?? '',
      name: (j['name'] as String?) ?? '항목',
      level: (j['level'] as String?) ?? 'good',
      direction: _worstPhaseDirection(j),
      unit: (j['unit'] as String?) ?? 'deg',
      description: (j['description'] as String?) ?? '',
      impact: _measure(j['impact']),
      rangeOfMotion: _measure(j['range_of_motion']),
      series: _series(j['series']),
      phaseScores: _phaseScores(j['phases']),
    );
  }

  /// 구간별 z_score → SwingPhase 순서의 0~100 점수. 4구간이 다 있어야 쓴다.
  /// 서버가 구간별 피처 점수를 직접 주지 않아 환산한 임시값이다.
  List<int>? _phaseScores(dynamic phasesRaw) {
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

  /// z-score(표준편차 단위) → 0~100 점수.
  /// |z|=1(프로 변동 경계, level good 의 끝)을 80점(_goodScore)에 맞춘다: 100·0.8^|z|.
  int _scoreFromZ(double z) => (100 * pow(0.8, z.abs())).round().clamp(0, 100);

  /// 가장 많이 어긋난 구간(worst_phase)의 방향을 피처 대표 방향으로 쓴다.
  String _worstPhaseDirection(Map<String, dynamic> j) {
    final worst = j['worst_phase'] as String?;
    final phases = (j['phases'] as List?) ?? const [];
    for (final p in phases.whereType<Map<String, dynamic>>()) {
      if (p['phase'] == worst) return (p['direction'] as String?) ?? 'similar';
    }
    return 'similar';
  }

  /// {user, reference, diff} → [Measure]. 없으면 null.
  Measure? _measure(dynamic raw) {
    if (raw is! Map) return null;
    double? d(dynamic v) => (v as num?)?.toDouble();
    return Measure(
      user: d(raw['user']),
      reference: d(raw['reference']),
      diff: d(raw['diff']),
    );
  }

  /// {user:[80], reference:[80], reference_std:[80]} → 시계열 목록. 없으면 null.
  List<SeriesSample>? _series(dynamic raw) {
    if (raw is! Map) return null;
    final user = (raw['user'] as List?) ?? const [];
    final ref = (raw['reference'] as List?) ?? const [];
    final std = (raw['reference_std'] as List?) ?? const [];
    final n = ref.length;
    if (n == 0) return null;
    double? at(List l, int i) => i < l.length ? (l[i] as num?)?.toDouble() : null;
    return [
      for (var i = 0; i < n; i++)
        SeriesSample(
          user: at(user, i),
          reference: at(ref, i),
          referenceStd: at(std, i),
        ),
    ];
  }

  /// 서버의 그룹 키를 화면 부위로 바꾼다.
  BodyPart _partOf(String key) {
    switch (key) {
      case 'lead_leg':
      case 'rear_leg':
        return BodyPart.leg;
      case 'lead_arm':
      case 'rear_arm':
        return BodyPart.arm;
      default:
        return BodyPart.torso;
    }
  }

  int _round(dynamic v) => v is num ? v.round() : 0;

  DateTime _parseTime(dynamic v) {
    if (v is String) {
      final parsed = DateTime.tryParse(v);
      if (parsed != null) return parsed.toLocal();
    }
    return DateTime.now();
  }

  /// 부위 설명 한 줄. (임시: 가장 많이 어긋난 세부 항목 기준)
  String _partDescription(List<FeatureAnalysis> features) {
    final bad = features.where((f) => f.level != 'good').toList();
    if (bad.isEmpty) {
      return '세부 항목이 프로 기준과 잘 맞는 편이에요.';
    }
    final f = bad.first;
    final dir = _directionWord(f.direction);
    return dir == null
        ? '${f.name}이(가) 프로 기준과 차이가 있어요.'
        : '${f.name}이(가) 기준보다 $dir 편이에요.';
  }

  /// 방향 → 서술어. similar 는 null(차이 없음).
  String? _directionWord(String direction) {
    switch (direction) {
      case 'higher':
        return '높은';
      case 'lower':
        return '낮은';
      default:
        return null;
    }
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
    if (worst != null && worst.level != 'good') {
      sb.write('다음 스윙에서는 ${worst.label}에 더 집중해 보세요.');
    } else {
      sb.write('전반적으로 안정적인 스윙이에요.');
    }
    return sb.toString();
  }

  /// 프로 기준에서 가장 많이 벗어난(점수가 가장 낮은) 부위.
  FeedbackItem? _worst(List<FeedbackItem> items) {
    if (items.isEmpty) return null;
    return items.reduce((a, b) => a.currentScore <= b.currentScore ? a : b);
  }

  // -------------------------------------------------------------------------
  // 관절별 분석(상세 피드백)
  // -------------------------------------------------------------------------

  /// 종합 피드백을 부위별 상세 분석 목록으로 펼친다.
  ///
  /// ⚠️ 백엔드 연동 상태 ⚠️
  ///  - 이름·점수·세부 항목(각도 그래프/임팩트/움직임 폭)은 서버 실제 값.
  ///  - 코치 문장·포인트는 아직 규칙 기반 임시 문구(백엔드 LLM 문장이 생기면 교체).
  List<PartAnalysis> buildPartAnalyses(OverallFeedback feedback) {
    final list = <PartAnalysis>[];
    for (final item in feedback.items) {
      final status = _statusOf(item, isFirst: feedback.isFirst);
      final needWork =
          status == JointStatus.worsened || status == JointStatus.proBad;
      list.add(PartAnalysis(
        key: item.key,
        label: item.label,
        part: item.part,
        isLeft: item.label.contains('왼'),
        status: status,
        currentScore: item.currentScore,
        previousScore: item.previousScore,
        reliability: item.reliability,
        features: item.features,
        summary: _jointSummary(item, status),
        coachComment: _jointCoach(item, status),
        pointsTitle: needWork ? '개선 포인트' : '유지 포인트',
        points: _jointPoints(item, status),
      ));
    }
    return list;
  }

  /// 부위 상태를 정한다.
  ///  - 첫 피드백([isFirst]): 비교 대상이 없으니 부위 점수(level) 대비로
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
            '${item.description}';
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
            '아래 세부 항목에서 기준과 차이가 큰 부분을 집중해 보세요.';
    }
  }

  List<String> _jointPoints(FeedbackItem item, JointStatus status) {
    // 기준과 차이가 큰 세부 항목을 포인트로 뽑는다(임시: 규칙 기반 문장).
    final bad = item.features.where((f) => f.level != 'good').toList();
    switch (status) {
      case JointStatus.worsened:
      case JointStatus.proBad:
        if (bad.isNotEmpty) {
          return [
            for (final f in bad.take(3))
              _directionWord(f.direction) == null
                  ? '${f.name}이(가) 기준 스윙과 차이가 있어요.'
                  : '${f.name}이(가) 기준보다 ${_directionWord(f.direction)} 편이에요.',
          ];
        }
        return [
          '스윙 구간까지 ${item.label}의 각도를 유지해 보세요.',
          '하체와 상체의 회전에 맞춰 자연스럽게 따라오도록 연습해 보세요.',
        ];
      case JointStatus.improved:
        return [
          '지금의 각도 유지 흐름을 그대로 이어가 보세요.',
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
          '다음 스윙에서도 같은 리듬으로 가져가 보세요.',
        ];
    }
  }

  /// 반복 피드백 샘플(디자인 시안과 동일한 값).
  /// 이전 스윙과 비교해 증감(→, +8/-9)과 "개선 / 개선 필요 / 유지" 를 보여준다.
  ///
  /// TODO(backend): 기록 저장·조회 API 가 생기면 실제 이전 스윙으로 교체.
  /// 세부 항목/시계열도 지금은 영상 없이 UI 를 확인하기 위한 합성 샘플이다.
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
      items: [
        FeedbackItem(
          key: 'lead_leg',
          label: '왼쪽 다리',
          part: BodyPart.leg,
          currentScore: 80,
          previousScore: 72,
          description: '하체의 균형이 좋아지고, 체중 이동이 더 안정적으로 이루어졌습니다.',
          features: [
            _sampleFeature('앞다리 무릎 각도',
                base: 150, amp: -18, userShift: 4, std: 6, level: 'good',
                direction: 'higher', phaseScores: [82, 88, 90, 85]),
            _sampleFeature('앞발 앞뒤 위치',
                base: 20, amp: 10, userShift: 2, std: 4, level: 'good',
                direction: 'similar', phaseScores: [84, 86, 83, 80]),
          ],
        ),
        FeedbackItem(
          key: 'lead_arm',
          label: '왼쪽 팔',
          part: BodyPart.arm,
          currentScore: 74,
          previousScore: 65,
          description: '테이크백에서 임팩트까지 팔 궤도가 일정해져, 상체 회전과의 연결이 부드러워졌습니다.',
          features: [
            _sampleFeature('앞팔 팔꿈치 각도',
                base: 120, amp: 25, userShift: 8, std: 9, level: 'caution',
                direction: 'higher', phaseScores: [80, 76, 70, 74]),
            _sampleFeature('손 높이',
                base: -10, amp: 30, userShift: -6, std: 7, level: 'good',
                direction: 'lower', phaseScores: [82, 85, 81, 78]),
          ],
        ),
        FeedbackItem(
          key: 'rear_arm',
          label: '오른쪽 팔',
          part: BodyPart.arm,
          currentScore: 61,
          previousScore: 70,
          description: '스윙 시 오른쪽 팔의 움직임이 이전보다 다소 불안정해졌습니다.',
          features: [
            _sampleFeature('뒷팔 팔꿈치 각도',
                base: 95, amp: 35, userShift: -22, std: 10, level: 'warning',
                direction: 'lower', phaseScores: [68, 60, 52, 58]),
          ],
        ),
        FeedbackItem(
          key: 'torso',
          label: '몸통',
          part: BodyPart.torso,
          currentScore: 76,
          previousScore: 75,
          description: '큰 변화 없이 안정적인 움직임을 유지하고 있습니다.',
          features: [
            _sampleFeature('상체 기울기',
                base: 8, amp: 14, userShift: 3, std: 4, level: 'good',
                direction: 'higher', phaseScores: [78, 80, 77, 75]),
            _sampleFeature('어깨 라인 기울기',
                base: 0, amp: 18, userShift: -4, std: 5, level: 'caution',
                direction: 'lower', phaseScores: [76, 74, 72, 70]),
          ],
        ),
      ],
    );
  }

  /// 영상 없이 UI 를 확인하기 위한 합성 피처(그래프/수치 포함).
  /// 기준 곡선은 부드러운 호(base + amp·sin)로, 내 스윙은 거기에 서서히 벌어지게 만든다.
  FeatureAnalysis _sampleFeature(
    String name, {
    required double base,
    required double amp,
    required double userShift,
    required double std,
    required String level,
    required String direction,
    required List<int> phaseScores,
  }) {
    const n = 80; // 구간 4개 × 20등분
    double r1(double v) => (v * 10).roundToDouble() / 10;
    final series = <SeriesSample>[
      for (var i = 0; i < n; i++)
        () {
          final t = i / (n - 1);
          final ref = base + amp * sin(pi * t);
          // 스윙 후반으로 갈수록 기준과 더 벌어지게.
          final user = ref + userShift * (0.3 + 0.7 * t);
          return SeriesSample(
              user: r1(user), reference: r1(ref), referenceStd: std);
        }(),
    ];
    return FeatureAnalysis(
      key: name,
      name: name,
      level: level,
      direction: direction,
      unit: 'deg',
      impact: Measure(
          user: r1(base + amp + userShift),
          reference: r1(base + amp),
          diff: r1(userShift)),
      rangeOfMotion: Measure(
          user: r1(amp.abs() + userShift.abs()),
          reference: r1(amp.abs()),
          diff: r1(userShift.abs())),
      series: series,
      phaseScores: phaseScores,
    );
  }
}
