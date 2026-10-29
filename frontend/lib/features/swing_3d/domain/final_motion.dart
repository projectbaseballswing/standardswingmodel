import 'directional_pose.dart';
import 'head_policy.dart';
import 'orientation.dart' as o;
import 'pose.dart';

/// Display-only offline S2 plus sequence-level O1/F1/H4. Raw input and score
/// observations remain separate. No network, identity-specific branches or
/// live-camera inputs belong in this reusable processing boundary.
class FinalMotion {
  FinalMotion._(
    this.directional,
    this.headResult,
    this.referenceScale,
    this.presentationEnd,
  );
  final DirectionalMotion directional;
  final Map<String, dynamic> headResult;
  final double referenceScale;
  final double presentationEnd;
  List<Vec3?> positionsAt(int index) => directional.clip.frames[index].positions
      .map((p) => p == null ? null : Vec3(p.x, p.y, p.z))
      .toList();
  Map<String, dynamic> headAt(int index) =>
      headResult['frames'][index]['H4'] as Map<String, dynamic>;

  factory FinalMotion.bind(
    Map<String, dynamic> data,
    Map<String, dynamic> body,
  ) {
    void require(bool ok, String message) {
      if (!ok) throw FormatException('Final display: $message');
    }

    require(
      data['contract'] == 'EXP007-final-display-v1' &&
          data['schema_version'] == 1,
      'unsupported contract',
    );
    final binding = data['binding'];
    final processing = data['processing'];
    require(binding is Map && processing is Map, 'missing provenance');
    final sourceHash = body['source_provenance']?['source_video_sha256'];
    require(
      sourceHash is String &&
          RegExp(r'^[0-9a-f]{64}$').hasMatch(sourceHash) &&
          binding['clip_id'] == body['id'] &&
          binding['source_sha256'] == sourceHash &&
          binding['source_oriented'] == true &&
          binding['coordinate_convention'] == o.renderConvention,
      'source identity mismatch',
    );
    require(
      processing['smoothing_condition'] == 'S2' &&
          processing['smoothing_passes'] == 1 &&
          processing['original_masks_preserved'] == true &&
          processing['raw_missingness_preserved'] == true &&
          processing['interpolation'] == false &&
          processing['offline'] == true &&
          processing['camera_reference'] == 'fixed_default_only' &&
          processing['score_model_modified'] == false,
      'S2 must be applied once offline',
    );
    const s2Config =
        'fee99b736a1edaea603615e2503dd3c9aff0a2f1fa919a570642b249c7e23bd6';
    const s2Core =
        '03f333fecd62f0f6c6c935e71b79dc14574c283ee9795fd923206a93b2d111ad';
    require(
      processing['s2_config_sha256'] == s2Config &&
          processing['s2_core_sha256'] == s2Core,
      'unsupported S2 implementation',
    );
    require(
      (processing['h4_policy_version'] == null ||
              processing['h4_policy_version'] == headPolicyVersion) &&
          (processing['h4_config_sha256'] == null ||
              processing['h4_config_sha256'] ==
                  headPolicyReferenceConfigSha256),
      'unsupported H4 policy',
    );
    final raw = data['raw_orientation'];
    final display = data['display_orientation'];
    require(
      raw is Map<String, dynamic> && display is Map<String, dynamic>,
      'missing raw/display sequences',
    );
    for (final sequence in [raw, display]) {
      require(
        sequence['source_oriented'] == true &&
            sequence['coordinate_convention'] == o.renderConvention &&
            sequence['handedness'] == body['handedness'] &&
            sequence['mirrored_input'] == body['mirrored_input'] &&
            sequence['source_provenance']?['source_sha256'] == sourceHash &&
            sequence['fps'] == body['fps'],
        'ambiguous restoration or handedness',
      );
    }
    require(
      raw['smoothing']?['condition'] == 'S0' &&
          raw['smoothing']?['joint_coordinates_modified'] == false,
      'raw observations must be unsmoothed S0',
    );
    require(
      display['smoothing']?['condition'] == 'S2' &&
          display['smoothing']?['version'] ==
              'motion-smoothing-2026-10-26-v1' &&
          display['smoothing']?['config_sha256'] ==
              processing['s2_config_sha256'] &&
          display['smoothing']?['raw_missingness_preserved'] == true &&
          display['smoothing']?['original_p2_masks_preserved'] == true,
      'display S2 sequence provenance mismatch',
    );
    final rawClip = o.OrientationClip.fromJson(raw as Map<String, dynamic>);
    final directional = DirectionalMotion.fromDisplay(
      display as Map<String, dynamic>,
    );
    final sourceFrames = body['frames'] as List;
    require(
      rawClip.frames.length == sourceFrames.length &&
          directional.clip.frames.length == sourceFrames.length &&
          binding['frame_count'] == sourceFrames.length,
      'frame count mismatch',
    );
    final ptsOrigin = rawClip.frames.first.extra['decoded_pts_s'];
    require(ptsOrigin is num && ptsOrigin.isFinite, 'decoded PTS required');
    final presentationEnd = data['presentation_end_s'];
    require(
      presentationEnd is num &&
          presentationEnd.isFinite &&
          presentationEnd > rawClip.frames.last.timestamp &&
          raw['presentation_end_s'] == presentationEnd &&
          display['presentation_end_s'] == presentationEnd,
      'presentation endpoint mismatch',
    );
    for (var i = 0; i < sourceFrames.length; i++) {
      final before = rawClip.frames[i], after = directional.clip.frames[i];
      final pts = before.extra['decoded_pts_s'];
      require(
        pts is num &&
            pts.isFinite &&
            after.extra['decoded_pts_s'] == pts &&
            (before.timestamp - (pts - ptsOrigin)).abs() < 1e-9,
        'decoded PTS mismatch at $i',
      );
      require(
        (before.timestamp - (sourceFrames[i]['timestamp_s'] as num)).abs() <
                1e-6 &&
            before.timestamp == after.timestamp,
        'timestamp mismatch at $i',
      );
      for (var j = 0; j < 12; j++) {
        final original = sourceFrames[i]['positions'][j] as List?;
        final point = before.positions[j]?.toJson();
        require(
          point == null
              ? original == null
              : original != null &&
                    List.generate(
                      3,
                      (k) => (point[k] - (original[k] as num)).abs() < 1e-9,
                    ).every((v) => v),
          'raw observation mismatch at $i/$j',
        );
        require(
          (before.positions[j] == null) == (after.positions[j] == null),
          'missing body observation changed at $i/$j',
        );
      }
      for (var j = 0; j < 4; j++) {
        require(
          (before.feet[j] == null) == (after.feet[j] == null),
          'missing foot observation changed at $i/$j',
        );
      }
      require(
        _equal(before.extra['p2'], after.extra['p2']),
        'P2 masks changed at $i',
      );
      final originalOrientation = body['orientation_data'];
      if (originalOrientation is Map && originalOrientation['frames'] is List) {
        final originalFrames = originalOrientation['frames'] as List;
        require(
          originalFrames.length == sourceFrames.length &&
              _equal(before.extra['p2'], originalFrames[i]['p2']),
          'upstream P2 masks changed at $i',
        );
      }
      require(
        _equal(before.extra['foot_visibility'], after.extra['foot_visibility']),
        'foot quality changed at $i',
      );
    }
    // Generic offline packages may omit the scale. Compute the same O1 body
    // reference once; never use a live zoom or a guessed player-specific size.
    final scale = data['reference_scale'] ?? directional.bodyScale;
    require(scale is num && scale.isFinite && scale > 0, 'invalid body scale');
    require(
      ((scale as num).toDouble() - directional.bodyScale).abs() < 1e-9,
      'reference camera/body scale mismatch',
    );
    final h4 = const HeadPolicy().analyze(
      display,
      directional.result,
      handedness: body['handedness'] as String?,
      referenceScale: scale.toDouble(),
    );
    return FinalMotion._(
      directional,
      h4,
      scale.toDouble(),
      (presentationEnd as num).toDouble(),
    );
  }
}

bool _equal(dynamic a, dynamic b) {
  if (a is List && b is List) {
    return a.length == b.length &&
        List.generate(a.length, (i) => _equal(a[i], b[i])).every((v) => v);
  }
  if (a is Map && b is Map) {
    return a.length == b.length &&
        a.keys.every((k) => b.containsKey(k) && _equal(a[k], b[k]));
  }
  return a == b;
}
