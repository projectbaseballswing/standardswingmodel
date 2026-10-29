import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';
import 'package:swing_analysis/features/swing_3d/domain/stabilizer.dart';

Map<String, dynamic> _json({
  List<double> factors = const [1, .9, 1.1, 1, 1],
  List<double>? timestamps,
}) {
  final times = timestamps ?? List.generate(factors.length, (i) => i * .05);
  return <String, dynamic>{
    'schema_version': 1,
    'id': 'limbs',
    'title': 'Spatial fixture',
    'handedness': 'right',
    'fps': 30,
    'coordinate_space': 'world',
    'coordinate_convention': 'source_view_hip_centered_xright_yup_zcamera',
    'joint_names': jointNames,
    'render_to_npz_joint_indices': List.generate(12, (j) => j),
    'timestamps_s': times,
    'frames': <Map<String, dynamic>>[
      for (var i = 0; i < factors.length; i++)
        <String, dynamic>{
          'index': i,
          'timestamp_s': times[i],
          'decoded_pts_s': times[i],
          'positions': <dynamic>[
            <double>[-.2, .5, 0],
            <double>[.2, .5, 0],
            <double>[-.2 - .3 * factors[i], .5, 0],
            <double>[.2 + .3 * factors[i], .5, 0],
            <double>[-.2 - .6 * factors[i], .5, 0],
            <double>[.2 + .6 * factors[i], .5, 0],
            <double>[-.15, 0, 0],
            <double>[.15, 0, 0],
            <double>[-.15, -.4 * factors[i], 0],
            <double>[.15, -.4 * factors[i], 0],
            <double>[-.15, -.8 * factors[i], 0],
            <double>[.15, -.8 * factors[i], 0],
          ],
          'visibility': List<dynamic>.filled(12, .99),
          'observed_valid': List<bool>.filled(12, true),
          'image_quality_render': <String, dynamic>{
            'combined_missing': List<bool>.filled(12, false),
            'interpolated': List<bool>.filled(12, false),
            'edge_filled': List<bool>.filled(12, false),
            'provenance': 'Image-only preprocessing hints',
          },
          'manual_review_annotations': <dynamic>[],
          'warnings': <String>['source provenance retained'],
        },
    ],
  };
}

Map<String, dynamic> _frame(Map<String, dynamic> json, int i) =>
    (json['frames'] as List)[i] as Map<String, dynamic>;

