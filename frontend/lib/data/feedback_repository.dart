import 'dart:math';

import '../api/analysis_api.dart';
import '../api/auth_api.dart' show ApiException;
import '../models/feedback.dart';
import 'session.dart';
import 'feedback_guidance.dart';
import 'feedback_language.dart';

/// 종합 피드백 데이터 공급.
///
/// ⚠️ 백엔드 연동 상태 ⚠️
///  - 새 업로드([firstTime] == true): GET /api/analyses/{id}로 완료를 기다린다.
///    전체 점수·부위별 점수·세부 항목은 서버에서 온 진짜 값이다.
///  - 과거 피드백([firstTime] == false): 저장된 결과를 한 번 조회한다.
/// 두 경로 모두 이전 스윙과의 비교 데이터는 생성하지 않는다.
///
/// 아직 백엔드가 주지 않아 프론트에서 임시로 채우는 값(교체 대상):
///  - summary / coachComment / 포인트(AI 코치 문장): 규칙 기반 임시 문구.
///
/// ★ 부위별 0~100 점수는 서버 overall.group_scores 의 실제 score 를 쓴다.
class FeedbackRepository {
  FeedbackRepository({AnalysisApi? api}) : _api = api ?? AnalysisApi();

  final AnalysisApi _api;

  /// 같은 화면의 영상 요청도 이 클라이언트를 함께 쓴다.
  AnalysisApi get api => _api;

  /// 부위 점수가 이 값 이상이면 "잘함", 미만이면 "개선 필요" 로 본다.
  /// distance_to_score 가 "프로 평균 거리 = 80점" 이라, 프로 평균 수준을 기준선으로 둔다.
  static const int goodScore = 80;

  /// 분석 결과를 가져온다.
  ///
  /// [firstTime]은 기존 라우팅과의 호환을 위한 이름이다.
  /// true는 새 업로드 완료를 기다리고, false는 과거 결과를 한 번 조회한다.
  Future<OverallFeedback> fetchFeedback(
    String analysisId, {
    bool firstTime = false,
  }) async {
    final body = firstTime
        ? await _api.waitForReport(analysisId, includeSeries: true)
        : await _api.getAnalysis(analysisId, includeSeries: true);
    switch (body['status']) {
      case 'queued':
        throw ApiException('분석 대기 중입니다. 잠시 후 다시 확인해주세요.');
      case 'processing':
        throw ApiException('분석이 진행 중입니다. 잠시 후 다시 확인해주세요.');
      case 'failed':
        final error = body['error'];
        final message = error is Map ? error['message'] : error;
        throw ApiException(
          message is String ? '분석에 실패했습니다. $message' : '분석에 실패했습니다.',
        );
      case 'done':
        if (body['result'] is! Map<String, dynamic>) {
          throw ApiException('저장된 분석 결과가 없습니다.');
        }
      default:
        throw ApiException('분석 상태를 확인할 수 없습니다.');
    }

    // 같은 회원의 직전 분석과 비교(반복 피드백). 직전이 없거나(첫 스윙)
    // 권한/네트워크 실패면 비교 없이 프로 기준(첫 피드백)으로 폴백한다.
    final comparison = await _fetchComparison(analysisId);

    try {
      return _mapReport(body, comparison: comparison);
    } on TypeError {
      throw ApiException('분석 결과의 형식이 올바르지 않습니다.');
    }
  }

  /// 직전 분석과의 비교 결과. 직전이 없거나 조회 실패면 null.
  Future<Map<String, dynamic>?> _fetchComparison(String analysisId) async {
    final userId = Session.instance.userId;
    if (userId == null || userId.isEmpty) return null;
    try {
      final c = await _api.fetchComparison(userId, analysisId);
      return c['has_previous'] == true ? c : null;
    } catch (_) {
      return null; // 비교는 부가 기능 — 실패해도 첫 피드백은 보여준다.
    }
  }

  void dispose() => _api.dispose();

