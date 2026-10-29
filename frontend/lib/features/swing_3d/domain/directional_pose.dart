import 'orientation.dart' as o;

/// Offline direction calculation plus independently supplied P2 display masks.
/// No policy is fitted from a filename, player or batting side.
class DirectionalMotion {
  DirectionalMotion._(this.clip, this.result, this.hasP2);
  final o.OrientationClip clip;
  final Map<String, dynamic> result;
  final bool hasP2;
  double get bodyScale => (result['body_scale'] as num).toDouble();
  Map<String, dynamic> frameAt(int index) =>
      result['frames'][index] as Map<String, dynamic>;
  List<bool>? edgesAt(int index) => hasP2
      ? (clip.frames[index].extra['p2']['edge_visible'] as List).cast<bool>()
      : null;
  bool torsoAt(int index) => hasP2
      ? clip.frames[index].extra['p2']['torso_visible'] as bool
      : [0, 1, 6, 7].every((j) => clip.frames[index].positions[j] != null);
  List<bool> warningsAt(int index) => hasP2
      ? (clip.frames[index].extra['p2']['joint_warnings'] as List).cast<bool>()
      : List.filled(12, false);
  List<String> reasonsAt(int index) {
    final frame = frameAt(index);
    return [
      if (hasP2)
        for (final message
            in clip.frames[index].extra['p2']['warnings'] as List? ?? [])
          'P2: $message',
      for (final message in frame['shoulder_reasons']) '어깨 방향: $message',
      for (final message in frame['pelvis_reasons']) '골반 방향: $message',
      for (final foot in frame['feet'])
        for (final message in foot['reasons'])
          '${foot['side'] == 'left' ? '왼발' : '오른발'} 방향: $message',
    ];
  }

  /// Final display contract validates binding to raw observations first.
  /// This constructor deliberately accepts only already restored coordinates.
  factory DirectionalMotion.fromDisplay(Map<String, dynamic> data) {
    if (data['source_oriented'] != true ||
        data['coordinate_convention'] != o.renderConvention) {
      throw const FormatException(
        'Display coordinates must be source restored',
      );
    }
    final clip = o.OrientationClip.fromJson(data);
    if (data['display_policy']?['id'] != 'P2' ||
        clip.frames.any((f) => f.extra['p2'] == null)) {
      throw const FormatException('Final display requires complete P2 masks');
    }
    return DirectionalMotion._(
      clip,
      const o.OrientationEngine().analyze(clip),
      true,
    );
  }

  /// Sidecars must describe the exact same source-oriented body observations.
  factory DirectionalMotion.bind(
    Map<String, dynamic> data,
    Map<String, dynamic> body,
  ) {
    final binding = data['binding'];
    final bodyHash = body['source_provenance']?['source_video_sha256'];
    if (binding is! Map ||
        binding['contract'] != 'EXP007-O1-binding-v1' ||
        binding['clip_id'] != body['id'] ||
        bodyHash is! String ||
        binding['source_sha256'] != bodyHash ||
        data['source_provenance']?['source_sha256'] != bodyHash) {
      throw const FormatException(
        'Direction data source/clip identity mismatch',
      );
    }
    if (data['source_oriented'] != true ||
        body['source_oriented'] != true ||
        data['mirrored_input'] != body['mirrored_input'] ||
        data['handedness'] != body['handedness'] ||
        data['coordinate_convention'] != body['coordinate_convention'] ||
        data['fps'] != body['fps']) {
      throw const FormatException(
        'Direction data coordinate restoration mismatch',
      );
    }
    final clip = o.OrientationClip.fromJson(data);
    final frames = body['frames'] as List;
    if (clip.frames.length != frames.length) {
      throw const FormatException('Direction data frame count mismatch');
    }
    for (var i = 0; i < frames.length; i++) {
      if (clip.frames[i].timestamp != frames[i]['timestamp_s']) {
        throw const FormatException('Direction data timestamp mismatch');
      }
      for (var j = 0; j < 12; j++) {
        final a = clip.frames[i].positions[j]?.toJson();
        final b = frames[i]['positions'][j];
        if (a == null
            ? b != null
            : b == null ||
                  List.generate(3, (k) => a[k] != b[k]).any((v) => v)) {
          throw const FormatException(
            'Direction data body coordinates mismatch',
          );
        }
      }
    }
    final masks = clip.frames.where((f) => f.extra['p2'] != null).length;
    if (masks != 0 && masks != clip.frames.length) {
      throw const FormatException('Partial P2 policy sequence');
    }
    if (masks != 0 && data['display_policy']?['id'] != 'P2') {
      throw const FormatException(
        'P2 masks require explicit policy provenance',
      );
    }
    return DirectionalMotion._(
      clip,
      const o.OrientationEngine().analyze(clip),
      masks != 0,
    );
  }
}