void main() {
  test(
    'stable limbs share fixed clip medians and preserve each raw direction',
    () {
      final clip = SwingClip.fromJson(_json());
      final stable = PoseStabilizer(clip);
      expect(stable.referenceLengths.length, 8);
      for (var i = 0; i < clip.frames.length; i++) {
        final result = stable.frameAt(i);
        for (final bone in limbBones) {
          final rawDirection =
              clip.frames[i].positions[bone.child]! -
              clip.frames[i].positions[bone.parent]!;
          final direction =
              result.positions[bone.child]! - result.positions[bone.parent]!;
          expect(
            direction.length,
            closeTo(stable.referenceLengths[bone.id]!, 1e-10),
          );
          expect(
            (direction / direction.length - rawDirection / rawDirection.length)
                .length,
            lessThan(1e-10),
          );
        }
      }
      expect(stable.frameAt(1).adjustedJointCount, 8);
      expect(stable.frameAt(1).adjustments[4]!.x, closeTo(-.06, 1e-10));
      expect(clip.frames[1].positions[4]!.x, closeTo(-.74, 1e-10));
      expect(stable.frameAt(1).source, same(clip.frames[1]));
      expect(
        stable.frameAt(1).warnings,
        contains('source provenance retained'),
      );
    },
  );

  test('missing point is never imputed and dependent wrist is not bridged', () {
    final json = _json();
    (_frame(json, 2)['positions'] as List)[2] = null;
    (_frame(json, 2)['observed_valid'] as List)[2] = false;
    final clip = SwingClip.fromJson(json);
    final stable = PoseStabilizer(clip);
    expect(stable.frameAt(2).positions[2], isNull);
    expect(stable.frameAt(2).positions[4], isNull);
    expect(stable.frameAt(2).rawPositions[4], isNotNull);
    expect(
      stable.frameAt(2).jointRisks[4],
      contains(PoseRisk.dependencyMissing),
    );
    expect(stable.frameAt(2).adjustments[2], isNull);
    expect(stable.frameAt(2).adjustments[4], isNull);
    expect(stable.frameAt(1).positions[2], isNotNull);
    expect(stable.frameAt(3).positions[2], isNotNull);
    expect(clip.frames[2].positions[2], isNull);
  });

  test(
    'image mask is a labeled hint: raw remains visible, stable omits chain',
    () {
      final json = _json();
      final hints = _frame(json, 2)['image_quality_render'] as Map;
      (hints['combined_missing'] as List)[2] = true;
      (hints['interpolated'] as List)[2] = true;
      final clip = SwingClip.fromJson(json);
      final result = PoseStabilizer(clip).frameAt(2);
      expect(clip.frames[2].observedValid[2], isTrue);
      expect(result.rawPositions[2], isNotNull);
      expect(result.positions[2], isNull);
      expect(result.positions[4], isNull);
      expect(
        result.jointRisks[2],
        containsAll([PoseRisk.imageFiltered, PoseRisk.imageInterpolated]),
      );
      expect(result.jointRisks[4], contains(PoseRisk.dependencyMissing));
      expect(result.automaticRiskJointCount, greaterThanOrEqualTo(2));
    },
  );

  test(
    'manual annotation is not an automatic detection or automatic omission',
    () {
      final json = _json();
      _frame(json, 2)['manual_review_annotations'] = <Map<String, dynamic>>[
        {
          'label': 'Prior overlay concern',
          'joint_indices': [2, 4],
          'note': 'A human review, not calibrated 3D truth',
        },
      ];
      final result = PoseStabilizer(SwingClip.fromJson(json)).frameAt(2);
      expect(result.jointRisks[2], contains(PoseRisk.manualReview));
      expect(result.jointRisks[4], contains(PoseRisk.manualReview));
      expect(PoseRisk.manualReview.isAutomatic, isFalse);
      expect(result.positions[2], isNotNull);
      expect(result.positions[4], isNotNull);
      expect(result.manualReviewJointCount, 2);
      expect(
        result.warnings.any((w) => w.contains('Prior overlay concern')),
        isTrue,
      );
    },
  );

  test(
    'world length anomaly is flagged and omitted without changing source',
    () {
      final json = _json(factors: [1, 1, 4, 1, 1]);
      final clip = SwingClip.fromJson(json);
      final result = PoseStabilizer(clip).frameAt(2);
      expect(result.jointRisks[2], contains(PoseRisk.lengthAnomaly));
      expect(result.positions[2], isNull);
      expect(result.positions[4], isNull);
      expect(result.rawPositions[2]!.x, closeTo(-1.4, 1e-10));
      expect(clip.frames[2].positions[2]!.x, closeTo(-1.4, 1e-10));
      expect(result.adjustments[2], isNull);
    },
  );

  test('movement risk uses actual delta time and skips long gaps', () {
    Map<String, dynamic> withFlip(List<double> times) {
      final json = _json(factors: [1, 1, 1, 1], timestamps: times);
      (_frame(json, 1)['positions'] as List)[2] = <double>[.1, .5, 0];
      (_frame(json, 1)['positions'] as List)[4] = <double>[.4, .5, 0];
      return json;
    }

    const config = StabilizerConfig(maximumBodyLengthsPerSecond: 20);
    final fast = PoseStabilizer(
      SwingClip.fromJson(withFlip([0, .02, .4, .42])),
      config: config,
    );
    final slow = PoseStabilizer(
      SwingClip.fromJson(withFlip([0, .1, .5, .6])),
      config: config,
    );
    expect(fast.frameAt(1).jointRisks[2], contains(PoseRisk.velocitySpike));
    expect(
      slow.frameAt(1).jointRisks[2],
      isNot(contains(PoseRisk.velocitySpike)),
    );
    expect(
      fast.frameAt(2).jointRisks[2],
      isNot(contains(PoseRisk.velocitySpike)),
    );
    expect(fast.frameAt(2).positions[2], isNotNull);
    expect(fast.clip.timestamps, [0, .02, .4, .42]);
  });

  test(
    'invalid hip root blanks stable and raw display without inventing root',
    () {
      final json = _json();
      (_frame(json, 2)['positions'] as List)[6] = null;
      (_frame(json, 2)['observed_valid'] as List)[6] = false;
      final clip = SwingClip.fromJson(json);
      final result = PoseStabilizer(clip).frameAt(2);
      expect(result.positions.every((p) => p == null), isTrue);
      expect(result.rawPositions.every((p) => p == null), isTrue);
      expect(result.jointRisks[0], contains(PoseRisk.invalidRoot));
      expect(clip.frames[2].positions[0], isNotNull);
      expect(clip.frames[2].positions[6], isNull);
    },
  );

  test(
    'insufficient reference samples are disclosed and do not fabricate lengths',
    () {
      final clip = SwingClip.fromJson(_json(factors: [1, 1.1]));
      final stable = PoseStabilizer(clip);
      expect(stable.referenceLengths, isEmpty);
      expect(stable.frameAt(1).jointRisks[2], contains(PoseRisk.noReference));
      expect(stable.frameAt(1).positions[2]!.x, clip.frames[1].positions[2]!.x);
      expect(stable.frameAt(1).adjustedJointCount, 0);
      expect(
        stable.frameAt(1).warnings.any((w) => w.contains('기준 표본 부족')),
        isTrue,
      );
    },
  );

  test(
    'low image visibility is a proxy risk, not a world missing observation',
    () {
      final json = _json();
      (_frame(json, 2)['visibility'] as List)[4] = .2;
      final clip = SwingClip.fromJson(json);
      final result = PoseStabilizer(clip).frameAt(2);
      expect(clip.frames[2].observedValid[4], isTrue);
      expect(result.rawPositions[4], isNotNull);
      expect(result.positions[4], isNull);
      expect(result.jointRisks[4], contains(PoseRisk.lowImageVisibility));
    },
  );
}
