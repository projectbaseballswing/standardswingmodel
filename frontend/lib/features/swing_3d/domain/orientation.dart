/// O1 research candidate. Pure Dart: shared by the renderer and all-video CLI.
/// No filename, identity or batting-side branch exists in the orientation math.
library;

import 'dart:math' as math;

const orientationVersion = 'O1-2026-10-26-v1';
const renderConvention = 'source_view_hip_centered_xright_yup_zcamera';
const bodyNames = [
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
const footNames = [
  'left_heel',
  'right_heel',
  'left_foot_index',
  'right_foot_index',
];
const bodySwap = [1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10];
const footSwap = [1, 0, 3, 2];
const bodyEdges = [
  (0, 1),
  (0, 2),
  (2, 4),
  (1, 3),
  (3, 5),
  (0, 6),
  (1, 7),
  (6, 7),
  (6, 8),
  (8, 10),
  (7, 9),
  (9, 11),
];

class OConfig {
  const OConfig();
  final double epsilon = 1e-8, minimumSin = .10;
  final double minimumWidthToHeight = .10, maximumWidthToHeight = 3;
  final double maximumGap = .12, jumpDegrees = 90, rateMinStep = 45;
  final double jumpDegreesPerSecond = 1200, flipDegrees = 150;
  final double maximumTwist = 120, footLengthMin = .65, footLengthMax = 1.35;
  final double footImageVisibilityMin = .5, ankleDistanceMax = 1.5;
  final double ankleLineDistanceMax = 1.0;
  final int recoverySamples = 2, footReferenceSamples = 3;
  Map<String, Object> toJson() => {
    'version': orientationVersion,
    'epsilon': epsilon,
    'minimum_sin': minimumSin,
    'width_height_range': [minimumWidthToHeight, maximumWidthToHeight],
    'max_gap_s': maximumGap,
    'jump_degrees': jumpDegrees,
    'rate_min_step_degrees': rateMinStep,
    'jump_degrees_per_second': jumpDegreesPerSecond,
    'flip_degrees': flipDegrees,
    'max_twist_degrees': maximumTwist,
    'foot_length_ratio': [footLengthMin, footLengthMax],
    'foot_IMAGE_visibility_min': footImageVisibilityMin,
    'ankle_distance_ratio_max': ankleDistanceMax,
    'ankle_line_ratio_max': ankleLineDistanceMax,
    'recovery_samples': recoverySamples,
    'foot_reference_samples': footReferenceSamples,
  };
}

class V3 {
  const V3(this.x, this.y, this.z);
  final double x, y, z;
  V3 operator +(V3 b) => V3(x + b.x, y + b.y, z + b.z);
  V3 operator -(V3 b) => V3(x - b.x, y - b.y, z - b.z);
  V3 operator *(double s) => V3(x * s, y * s, z * s);
  double dot(V3 b) => x * b.x + y * b.y + z * b.z;
  V3 cross(V3 b) => V3(y * b.z - z * b.y, z * b.x - x * b.z, x * b.y - y * b.x);
  double get length => math.sqrt(dot(this));
  V3? unit([double epsilon = 1e-8]) =>
      length > epsilon ? this * (1 / length) : null;
  List<double> toJson() => [x, y, z];
}

double radiansToDegrees(double x) => x * 180 / math.pi;
double angle(V3 a, V3 b) =>
    radiansToDegrees(math.acos((a.dot(b) / a.length / b.length).clamp(-1, 1)));
double wrapDegrees(double x) => (x + 180) % 360 - 180;
double median(List<double> values) {
  final a = [...values]..sort();
  return a.length.isOdd
      ? a[a.length ~/ 2]
      : (a[a.length ~/ 2 - 1] + a[a.length ~/ 2]) / 2;
}

class Q4 {
  const Q4(this.x, this.y, this.z, this.w);
  final double x, y, z, w;
  double dot(Q4 b) => x * b.x + y * b.y + z * b.z + w * b.w;
  Q4 get negative => Q4(-x, -y, -z, -w);
  List<double> toJson() => [x, y, z, w];
  double distance(Q4 b) =>
      radiansToDegrees(2 * math.acos(dot(b).abs().clamp(0, 1)));
  factory Q4.basis(V3 a, V3 b, V3 c) {
    final m00 = a.x,
        m01 = b.x,
        m02 = c.x,
        m10 = a.y,
        m11 = b.y,
        m12 = c.y,
        m20 = a.z,
        m21 = b.z,
        m22 = c.z;
    final trace = m00 + m11 + m22;
    double x, y, z, w, s;
    if (trace > 0) {
      s = math.sqrt(trace + 1) * 2;
      w = .25 * s;
      x = (m21 - m12) / s;
      y = (m02 - m20) / s;
      z = (m10 - m01) / s;
    } else if (m00 > m11 && m00 > m22) {
      s = math.sqrt(1 + m00 - m11 - m22) * 2;
      w = (m21 - m12) / s;
      x = .25 * s;
      y = (m01 + m10) / s;
      z = (m02 + m20) / s;
    } else if (m11 > m22) {
      s = math.sqrt(1 + m11 - m00 - m22) * 2;
      w = (m02 - m20) / s;
      x = (m01 + m10) / s;
      y = .25 * s;
      z = (m12 + m21) / s;
    } else {
      s = math.sqrt(1 + m22 - m00 - m11) * 2;
      w = (m10 - m01) / s;
      x = (m02 + m20) / s;
      y = (m12 + m21) / s;
      z = .25 * s;
    }
    final n = math.sqrt(x * x + y * y + z * z + w * w);
    return Q4(x / n, y / n, z / n, w / n);
  }
}

class Axes {
  Axes(this.x, this.up, this.forward) : quaternion = Q4.basis(x, up, forward);
  final V3 x, up, forward;
  Q4 quaternion;
  double get determinant => x.dot(up.cross(forward));
  double? get yaw =>
      math.sqrt(forward.x * forward.x + forward.z * forward.z) > 1e-8
      ? radiansToDegrees(math.atan2(forward.x, forward.z))
      : null;
  Map<String, dynamic> toJson() => {
    'x': x.toJson(),
    'up': up.toJson(),
    'forward': forward.toJson(),
    'quaternion_xyzw': quaternion.toJson(),
    'determinant': determinant,
    'yaw_degrees': yaw,
  };
}

class OFrame {
  OFrame(
    this.timestamp,
    this.positions,
    this.feet,
    this.footVisibility,
    this.extra,
  );
  final double timestamp;
  final List<V3?> positions, feet;
  final List<double?> footVisibility;
  final Map<String, dynamic> extra;
}

/// Both conventions are explicit. Handedness never determines a facing angle.
class OrientationClip {
  OrientationClip(this.frames, this.fps, this.metadata);
  final List<OFrame> frames;
  final double fps;
  final Map<String, dynamic> metadata;
  double get duration => frames.last.timestamp + 1 / fps;
  int frameAt(double seconds) {
    var low = 0, high = frames.length;
    while (low < high) {
      final m = (low + high) ~/ 2;
      if (frames[m].timestamp <= seconds) {
        low = m + 1;
      } else {
        high = m;
      }
    }
    return math.max(0, low - 1);
  }

  factory OrientationClip.fromJson(Map<String, dynamic> data) {
    if (data['schema_version'] != 1) {
      throw const FormatException('orientation schema_version must be 1');
    }
    final convention = data['coordinate_convention'];
    final transformed = convention == renderConvention;
    if (!transformed && convention != 'mediapipe_inference_world') {
      throw const FormatException('Unknown coordinate convention');
    }
    if (data['source_oriented'] != transformed ||
        data['mirrored_input'] is! bool) {
      throw const FormatException('Ambiguous/double coordinate restoration');
    }
    if (!['left', 'right', 'unknown'].contains(data['handedness'])) {
      throw const FormatException('Explicit handedness metadata required');
    }
    if (!_namesEqual(data['joint_names'], bodyNames)) {
      throw const FormatException('Body joint order differs');
    }
    if (data['foot_joint_names'] != null &&
        !_namesEqual(data['foot_joint_names'], footNames)) {
      throw const FormatException('Foot joint order differs');
    }
    final raw = data['frames'];
    if (raw is! List || raw.isEmpty) throw const FormatException('No frames');
    if (data['frame_count'] != null && data['frame_count'] != raw.length) {
      throw const FormatException('Frame count mismatch');
    }
    final fps = _number(data['fps'], 'fps');
    if (fps <= 0) throw const FormatException('FPS must be positive');
    final frames = <OFrame>[];
    var previous = -1.0;
    for (var i = 0; i < raw.length; i++) {
      if (raw[i] is! Map<String, dynamic>) {
        throw const FormatException('Invalid frame');
      }
      final row = raw[i] as Map<String, dynamic>;
      if (row['feet'] != null && data['foot_joint_names'] == null) {
        throw const FormatException('Explicit heel/toe joint order required');
      }
      final p2 = row['p2'];
      if (p2 != null) {
        if (p2 is! Map || p2['torso_visible'] is! bool) {
          throw const FormatException('Invalid P2 display mask');
        }
        for (final name in ['edge_visible', 'joint_warnings']) {
          final mask = p2[name];
          if (mask is! List ||
              mask.length != 12 ||
              mask.any((v) => v is! bool)) {
            throw FormatException('Invalid P2 $name mask');
          }
        }
      }
      final legacy = row['legacy_feet'];
      if (legacy != null) {
        if (legacy is! List || legacy.length != 2) {
          throw const FormatException('Expected two optional F1 records');
        }
        for (final foot in legacy) {
          if (foot is! Map ||
              ![
                'directional',
                'simplified',
                'missing',
              ].contains(foot['mode'])) {
            throw const FormatException('Invalid F1 mode');
          }
          final direction = _points([foot['direction']], 1).single;
          if (foot['mode'] == 'directional' &&
              (direction == null || direction.length <= 1e-8)) {
            throw const FormatException(
              'Directional F1 record has no direction',
            );
          }
        }
      }
      final t = _number(row['timestamp_s'], 'timestamp_s');
      if (t < 0 || t <= previous || (i == 0 && t.abs() > 1e-8)) {
        throw const FormatException('Timestamps must increase from zero');
      }
      if (row['index'] != null && row['index'] != i) {
        throw const FormatException('Frame index mismatch');
      }
      previous = t;
      var p = _points(row['positions'], 12);
      var feet = row['feet'] == null
          ? List<V3?>.filled(4, null)
          : _points(row['feet'], 4);
      var vis = _visibility(row['foot_visibility']);
      if (!transformed) {
        if (row.containsKey('p2') || row.containsKey('legacy_feet')) {
          throw const FormatException(
            'Policy masks must be supplied after source restoration',
          );
        }
        final mirror = data['mirrored_input'] as bool;
        if (mirror) {
          p = [for (final j in bodySwap) p[j]];
          feet = [for (final j in footSwap) feet[j]];
          vis = [for (final j in footSwap) vis[j]];
        }
        final root = p[6] != null && p[7] != null ? (p[6]! + p[7]!) * .5 : null;
        V3? restore(V3? v) {
          if (v == null || root == null) return null;
          final d = v - root;
          return V3(mirror ? -d.x : d.x, -d.y, -d.z);
        }

        p = p.map(restore).toList();
        feet = feet.map(restore).toList();
      }
      frames.add(OFrame(t, p, feet, vis, row));
    }
    return OrientationClip(frames, fps, data);
  }
}

bool _namesEqual(dynamic raw, List<String> names) =>
    raw is List &&
    raw.length == names.length &&
    List.generate(names.length, (i) => raw[i] == names[i]).every((v) => v);
double _number(dynamic value, String label) {
  if (value is! num || !value.isFinite) {
    throw FormatException('Nonfinite/invalid $label');
  }
  return value.toDouble();
}

List<V3?> _points(dynamic raw, int length) {
  if (raw is! List || raw.length != length) {
    throw FormatException('Expected $length XYZ/null joints');
  }
  return raw.map<V3?>((v) {
    if (v == null) return null;
    if (v is! List || v.length != 3) {
      throw const FormatException('Expected XYZ');
    }
    final xyz = V3(_number(v[0], 'x'), _number(v[1], 'y'), _number(v[2], 'z'));
    if ([xyz.x, xyz.y, xyz.z].any((value) => value.abs() > 1e6)) {
      throw const FormatException(
        'World coordinate exceeds numeric safety bound',
      );
    }
    return xyz;
  }).toList();
}

List<double?> _visibility(dynamic raw) {
  if (raw == null) return List<double?>.filled(4, null);
  if (raw is! List || raw.length != 4) {
    throw const FormatException('Expected four foot IMAGE visibility values');
  }
  final values = raw
      .map<double?>(
        (v) => v == null ? null : _number(v, 'foot IMAGE visibility'),
      )
      .toList();
  if (values.any((v) => v != null && (v < 0 || v > 1))) {
    throw const FormatException('IMAGE visibility must be in [0,1]');
  }
  return values;
}

Axes? _bodyBasis(V3 across, V3 up, List<String> reasons, OConfig config) {
  if (up.length <= config.epsilon) {
    reasons.add('degenerate_torso_height');
    return null;
  }
  if (across.length <= config.epsilon) {
    reasons.add('degenerate_bilateral_width');
    return null;
  }
  final u = up.unit()!;
  final projected = across - u * across.dot(u);
  if (projected.length / across.length < config.minimumSin) {
    reasons.add('near_collinear_axes');
    return null;
  }
  final ratio = across.length / up.length;
  if (ratio < config.minimumWidthToHeight ||
      ratio > config.maximumWidthToHeight) {
    reasons.add('width_height_outside_display_range');
  }
  final x = projected.unit()!;
  final f = x.cross(u).unit()!;
  return Axes(x, f.cross(x).unit()!, f);
}

class _Continuity {
  Axes? previous;
  double? previousTime, unwrappedYaw;
  bool recovering = false;
  int good = 0;
  Map<String, dynamic> inspect(
    Axes? axes,
    double time,
    double gap,
    List<String> reasons,
    OConfig config,
  ) {
    double? delta, forwardDelta, rate;
    final dt = previousTime == null ? null : time - previousTime!;
    final adjacent =
        previous != null && axes != null && dt != null && dt <= gap;
    final flags = <String>[];
    if (adjacent) {
      if (previous!.quaternion.dot(axes.quaternion) < 0) {
        axes.quaternion = axes.quaternion.negative;
      }
      delta = previous!.quaternion.distance(axes.quaternion);
      forwardDelta = angle(previous!.forward, axes.forward);
      rate = delta / dt;
      if (delta > config.jumpDegrees ||
          (delta > config.rateMinStep && rate > config.jumpDegreesPerSecond)) {
        flags.add('abrupt_rotation');
      }
      if (forwardDelta >= config.flipDegrees) {
        flags.add('near_180_forward_flip');
      }
      if (axes.yaw != null && previous!.yaw != null && unwrappedYaw != null) {
        unwrappedYaw = unwrappedYaw! + wrapDegrees(axes.yaw! - previous!.yaw!);
      } else {
        unwrappedYaw = axes.yaw;
      }
    } else {
      if (previousTime != null && dt! > gap) {
        flags.add('time_gap_reset');
        recovering = true;
        good = 0;
      }
      unwrappedYaw = axes?.yaw;
    }
    reasons.addAll(flags);
    final unsafe = axes == null || reasons.any((r) => r != 'time_gap_reset');
    if (unsafe) {
      recovering = true;
      good = 0;
    } else if (recovering) {
      good++;
      if (good >= config.recoverySamples) {
        recovering = false;
      } else {
        reasons.add('continuity_reacquisition');
      }
    }
    final directional = !unsafe && !recovering;
    previous = axes;
    previousTime = time;
    return {
      'adjacent_supported': adjacent,
      'delta_degrees': delta,
      'forward_delta_degrees': forwardDelta,
      'degrees_per_timestamp_second': rate,
      'near_180_flip': flags.contains('near_180_forward_flip'),
      'abrupt': flags.contains('abrupt_rotation'),
      'forward_opposes_previous': forwardDelta != null && forwardDelta > 90,
      'unwrapped_yaw_degrees': unwrappedYaw,
      'directional': directional,
    };
  }
}

class OrientationEngine {
  const OrientationEngine({this.config = const OConfig()});
  final OConfig config;
  Map<String, dynamic> analyze(OrientationClip clip) {
    final gap = math.max(config.maximumGap, 3 / clip.fps);
    final sizes = <double>[];
    for (final f in clip.frames) {
      final p = f.positions;
      if ([0, 1, 6, 7].every((j) => p[j] != null)) {
        final h = ((p[0]! + p[1]!) * .5 - (p[6]! + p[7]!) * .5).length;
        if (h > config.epsilon) sizes.add(h);
      }
    }
    final referenceLengths = <double?>[];
    for (var side = 0; side < 2; side++) {
      final lengths = <double>[];
      for (final f in clip.frames) {
        if (f.feet[side] != null && f.feet[side + 2] != null) {
          final d = (f.feet[side + 2]! - f.feet[side]!).length;
          if (d > config.epsilon) lengths.add(d);
        }
      }
      referenceLengths.add(
        lengths.length >= config.footReferenceSamples ? median(lengths) : null,
      );
    }
    final shoulderTrack = _Continuity(), pelvisTrack = _Continuity();
    final footTracks = [_Continuity(), _Continuity()];
    final output = <Map<String, dynamic>>[];
    for (var index = 0; index < clip.frames.length; index++) {
      final row = clip.frames[index], p = row.positions;
      final sr = <String>[], pr = <String>[];
      Axes? shoulder, pelvis;
      V3? up;
      double? twist;
      if (![0, 1, 6, 7].every((j) => p[j] != null)) {
        sr.add('missing_torso_joint');
        pr.add('missing_torso_joint');
      } else {
        up = (p[0]! + p[1]!) * .5 - (p[6]! + p[7]!) * .5;
        shoulder = _bodyBasis(p[0]! - p[1]!, up, sr, config);
        pelvis = _bodyBasis(p[6]! - p[7]!, up, pr, config);
        if (shoulder != null && pelvis != null) {
          twist = radiansToDegrees(
            math.atan2(
              shoulder.up.dot(pelvis.forward.cross(shoulder.forward)),
              pelvis.forward.dot(shoulder.forward),
            ),
          );
          if (twist.abs() > config.maximumTwist) {
            sr.add('shoulder_pelvis_direction_conflict');
            pr.add('shoulder_pelvis_direction_conflict');
          }
        }
      }
      final st = shoulderTrack.inspect(
        shoulder,
        row.timestamp,
        gap,
        sr,
        config,
      );
      final pt = pelvisTrack.inspect(pelvis, row.timestamp, gap, pr, config);
      final feet = <Map<String, dynamic>>[];
      for (var side = 0; side < 2; side++) {
        final reasons = <String>[];
        final ankle = p[10 + side],
            heel = row.feet[side],
            toe = row.feet[side + 2];
        V3? direction;
        Axes? basis;
        double? length, nearRatio, lineRatio, visibility;
        if (ankle == null) reasons.add('missing_ankle');
        if (heel == null || toe == null) {
          reasons.add('missing_heel_toe');
        } else {
          final v = toe - heel;
          length = v.length;
          direction = v.unit(config.epsilon);
          if (direction == null) {
            reasons.add('degenerate_heel_toe');
          } else {
            const vertical = V3(0, 1, 0);
            final x = vertical.cross(direction);
            if (x.length < config.minimumSin) {
              reasons.add('foot_up_axis_degenerate');
            } else {
              basis = Axes(
                x.unit()!,
                direction.cross(x.unit()!).unit()!,
                direction,
              );
            }
            if (ankle != null) {
              nearRatio =
                  math.min((ankle - heel).length, (ankle - toe).length) /
                  length;
              lineRatio = (ankle - heel).cross(direction).length / length;
              if (nearRatio > config.ankleDistanceMax ||
                  lineRatio > config.ankleLineDistanceMax) {
                reasons.add('ankle_heel_toe_inconsistent');
              }
            }
          }
        }
        final a = row.footVisibility[side], b = row.footVisibility[side + 2];
        if (a != null && b != null) visibility = math.min(a, b);
        if (visibility == null || visibility < config.footImageVisibilityMin) {
          reasons.add('low_or_missing_IMAGE_visibility_proxy');
        }
        final reference = referenceLengths[side];
        if (reference == null) {
          reasons.add('no_foot_length_reference');
        } else if (length != null &&
            (length / reference < config.footLengthMin ||
                length / reference > config.footLengthMax)) {
          reasons.add('foot_length_deviation');
        }
        final continuity = footTracks[side].inspect(
          basis,
          row.timestamp,
          gap,
          reasons,
          config,
        );
        feet.add({
          'side': side == 0 ? 'left' : 'right',
          'direction': direction?.toJson(),
          'axes': basis?.toJson(),
          'mode': ankle == null
              ? 'missing'
              : continuity['directional'] == true
              ? 'directional'
              : 'neutral',
          'reasons': reasons,
          'world_length': length,
          'reference_length': reference,
          'ankle_near_ratio': nearRatio,
          'ankle_line_ratio': lineRatio,
          'IMAGE_visibility_min': visibility,
          'continuity': continuity,
        });
      }
      output.add({
        'index': index,
        'timestamp_s': row.timestamp,
        'shoulder': shoulder?.toJson(),
        'pelvis': pelvis?.toJson(),
        'torso_up': up?.unit()?.toJson(),
        'twist_degrees': twist,
        'shoulder_reasons': sr,
        'pelvis_reasons': pr,
        'shoulder_continuity': st,
        'pelvis_continuity': pt,
        'body_mode': st['directional'] == true && pt['directional'] == true
            ? 'directional'
            : 'neutral',
        'head_mode': st['directional'] == true ? 'torso_proxy' : 'neutral',
        'feet': feet,
      });
    }
    return {
      'algorithm': orientationVersion,
      'config': config.toJson(),
      'frame_count': output.length,
      'body_scale': sizes.isEmpty ? 1.0 : median(sizes) / .5,
      'effective_gap_s': gap,
      'foot_length_references': referenceLengths,
      'frames': output,
      'accuracy': 'not_measured',
      'head_direction': 'torso_proxy_only',
      'joint_coordinates_modified': false,
    };
  }
}
