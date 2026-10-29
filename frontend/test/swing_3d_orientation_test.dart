import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/orientation.dart';

V3 rotate(V3 p, double degrees) {
  final a = degrees * math.pi / 180;
  return V3(
    math.cos(a) * p.x + math.sin(a) * p.z,
    p.y,
    -math.sin(a) * p.x + math.cos(a) * p.z,
  );
}

Map<String, dynamic> synthetic({
  List<double>? turns,
  double? hip,
  double? leftFoot,
  double? rightFoot,
}) {
  turns ??= List.filled(6, 0.0);
  final base = [
    const V3(.23, .5, 0),
    const V3(-.23, .5, 0),
    const V3(.34, .25, 0),
    const V3(-.34, .25, 0),
    const V3(.42, .05, .1),
    const V3(-.42, .05, .1),
    const V3(.15, 0, 0),
    const V3(-.15, 0, 0),
    const V3(.17, -.45, 0),
    const V3(-.17, -.45, 0),
    const V3(.18, -.9, 0),
    const V3(-.18, -.9, 0),
  ];
  return {
    'schema_version': 1,
    'coordinate_convention': renderConvention,
    'source_oriented': true,
    'mirrored_input': false,
    'handedness': 'unknown',
    'joint_names': bodyNames,
    'foot_joint_names': footNames,
    'frame_count': turns.length,
    'fps': 60,
    'frames': [
      for (var i = 0; i < turns.length; i++)
        () {
          final p = [
            for (var j = 0; j < 12; j++)
              rotate(base[j], j < 6 ? turns![i] : hip ?? turns![i]),
          ];
          final lf = rotate(const V3(0, 0, 1), leftFoot ?? turns![i]);
          final rf = rotate(const V3(0, 0, 1), rightFoot ?? turns![i]);
          return {
            'index': i,
            'timestamp_s': i / 60,
            'positions': p.map<dynamic>((v) => v.toJson()).toList(),
            'feet': <dynamic>[
              (p[10] - lf * .05).toJson(),
              (p[11] - rf * .05).toJson(),
              (p[10] + lf * .18).toJson(),
              (p[11] + rf * .18).toJson(),
            ],
            'foot_visibility': [.99, .99, .99, .99],
          };
        }(),
    ],
  };
}

Map<String, dynamic> compute(Map<String, dynamic> c) =>
    const OrientationEngine().analyze(OrientationClip.fromJson(c));
Map<String, dynamic> clone(Map<String, dynamic> c) =>
    jsonDecode(jsonEncode(c)) as Map<String, dynamic>;
void near(dynamic actual, List<double> expected, [double tolerance = 1e-9]) {
  expect(actual, hasLength(expected.length));
  for (var j = 0; j < expected.length; j++) {
    expect(actual[j], closeTo(expected[j], tolerance));
  }
}

