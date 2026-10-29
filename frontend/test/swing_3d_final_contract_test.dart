import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/final_motion.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';
import 'synthetic_pose_fixture.dart';

Map<String, dynamic> bundle(String stem) =>
    syntheticClipJson(short: stem == 'right30');
void near(dynamic a, dynamic b, String path) {
  if (b is num) {
    expect(a, isA<num>(), reason: path);
    expect((a as num).toDouble(), closeTo(b.toDouble(), 1e-8), reason: path);
  } else if (b is List) {
    expect(a, isA<List>(), reason: path);
    expect((a as List).length, b.length, reason: path);
    for (var i = 0; i < b.length; i++) {
      near(a[i], b[i], '$path[$i]');
    }
  } else if (b is Map) {
    expect(a, isA<Map>(), reason: path);
    expect((a as Map).keys.toSet(), b.keys.toSet(), reason: path);
    for (final k in b.keys) {
      near(a[k], b[k], '$path.$k');
    }
  } else {
    expect(a, b, reason: path);
  }
}

void main() {
  test('synthetic S2 + O1/F1 + H4 binds without modifying raw observations', () {
    for (final stem in ['left60', 'right30']) {
      final json = bundle(stem), before = jsonEncode(json);
      final clip = SwingClip.fromJson(json), finalMotion = clip.finalMotion!;
      for (var i = 0; i < clip.frameCount; i++) {
        expect(
          clip.frames[i].positions.map((p) => p?.toList()).toList(),
          json['frames'][i]['positions'],
        );
        expect(
          finalMotion.positionsAt(i).map((p) => p?.toList()).toList(),
          json['final_display_data']['display_orientation']['frames'][i]['positions'],
        );
        expect(
          finalMotion.directional.clip.frames[i].extra['p2'],
          json['orientation_data']['frames'][i]['p2'],
        );
        expect(clip.frameIndexAt(clip.timestamps[i]), i);
      }
      expect(jsonEncode(json), before);
      expect(clip.frameCount, stem == 'left60' ? 100 : 27);
    }
  });
  test(
    'synthetic right-handed clip carries all 27 decoded-PTS frames at 30 FPS',
    () async {
      TestWidgetsFlutterBinding.ensureInitialized();
      final clip = SwingClip.fromJson(bundle('right30'));
      expect(clip.frameCount, 27);
      expect(clip.fps, closeTo(30.0, 1e-9));
      expect(clip.effectiveFps, closeTo(30, 1e-9));
      expect(clip.duration, closeTo(.9, 1e-9));
      expect(clip.isSample, false);
      expect(clip.analysisId, 'synthetic-right30');
      expect(clip.finalMotion, isNotNull);
      for (var i = 0; i < 27; i++) {
        expect(clip.timestamps[i], closeTo(i / 30, 1e-9));
      }
      expect(
        clip.finalMotion!.directional.clip.metadata['presentation_end_s'],
        closeTo(.9, 1e-9),
      );
    },
  );
  test(
    'unknown direction metadata leaves H4 featureless without inventing batting side',
    () {
      final json = bundle('left60');
      for (final seq in [
        json,
        json['orientation_data'],
        json['final_display_data']['raw_orientation'],
        json['final_display_data']['display_orientation'],
      ]) {
        seq['handedness'] = 'unknown';
      }
      final motion = SwingClip.fromJson(json).finalMotion!;
      expect(motion.headResult['baseline']['reason'], 'unknown_batting_side');
      for (var i = 0; i < 100; i++) {
        expect(motion.headAt(i)['display_features'], false);
        expect(motion.headAt(i)['axes'], null);
      }
    },
  );
  test(
    'optional feet absence keeps knees/ankles and both neutral foot fallbacks',
    () {
      final json = bundle('left60');
      for (final seq in [
        json['orientation_data'],
        json['final_display_data']['raw_orientation'],
        json['final_display_data']['display_orientation'],
      ]) {
        seq.remove('foot_joint_names');
        for (final f in seq['frames']) {
          f.remove('feet');
          f.remove('foot_visibility');
          f.remove('legacy_feet');
        }
      }
      final clip = SwingClip.fromJson(json), finalMotion = clip.finalMotion!;
      for (final index in [0, 54, 71, 89, 99]) {
        expect(
          finalMotion.directional.frameAt(index)['feet'].map((f) => f['mode']),
          ['neutral', 'neutral'],
        );
        for (final j in [8, 9, 10, 11]) {
          expect(
            clip.frames[index].positions[j]!.toList(),
            json['frames'][index]['positions'][j],
          );
          expect(
            finalMotion.positionsAt(index)[j]!.toList(),
            json['final_display_data']['display_orientation']['frames'][index]['positions'][j],
          );
        }
      }
    },
  );
  test('generic package can derive the fixed O1 reference scale once', () {
    final json = bundle('left60'),
        expected = SwingClip.fromJson(bundle('left60')).finalMotion!;
    json['final_display_data']['reference_scale'] = null;
    final actual = SwingClip.fromJson(json).finalMotion!;
    expect(actual.referenceScale, expected.referenceScale);
    near(actual.headResult, expected.headResult, 'derived-scale');
  });
  test(
    'invalid source, time, smoothing and P2 contracts reject explicitly',
    () {
      final mutations =
          <void Function(Map<String, dynamic>, Map<String, dynamic>)>[
            (d, b) => d['binding']['source_sha256'] = '0' * 64,
            (d, b) {
              d['binding']['source_sha256'] = null;
              b['source_provenance'].remove('source_video_sha256');
            },
            (d, b) =>
                d['display_orientation']['source_provenance']['source_sha256'] =
                    '0' * 64,
            (d, b) => d['processing']['smoothing_passes'] = 2,
            (d, b) => d['processing']['interpolation'] = true,
            (d, b) => d['processing']['s2_config_sha256'] = '0' * 64,
            (d, b) => d['processing']['h4_policy_version'] = 'unverified',
            (d, b) => d['raw_orientation']['smoothing']['condition'] = 'S2',
            (d, b) => d['display_orientation']['smoothing']['condition'] = 'S0',
            (d, b) =>
                d['display_orientation']['smoothing']['version'] = 'unverified',
            (d, b) =>
                d['display_orientation']['frames'][1]['timestamp_s'] += .001,
            (d, b) {
              d['raw_orientation']['frames'][1]['decoded_pts_s'] += .001;
              d['display_orientation']['frames'][1]['decoded_pts_s'] += .001;
            },
            (d, b) =>
                d['display_orientation']['frames'][1]['p2']['edge_visible'][0] =
                    false,
            (d, b) {
              for (final seq in [
                d['raw_orientation'],
                d['display_orientation'],
              ]) {
                seq['frames'][1]['p2']['edge_visible'][0] = false;
              }
            },
            (d, b) => d['display_orientation']['frames'][1].remove('p2'),
            (d, b) =>
                d['display_orientation']['frames'][1]['positions'][4] = null,
            (d, b) =>
                d['raw_orientation']['frames'][1]['positions'][4][0] += .001,
            (d, b) => d['display_orientation']['source_oriented'] = false,
            (d, b) => d['display_orientation']['mirrored_input'] = false,
            (d, b) => d['display_orientation']['fps'] = 30,
            (d, b) => d['presentation_end_s'] += .1,
            (d, b) => d['reference_scale'] = 10000.0,
          ];
      for (var i = 0; i < mutations.length; i++) {
        final body = bundle('left60'),
            data = body['final_display_data'] as Map<String, dynamic>;
        mutations[i](data, body);
        expect(
          () => FinalMotion.bind(data, body),
          throwsFormatException,
          reason: 'mutation $i',
        );
      }
    },
  );
}