  /// 서버 응답을 새 업로드와 과거 기록에 공통으로 사용하는 모델로 변환한다.
  ///
  /// [comparison] 이 있으면(직전 분석 존재) 이전 점수·이전 대비 LLM 코칭을 얹어
  /// 반복 피드백(이전 대비 증감)으로 보여준다. 없으면 프로 기준(첫 피드백).
  OverallFeedback _mapReport(
    Map<String, dynamic> body, {
    Map<String, dynamic>? comparison,
  }) {
    final result = body['result'] as Map<String, dynamic>? ?? const {};
    if (result['overall'] is! Map<String, dynamic>) {
      throw ApiException('종합 분석 결과가 없습니다.');
    }
    final overall = result['overall'] as Map<String, dynamic>;
    final guidance = buildFeedbackGuidance(result);
    final version =
        (result['model_version'] ?? overall['model_version']) as String? ??
        'unknown';
    final eventBased = version.startsWith('0.2');
    final rawJoints = (result['joints'] as List?) ?? const [];
    final rawGroups = (overall['group_scores'] as List?) ?? const [];

    final available = overall['available'] != false;
    final totalScore = available ? _number(overall['score']) : null;
    final reliability = _reliability(overall['reliability']);

    final rotationChecks = [
      for (final c in _rows(overall['rotation_checks']))
        RotationCheck(
          key: c['key'] as String? ?? '',
          name: c['name'] as String? ?? '',
          passed: c['passed'] as bool?,
          affectsScore: c['affects_score'] == true,
          message: feedbackReportNotice(c['message'] as String? ?? ''),
        ),
    ];

    // 백엔드 LLM 코칭.
    //  - 비교(직전 분석 있음)면 '이전 대비' 코칭을, 아니면 '프로 기준' 코칭을 쓴다.
    //  - 비교인데 LLM 이 없으면 coaching=null → 규칙 기반(이전 대비 증감) 폴백.
    final coachingEnvelope = comparison ?? result;
    var review = CoachingReview.fromJson(coachingEnvelope['coaching_review']);
    Coaching? selectedCoaching;
    if (review.canDisplay) {
      // Do not parse or display any pending/blocked candidate, even if a
      // malformed server response accidentally includes its private text.
      try {
        selectedCoaching = _mapCoaching(coachingEnvelope['coaching']);
      } on TypeError {
        selectedCoaching = null;
      }
      if (selectedCoaching == null) {
        review = const CoachingReview(status: 'blocked');
      }
    }
    final coaching = available && reliableFeedback(reliability)
        ? selectedCoaching
        : null;

    // 부위별 이전 점수 / 전체 이전 점수(비교일 때만).
    final previousByPart = <String, double?>{};
    double? previousTotal;
    if (comparison != null) {
      previousTotal = _number(comparison['overall_previous_score']);
      for (final p in (comparison['parts'] as List?) ?? const []) {
        if (p is! Map<String, dynamic>) continue;
        final key = p['key'];
        if (key is String && key.isNotEmpty) {
          previousByPart[key] = _number(p['previous_score']);
        }
      }
    }

    // 부위별 세부 항목(피처)을 모은다.
    // 신뢰도 낮음(뒷팔 팔꿈치 등)과 미측정 세부 항목은 제외하되 부위 점수는 보존한다.
    final featuresByPart = <String, List<FeatureAnalysis>>{};
    for (final j in rawJoints.whereType<Map<String, dynamic>>()) {
      if (j['available'] == false || j['reliability'] == 'low') continue;
      final part = (j['body_part'] as String?) ?? 'other';
      (featuresByPart[part] ??= []).add(
        _mapFeature(
          j,
          eventBased: eventBased,
          coaching: guidance.eligibleJoints.contains(j['key'])
              ? coaching
              : null,
          guidance: guidance,
        ),
      );
    }

    // UI expansion and summaries use the same measured, deterministic ranking.
    for (final features in featuresByPart.values) {
      features.sort((a, b) {
        final az = a.evidence?.isIssue == true ? a.evidence!.z.abs() : -1.0;
        final bz = b.evidence?.isIssue == true ? b.evidence!.z.abs() : -1.0;
        final cmp = bz.compareTo(az);
        return cmp != 0 ? cmp : a.key.compareTo(b.key);
      });
    }

    // 부위(그룹) 단위로 묶는다. 점수는 group_scores.score 실제값.
    final items = <FeedbackItem>[];
    for (final g in rawGroups.whereType<Map<String, dynamic>>()) {
      final key = (g['key'] as String?) ?? '';
      final features = featuresByPart[key] ?? const <FeatureAnalysis>[];
      final groupAvailable = g['available'] != false;
      final score = groupAvailable ? _number(g['score']) : null;
      final groupReliability = _reliability(g['reliability']);
      items.add(
        FeedbackItem(
          key: key,
          label: (g['name'] as String?) ?? '부위',
          part: _partOf(key),
          currentScore: score,
          previousScore: previousByPart[key],
          available: groupAvailable,
          level: score == null || !groupAvailable || groupReliability == 'low'
              ? 'unavailable'
              : score >= goodScore
              ? 'good'
              : 'caution',
          description: !groupAvailable
              ? '이 부위는 분석할 수 없습니다.'
              : score == null
              ? '부위 점수가 제공되지 않았습니다.'
              : groupReliability == 'low'
              ? '이 부위는 관절 추정이 불확실해 점수만 참고용으로 보여드려요. 점수 차이가 실제 자세의 개선이나 악화를 뜻하지는 않아요.'
              : features.isEmpty
              ? '비교할 세부 관절 정보가 없어 부위 점수만 참고용으로 보여드려요.'
              : _partDescription(features),
          reliability: groupReliability,
          features: groupAvailable && groupReliability != 'low'
              ? features
              : const [],
        ),
      );
    }

    // 0.1의 pose/velocity 등 그룹 점수는 관절 부위 점수가 아니다.
    // 연결되지 않은 관절은 점수를 합성하지 않고 별도 부위로 보존한다.
    for (final entry in featuresByPart.entries) {
      if (items.any((i) => i.key == entry.key)) continue;
      final label = switch (entry.key) {
        'arm' => '팔',
        'leg' => '다리',
        'torso' => '몸통',
        _ => entry.key,
      };
      items.add(
        FeedbackItem(
          key: entry.key,
          label: label,
          part: _partOf(entry.key),
          currentScore: null,
          description: '부위 점수는 미제공이며 측정된 관절 정보만 표시합니다.',
          level: 'unavailable',
          reliability: reliability,
          features: entry.value,
        ),
      );
    }

    return OverallFeedback(
      analysisId: body['analysis_id'] is String
          ? body['analysis_id'] as String
          : '',
      videoStatus: body['video_status'] is String
          ? body['video_status'] as String
          : 'unknown',
      recordedAt: _parseTime(body),
      totalScore: totalScore,
      modelVersion: version,
      available: available,
      reliability: reliability,
      warnings: _strings(
        _map(overall['quality'])['warnings'],
      ).map(feedbackReportNotice).toList(),
      phases: _mapPhases(
        _map(result['phases'])['phases'],
        swingChecks: rotationChecks,
        coaching: coaching,
        // 관절 key → 설명. '주요 관절 차이'에서 각 관절이 뭘 재는지 작게 보여준다.
        jointDescriptions: {
          for (final j in _rows(result['joints']))
            if (j['key'] is String)
              (j['key'] as String): feedbackFeatureDescription(
                j['key'] as String,
                j['description'] as String? ?? '',
              ),
        },
        guidance: guidance,
        analysisFps: _number(_map(result['phases'])['user_fps']),
      ),
      rotationChecks: rotationChecks,
      postureScore: available ? _number(overall['posture_score']) : null,
      speedScore: available ? _number(overall['speed_score']) : null,
      postureCapped: overall['posture_capped'] == true,
      speedMetrics: _mapSpeed(_map(result['speed'])),
      events: eventBased
          ? _mapEvents(_map(result['phases'])['events'])
          : const [],
      summary: !available
          ? '영상에서 종합 분석에 필요한 정보를 확인하지 못했습니다.'
          : totalScore == null
          ? '종합 점수가 제공되지 않았습니다. 측정된 항목만 확인하세요.'
          : reliability == 'low'
          ? '분석 신뢰도가 낮습니다. 점수는 참고용으로 확인하세요.'
          // LLM 코칭이 있으면 그 문장을, 없으면 규칙 기반 문구를 쓴다.
          : (coaching != null && coaching.overallSummary.isNotEmpty)
          ? coaching.overallSummary
          : guidance.issues.isNotEmpty
          ? '기준 스윙과 차이가 있는 동작을 살펴볼게요. 먼저 확인할 부분을 아래에 정리했어요.'
          : '측정 가능한 동작을 기준 스윙과 비교했어요. 지금은 먼저 고치라고 권할 만큼 확실한 차이가 없어요.',
      coachComment: !available || reliability == 'low'
          ? '분석 정보가 부족하거나 신뢰도가 낮아 자세에 대한 판단을 보류합니다.'
          : (coaching != null && coaching.overallCoach.isNotEmpty)
          ? coaching.overallCoach
          : guidance.issues.isNotEmpty
          ? '${guidance.issues.first.observation} ${guidance.issues.first.action}'
          : '지금 측정만으로 꼭 고쳐야 할 동작을 단정할 수는 없어요. 원본 영상에서 확인되는 구간부터 살펴보세요.',
      priorities: guidance.issues.take(3).toList(),
      strengths: guidance.strengths.take(2).toList(),
      scoreExplanation: guidance.scoreExplanation,
      coachingReview: review,
      coachSource:
          coaching?.overallCoach.isNotEmpty == true ||
              coaching?.coachFeedback != null
          ? coaching!.sourceLabel
          : '분석 결과 안내 · 기본 설명',
      summarySource: coaching?.overallSummary.isNotEmpty == true
          ? coaching!.sourceLabel
          : '분석 결과 안내 · 기본 설명',
      items: items,
      coaching: coaching,
      scoreContributions: [
        for (final c in _rows(overall['score_contributions']))
          if ((c['key'] as String?)?.isNotEmpty ?? false)
            ScoreContribution(
              key: c['key'] as String,
              name: (c['name'] as String?) ?? '부위',
              share: _number(c['share']) ?? 0,
              score: _number(c['score']),
              reliability: _reliability(c['reliability']),
            ),
      ],
      // 직전 분석이 있으면 이전 전체 점수를 실어 반복 피드백(증감)을 켠다.
      previousTotalScore: previousTotal,
    );
  }