void main() {
  test(
    'front, back, left and right have independent known geometric answers',
    () {
      for (final pair in <(double, List<double>)>[
        (0, [0, 0, 1]),
        (90, [1, 0, 0]),
        (180, [0, 0, -1]),
        (270, [-1, 0, 0]),
      ]) {
        final r = compute(
          synthetic(turns: List.filled(6, pair.$1)),
        )['frames'][0];
        near(r['shoulder']['forward'], pair.$2);
        near(r['pelvis']['forward'], pair.$2);
        expect(r['shoulder']['determinant'], closeTo(1, 1e-12));
        expect(r['head_mode'], 'torso_proxy');
      }
    },
  );
  test(
    'continuous 360 degrees does not flip quaternion or mistake yaw wrap for a jump',
    () {
      final r =
          compute(
                synthetic(turns: List.generate(361, (i) => i.toDouble())),
              )['frames']
              as List;
      for (var i = 1; i < r.length; i++) {
        final q = r[i]['shoulder']['quaternion_xyzw'] as List,
            prev = r[i - 1]['shoulder']['quaternion_xyzw'] as List;
        expect(
          List.generate(
            4,
            (j) => (q[j] as num) * (prev[j] as num),
          ).reduce((a, b) => a + b),
          greaterThan(0),
        );
        expect(r[i]['shoulder_continuity']['delta_degrees'], closeTo(1, 1e-8));
        expect(r[i]['body_mode'], 'directional');
        expect(r[i]['shoulder_continuity']['near_180_flip'], false);
      }
      expect(
        r.last['shoulder_continuity']['unwrapped_yaw_degrees'],
        closeTo(360, 1e-7),
      );
    },
  );
  test('shoulder/hip twist and feet can rotate independently', () {
    final r = compute(
      synthetic(
        turns: List.filled(6, 60.0),
        hip: -15,
        leftFoot: 30,
        rightFoot: -45,
      ),
    )['frames'][0];
    expect(r['twist_degrees'], closeTo(75, 1e-9));
    near(r['feet'][0]['direction'], [.5, 0, math.sqrt(3) / 2]);
    near(r['feet'][1]['direction'], [-math.sqrt(.5), 0, math.sqrt(.5)]);
  });
  test(
    'coordinate restore is single and identical for mirrored/unmirrored inputs',
    () {
      final original = synthetic(turns: List.filled(6, 37.0));
      for (final mirror in [false, true]) {
        final raw = clone(original)
          ..['coordinate_convention'] = 'mediapipe_inference_world'
          ..['source_oriented'] = false
          ..['mirrored_input'] = mirror;
        for (final f in raw['frames']) {
          for (final field in ['positions', 'feet']) {
            final source = f[field] as List;
            final mapping = field == 'positions' ? bodySwap : footSwap;
            f[field] = [
              for (var j = 0; j < source.length; j++)
                [
                  (mirror ? -1 : 1) * source[mirror ? mapping[j] : j][0] + .6,
                  -source[mirror ? mapping[j] : j][1] + .9,
                  -source[mirror ? mapping[j] : j][2] + 1.3,
                ],
            ];
          }
        }
        final restored = OrientationClip.fromJson(raw),
            expected = OrientationClip.fromJson(original);
        for (var i = 0; i < 6; i++) {
          for (var j = 0; j < 12; j++) {
            near(
              restored.frames[i].positions[j]!.toJson(),
              expected.frames[i].positions[j]!.toJson(),
            );
          }
        }
        near(
          compute(raw)['frames'][0]['shoulder']['forward'],
          compute(original)['frames'][0]['shoulder']['forward'].cast<double>(),
        );
      }
    },
  );
  test(
    'LR index exchange reverses signed forward; it is not silently auto-flipped',
    () {
      final c = synthetic();
      for (final f in c['frames']) {
        final p = f['positions'];
        f['positions'] = [for (final j in bodySwap) p[j]];
      }
      near(compute(c)['frames'][0]['shoulder']['forward'], [0, 0, -1]);
    },
  );
  test(
    'source-oriented mirror metadata and handedness do not force facing direction',
    () {
      final c = synthetic(turns: List.filled(6, 43.0));
      final r = compute(c);
      c['mirrored_input'] = true;
      c['handedness'] = 'left';
      c['id'] = 'arbitrary-new-user';
      expect(compute(c), r);
      c['handedness'] = 'right';
      expect(compute(c), r);
    },
  );
  test(
    'single 180-degree anomaly is neutralized without altering observations',
    () {
      final c = synthetic(turns: [0, 0, 180, 0, 0, 0]);
      final snapshot = jsonEncode(c);
      final r = compute(c)['frames'];
      expect(r[2]['shoulder_continuity']['near_180_flip'], true);
      expect(r[2]['body_mode'], 'neutral');
      expect(r[3]['body_mode'], 'neutral');
      expect(r[4]['body_mode'], 'neutral');
      expect(r[5]['body_mode'], 'directional');
      expect(jsonEncode(c), snapshot);
      near(r[2]['shoulder']['forward'], [0, 0, -1]);
    },
  );
  test(
    'missing joints and time gaps reset continuity rather than bridging',
    () {
      final c = synthetic();
      c['frames'][1]['positions'][0] = null;
      for (var i = 3; i < 6; i++) {
        c['frames'][i]['timestamp_s'] += 1;
      }
      final r = compute(c)['frames'];
      expect(r[1]['shoulder'], null);
      expect(r[2]['body_mode'], 'neutral');
      expect(r[3]['shoulder_continuity']['adjacent_supported'], false);
      expect(r[3]['shoulder_reasons'], contains('time_gap_reset'));
    },
  );
  test('degenerate torso and collinear axes do not produce NaNs', () {
    final c = synthetic();
    c['frames'][0]['positions'][0] = [0, .5, 0];
    c['frames'][0]['positions'][1] = [0, .5, 0];
    c['frames'][1]['positions'][0] = [0, .6, 0];
    c['frames'][1]['positions'][1] = [0, .4, 0];
    final r = compute(c);
    expect(r['frames'][0]['shoulder'], null);
    expect(r['frames'][1]['shoulder'], null);
    expect(() => jsonEncode(r), returnsNormally);
  });
  test(
    'missing/low-quality/additional foot data produces neutral independent feet',
    () {
      final c = synthetic();
      c['frames'][0]['feet'][0] = null;
      c['frames'][1]['foot_visibility'][0] = .1;
      c['frames'][2]['positions'][10] = null;
      final r = compute(c)['frames'];
      expect(r[0]['feet'][0]['mode'], 'neutral');
      expect(r[0]['feet'][1]['mode'], 'directional');
      expect(r[1]['feet'][0]['mode'], 'neutral');
      expect(r[2]['feet'][0]['mode'], 'missing');
      for (final f in c['frames']) {
        f.remove('feet');
        f.remove('foot_visibility');
      }
      expect(compute(c)['frames'][0]['feet'][0]['mode'], 'neutral');
    },
  );
  test('ankle geometry and adjacent foot reversal are diagnosed', () {
    final c = synthetic();
    c['frames'][1]['feet'][0] = [3, 3, 3];
    c['frames'][1]['feet'][2] = [3, 3, 3.23];
    final swapped = c['frames'][3]['feet'][0];
    c['frames'][3]['feet'][0] = c['frames'][3]['feet'][2];
    c['frames'][3]['feet'][2] = swapped;
    final r = compute(c)['frames'];
    expect(r[1]['feet'][0]['reasons'], contains('ankle_heel_toe_inconsistent'));
    expect(r[3]['feet'][0]['continuity']['near_180_flip'], true);
  });
  test(
    'invalid count, unknown convention, nonfinite and duplicate timestamps reject',
    () {
      final c = synthetic();
      c['frame_count'] = 7;
      expect(() => compute(c), throwsFormatException);
      c['frame_count'] = 6;
      c['coordinate_convention'] = 'unknown';
      expect(() => compute(c), throwsFormatException);
      c['coordinate_convention'] = renderConvention;
      c['frames'][1]['timestamp_s'] = 0;
      expect(() => compute(c), throwsFormatException);
      c['frames'][1]['timestamp_s'] = 1 / 60;
      c['frames'][0]['positions'][0][0] = double.nan;
      expect(() => compute(c), throwsFormatException);
    },
  );
  test('malformed optional display inputs reject before renderer access', () {
    final c = synthetic();
    c['frames'][0]['p2'] = {
      'torso_visible': true,
      'edge_visible': [true],
      'joint_warnings': List.filled(12, false),
    };
    expect(() => compute(c), throwsFormatException);
    c['frames'][0].remove('p2');
    c['frames'][0]['legacy_feet'] = [
      {'mode': 'directional', 'direction': null},
      {'mode': 'missing', 'direction': null},
    ];
    expect(() => compute(c), throwsFormatException);
    c['frames'][0].remove('legacy_feet');
    c.remove('foot_joint_names');
    expect(() => compute(c), throwsFormatException);
  });
  test(
    'unbounded coordinates and invalid visibility cannot overflow geometry',
    () {
      final c = synthetic();
      c['frames'][0]['positions'][0][0] = 1e308;
      expect(() => compute(c), throwsFormatException);
      c['frames'][0]['positions'][0][0] = .23;
      c['frames'][0]['foot_visibility'][0] = 1.5;
      expect(() => compute(c), throwsFormatException);
    },
  );
}
