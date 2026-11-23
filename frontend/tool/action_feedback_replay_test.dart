// Explicit offline replay. Inputs/outputs are local sanitized research data.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_guidance.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';

void main() {
  test(
    'six saved reports: action guidance replay without network or mutation',
    () async {
      const inputPath = String.fromEnvironment('ACTION_REPLAY_INPUT');
      const outputPath = String.fromEnvironment('ACTION_REPLAY_OUTPUT');
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
            expect(request.url.path, '/api/analyses/action-replay');
            return http.Response(
              jsonEncode(body),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        );
        final repo = FeedbackRepository(api: api);
        final feedback = await repo.fetchFeedback('action-replay');
        final result = Map<String, dynamic>.from(body['result']);
        final guidance = buildFeedbackGuidance(result);
        final rows = <Map<String, dynamic>>[];
        for (final e in guidance.observations) {
          final joint = (result['joints'] as List)
              .cast<Map<String, dynamic>>()
              .firstWhere((j) => j['key'] == e.joint);
          final phase = (joint['phases'] as List)
              .cast<Map<String, dynamic>>()
              .firstWhere((p) => p['phase'] == e.phase);
          rows.add({
            'feature': e.joint, 'phase': e.phase, 'phase_name': e.phaseName,
            'is_issue': e.isIssue,
            'is_priority':
                feedback.priorities.firstOrNull?.joint == e.joint &&
                feedback.priorities.firstOrNull?.phase == e.phase,
            'observation': e.observation, 'action': e.action,
            // BEGIN candidate-only fields (baseline generator replaces this block).
            'practice': e.practice, 'limitations': e.limitations,
            'quality_notice': e.qualityNotice,
            'practice_eligible': e.practiceEligible,
            // END candidate-only fields.
            'evidence': {
              'part': e.part,
              'unit': joint['unit'],
              'joint_reliability': joint['reliability'],
              'user_mean': phase['user_mean'],
              'reference_mean': phase['reference_mean'],
              'diff': phase['diff'],
              'direction': phase['direction'],
              'level': phase['level'],
              'z_score': phase['z_score'],
            },
          });
        }
        expect(jsonEncode(body), before);
        expect(feedback.coaching, isNull);
        cases.add({
          'id': input['id'],
          'input_unchanged': true,
          'coaching_present': false,
          'rows': rows,
          'score_snapshot': {
            'total': feedback.totalScore,
            'posture': feedback.postureScore,
            'speed': feedback.speedScore,
            'parts': {for (final p in feedback.items) p.key: p.currentScore},
            'phases': {for (final p in feedback.phases) p.key: p.score},
            'joint_phase': {
              for (final p in feedback.items)
                for (final j in p.features)
                  j.key: j.phaseScores?.map((x) => x.score).toList(),
            },
          },
          'joint_comments': {
            for (final p in feedback.items)
              for (final j in p.features) j.key: j.displayedComment,
          },
          'phase_comments': {for (final p in feedback.phases) p.key: p.ruleTip},
          'quality': result['overall']['quality'],
        });
        repo.dispose();
      }
      expect(cases, hasLength(6));
      final output = File(outputPath);
      output.parent.createSync(recursive: true);
      output.writeAsStringSync(
        const JsonEncoder.withIndent('  ').convert(cases),
      );
    },
  );
}
