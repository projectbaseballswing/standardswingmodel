import 'dart:math' as math;
import 'directional_pose.dart';
import 'final_motion.dart';

const jointNames = <String>[
  'left_shoulder',
  'right_shoulder',
  'left_elbow',
  'right_elbow',
  'left_wrist',
  'right_wrist',
  'left_hip',
  'right_hip',
  'left_knee',
  'right_knee',
  'left_ankle',
  'right_ankle',
];

/// The JSON converter has already reflected and relabelled mirrored sources.
/// These names/indexes always describe the converter's render order.
const bilateralJointPairs = <(int, int)>[
  (0, 1),
  (2, 3),
  (4, 5),
  (6, 7),
  (8, 9),
  (10, 11),
];

class Vec3 {
  const Vec3(this.x, this.y, this.z);

  final double x;
  final double y;
  final double z;

  bool get isFinite => x.isFinite && y.isFinite && z.isFinite;
  double get length => math.sqrt(x * x + y * y + z * z);
  Vec3 operator +(Vec3 other) => Vec3(x + other.x, y + other.y, z + other.z);
  Vec3 operator -(Vec3 other) => Vec3(x - other.x, y - other.y, z - other.z);
  Vec3 operator *(double scale) => Vec3(x * scale, y * scale, z * scale);
  Vec3 operator /(double scale) => Vec3(x / scale, y / scale, z / scale);
  List<double> toList() => <double>[x, y, z];

  @override
  String toString() => 'Vec3($x, $y, $z)';
}

class PoseBone {
  const PoseBone(this.id, this.parent, this.child);
  final String id;
  final int parent;
  final int child;
}

/// Parent-first ordering is intentional: an elbow adjustment carries its wrist.
const limbBones = <PoseBone>[
  PoseBone('left_upper_arm', 0, 2),
  PoseBone('left_forearm', 2, 4),
  PoseBone('right_upper_arm', 1, 3),
  PoseBone('right_forearm', 3, 5),
  PoseBone('left_thigh', 6, 8),
  PoseBone('left_shin', 8, 10),
  PoseBone('right_thigh', 7, 9),
  PoseBone('right_shin', 9, 11),
];

class ImageQualityHints {
  ImageQualityHints({
    required List<bool> combinedMissing,
    required List<bool> interpolated,
    required List<bool> edgeFilled,
    required this.provenance,
  }) : combinedMissing = List.unmodifiable(combinedMissing),
       interpolated = List.unmodifiable(interpolated),
       edgeFilled = List.unmodifiable(edgeFilled);

  final List<bool> combinedMissing;
  final List<bool> interpolated;
  final List<bool> edgeFilled;
  final String provenance;

  bool hasHint(int joint) =>
      combinedMissing[joint] || interpolated[joint] || edgeFilled[joint];
}

class ManualReviewAnnotation {
  ManualReviewAnnotation({
    required this.label,
    required List<int> jointIndices,
    required this.note,
  }) : jointIndices = List.unmodifiable(jointIndices);

  final String label;
  final List<int> jointIndices;
  final String note;
}

class PoseFrame {
  PoseFrame._({
    required this.index,
    required this.timestamp,
    required this.decodedPts,
    required List<Vec3?> positions,
    required List<double?> visibility,
    required List<bool> observedValid,
    required this.imageQuality,
    required List<ManualReviewAnnotation> manualAnnotations,
    required List<String> warnings,
    required this.sourceFrameAsset,
  }) : positions = List.unmodifiable(positions),
       visibility = List.unmodifiable(visibility),
       observedValid = List.unmodifiable(observedValid),
       manualAnnotations = List.unmodifiable(manualAnnotations),
       warnings = List.unmodifiable(warnings);

  final int index;
  final double timestamp;
  final double? decodedPts;
  final List<Vec3?> positions;

  /// Image landmark visibility, a proxy hint; NOT a world-coordinate confidence.
  final List<double?> visibility;
  final List<bool> observedValid;
  final ImageQualityHints imageQuality;
  final List<ManualReviewAnnotation> manualAnnotations;
  final List<String> warnings;
  final String? sourceFrameAsset;

  bool get hasValidRoot =>
      observedValid[6] &&
      observedValid[7] &&
      positions[6] != null &&
      positions[7] != null;
  int get finiteJointCount => positions.where((p) => p != null).length;

