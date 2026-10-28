/// H4 v2 display policy, ported from the frozen EXP-006 Python implementation.
/// This is an illustrative head orientation, never measured face tracking.
/// Run once for a complete S2/O1 clip; seeking and the live camera are not inputs.
library;

import 'dart:convert';
import 'dart:math' as math;

const headPolicyVersion = 'H4-conservative-batter-v2';
const headPolicyReferenceConfigSha256 =
    '91a233ce4885c96336218eb384efc46fe5b51a55eddad36c7765ed7e2b791541';
const headPolicyConfig = <String, dynamic>{
  'version': headPolicyVersion,
  'purpose':
      'Illustrative batter-like side-profile display, NOT actual head tracking',
  'coordinate_convention': 'source_view_hip_centered_xright_yup_zcamera',
  'baseline_window_s': .2,
  'baseline_max_frames': 10,
  'baseline_min_valid_frames': 3,
  'baseline_trim_deg': 20.0,
  'baseline_min_resultant': .94,
  'baseline_shoulder_pelvis_max_deg': 45.0,
  'torso_gain': .4,
  'sensitivity_torso_gains': [.3, .4, .5],
  'torso_jump_deg': 45.0,
  'torso_rate_min_step_deg': 15.0,
  'torso_rate_limit_deg_s': 600.0,
  'torso_hold_s': .15,
  'torso_fallback_scope':
      'After torso-support expiry with valid baseline and body, preserve previous display yaw or baseline as an artistic prior; disable face auxiliary; retain all side/clamp/rate/span constraints',
  'early_clamp_deg': 25.0,
  'late_clamp_deg': 45.0,
  'clamp_ramp_start_fraction': .2,
  'clamp_ramp_end_fraction': .8,
  'max_clip_yaw_span_deg': 45.0,
  'side_profile_min_deg': 70.0,
  'side_profile_max_deg': 115.0,
  'reference_camera': {
    'yaw_rad': .25,
    'pitch_rad': .1,
    'zoom': 1.0,
    'distance_scale': 3.6,
    'target_y_scale': -.1,
  },
  'head_center_shoulder_up_scale': .235,
  'smoothing_tau_s': .15,
  'max_yaw_rate_deg_s': 90.0,
  'max_continuity_gap_s': .2,
  'face_weight': .08,
  'face_max_contribution_deg': 5.0,
  'face_stable_samples': 3,
  'face_max_step_deg': 12.0,
  'face_max_rate_deg_s': 180.0,
  'face_max_gap_s': .12,
  'face_baseline_alignment_max_deg': 35.0,
  'pitch_roll_policy':
      'zero: neutral display assumption, not measured gravity or skull tilt',
  'missing_policy':
      'Featureless neutral if baseline/metadata/body or constraint intersection unavailable',
  'baseline_is_offline': true,
  'live_camera_affects_head': false,
  'new_joint_estimation': false,
  'accuracy_claim': false,
};

typedef _Map = Map<String, dynamic>;
typedef _Interval = (double, double);
const _tau = 2 * math.pi;
double _wrap(double a) => (a + math.pi) % _tau - math.pi;
double _deg(double a) => a * 180 / math.pi;
double _rad(num a) => a * math.pi / 180;
double _dot(List<double> a, List<double> b) =>
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
List<double> _minus(List<double> a, List<double> b) =>
    List.generate(3, (i) => a[i] - b[i]);
List<double>? _vector(dynamic value) {
  if (value is! List ||
      value.length != 3 ||
      value.any((v) => v is! num || !v.isFinite)) {
    return null;
  }
  return value.map((v) => (v as num).toDouble()).toList();
}

List<double>? _unit(dynamic value) {
  final a = _vector(value);
  if (a == null) return null;
  final n = math.sqrt(_dot(a, a));
  return n > 1e-10 ? a.map((v) => v / n).toList() : null;
}

/// Orthogonal right-handed basis; local +Z is the facial forward direction.
bool validHeadAxes(dynamic axes) => _validAxes(axes);

bool _validAxes(dynamic axes) {
  if (axes is! Map) return false;
  final vs = ['x', 'up', 'forward'].map((k) => _vector(axes[k])).toList();
  if (vs.any((v) => v == null)) return false;
  final x = vs[0]!, u = vs[1]!, f = vs[2]!;
  for (var i = 0; i < 3; i++) {
    for (var j = 0; j < 3; j++) {
      if ((_dot(vs[i]!, vs[j]!) - (i == j ? 1 : 0)).abs() >= 1e-5) return false;
    }
  }
  final det =
      x[0] * (u[1] * f[2] - u[2] * f[1]) -
      u[0] * (x[1] * f[2] - x[2] * f[1]) +
      f[0] * (x[1] * u[2] - x[2] * u[1]);
  return (det - 1).abs() < 1e-5;
}

