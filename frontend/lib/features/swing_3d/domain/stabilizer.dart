import 'dart:math' as math;

import 'pose.dart';

enum PoseRisk {
  missing('관측 없음', true),
  invalidRoot('골반 기준점 없음', true),
  imageFiltered('영상 좌표 필터 경고', true),
  imageInterpolated('영상 좌표 보간 이력', true),
  imageEdgeFilled('영상 좌표 가장자리 채움 이력', true),
  lowImageVisibility('낮은 영상 가시성', true),
  lengthAnomaly('world 연결 길이 급변', true),
  velocitySpike('world 시간당 이동 급변', true),
  dependencyMissing('상위 관절 없음', true),
  noReference('길이 기준 표본 부족', false),
  manualReview('수동 검토 주의', false);

  const PoseRisk(this.label, this.suppressesStabilized);
  final String label;
  final bool suppressesStabilized;
  bool get isAutomatic => this != PoseRisk.manualReview;
}

/// Explicit display heuristics, not calibrated anatomical or accuracy limits.
class StabilizerConfig {
  const StabilizerConfig({
    this.minimumImageVisibility = 0.5,
    this.minimumReferenceSamples = 3,
    this.minimumLengthRatio = 0.65,
    this.maximumLengthRatio = 1.35,
    this.maximumBodyLengthsPerSecond = 30,
    this.maximumMotionGapSeconds = 0.12,
  });

  final double minimumImageVisibility;
  final int minimumReferenceSamples;
  final double minimumLengthRatio;
  final double maximumLengthRatio;
  final double maximumBodyLengthsPerSecond;
  final double maximumMotionGapSeconds;
}

class StabilizedFrame {
  StabilizedFrame({
    required this.source,
    required List<Vec3?> positions,
    required List<Set<PoseRisk>> jointRisks,
    required List<String> warnings,
  }) : positions = List.unmodifiable(positions),
       jointRisks = List.unmodifiable(
         jointRisks.map((r) => Set<PoseRisk>.unmodifiable(r)),
       ),
       warnings = List.unmodifiable(warnings),
       adjustments = List.unmodifiable(
         List<Vec3?>.generate(12, (j) {
           final original = source.positions[j];
           final displayed = positions[j];
           return original == null || displayed == null
               ? null
               : displayed - original;
         }),
       );

  final PoseFrame source;
  final List<Vec3?> positions;
  final List<Set<PoseRisk>> jointRisks;
  final List<String> warnings;

  /// Exact stable-minus-source vector. Null means omitted/missing, never zero.
  final List<Vec3?> adjustments;

  List<Vec3?> get rawPositions => List<Vec3?>.unmodifiable(
    List.generate(
      12,
      (j) => source.hasValidRoot && source.observedValid[j]
          ? source.positions[j]
          : null,
    ),
  );
  int get omittedJointCount => List.generate(
    12,
    (j) => j,
  ).where((j) => source.positions[j] != null && positions[j] == null).length;
  int get adjustedJointCount =>
      adjustments.where((d) => d != null && d.length > 0.000001).length;
  int get automaticRiskJointCount => jointRisks
      .where(
        (r) =>
            r.any((risk) => risk.isAutomatic && risk != PoseRisk.noReference),
      )
      .length;
  int get manualReviewJointCount =>
      jointRisks.where((r) => r.contains(PoseRisk.manualReview)).length;
  double get maximumAdjustment => adjustments.fold<double>(
    0,
    (value, d) => math.max(value, d?.length ?? 0),
  );
}