  /// 서버 result.coaching 을 모델로 변환한다. 없거나 형식이 틀리면 null.
  ///
  /// 종합 요약/코칭(overall_summary/overall_coach)이 둘 다 문자열일 때만 유효로 본다.
  /// 그래야 부분적으로 깨진 응답에 섞이지 않는다.
  Coaching? _mapCoaching(dynamic raw) {
    if (raw is! Map<String, dynamic>) return null;
    final summary = raw['overall_summary'];
    final coach = raw['overall_coach'];
    if (summary is! String || coach is! String) return null;

    final parts = <String, PartCoaching>{};
    for (final p in (raw['parts'] as List?) ?? const []) {
      if (p is! Map<String, dynamic>) continue;
      final key = p['key'];
      if (key is! String || key.isEmpty) continue;
      parts[key] = PartCoaching(
        summary: (p['summary'] as String?) ?? '',
        keepPoints: _strings(p['keep_points']),
        improvePoints: _strings(p['improve_points']),
      );
    }

    // 관절(피처) key → 코멘트. scope='full' 일 때만 서버가 채워 준다.
    final joints = <String, String>{};
    for (final j in (raw['joints'] as List?) ?? const []) {
      if (j is! Map<String, dynamic>) continue;
      final key = j['key'];
      final comment = j['comment'];
      if (key is! String || key.isEmpty) continue;
      if (comment is! String || comment.isEmpty) continue;
      joints[key] = comment;
    }

    // 구간 key → 구간 코칭(card_line/comment/tip). scope='full' 일 때만.
    final phases = <String, PhaseCoaching>{};
    for (final p in (raw['phases'] as List?) ?? const []) {
      if (p is! Map<String, dynamic>) continue;
      final key = p['key'];
      if (key is! String || key.isEmpty) continue;
      phases[key] = PhaseCoaching(
        cardLine: (p['card_line'] as String?) ?? '',
        comment: (p['comment'] as String?) ?? '',
        tip: (p['tip'] as String?) ?? '',
      );
    }

    return Coaching(
      overallSummary: summary,
      overallCoach: coach,
      coachFeedback: _mapCoachFeedback(raw['coach_feedback']),
      parts: parts,
      joints: joints,
      phases: phases,
      // 'pending'=관절·구간 생성 중(화면은 '작성 중' 후 재조회), 'done'/'failed'=확정.
      extendedStatus: raw['extended_status'] is String
          ? raw['extended_status'] as String
          : null,
    );
  }