  factory PoseFrame.fromJson(
    Map<String, dynamic> json, {
    required int expectedIndex,
    required double expectedTimestamp,
  }) {
    final path = 'frames[$expectedIndex]';
    final index = _integer(json['index'], '$path.index');
    if (index != expectedIndex) {
      _bad(
        '$path.index',
        'expected contiguous index $expectedIndex, got $index',
      );
    }
    final timestamp = _number(json['timestamp_s'], '$path.timestamp_s');
    if ((timestamp - expectedTimestamp).abs() > 0.000001) {
      _bad('$path.timestamp_s', 'does not match timestamps_s[$expectedIndex]');
    }
    final rawPositions = _listOfLength(
      json['positions'],
      12,
      '$path.positions',
    );
    final positions = <Vec3?>[];
    for (var j = 0; j < 12; j++) {
      final value = rawPositions[j];
      if (value == null) {
        positions.add(null);
      } else {
        final xyz = _listOfLength(value, 3, '$path.positions[$j]');
        positions.add(
          Vec3(
            _number(xyz[0], '$path.positions[$j][0]'),
            _number(xyz[1], '$path.positions[$j][1]'),
            _number(xyz[2], '$path.positions[$j][2]'),
          ),
        );
      }
    }
    final rawVisibility = _listOfLength(
      json['visibility'],
      12,
      '$path.visibility',
    );
    final visibility = <double?>[];
    for (var j = 0; j < 12; j++) {
      final value = rawVisibility[j];
      if (value == null) {
        visibility.add(null);
      } else {
        final score = _number(value, '$path.visibility[$j]');
        if (score < 0 || score > 1) {
          _bad('$path.visibility[$j]', 'expected a score in [0, 1]');
        }
        visibility.add(score);
      }
    }
    final observed = _bools(json['observed_valid'], '$path.observed_valid');
    for (var j = 0; j < 12; j++) {
      if (observed[j] && positions[j] == null) {
        _bad('$path.observed_valid[$j]', 'cannot be true for a null position');
      }
    }
    final hintJson = json['image_quality_render'] == null
        ? <String, dynamic>{}
        : _map(json['image_quality_render'], '$path.image_quality_render');
    List<bool> hint(String name) => hintJson.containsKey(name)
        ? _bools(hintJson[name], '$path.image_quality_render.$name')
        : List.filled(12, false);
    final quality = ImageQualityHints(
      combinedMissing: hint('combined_missing'),
      interpolated: hint('interpolated'),
      edgeFilled: hint('edge_filled'),
      provenance: hintJson['provenance'] == null
          ? 'No image preprocessing hints supplied; absence is not evidence of accuracy.'
          : _string(
              hintJson['provenance'],
              '$path.image_quality_render.provenance',
            ),
    );
    final annotations = <ManualReviewAnnotation>[];
    final rawAnnotations = json['manual_review_annotations'] ?? <dynamic>[];
    if (rawAnnotations is! List) {
      _bad('$path.manual_review_annotations', 'expected an array');
    }
    for (var a = 0; a < rawAnnotations.length; a++) {
      final annotationPath = '$path.manual_review_annotations[$a]';
      final annotation = _map(rawAnnotations[a], annotationPath);
      final indices = annotation['joint_indices'];
      if (indices is! List) {
        _bad('$annotationPath.joint_indices', 'expected an array');
      }
      final joints = <int>[];
      for (final value in indices) {
        final j = _integer(value, '$annotationPath.joint_indices');
        if (j < 0 || j >= 12 || joints.contains(j)) {
          _bad(
            '$annotationPath.joint_indices',
            'expected distinct joint indexes in [0, 11]',
          );
        }
        joints.add(j);
      }
      annotations.add(
        ManualReviewAnnotation(
          label: _string(annotation['label'], '$annotationPath.label'),
          jointIndices: joints,
          note: _string(annotation['note'], '$annotationPath.note'),
        ),
      );
    }
    return PoseFrame._(
      index: index,
      timestamp: timestamp,
      decodedPts: json['decoded_pts_s'] == null
          ? null
          : _number(json['decoded_pts_s'], '$path.decoded_pts_s'),
      positions: positions,
      visibility: visibility,
      observedValid: observed,
      imageQuality: quality,
      manualAnnotations: annotations,
      warnings: _strings(json['warnings'] ?? <dynamic>[], '$path.warnings'),
      sourceFrameAsset: json['source_frame_asset'] == null
          ? null
          : _string(json['source_frame_asset'], '$path.source_frame_asset'),
    );
  }
}

