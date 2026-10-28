import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/head_policy.dart';

Map<String, dynamic> clone(Map<String, dynamic> value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;
void nearTree(dynamic actual, dynamic expected, String path) {
  if (expected is num) {
    expect(actual, isA<num>(), reason: path);
    expect(
      (actual as num).toDouble(),
      closeTo(expected.toDouble(), 1e-8),
      reason: path,
    );
  } else if (expected is List) {
    expect(actual, isA<List>(), reason: path);
    expect((actual as List).length, expected.length, reason: path);
    for (var i = 0; i < expected.length; i++) {
      nearTree(actual[i], expected[i], '$path[$i]');
    }
  } else if (expected is Map) {
    expect(actual, isA<Map>(), reason: path);
    expect((actual as Map).keys.toSet(), expected.keys.toSet(), reason: path);
    for (final key in expected.keys) {
      nearTree(actual[key], expected[key], '$path.$key');
    }
  } else {
    expect(actual, expected, reason: path);
  }
}

Map<String, dynamic> run(Map<String, dynamic> c, {String? hand}) =>
    const HeadPolicy().analyze(
      c['clip'] as Map<String, dynamic>,
      c['orientations'] as Map<String, dynamic>,
      handedness: hand ?? c['handedness'] as String?,
      referenceScale: (c['reference_scale'] as num).toDouble(),
    );

Map<String, dynamic> synthetic(List<double> yaws, {String hand = 'right'}) {
  final frames = <Map<String, dynamic>>[],
      orientations = <Map<String, dynamic>>[];
  for (var i = 0; i < yaws.length; i++) {
    final axes = headAxesFromYaw(yaws[i] * math.pi / 180),
        x = axes['x'] as List;
    List<double> p(double side, double height) => [
      (x[0] as num) * side,
      height,
      (x[2] as num) * side,
    ];
    frames.add({
      'timestamp_s': i / 60,
      'positions': [
        p(.2, .5),
        p(-.2, .5),
        p(.3, .3),
        p(-.3, .3),
        p(.4, .2),
        p(-.4, .2),
        p(.13, 0),
        p(-.13, 0),
        p(.1, -.4),
        p(-.1, -.4),
        p(.1, -.8),
        p(-.1, -.8),
      ],
      'p2': {'torso_visible': true},
    });
    orientations.add({
      'timestamp_s': i / 60,
      'shoulder': axes,
      'pelvis': axes,
      'shoulder_continuity': {'abrupt': false, 'directional': true},
      'pelvis_continuity': {'abrupt': false, 'directional': true},
    });
  }
  return {
    'handedness': hand,
    'reference_scale': 1.0,
    'clip': {
      'coordinate_convention': headPolicyConfig['coordinate_convention'],
      'source_oriented': true,
      'presentation_end_s': yaws.length / 60,
      'frames': frames,
    },
    'orientations': {'frames': orientations},
  };
}

void main() {
  final cases = [
    for (final hand in ['left', 'right'])
      for (final yaw in [-150.0, -90.0, 0.0, 60.0, 120.0, 170.0])
        synthetic(List.generate(60, (i) => yaw + i * .4), hand: hand),
  ];
  test('diverse synthetic rotations stay bounded and do not mutate input', () {
    for (final c in cases) {
      final before = jsonEncode(c), result = run(c);
      expect(jsonEncode(c), before);
      expect(
        result['summary']['clip_yaw_span_deg'],
        lessThanOrEqualTo(45.000001),
      );
      expect(
        result['summary']['maximum_adjacent_rate_deg_s'],
        lessThanOrEqualTo(90.000001),
      );
      for (final f in result['frames']) {
        if (f['H4']['display_features'] == true) {
          expect(validHeadAxes(f['H4']['axes']), true);
        }
      }
    }
  });
  test('unknown handedness becomes neutral without inventing direction', () {
    final c = clone(cases.first);
    c['handedness'] = null;
    final result = run(c);
    expect(result['baseline']['reason'], 'unknown_batting_side');
    for (final f in result['frames']) {
      expect(f['H4']['mode'], 'neutral');
      expect(f['H4']['axes'], null);
      expect(f['H4']['display_features'], false);
    }
  });
  test('coordinate restoration and temporal identity are enforced', () {
    for (final key in ['source_oriented', 'coordinate_convention']) {
      final c = clone(cases.first);
      c['clip'].remove(key);
      expect(() => run(c), throwsFormatException);
    }
    final c = clone(cases.first);
    c['clip']['frames'][1]['timestamp_s'] = 0;
    expect(() => run(c), throwsFormatException);
    final d = clone(cases.first);
    d['orientations']['frames'][1]['timestamp_s'] += .001;
    expect(() => run(d), throwsFormatException);
  });
  test('live camera and identity metadata cannot steer the computed head', () {
    final c = clone(cases.first), before = run(c);
    c['clip']['id'] = 'new-user';
    c['clip']['player'] = 'unseen';
    c['clip']['live_camera'] = {'yaw': -2.1, 'pitch': .9, 'zoom': 4};
    nearTree(run(c), before, 'camera-independent');
  });
  test('yaw crosses the angle wrap continuously on both batting sides', () {
    for (final hand in ['left', 'right']) {
      final c = synthetic(List.generate(60, (i) => 170 + i * .5), hand: hand);
      final result = run(c), summary = result['summary'];
      expect(summary['neutral_frames'], 0);
      expect(
        summary['maximum_adjacent_rate_deg_s'],
        lessThanOrEqualTo(90.000001),
      );
      expect(summary['clip_yaw_span_deg'], lessThanOrEqualTo(45.000001));
      for (final f in result['frames']) {
        expect(validHeadAxes(f['H4']['axes']), true);
      }
    }
  });
  test(
    'body/P2 gaps stay neutral; expired torso support uses explicit display hold',
    () {
      final c = clone(synthetic(List.filled(50, 0.0)));
      for (var i = 20; i < 40; i++) {
        c['orientations']['frames'][i]['shoulder_continuity']['directional'] =
            false;
      }
      c['clip']['frames'][25]['p2']['torso_visible'] = false;
      c['clip']['frames'][26]['positions'][0] = null;
      final result = run(c), fs = result['frames'];
      expect(fs[25]['H4']['mode'], 'neutral');
      expect(fs[26]['H4']['mode'], 'neutral');
      expect(fs[35]['H4']['mode'], 'conservative_batter');
      expect(fs[35]['H4']['conservative_torso_display_hold'], true);
      expect(fs[35]['diagnostic']['face_used'], false);
    },
  );
  test('short clip and malformed handed axes cannot invent a baseline', () {
    expect(run(synthetic([0, 0]))['summary']['directional_frames'], 0);
    final c = synthetic(List.filled(20, 0.0));
    for (final f in c['orientations']['frames']) {
      f['shoulder']['forward'] = [0.0, 0.0, -1.0];
    }
    expect(run(c)['summary']['directional_frames'], 0);
    expect(
      validHeadAxes({
        'x': [1, 0, 0],
        'up': [0, 1, 0],
        'forward': [0, 0, -1],
      }),
      false,
    );
  });
  test('H4 local +Z and quaternion agree, independent of torso rotation', () {
    for (final degrees in [0.0, 90.0, 180.0, -179.0]) {
      final a = headAxesFromYaw(degrees * math.pi / 180),
          q = a['quaternion_xyzw'] as List;
      final expected = [
        2 * (q[1] as num) * (q[3] as num),
        0.0,
        1 - 2 * (q[1] as num) * (q[1] as num),
      ];
      nearTree(a['forward'], expected, 'local+Z');
    }
  });
}