/// Spatial only: a clip-wide robust length, each frame's original direction.
/// No interpolation, temporal smoothing, or copying an occluded pose forward.
class PoseStabilizer {
  PoseStabilizer(this.clip, {this.config = const StabilizerConfig()}) {
    _validateConfig();
    final risks = <List<Set<PoseRisk>>>[
      for (final frame in clip.frames) _initialRisks(frame),
    ];
    final refs = <String, double>{};
    for (final bone in limbBones) {
      final lengths = <double>[];
      for (var i = 0; i < clip.frames.length; i++) {
        final frame = clip.frames[i];
        if (!_referenceEligible(frame, risks[i], bone.parent) ||
            !_referenceEligible(frame, risks[i], bone.child)) {
          continue;
        }
        final length =
            (frame.positions[bone.child]! - frame.positions[bone.parent]!)
                .length;
        if (length.isFinite && length > 0.000001) lengths.add(length);
      }
      if (lengths.length >= config.minimumReferenceSamples) {
        refs[bone.id] = _median(lengths);
      }
    }
    referenceLengths = Map.unmodifiable(refs);
    bodyScale = _bodyScale();

    for (var i = 0; i < clip.frames.length; i++) {
      final frame = clip.frames[i];
      for (final bone in limbBones) {
        final parent = frame.positions[bone.parent];
        final child = frame.positions[bone.child];
        if (parent == null || child == null) continue;
        final reference = refs[bone.id];
        if (reference == null) {
          risks[i][bone.child].add(PoseRisk.noReference);
          continue;
        }
        final ratio = (child - parent).length / reference;
        if (!ratio.isFinite ||
            ratio < config.minimumLengthRatio ||
            ratio > config.maximumLengthRatio) {
          risks[i][bone.child].add(PoseRisk.lengthAnomaly);
        }
      }
    }

    // Compare only adjacent valid observations; a gap/occlusion is never bridged.
    final maxGap = math.max(config.maximumMotionGapSeconds, 3 / clip.fps);
    for (var i = 1; i < clip.frames.length; i++) {
      final previous = clip.frames[i - 1];
      final current = clip.frames[i];
      final dt = current.timestamp - previous.timestamp;
      if (dt > maxGap || bodyScale == null) continue;
      for (var j = 0; j < 12; j++) {
        if (!_motionEligible(previous, risks[i - 1], j) ||
            !_motionEligible(current, risks[i], j)) {
          continue;
        }
        final speed =
            (current.positions[j]! - previous.positions[j]!).length /
            dt /
            bodyScale!;
        if (speed > config.maximumBodyLengthsPerSecond) {
          risks[i][j].add(PoseRisk.velocitySpike);
        }
      }
    }

    frames = List.unmodifiable(<StabilizedFrame>[
      for (var i = 0; i < clip.frames.length; i++)
        _stabilizeFrame(clip.frames[i], risks[i]),
    ]);
  }

  final SwingClip clip;
  final StabilizerConfig config;
  late final Map<String, double> referenceLengths;
  late final double? bodyScale;
  late final List<StabilizedFrame> frames;

  StabilizedFrame frameAt(int index) => frames[index];

  void _validateConfig() {
    if (!config.minimumImageVisibility.isFinite ||
        config.minimumImageVisibility < 0 ||
        config.minimumImageVisibility > 1 ||
        config.minimumReferenceSamples < 1 ||
        !config.minimumLengthRatio.isFinite ||
        config.minimumLengthRatio <= 0 ||
        !config.maximumLengthRatio.isFinite ||
        config.maximumLengthRatio < config.minimumLengthRatio ||
        !config.maximumBodyLengthsPerSecond.isFinite ||
        config.maximumBodyLengthsPerSecond <= 0 ||
        !config.maximumMotionGapSeconds.isFinite ||
        config.maximumMotionGapSeconds <= 0) {
      throw ArgumentError(
        'Invalid StabilizerConfig: finite positive thresholds and valid sample count are required.',
      );
    }
  }