  /// "AI 코치의 한마디" 4단 상세. 네 필드가 모두 문자열일 때만 유효로 본다.
  /// (규칙 기반 폴백/옛 캐시에는 없어서 null → 화면은 한 문장 코멘트로 폴백)
  CoachFeedback? _mapCoachFeedback(dynamic raw) {
    if (raw is! Map<String, dynamic>) return null;
    final problem = raw['problem'];
    final cause = raw['cause'];
    final fix = raw['fix'];
    final drill = raw['drill'];
    if (problem is! String ||
        cause is! String ||
        fix is! String ||
        drill is! String) {
      return null;
    }
    return CoachFeedback(
      problem: problem,
      cause: cause,
      fix: fix,
      drill: drill,
    );
  }

  /// 서버 joints[] 한 건을 세부 항목으로 변환한다.
  ///
  /// [coaching] 이 있으면(scope='full') 이 피처 key 에 해당하는 LLM 코멘트를 붙인다.
  FeatureAnalysis _mapFeature(
    Map<String, dynamic> j, {
    required bool eventBased,
    Coaching? coaching,
    FeedbackGuidance guidance = const FeedbackGuidance(),
  }) {
    final key = (j['key'] as String?) ?? '';
    final evidence = [
      ...guidance.issues,
      ...guidance.strengths,
    ].where((e) => e.joint == key).firstOrNull;
    final worst = _rows(
      j['phases'],
    ).where((p) => p['phase'] == j['worst_phase']).firstOrNull;
    return FeatureAnalysis(
      key: key,
      name: feedbackFeatureName(key, (j['name'] as String?) ?? '항목'),
      level: (j['level'] as String?) ?? 'good',
      direction: _worstPhaseDirection(j),
      directionText: evidence != null
          ? '${evidence.phaseName} 구간에서 ${evidence.direction}'
          : contextualDirection(
              key,
              _worstPhaseDirection(j),
              worst?['phase_name'] as String?,
              serverText: _worstPhaseDirectionText(j),
            ),
      unit: (j['unit'] as String?) ?? 'deg',
      description: feedbackFeatureDescription(
        key,
        (j['description'] as String?) ?? '',
      ),
      comment: coaching?.joints[key] ?? '',
      impact: _measure(j['impact']),
      rangeOfMotion: _measure(j['range_of_motion']),
      series: _series(j['series']),
      phaseScores: _phaseScores(j['phases'], eventBased: eventBased),
      reliability: _reliability(j['reliability']),
      eventBasedSeries: eventBased,
      evidence: evidence,
      ruleComment: evidence == null
          ? '이 구간은 관절을 믿고 비교하기 어려워 교정 안내를 보류할게요.'
          : evidence.isIssue
          ? evidence.observation
          : '${evidence.observation} 다른 구간에서는 결과가 달라질 수 있어요.',
      contribution: _number(j['contribution']),
    );
  }

