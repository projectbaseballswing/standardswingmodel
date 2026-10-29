import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';

Map<String, dynamic> _json({List<double> times = const [0, .04, .20, .23]}) =>
    <String, dynamic>{
      'schema_version': 1,
      'id': 'fixture',
      'title': 'Strict world fixture',
      'handedness': 'right',
      'fps': 30,
      'coordinate_space': 'world',
      'coordinate_convention': 'source_view_hip_centered_xright_yup_zcamera',
      'joint_names': List<String>.from(jointNames),
      'render_to_npz_joint_indices': List.generate(12, (j) => j),
      'timestamps_s': List<double>.from(times),
      'frames': <Map<String, dynamic>>[
        for (var f = 0; f < times.length; f++)
          <String, dynamic>{
            'index': f,
            'timestamp_s': times[f],
            'decoded_pts_s': times[f],
            'positions': List<dynamic>.generate(
              12,
              (j) => <double>[j.toDouble(), f.toDouble(), .25],
            ),
            'visibility': List<dynamic>.filled(12, .9),
            'observed_valid': List<bool>.filled(12, true),
            'image_quality_render': <String, dynamic>{
              'combined_missing': List<bool>.filled(12, false),
              'interpolated': List<bool>.filled(12, false),
              'edge_filled': List<bool>.filled(12, false),
              'provenance': 'Image processing hints only',
            },
            'manual_review_annotations': <dynamic>[],
            'warnings': <String>['Fixture source warning'],
            'source_frame_asset': 'assets/frames/fixture/$f.jpg',
          },
      ],
    };

Map<String, dynamic> _frame(Map<String, dynamic> json, int index) =>
    (json['frames'] as List)[index] as Map<String, dynamic>;

