// Offline audit utility: invoke explicitly with flutter test tool/replay_feedback_test.dart
// --dart-define=FEEDBACK_REPLAY_INPUT=... --dart-define=FEEDBACK_REPLAY_OUTPUT=...
// Input is the previously sanitized stage-2 report set. No real API is called.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';

void main() {
  test(
    'replay existing sanitized reports through current Flutter mapping',
    () async {
      const inputPath = String.fromEnvironment('FEEDBACK_REPLAY_INPUT');
      const outputPath = String.fromEnvironment('FEEDBACK_REPLAY_OUTPUT');
      expect(inputPath, isNotEmpty);
      expect(outputPath, isNotEmpty);
      Session.instance.clear();
      final inputs = jsonDecode(File(inputPath).readAsStringSync()) as List;
      final cases = <Map<String, dynamic>>[];
      for (final input in inputs) {
        final body = Map<String, dynamic>.from(input['body']);
        final before = jsonEncode(body);
        final api = AnalysisApi(
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/analyses/audit-fixture');
            return http.Response(
              jsonEncode(body),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        );
        final repo = FeedbackRepository(api: api);
        final f = await repo.fetchFeedback('audit-fixture');
        final parts = repo.buildPartAnalyses(f);
        final rows = <Map<String, dynamic>>[];
        void add(
          String section,
          String slot,
          String target,
          String text, {
          bool rendered = true,
          String origin = 'rule_or_measured',
        }) {
          if (text.isNotEmpty) {
            rows.add({
              'section': section,
              'slot': slot,
              'target': target,
              'text': text,
              'rendered': rendered,
              'origin': origin,
            });
          }
        }

        add('종합', '요약', '전체', f.summary);
        add('종합', '코치 제목', '전체', f.coachSource);
        add(
          '종합',
          '코치 한마디',
          '전체',
          f.coachComment,
          rendered: f.priorities.isEmpty || f.coaching != null,
        );
        add('종합', '승인 상태', '전체', f.coachingReview.notice);
        add('종합', '점수 산출 설명', '전체', f.scoreExplanation);
        for (var i = 0; i < f.priorities.length; i++) {
          final e = f.priorities[i];
          add('종합', '우선 확인', e.name, e.observation, rendered: i == 0);
        }
        for (var i = 0; i < f.strengths.length; i++) {
          final e = f.strengths[i];
          add('종합', '기준과 비슷한 구간', e.name, e.observation, rendered: i == 0);
        }
        for (final item in f.items) {
          final p = parts.firstWhere((p) => p.key == item.key);
          add('부위', '목록 설명', item.label, item.description);
          add('부위', '상세 요약', p.label, p.summary, rendered: false);
          add('부위', '상세 코치', p.label, p.coachComment);
          for (final point in p.points) {
            add('부위', p.pointsTitle, p.label, point);
          }
          for (final feat in item.features) {
            add('관절', '코치 코멘트', feat.name, feat.displayedComment);
            add('관절', '항목 정의', feat.name, feat.description, rendered: false);
            add('관절', '대표 방향', feat.name, feat.directionText ?? '');
          }
        }
        for (final p in f.phases) {
          add('구간', '분석 근거 안내 · 규칙 기반', p.name, p.ruleTip);
          for (final w in p.warnings) {
            add('구간', '경고', p.name, w);
          }
          for (final d in p.deviations) {
            add(
              '구간',
              '주요 관절 차이',
              p.name,
              '${d.name}: ${d.directionText ?? d.direction}',
            );
          }
          // Teammate PR84 hides these values from the current phase screen.
          for (final c in p.checks) {
            add('구간', '몸통 회전 확인', p.name, c.message, rendered: false);
          }
        }
        expect(jsonEncode(body), before);
        expect(f.coaching, isNull);
        cases.add({
          'id': input['id'],
          'rows': rows,
          'input_unchanged': true,
          'score': f.totalScore,
          'version': f.modelVersion,
          'coaching_present': f.coaching != null,
          'has_comparison': f.hasComparison,
          'score_snapshot': {
            'total': f.totalScore,
            'posture': f.postureScore,
            'speed': f.speedScore,
            'parts': {for (final p in f.items) p.key: p.currentScore},
            'phases': {for (final p in f.phases) p.key: p.score},
            'joint_phase': {
              for (final p in f.items)
                for (final j in p.features)
                  j.key: j.phaseScores?.map((x) => x.score).toList(),
            },
          },
        });
        repo.dispose();
      }
      final output = File(outputPath);
      output.parent.createSync(recursive: true);
      output.writeAsStringSync(
        const JsonEncoder.withIndent('  ').convert(cases),
      );
      expect(cases, hasLength(6));
    },
  );
}