  /// 관절 z-score 환산 참고 점수. 결측 구간은 null로 남기며 실제 구간 점수와 분리한다.
  List<JointPhaseScore>? _phaseScores(
    dynamic phasesRaw, {
    required bool eventBased,
  }) {
    if (phasesRaw is! List) return null;
    final byKey = <String, JointPhaseScore>{};
    for (final p in phasesRaw.whereType<Map<String, dynamic>>()) {
      final key = p['phase'] as String?;
      if (key == null) continue;
      final z = p['available'] == false ? null : _number(p['z_score']);
      byKey[key] = JointPhaseScore(
        key: key,
        name: p['phase_name'] as String? ?? key,
        score: z == null ? null : _scoreFromZ(z),
      );
    }
    if (byKey.isEmpty) return null;
    return eventBased
        ? [
            for (final ph in SwingPhase.values)
              byKey[ph.key] ?? JointPhaseScore(key: ph.key, name: ph.ko),
          ]
        : byKey.values.toList();
  }

  /// z-score(표준편차 단위) → 0~100 점수.
  /// |z|=1(프로 변동 경계, level good 의 끝)을 80점(goodScore)에 맞춘다: 100·0.8^|z|.
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

  /// 가장 많이 어긋난 구간의 서버 방향 문구. 없으면(이전 버전 기록) null.
  String? _worstPhaseDirectionText(Map<String, dynamic> j) {
    final worst = j['worst_phase'] as String?;
    final phases = (j['phases'] as List?) ?? const [];
    for (final p in phases.whereType<Map<String, dynamic>>()) {
      if (p['phase'] == worst) return p['direction_text'] as String?;
    }
    return null;
  }