void main() {
  test(
    'actual irregular timestamps use floor binary search, never invented poses',
    () {
      final clip = SwingClip.fromJson(_json());
      expect(clip.frameIndexAt(-100), 0);
      expect(clip.frameIndexAt(0), 0);
      expect(clip.frameIndexAt(.039999), 0);
      expect(clip.frameIndexAt(.04), 1);
      expect(clip.frameIndexAt(.19999), 1);
      expect(clip.frameIndexAt(.20), 2);
      expect(clip.frameIndexAt(.23), 3);
      expect(clip.frameIndexAt(100), 3);
      expect(clip.duration, closeTo(.23 + 1 / 30, 1e-12));
      expect(() => clip.frameIndexAt(double.nan), throwsArgumentError);
      expect(() => clip.frameIndexAt(double.infinity), throwsArgumentError);
    },
  );

  test('a null whole point is a missing observation, not the origin', () {
    final json = _json();
    (_frame(json, 1)['positions'] as List)[4] = null;
    (_frame(json, 1)['observed_valid'] as List)[4] = false;
    (_frame(json, 1)['visibility'] as List)[4] = null;
    final clip = SwingClip.fromJson(json);
    expect(clip.frames[1].positions[4], isNull);
    expect(clip.frames[1].visibility[4], isNull);
    expect(clip.frames[1].finiteJointCount, 11);
    expect(clip.frames[0].positions[4]!.x, 4);
    expect(clip.frames[2].positions[4]!.x, 4);
  });

  test(
    'malformed coordinate length and nonfinite values are explicit errors',
    () {
      for (final bad in <Object>[
        [1, 2],
        [1, double.nan, 3],
        [1, double.infinity, 3],
        [1, null, 3],
      ]) {
        final json = _json();
        (_frame(json, 0)['positions'] as List)[2] = bad;
        expect(() => SwingClip.fromJson(json), throwsA(isA<FormatException>()));
      }
      final json = _json();
      (_frame(json, 0)['positions'] as List).removeLast();
      expect(
        () => SwingClip.fromJson(json),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'path',
            contains('frames[0].positions'),
          ),
        ),
      );
    },
  );

  test(
    'frame count, index, timestamp and joint order cannot silently mismatch',
    () {
      final shortened = _json();
      (shortened['frames'] as List).removeLast();
      expect(() => SwingClip.fromJson(shortened), throwsFormatException);
      final wrongIndex = _json();
      _frame(wrongIndex, 2)['index'] = 3;
      expect(() => SwingClip.fromJson(wrongIndex), throwsFormatException);
      final wrongTime = _json();
      _frame(wrongTime, 2)['timestamp_s'] = .201;
      expect(() => SwingClip.fromJson(wrongTime), throwsFormatException);
      final wrongDeclaredCount = _json()..['frame_count'] = 99;
      expect(
        () => SwingClip.fromJson(wrongDeclaredCount),
        throwsFormatException,
      );
      final wrongNames = _json();
      (wrongNames['joint_names'] as List)[0] = 'right_shoulder';
      expect(() => SwingClip.fromJson(wrongNames), throwsFormatException);
    },
  );

  test(
    'time axis must be nonempty, finite, relative and strictly increasing',
    () {
      for (final times in <List<double>>[
        [],
        [0, 0],
        [0, .1, .05],
        [-.1, 0],
        [1, 2],
        [0, double.infinity],
      ]) {
        expect(
          () => SwingClip.fromJson(_json(times: times)),
          throwsFormatException,
        );
      }
      final json = _json()..['fps'] = 0;
      expect(() => SwingClip.fromJson(json), throwsFormatException);
      final single = SwingClip.fromJson(_json(times: [0]));
      expect(single.frameIndexAt(10), 0);
      expect(single.duration, closeTo(1 / 30, 1e-12));
    },
  );

  test(
    'render-order bilateral mapping is metadata, not applied a second time',
    () {
      final json = _json()..['handedness'] = 'left';
      const mapping = [1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10];
      json['render_to_npz_joint_indices'] = mapping;
      (_frame(json, 0)['positions'] as List)[0] = <double>[-.45, .2, -.7];
      (_frame(json, 0)['positions'] as List)[1] = <double>[.15, .4, .8];
      final clip = SwingClip.fromJson(json);
      expect(clip.renderToNpzJointIndices, mapping);
      expect(clip.frames[0].positions[0]!.toList(), [-.45, .2, -.7]);
      expect(clip.frames[0].positions[1]!.toList(), [.15, .4, .8]);
      expect(bilateralJointPairs.length, 6);
      json['render_to_npz_joint_indices'] = List.filled(12, 0);
      expect(() => SwingClip.fromJson(json), throwsFormatException);
    },
  );

  test(
    'mask and confidence contradictions are rejected with no fallback repair',
    () {
      final missing = _json();
      (_frame(missing, 0)['positions'] as List)[0] = null;
      expect(() => SwingClip.fromJson(missing), throwsFormatException);
      final score = _json();
      (_frame(score, 0)['visibility'] as List)[0] = 1.1;
      expect(() => SwingClip.fromJson(score), throwsFormatException);
      final mask = _json();
      (_frame(mask, 0)['image_quality_render'] as Map)['combined_missing'] =
          List.filled(11, false);
      expect(() => SwingClip.fromJson(mask), throwsFormatException);
      final coordinate = _json()..['coordinate_space'] = 'image';
      expect(() => SwingClip.fromJson(coordinate), throwsFormatException);
    },
  );

  test(
    'manual labels preserve provenance and cannot contain invalid indexes',
    () {
      final json = _json();
      _frame(json, 0)['manual_review_annotations'] = <Map<String, dynamic>>[
        {
          'label': 'Known failure',
          'joint_indices': [2, 4],
          'note': 'Manual review, not automatic detection',
        },
      ];
      final clip = SwingClip.fromJson(json);
      expect(clip.frames[0].manualAnnotations.single.jointIndices, [2, 4]);
      expect(
        clip.frames[0].manualAnnotations.single.note,
        contains('not automatic'),
      );
      ((_frame(json, 0)['manual_review_annotations'] as List).single
          as Map)['joint_indices'] = [
        12,
      ];
      expect(() => SwingClip.fromJson(json), throwsFormatException);
    },
  );

  test(
    'parsed source arrays remain immutable and detached from JSON containers',
    () {
      final json = _json();
      final clip = SwingClip.fromJson(json);
      (_frame(json, 0)['positions'] as List)[0] = [100, 100, 100];
      expect(clip.frames[0].positions[0]!.x, 0);
      expect(() => clip.frames[0].positions[0] = null, throwsUnsupportedError);
      expect(() => clip.timestamps[0] = 1, throwsUnsupportedError);
    },
  );
}