class SwingClip {
  SwingClip._({
    required this.id,
    required this.title,
    required this.handedness,
    required this.fps,
    required List<double> timestamps,
    required List<PoseFrame> frames,
    required List<int> renderToNpzJointIndices,
    required this.imageQualityNote,
    required this.coordinateConvention,
    required List<String> warnings,
    required this.directional,
    required this.finalMotion,
    required this.analysisId,
    required this.dataKind,
  }) : timestamps = List.unmodifiable(timestamps),
       frames = List.unmodifiable(frames),
       renderToNpzJointIndices = List.unmodifiable(renderToNpzJointIndices),
       warnings = List.unmodifiable(warnings);

  final String id;
  final String title;
  final String handedness;
  final double fps;
  final List<double> timestamps;
  final List<PoseFrame> frames;
  final List<int> renderToNpzJointIndices;
  final String imageQualityNote;
  final String coordinateConvention;
  final List<String> warnings;
  final DirectionalMotion? directional;
  final FinalMotion? finalMotion;
  final String? analysisId;
  final String dataKind;
  bool get isSample => dataKind == 'sample';

  /// Final display uses decoded PTS plus its declared final sample hold.
  /// Legacy clips retain their nominal frame hold; no motion is invented.
  double get duration =>
      finalMotion?.presentationEnd ?? timestamps.last + 1 / fps;

  /// Observed median PTS rate, distinct from the source nominal FPS metadata.
  double get effectiveFps {
    if (timestamps.length < 2) return fps;
    final gaps = [
      for (var i = 1; i < timestamps.length; i++)
        timestamps[i] - timestamps[i - 1],
    ]..sort();
    final middle = gaps.length ~/ 2;
    return 1 /
        (gaps.length.isOdd
            ? gaps[middle]
            : (gaps[middle - 1] + gaps[middle]) / 2);
  }

  int get frameCount => frames.length;

  /// Sample-and-hold on actual timestamps, including irregular gaps. No blend.
  int frameIndexAt(double seconds) {
    if (!seconds.isFinite) {
      throw ArgumentError.value(seconds, 'seconds', 'must be finite');
    }
    if (seconds <= timestamps.first) return 0;
    if (seconds >= timestamps.last) return timestamps.length - 1;
    var low = 0;
    var high = timestamps.length;
    while (low < high) {
      final middle = (low + high) >> 1;
      if (timestamps[middle] <= seconds) {
        low = middle + 1;
      } else {
        high = middle;
      }
    }
    return low - 1;
  }