  List<Set<PoseRisk>> _initialRisks(PoseFrame frame) {
    final risks = List.generate(12, (_) => <PoseRisk>{});
    for (var j = 0; j < 12; j++) {
      if (frame.positions[j] == null || !frame.observedValid[j]) {
        risks[j].add(PoseRisk.missing);
      }
      if (!frame.hasValidRoot) risks[j].add(PoseRisk.invalidRoot);
      if (frame.imageQuality.combinedMissing[j]) {
        risks[j].add(PoseRisk.imageFiltered);
      }
      if (frame.imageQuality.interpolated[j]) {
        risks[j].add(PoseRisk.imageInterpolated);
      }
      if (frame.imageQuality.edgeFilled[j]) {
        risks[j].add(PoseRisk.imageEdgeFilled);
      }
      final visibility = frame.visibility[j];
      if (visibility != null && visibility < config.minimumImageVisibility) {
        risks[j].add(PoseRisk.lowImageVisibility);
      }
    }
    for (final annotation in frame.manualAnnotations) {
      for (final joint in annotation.jointIndices) {
        risks[joint].add(PoseRisk.manualReview);
      }
    }
    return risks;
  }

  bool _referenceEligible(
    PoseFrame frame,
    List<Set<PoseRisk>> risks,
    int joint,
  ) =>
      frame.positions[joint] != null &&
      frame.observedValid[joint] &&
      frame.visibility[joint] != null &&
      risks[joint].isEmpty;

  bool _motionEligible(PoseFrame frame, List<Set<PoseRisk>> risks, int joint) =>
      frame.positions[joint] != null &&
      frame.observedValid[joint] &&
      !risks[joint].any(
        (risk) => risk.suppressesStabilized || risk == PoseRisk.manualReview,
      );

  double? _bodyScale() {
    final values = <double>[];
    for (final frame in clip.frames) {
      if (!frame.hasValidRoot ||
          frame.positions[0] == null ||
          frame.positions[1] == null) {
        continue;
      }
      final shoulders = (frame.positions[0]! + frame.positions[1]!) / 2;
      final hips = (frame.positions[6]! + frame.positions[7]!) / 2;
      final length = (shoulders - hips).length;
      if (length.isFinite && length > 0.000001) values.add(length);
    }
    return values.isEmpty ? null : _median(values);
  }

  StabilizedFrame _stabilizeFrame(PoseFrame frame, List<Set<PoseRisk>> risks) {
    final positions = List<Vec3?>.from(frame.positions);
    for (var j = 0; j < 12; j++) {
      if (risks[j].any((risk) => risk.suppressesStabilized)) {
        positions[j] = null;
      }
    }
    for (final bone in limbBones) {
      final parent = positions[bone.parent];
      if (parent == null) {
        if (positions[bone.child] != null) {
          risks[bone.child].add(PoseRisk.dependencyMissing);
        }
        positions[bone.child] = null;
        continue;
      }
      if (positions[bone.child] == null) continue;
      final reference = referenceLengths[bone.id];
      if (reference == null) continue;
      final rawParent = frame.positions[bone.parent]!;
      final rawChild = frame.positions[bone.child]!;
      final direction = rawChild - rawParent;
      if (!direction.length.isFinite || direction.length <= 0.000001) {
        risks[bone.child].add(PoseRisk.lengthAnomaly);
        positions[bone.child] = null;
      } else {
        positions[bone.child] =
            parent + direction * (reference / direction.length);
      }
    }
    final warnings = <String>[...frame.warnings];
    for (final annotation in frame.manualAnnotations) {
      warnings.add('수동 검토: ${annotation.label} — ${annotation.note}');
    }
    final automatic = <PoseRisk>{
      for (final joint in risks) ...joint.where((risk) => risk.isAutomatic),
    };
    for (final risk in automatic) {
      warnings.add(
        '${risk.label}: ${risks.where((joint) => joint.contains(risk)).length}개 관절',
      );
    }
    if (bodyScale == null) warnings.add('몸통 기준 길이가 없어 시간당 이동 검사를 적용하지 않았습니다.');
    return StabilizedFrame(
      source: frame,
      positions: positions,
      jointRisks: risks,
      warnings: warnings,
    );
  }
}

double _median(List<double> values) {
  final ordered = List<double>.from(values)..sort();
  final middle = ordered.length ~/ 2;
  return ordered.length.isOdd
      ? ordered[middle]
      : (ordered[middle - 1] + ordered[middle]) / 2;
}