  /// {user, reference, diff} → [Measure]. 없으면 null.
  Measure? _measure(dynamic raw) {
    if (raw is! Map) return null;
    return Measure(
      user: _number(raw['user']),
      reference: _number(raw['reference']),
      diff: _number(raw['diff']),
    );
  }

  /// {user:[80], reference:[80], reference_std:[80]} → 시계열 목록. 없으면 null.
  List<SeriesSample>? _series(dynamic raw) {
    if (raw is! Map) return null;
    final user = (raw['user'] as List?) ?? const [];
    final ref = (raw['reference'] as List?) ?? const [];
    final std = (raw['reference_std'] as List?) ?? const [];
    final n = max(user.length, max(ref.length, std.length));
    if (n == 0) return null;
    double? at(List l, int i) => i < l.length ? _number(l[i]) : null;
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
      case 'leg':
        return BodyPart.leg;
      case 'lead_arm':
      case 'rear_arm':
      case 'arm':
        return BodyPart.arm;
      default:
        return BodyPart.torso;
    }
  }

  double? _number(dynamic v) => v is num && v.isFinite ? v.toDouble() : null;
  String _reliability(dynamic v) => v is String ? v : 'medium';
  Map<String, dynamic> _map(dynamic v) =>
      v is Map<String, dynamic> ? v : const {};
  List<String> _strings(dynamic v) =>
      v is List ? v.whereType<String>().toList() : const [];
  Iterable<Map<String, dynamic>> _rows(dynamic v) =>
      v is List ? v.whereType<Map<String, dynamic>>() : const [];

  /// [coaching] 이 있으면(scope='full') 구간 key 로 LLM 코칭(card_line/comment/tip)을 붙인다.
  List<AnalysisPhase> _mapPhases(
    dynamic raw, {
    List<RotationCheck> swingChecks = const [],
    Coaching? coaching,
    Map<String, String> jointDescriptions = const {},
    FeedbackGuidance guidance = const FeedbackGuidance(),
    double? analysisFps,
  }) => [
    for (final p in _rows(raw))
      () {
        final key = p['key'] as String? ?? '';
        final valid =
            p['available'] != false && reliableFeedback(p['reliability']);
        final coach = valid ? coaching?.phases[key] : null;
        final originalDeviations = _rows(p['top_deviations']).toList();
        final shown = originalDeviations
            .where(
              (d) =>
                  valid &&
                  guidance.observations.any(
                    (e) => e.joint == d['joint'] && e.phase == key,
                  ) &&
                  _number(d['z_score']) != null,
            )
            .toList();
        final evidence = guidance.observations
            .where((e) => e.phase == key && e.isIssue)
            .firstOrNull;
        return AnalysisPhase(
          key: key,
          name: p['name'] as String? ?? p['key'] as String? ?? '구간',
          available: p['available'] != false,
          reliability: _reliability(p['reliability']),
          score: p['available'] == false ? null : _number(p['score']),
          unavailableReason: p['unavailable_reason'] is String
              ? feedbackReportNotice(p['unavailable_reason'] as String)
              : null,
          userDurationMs: p['available'] == false
              ? null
              : _number(p['user_duration_ms']),
          referenceDurationMs: _number(p['reference_duration_ms']),
          tempoRatio: p['available'] == false
              ? null
              : _number(p['tempo_ratio']),
          tempoLevel: p['available'] == false
              ? null
              : p['tempo_level'] as String?,
          warnings: [
            ..._strings(
              p['warnings'],
            ).map((w) => safeTempoWarning(w, analysisFps)),
            if (shown.length < originalDeviations.length)
              '관절 ${originalDeviations.length - shown.length}곳은 측정 근거가 부족해 이 구간의 교정 안내에서 제외했어요. 분석 점수는 그대로 유지했어요.',
          ],
          checks: key == 'swing' ? swingChecks : const [],
          deviations: p['available'] == false
              ? const []
              : [
                  for (final d in shown)
                    PhaseDeviation(
                      joint: d['joint'] as String? ?? '',
                      name: feedbackFeatureName(
                        d['joint'] as String? ?? '',
                        d['joint_name'] as String? ?? '관절',
                      ),
                      diff: _number(d['diff']),
                      zScore: _number(d['z_score']),
                      direction: d['direction'] as String? ?? 'similar',
                      directionText: featureDirection(
                        d['joint'] as String? ?? '',
                        d['direction'] as String? ?? '',
                        serverText: d['direction_text'] as String?,
                      ),
                      level: d['level'] as String? ?? '',
                      description:
                          jointDescriptions[d['joint'] as String? ?? ''] ?? '',
                    ),
                ],
          coachCardLine: coach?.cardLine ?? '',
          coachComment: coach?.comment ?? '',
          coachTip: coach?.tip ?? '',
          ruleTip: evidence == null
              ? '이 구간은 우선 교정을 권할 만큼 확실한 관절 차이가 확인되지 않았어요. 원본에서 동작을 살펴보세요.'
              : '${evidence.observation} ${evidence.action}',
        );
      }(),
  ];

  List<SpeedMetric> _mapSpeed(Map<String, dynamic> raw) => [
    for (final m in _rows(raw['metrics']))
      SpeedMetric(
        key: m['key'] as String? ?? '',
        name: m['name'] as String? ?? '속도 지표',
        unit: m['unit'] as String? ?? '',
        available: raw['available'] != false && m['available'] == true,
        reliability: _reliability(m['reliability'] ?? 'low'),
        user: raw['available'] == false || m['available'] != true
            ? null
            : _number(m['user']),
        reference: _number(m['reference']),
      ),
  ];

  List<SwingEvent> _mapEvents(dynamic raw) => [
    for (final e in _map(raw).entries)
      if (_map(e.value)['frame'] is int && (_map(e.value)['frame'] as int) >= 0)
        SwingEvent(
          key: e.key,
          name: _map(e.value)['name'] as String? ?? e.key,
          frame: _map(e.value)['frame'] as int,
          msFromImpact: _number(_map(e.value)['ms_from_impact']),
        ),
  ];

  DateTime _parseTime(Map<String, dynamic> body) {
    for (final key in ['recorded_at', 'created_at', 'finished_at']) {
      final value = body[key];
      if (value is String) {
        final parsed = DateTime.tryParse(value);
        if (parsed != null) return parsed.toLocal();
      }
    }
    throw ApiException('분석 기록의 시각 정보가 없습니다.');
  }

  /// 부위 설명 한 줄. (임시: 가장 많이 어긋난 세부 항목 기준)
  String _partDescription(List<FeatureAnalysis> features) {
    final issue = features
        .where((f) => f.evidence?.isIssue == true)
        .firstOrNull;
    if (issue != null) return issue.evidence!.observation;
    final strength = features
        .where((f) => f.evidence?.isIssue == false)
        .firstOrNull;
    return strength != null
        ? strength.evidence!.observation
        : '이 구간에서는 자세 교정을 제안할 만큼 확실한 측정 근거가 없어요.';
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
      final status = item.status(hasComparison: feedback.hasComparison);
      final hasIssue = item.features.any((f) => f.evidence?.isIssue == true);
      // LLM 부위 코칭이 있으면 요약/포인트를 그걸로 대체(없으면 규칙 기반).
      // - 측정 불가(limited) 부위는 안내 문구를 써야 하므로 LLM 로 덮지 않는다.
      // - feedback.coaching 은 비교면 '이전 대비', 아니면 '프로 기준' 코칭이라
      //   (리포지토리에서 이미 상황에 맞게 선택됨) 상태 구분 없이 그대로 쓴다.
      final partCoaching = status == JointStatus.limited
          ? null
          : feedback.coaching?.parts[item.key];
      final llmPoints = partCoaching?.points ?? const <String>[];
      // 몸통이 회전 확인에 걸렸으면 그 문장을 규칙 기반 포인트 앞에 둔다.
      final rotationPoints =
          item.key == 'torso' && status != JointStatus.limited
          ? [
              for (final c in feedback.rotationChecks)
                if (c.passed == false) c.message,
            ]
          : const <String>[];
      list.add(
        PartAnalysis(
          key: item.key,
          label: item.label,
          part: item.part,
          isLeft: item.label.contains('왼'),
          status: status,
          currentScore: item.currentScore,
          previousScore: item.previousScore,
          reliability: item.reliability,
          features: item.features,
          summary: partCoaching != null && partCoaching.summary.isNotEmpty
              ? partCoaching.summary
              : _jointSummary(item, status),
          coachComment: _jointCoach(item, status),
          pointsTitle: status == JointStatus.limited
              ? '분석 안내'
              : hasIssue || rotationPoints.isNotEmpty
              ? '먼저 확인할 움직임'
              : '측정 근거 안내',
          pointsSource: llmPoints.isNotEmpty
              ? 'GPT 코칭 · 검토 완료'
              : '분석 결과 안내 · 기본 설명',
          points: llmPoints.isNotEmpty
              ? llmPoints
              : [
                  ...rotationPoints,
                  ..._jointPoints(item, status),
                ].take(3).toList(),
        ),
      );
    }
    return list;
  }

  String _jointSummary(FeedbackItem item, JointStatus status) {
    if (status == JointStatus.limited) return item.description;
    if (item.delta != null) {
      final delta = item.delta!;
      final change = delta.abs() <= 2
          ? '2점 이내로 변했어요'
          : '${feedbackNumber(delta.abs())}점 ${delta > 0 ? '올랐어요' : '낮아졌어요'}';
      return '${item.label} 점수가 직전보다 $change. '
          '점수만으로 원인을 알 수는 없어요. 기준 스윙과의 차이는 아래에서 확인하세요.';
    }
    return '${item.label}의 자세 유사도는 ${feedbackNumber(item.currentScore)}점이에요. '
        '전체적인 점수가 좋아도 순간마다 자세 차이는 있을 수 있어요.';
  }

  String _jointCoach(FeedbackItem item, JointStatus status) {
    if (status == JointStatus.limited) {
      return '관절을 믿고 비교하기 어려워 자세 교정은 안내하지 않을게요. 점수는 참고로만 확인해 주세요.';
    }
    final issue = item.features
        .where((f) => f.evidence?.isIssue == true)
        .firstOrNull;
    return issue != null
        ? issue.evidence!.action
        : '지금 결과만으로 특정 동작을 고치라고 말하기는 어려워요. 아래에서 확인된 구간을 살펴보세요.';
  }

  List<String> _jointPoints(FeedbackItem item, JointStatus status) {
    if (status == JointStatus.limited) {
      return ['점수 차이가 실제 자세의 개선이나 악화를 뜻하지는 않아요.'];
    }
    final issues = item.features
        .where((f) => f.evidence?.isIssue == true)
        .take(3)
        .toList();
    if (issues.isNotEmpty) {
      return [for (final f in issues) f.evidence!.observation];
    }
    final strengths = item.features
        .where((f) => f.evidence?.isIssue == false)
        .take(2);
    return [
      for (final f in strengths) f.evidence!.observation,
      '다른 구간에서는 결과가 달라질 수 있어요.',
    ];
  }
}