double? _yaw(dynamic value) {
  final v = _unit(value);
  return v != null && math.sqrt(v[0] * v[0] + v[2] * v[2]) > 1e-8
      ? math.atan2(v[0], v[2])
      : null;
}

double? _angle(dynamic a, dynamic b) {
  final ua = _unit(a), ub = _unit(b);
  return ua == null || ub == null
      ? null
      : _deg(math.acos(_dot(ua, ub).clamp(-1.0, 1.0)));
}

Map<String, dynamic> headAxesFromYaw(double value) {
  final s = math.sin(value), c = math.cos(value);
  return {
    'x': [c, 0.0, -s],
    'up': [0.0, 1.0, 0.0],
    'forward': [s, 0.0, c],
    'quaternion_xyzw': [0.0, math.sin(value / 2), 0.0, math.cos(value / 2)],
    'yaw_degrees': _deg(_wrap(value)),
    'determinant': 1.0,
  };
}

/// No player identity, frame-specific exception or live-camera input exists.
class HeadPolicy {
  const HeadPolicy();

  Map<String, dynamic> analyze(
    Map<String, dynamic> clip,
    Map<String, dynamic> orientations, {
    required String? handedness,
    required double referenceScale,
  }) {
    final cfg = jsonDecode(jsonEncode(headPolicyConfig)) as _Map;
    double n(String key) => (cfg[key] as num).toDouble();
    final scale = referenceScale;
    if (!scale.isFinite || scale <= 0) {
      throw const FormatException('Positive H4 reference scale required');
    }
    final fs = clip['frames'], os = orientations['frames'];
    if (fs is! List || fs.isEmpty || os is! List || fs.length != os.length) {
      throw const FormatException('Equal nonempty H4 body/O1 arrays required');
    }
    if (clip['coordinate_convention'] != cfg['coordinate_convention'] ||
        clip['source_oriented'] != true) {
      throw const FormatException(
        'H4 requires source-restored canonical coordinates',
      );
    }
    final ts = <double>[];
    for (var i = 0; i < fs.length; i++) {
      final t = fs[i]['timestamp_s'];
      if (t is! num ||
          !t.isFinite ||
          t != os[i]['timestamp_s'] ||
          (i > 0 && t <= ts.last)) {
        throw const FormatException(
          'H4 requires aligned increasing timestamps',
        );
      }
      ts.add(t.toDouble());
    }
    final dts = [for (var i = 1; i < ts.length; i++) ts[i] - ts[i - 1]]..sort();
    final dtTail = dts.isEmpty
        ? 0.0
        : dts.length.isOdd
        ? dts[dts.length ~/ 2]
        : (dts[dts.length ~/ 2 - 1] + dts[dts.length ~/ 2]) / 2;
    var duration =
        ((clip['presentation_end_s'] ?? ts.last + dtTail) as num).toDouble() -
        ts.first;
    if (!duration.isFinite || duration <= 0) duration = math.max(dtTail, 1e-6);
    final cam = cfg['reference_camera'] as _Map;
    final distance =
        (cam['distance_scale'] as num) * scale * (cam['zoom'] as num);
    final cyaw = (cam['yaw_rad'] as num).toDouble(),
        cpitch = (cam['pitch_rad'] as num).toDouble();
    final camera = <double>[
      math.sin(cyaw) * math.cos(cpitch) * distance,
      (cam['target_y_scale'] as num) * scale + math.sin(cpitch) * distance,
      math.cos(cyaw) * math.cos(cpitch) * distance,
    ];
    final centers = <List<double>?>[], bodyReasons = <String?>[];
    for (var i = 0; i < fs.length; i++) {
      final points = fs[i]['positions'];
      List<double>? center;
      String? reason;
      if (points is! List || points.length != 12) {
        reason = 'invalid_body_length';
      } else if ([0, 1, 6, 7].any((j) => _vector(points[j]) == null)) {
        reason = 'missing_shoulder_or_pelvis';
      } else if (!_validAxes(os[i]['shoulder']) ||
          !_validAxes(os[i]['pelvis'])) {
        reason = 'unavailable_body_axes';
      } else if (fs[i]['p2'] is Map &&
          (fs[i]['p2'] as Map).isNotEmpty &&
          fs[i]['p2']['torso_visible'] != true) {
        reason = 'P2_torso_not_displayable';
      } else {
        final a = _vector(points[0])!, b = _vector(points[1])!;
        final up = _vector(os[i]['shoulder']['up'])!;
        center = List.generate(
          3,
          (k) =>
              (a[k] + b[k]) * .5 +
              up[k] * n('head_center_shoulder_up_scale') * scale,
        );
      }
      centers.add(center);
      bodyReasons.add(reason);
    }
    final candidates = <int>[], lead = <double>[], torso = <double>[];
    final rays = <List<double>>[];
    final validHand = handedness == 'left' || handedness == 'right';
    for (var i = 0; i < fs.length; i++) {
      if (i >= cfg['baseline_max_frames'] ||
          ts[i] - ts.first > n('baseline_window_s') + 1e-9) {
        break;
      }
      if (!validHand || centers[i] == null) continue;
      final o = os[i],
          sc = o['shoulder_continuity'] ?? {},
          pc = o['pelvis_continuity'] ?? {};
      if (sc['abrupt'] == true ||
          pc['abrupt'] == true ||
          sc['directional'] == false ||
          pc['directional'] == false) {
        continue;
      }
      final sx = _unit(o['shoulder']['x'])!, px = _unit(o['pelvis']['x'])!;
      if (_angle(sx, px)! > n('baseline_shoulder_pelvis_max_deg')) continue;
      final v = handedness == 'right' ? sx : sx.map((v) => -v).toList();
      final ly = _yaw(v), ty = _yaw(o['shoulder']['forward']);
      final ray = _unit(_minus(camera, centers[i]!));
      if (ly == null || ty == null || ray == null) continue;
      candidates.add(i);
      lead.add(ly);
      torso.add(ty);
      rays.add(ray);
    }
    final (leadBase, keep, resultant) = _circular(lead, cfg);
    double? baseline, torsoBase;
    int? branch;
    var projection = 0.0;
    if (leadBase != null) {
      torsoBase = _circular([for (final i in keep) torso[i]], cfg).$1;
      final ray = _unit(
        List.generate(
          3,
          (k) => keep.fold<double>(0, (s, i) => s + rays[i][k]) / keep.length,
        ),
      );
      if (ray != null && torsoBase != null) {
        final relation = _wrap(leadBase - (_yaw(ray) ?? cyaw));
        branch = math.sin(relation).abs() < 1e-8
            ? (handedness == 'right' ? 1 : -1)
            : (relation > 0 ? 1 : -1);
        baseline = _project(leadBase, _intervals(ray, branch, cfg, leadBase));
        projection = baseline != null ? _deg(baseline - leadBase) : 0.0;
      }
    }
    final baseReason = !validHand
        ? 'unknown_batting_side'
        : baseline == null
        ? 'insufficient_stable_initial_body'
        : null;
    final retained = baseline == null
        ? <int>[]
        : [for (final i in keep) candidates[i]];
    final output = <_Map>[];
    double? previous, previousTime, minSeen, maxSeen;
    var previousVisible = false;
    var torsoUnwrapped = torsoBase;
    double? torsoLast, torsoLastTime;
    var faceHistory = <(double, double)>[];
    for (var i = 0; i < fs.length; i++) {
      final f = fs[i], o = os[i], t = ts[i], center = centers[i];
      final reasons = <String>[], neutral = <String>[];
      final progress = ((t - ts.first) / duration).clamp(0.0, 1.0);
      final u =
          ((progress - n('clamp_ramp_start_fraction')) /
                  (n('clamp_ramp_end_fraction') -
                      n('clamp_ramp_start_fraction')))
              .clamp(0.0, 1.0);
      final limit =
          n('early_clamp_deg') +
          u * (n('late_clamp_deg') - n('early_clamp_deg'));
      final diag = <String, dynamic>{
        'progress_fraction': progress,
        'clamp_limit_deg': limit,
        'baseline_yaw_deg': baseline == null ? null : _deg(baseline),
        'torso_yaw_deg': null,
        'torso_delta_deg': null,
        'face_yaw_deg': null,
        'face_used': false,
        'face_contribution_deg': 0.0,
        'camera_angle_deg': null,
        'head_yaw_deg': null,
        'yaw_from_baseline_deg': null,
        'step_deg': null,
        'rate_deg_s': null,
        'head_center': center,
        'fixed_reference_camera_position': camera,
        'constraint_projection_deg': null,
        'smooth_target_deg': null,
        'desired_yaw_deg': null,
      };
      if (baseline == null) neutral.add(baseReason!);
      if (center == null) neutral.add(bodyReasons[i]!);
      final ray = center == null ? null : _unit(_minus(camera, center));
      if (center != null && ray == null) {
        neutral.add('head_at_reference_camera');
      }
      final ty = _validAxes(o['shoulder'])
          ? _yaw(o['shoulder']['forward'])
          : null;
      final tc = o['shoulder_continuity'] ?? {};
      var torsoValid =
          ty != null && tc['abrupt'] != true && tc['directional'] != false;
      if (torsoValid &&
          torsoLastTime != null &&
          t - torsoLastTime <= n('max_continuity_gap_s')) {
        final change = _wrap(ty - torsoLast!);
        final rate = _deg(change).abs() / (t - torsoLastTime);
        if (_deg(change).abs() > n('torso_jump_deg') ||
            (_deg(change).abs() > n('torso_rate_min_step_deg') &&
                rate > n('torso_rate_limit_deg_s'))) {
          torsoValid = false;
          reasons.add('abrupt_torso_input_ignored');
        }
      }
      if (torsoValid && torsoBase != null) {
        torsoUnwrapped =
            torsoLast == null || t - torsoLastTime! > n('max_continuity_gap_s')
            ? torsoBase + _wrap(ty! - torsoBase)
            : torsoUnwrapped! + _wrap(ty! - torsoLast);
        torsoLast = ty;
        torsoLastTime = t;
      }
      final torsoSupported =
          torsoLastTime != null && t - torsoLastTime <= n('torso_hold_s');
      final displayHold =
          baseline != null && !torsoSupported && center != null && ray != null;
      if (displayHold) {
        reasons.add('conservative_torso_uncertain_display_hold');
      } else if (!torsoValid && torsoSupported) {
        reasons.add('short_torso_direction_hold');
      }
      final delta = torsoSupported && torsoBase != null
          ? torsoUnwrapped! - torsoBase
          : 0.0;
      diag.addAll({
        'torso_yaw_deg': ty == null ? null : _deg(ty),
        'torso_delta_deg': _deg(delta),
        'torso_valid_current': torsoValid,
        'torso_supported': torsoSupported,
        'conservative_torso_display_hold': displayHold,
        'torso_support_age_s': torsoLastTime == null ? null : t - torsoLastTime,
      });
      final supplied = f['head_candidates'];
      final head = supplied is Map ? supplied['H2'] : null;
      final fy = head is Map && _validAxes(head['axes'])
          ? _yaw(head['axes']['forward'])
          : null;
      var faceValid =
          fy != null &&
          head['mode'] == 'face_landmarks' &&
          head['display_features'] != false;
      if (faceValid && !torsoValid) {
        reasons.add('face_auxiliary_disabled_torso_uncertain');
        faceValid = false;
      }
      if (faceValid) {
        diag['face_yaw_deg'] = _deg(fy!);
        if (faceHistory.isNotEmpty) {
          final (ft, fa) = faceHistory.last;
          final fd = t - ft, step = _deg(_wrap(fy - fa)).abs();
          if (fd > n('face_max_gap_s') ||
              step > n('face_max_step_deg') ||
              step / fd > n('face_max_rate_deg_s')) {
            faceHistory = [];
          }
        }
        faceHistory.add((t, fy));
        if (faceHistory.length > cfg['face_stable_samples']) {
          faceHistory.removeAt(0);
        }
      } else {
        faceHistory = [];
      }
      double? desired = baseline == null
          ? null
          : baseline + n('torso_gain') * delta;
      if (displayHold) desired = previous ?? baseline;
      if (faceValid && baseline != null) {
        if (faceHistory.length < cfg['face_stable_samples']) {
          reasons.add('face_temporal_support_insufficient');
        } else if (_deg(_wrap(fy! - baseline)).abs() >
            n('face_baseline_alignment_max_deg')) {
          reasons.add('face_inconsistent_with_side_baseline');
        } else if (ray == null ||
            _angle(headAxesFromYaw(fy)['forward'], ray)! <
                n('side_profile_min_deg')) {
          reasons.add('face_points_toward_reference_camera');
        } else {
          final correction = (n('face_weight') * _wrap(fy - desired!)).clamp(
            -_rad(n('face_max_contribution_deg')),
            _rad(n('face_max_contribution_deg')),
          );
          desired += correction;
          diag['face_used'] = true;
          diag['face_contribution_deg'] = _deg(correction);
        }
      } else if (!faceValid) {
        reasons.add('no_reliable_face_auxiliary');
      }
      double? chosen, smooth;
      if (neutral.isEmpty) {
        var allowed = _intervals(ray!, branch!, cfg, baseline!);
        allowed = _intersect(
          allowed,
          baseline - _rad(limit),
          baseline + _rad(limit),
        );
        if (minSeen != null) {
          final span = _rad(n('max_clip_yaw_span_deg'));
          allowed = _intersect(allowed, maxSeen! - span, minSeen + span);
        }
        if (previousVisible &&
            previous != null &&
            t - previousTime! <= n('max_continuity_gap_s')) {
          final dt = t - previousTime;
          final alpha = 1 - math.exp(-dt / n('smoothing_tau_s'));
          smooth = previous + alpha * _wrap(desired! - previous);
          final maxstep = _rad(n('max_yaw_rate_deg_s')) * dt;
          allowed = _intersect(allowed, previous - maxstep, previous + maxstep);
        } else {
          smooth = previous ?? baseline;
          if (previous != null) reasons.add('reacquired_after_neutral_or_gap');
        }
        chosen = _project(smooth, allowed);
        diag.addAll({
          'desired_yaw_deg': _deg(desired!),
          'smooth_target_deg': _deg(smooth),
        });
        if (chosen == null) neutral.add('side_clamp_rate_intersection_empty');
      }
      late final _Map pose;
      if (neutral.isEmpty) {
        final value = chosen!;
        final basis = headAxesFromYaw(value),
            cameraAngle = _angle(headAxesFromYaw(value)['forward'], ray)!;
        if (cameraAngle < n('side_profile_min_deg') - 1e-8 ||
            cameraAngle > n('side_profile_max_deg') + 1e-8) {
          throw StateError('H4 reference-camera constraint failed');
        }
        if (previousVisible &&
            previous != null &&
            t - previousTime! <= n('max_continuity_gap_s')) {
          final step = value - previous;
          diag['step_deg'] = _deg(step);
          diag['rate_deg_s'] = _deg(step).abs() / (t - previousTime);
        }
        minSeen = minSeen == null ? value : math.min(minSeen, value);
        maxSeen = maxSeen == null ? value : math.max(maxSeen, value);
        diag.addAll({
          'camera_angle_deg': cameraAngle,
          'head_yaw_deg': _deg(value),
          'yaw_from_baseline_deg': _deg(value - baseline!),
          'constraint_projection_deg': _deg(value - smooth!),
        });
        if ((value - smooth).abs() > 1e-9) {
          reasons.add('side_clamp_or_rate_projection');
        }
        pose = {
          'mode': 'conservative_batter',
          'axes': basis,
          'display_features': true,
          'reasons': reasons,
          'is_estimate': true,
          'is_measured': false,
          'policy_version': headPolicyVersion,
          'pitch_roll': 'neutral_display_assumption',
          'camera_reference': 'fixed_default_only',
          'torso_support_age_s': diag['torso_support_age_s'],
          'conservative_torso_display_hold': displayHold,
        };
        previous = value;
        previousTime = t;
        previousVisible = true;
      } else {
        pose = {
          'mode': 'neutral',
          'axes': null,
          'display_features': false,
          'reasons': [...neutral, ...reasons],
          'is_estimate': true,
          'is_measured': false,
          'policy_version': headPolicyVersion,
          'pitch_roll': 'unavailable',
          'camera_reference': 'fixed_default_only',
        };
        previousVisible = false;
      }
      diag['displayed_clip_yaw_span_deg'] = minSeen == null
          ? null
          : _deg(maxSeen! - minSeen);
      output.add({
        'index': i,
        'timestamp_s': t,
        'H4': pose,
        'diagnostic': diag,
      });
    }
    final shown = output
        .where((f) => f['H4']['display_features'] == true)
        .toList();
    final vals = [
      for (final f in shown)
        (f['diagnostic']['camera_angle_deg'] as num).toDouble(),
    ];
    final rates = [
      for (final f in shown)
        if (f['diagnostic']['rate_deg_s'] != null)
          (f['diagnostic']['rate_deg_s'] as num).toDouble(),
    ];
    return {
      'version': headPolicyVersion,
      'config': cfg,
      'frozen_default_file_sha256': headPolicyReferenceConfigSha256,
      'reference_camera_position': camera,
      'baseline': {
        'available': baseline != null,
        'reason': baseReason,
        'candidate_indices': candidates,
        'retained_indices': retained,
        'lead_yaw_deg': leadBase == null ? null : _deg(leadBase),
        'torso_yaw_deg': torsoBase == null ? null : _deg(torsoBase),
        'head_yaw_deg': baseline == null ? null : _deg(baseline),
        'side_projection_deg': projection,
        'side_branch': branch,
        'circular_resultant': resultant,
        'source':
            'initial anatomical lead shoulder + handedness + fixed-camera display constraint; not measured pitcher location',
        'offline_initialization': true,
      },
      'summary': {
        'frames': output.length,
        'directional_frames': shown.length,
        'neutral_frames': output.length - shown.length,
        'front_gaze_under30_frames': vals.where((v) => v < 30).length,
        'front_gaze_under60_frames': vals.where((v) => v < 60).length,
        'side_min_violation_frames': vals
            .where((v) => v < n('side_profile_min_deg') - 1e-8)
            .length,
        'minimum_camera_angle_deg': vals.isEmpty ? null : vals.reduce(math.min),
        'maximum_camera_angle_deg': vals.isEmpty ? null : vals.reduce(math.max),
        'maximum_adjacent_rate_deg_s': rates.isEmpty
            ? null
            : rates.reduce(math.max),
        'clip_yaw_span_deg': minSeen == null ? null : _deg(maxSeen! - minSeen),
        'baseline_clamp_violations': shown
            .where(
              (f) =>
                  (f['diagnostic']['yaw_from_baseline_deg'] as num).abs() >
                  (f['diagnostic']['clamp_limit_deg'] as num) + 1e-8,
            )
            .length,
        'face_auxiliary_frames': shown
            .where((f) => f['diagnostic']['face_used'] == true)
            .length,
        'conservative_torso_display_hold_frames': shown
            .where(
              (f) => f['diagnostic']['conservative_torso_display_hold'] == true,
            )
            .length,
        'accuracy_claim': false,
      },
      'frames': output,
      'joint_coordinates_modified': false,
      'actual_head_accuracy': 'not_measured',
    };
  }
}