  factory SwingClip.fromJson(Map<String, dynamic> json) {
    if (_integer(json['schema_version'], 'schema_version') != 1) {
      _bad('schema_version', 'only version 1 is supported');
    }
    if (json['coordinate_space'] != 'world') {
      _bad('coordinate_space', 'expected world, not image/pixel coordinates');
    }
    const expectedConvention = 'source_view_hip_centered_xright_yup_zcamera';
    if (json['coordinate_convention'] != expectedConvention) {
      _bad(
        'coordinate_convention',
        'expected $expectedConvention; transform coordinates in the converter',
      );
    }
    final names = _strings(json['joint_names'], 'joint_names');
    if (names.length != 12) _bad('joint_names', 'expected 12 names');
    for (var j = 0; j < 12; j++) {
      if (names[j] != jointNames[j]) {
        _bad('joint_names[$j]', 'expected ${jointNames[j]}');
      }
    }
    final fps = _number(json['fps'], 'fps');
    if (fps <= 0) _bad('fps', 'must be positive');
    final rawTimes = json['timestamps_s'];
    if (rawTimes is! List || rawTimes.isEmpty) {
      _bad('timestamps_s', 'expected a nonempty array');
    }
    final times = <double>[];
    for (var i = 0; i < rawTimes.length; i++) {
      final value = _number(rawTimes[i], 'timestamps_s[$i]');
      if (value < 0 || (i > 0 && value <= times.last)) {
        _bad('timestamps_s[$i]', 'must be nonnegative and strictly increasing');
      }
      times.add(value);
    }
    if (times.first.abs() > 0.000001) {
      _bad('timestamps_s[0]', 'must start at zero relative to the clip');
    }
    if (json.containsKey('frame_count') &&
        _integer(json['frame_count'], 'frame_count') != times.length) {
      _bad('frame_count', 'does not match timestamps_s length');
    }
    final rawFrames = _listOfLength(json['frames'], times.length, 'frames');
    final frames = <PoseFrame>[
      for (var i = 0; i < rawFrames.length; i++)
        PoseFrame.fromJson(
          _map(rawFrames[i], 'frames[$i]'),
          expectedIndex: i,
          expectedTimestamp: times[i],
        ),
    ];
    final mapping = _listOfLength(
      json['render_to_npz_joint_indices'],
      12,
      'render_to_npz_joint_indices',
    ).map((value) => _integer(value, 'render_to_npz_joint_indices')).toList();
    if (mapping.toSet().length != 12 || mapping.any((j) => j < 0 || j >= 12)) {
      _bad('render_to_npz_joint_indices', 'expected a permutation of [0, 11]');
    }
    final hand = _string(json['handedness'], 'handedness');
    if (!<String>{'left', 'right', 'unknown'}.contains(hand)) {
      _bad('handedness', 'expected left, right, or unknown');
    }
    final kind = json['data_kind'] ?? 'sample';
    if (kind != 'sample' && kind != 'analysis') {
      _bad('data_kind', 'expected sample or analysis');
    }
    final analysisId = json['analysis_id'] == null
        ? null
        : _string(json['analysis_id'], 'analysis_id');
    if ((kind == 'analysis') != (analysisId != null)) {
      _bad(
        'analysis_id',
        'analysis data needs an ID; sample must not claim an analysis',
      );
    }
    return SwingClip._(
      id: _string(json['id'], 'id'),
      title: _string(json['title'], 'title'),
      handedness: hand,
      fps: fps,
      timestamps: times,
      frames: frames,
      renderToNpzJointIndices: mapping,
      imageQualityNote: json['image_quality_note'] == null
          ? 'Image visibility/masks are hints, not world accuracy or confidence.'
          : _string(json['image_quality_note'], 'image_quality_note'),
      coordinateConvention: expectedConvention,
      warnings: _strings(json['warnings'] ?? <dynamic>[], 'warnings'),
      directional: json['orientation_data'] == null
          ? null
          : DirectionalMotion.bind(
              _map(json['orientation_data'], 'orientation_data'),
              json,
            ),
      analysisId: analysisId,
      finalMotion: json['final_display_data'] == null
          ? null
          : FinalMotion.bind(
              _map(json['final_display_data'], 'final_display_data'),
              json,
            ),
      dataKind: kind as String,
    );
  }
}

Never _bad(String path, String message) =>
    throw FormatException('$path: $message');

double _number(Object? value, String path) {
  if (value is! num || !value.toDouble().isFinite) {
    _bad(path, 'expected a finite number; use null for a missing joint');
  }
  return value.toDouble();
}

int _integer(Object? value, String path) {
  if (value is! int) _bad(path, 'expected an integer');
  return value;
}

String _string(Object? value, String path) {
  if (value is! String || value.trim().isEmpty) {
    _bad(path, 'expected a nonempty string');
  }
  return value;
}

Map<String, dynamic> _map(Object? value, String path) {
  if (value is! Map<String, dynamic>) _bad(path, 'expected an object');
  return value;
}

List<dynamic> _listOfLength(Object? value, int count, String path) {
  if (value is! List || value.length != count) {
    _bad(path, 'expected an array of length $count');
  }
  return value;
}

List<bool> _bools(Object? value, String path) {
  final values = _listOfLength(value, 12, path);
  return <bool>[
    for (var j = 0; j < values.length; j++)
      if (values[j] is bool)
        values[j] as bool
      else
        _bad('$path[$j]', 'expected a boolean'),
  ];
}

List<String> _strings(Object? value, String path) {
  if (value is! List) _bad(path, 'expected an array of strings');
  return <String>[
    for (var i = 0; i < value.length; i++) _string(value[i], '$path[$i]'),
  ];
}