(double?, List<int>, double?) _circular(List<double> values, _Map cfg) {
  if (values.length < cfg['baseline_min_valid_frames']) return (null, [], null);
  var medoid = values.first, cost = double.infinity;
  for (final a in values) {
    final c = values.fold<double>(0, (s, b) => s + _wrap(a - b).abs());
    if (c < cost) {
      medoid = a;
      cost = c;
    }
  }
  final keep = [
    for (var i = 0; i < values.length; i++)
      if (_deg(_wrap(values[i] - medoid)).abs() <= cfg['baseline_trim_deg']) i,
  ];
  if (keep.length < cfg['baseline_min_valid_frames']) return (null, keep, null);
  final re =
      keep.fold<double>(0, (s, i) => s + math.cos(values[i])) / keep.length;
  final im =
      keep.fold<double>(0, (s, i) => s + math.sin(values[i])) / keep.length;
  final r = math.sqrt(re * re + im * im);
  return (
    r < cfg['baseline_min_resultant'] ? null : math.atan2(im, re),
    keep,
    r,
  );
}

List<_Interval> _intervals(
  List<double> ray,
  int branch,
  _Map cfg,
  double around,
) {
  final cy = _yaw(ray);
  if (cy == null) return [(double.negativeInfinity, double.infinity)];
  final a = cy + branch * _rad(cfg['side_profile_min_deg']),
      b = cy + branch * _rad(cfg['side_profile_max_deg']);
  final lo = math.min(a, b), hi = math.max(a, b);
  final q = (around - (lo + hi) / 2) / _tau;
  // Python round uses ties-to-even; preserving it avoids branch differences.
  final floor = q.floor(), fraction = q - q.floor();
  final k = fraction == .5 ? (floor.isEven ? floor : floor + 1) : q.round();
  return [
    for (final j in [-1, 0, 1]) (lo + (k + j) * _tau, hi + (k + j) * _tau),
  ];
}

List<_Interval> _intersect(List<_Interval> intervals, double lo, double hi) => [
  for (final v in intervals)
    if (math.max(v.$1, lo) <= math.min(v.$2, hi) + 1e-12)
      (math.max(v.$1, lo), math.min(v.$2, hi)),
];
double? _project(double value, List<_Interval> intervals) {
  double? result;
  for (final (a, b) in intervals) {
    final c = math.min(math.max(value, a), b);
    if (result == null || (c - value).abs() < (result - value).abs()) {
      result = c;
    }
  }
  return result;
}
