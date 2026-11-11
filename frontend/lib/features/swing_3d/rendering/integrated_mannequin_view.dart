import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:three_js/three_js.dart' as three;
import '../domain/head_policy.dart';
import 'mannequin_style.dart';

/// A mesh mannequin driven by the twelve supplied joints, without pose fitting.
///
/// Coordinates are already X-right, Y-up, Z-toward-camera. No axis conversion,
/// mirroring, temporal interpolation, or missing-joint filling happens here.
/// [yaw]/[pitch] are radians and [distance] is in the input coordinate units.
class MannequinView extends StatefulWidget {
  const MannequinView({
    super.key,
    required this.positions,
    required this.jointWarnings,
    this.rawPositions,
    this.orientation,
    this.headPose,
    this.showAxes = false,
    this.cameraTargetY = -.10,
    this.onDiagnostics,
    this.edgeVisible,
    this.torsoVisible = true,
    this.footModes,
    this.footDirections,
    this.showEstimates = true,
    this.yaw = 0.45,
    this.pitch = 0.12,
    this.distance = 3.6,
    this.bodyScale = 1.0,
    this.onReady,
    this.onError,
  });

  final List<List<double>?> positions;
  final List<bool> jointWarnings;
  final List<List<double>?>? rawPositions;
  final List<bool>? edgeVisible;
  final bool torsoVisible;
  final List<String>? footModes;
  final List<List<double>?>? footDirections;
  final Map<String, dynamic>? orientation;

  /// Optional independent world-space head policy. Null preserves legacy H0;
  /// an explicit neutral policy suppresses facial direction markers.
  final Map<String, dynamic>? headPose;
  final double cameraTargetY;
  final bool showAxes;
  final ValueChanged<Map<String, dynamic>>? onDiagnostics;
  final bool showEstimates;
  final double yaw;
  final double pitch;
  final double distance;

  /// Scales only illustrative thickness/head/hand/foot sizes and the scene guide.
  /// It never rescales the input joints or changes a measured segment length.
  final double bodyScale;
  final VoidCallback? onReady;
  final ValueChanged<String>? onError;

  @override
  State<MannequinView> createState() => _MannequinViewState();
}

class _MannequinViewState extends State<MannequinView> {
  static const _edges = <(int, int, double)>[
    (0, 1, .064),
    (0, 2, .052),
    (2, 4, .040),
    (1, 3, .052),
    (3, 5, .040),
    (0, 6, .037),
    (1, 7, .037),
    (6, 7, .075),
    (6, 8, .070),
    (8, 10, .050),
    (7, 9, .070),
    (9, 11, .050),
  ];
  // 운동선수형 비율(어깨·허벅지 굵게, 손목·발목 가늘게). compare3d 뷰어 RB 와 일치.
  static const _jointRadii = <double>[
    .085,
    .085,
    .050,
    .050,
    .033,
    .033,
    .076,
    .076,
    .058,
    .058,
    .039,
    .039,
  ];

  late final _ReportingThreeJS _three;
  late final three.PerspectiveCamera _camera;
  late final three.SphereGeometry _sphere;
  late final three.CylinderGeometry _cylinder;
  // 사지별 테이퍼 원뿔대(반경은 geom에 baked, 길이만 스케일). 관절 구가 끝을 메워 매끈하게 블렌딩.
  final _limbGeo = <three.CylinderGeometry>[];
  // 매끈한 단일 몸통(가슴 넓고 허리 좁고 골반 넓은 프로파일 회전체). compare3d 뷰어와 동일.
  late final three.LatheGeometry _torsoLathe;
  // 앞뒤(forward)로 납작하게 눌러 실제 사람 몸통 단면에 가깝게.
  static const _torsoFlatten = 0.66;
  // compare3d 룩: 민둥 달걀 머리. 코·눈·뒤통수 원반(얼굴마커)을 끈다.
  static const _showFaceFeatures = false;
  // 몸통(Lathe)에 흡수되는 구조용 뼈: 어깨선(0)·좌우 몸통옆(5,6)·골반(7).
  static const _torsoEdges = {0, 5, 6, 7};
  late final three.Material _ivory;
  late final three.Material _cyan;
  late final three.Material _warning;
  late final three.Material _estimated;
  late final three.Material _rawGhost;
  final _materials = <three.Material>[];
  final _joints = <three.Mesh>[];
  final _limbs = <three.Mesh>[];
  final _rawJoints = <three.Mesh>[];
  final _rawLimbs = <three.Mesh>[];
  final _hands = <three.Mesh>[];
  final _feet = <three.Mesh>[];
  final _face = <three.Mesh>[];
  final _axisLines = <three.Mesh>[];
  final _axisTips = <three.Mesh>[];
  late final three.Material _headColor;
  late final three.Material _neutralColor;
  late final three.Material _directionColor;
  final _guide = three.Group();
  late final three.Mesh _torso;
  // 배트(손잡이 가늘고 배럴 두꺼운 테이퍼) + 노브. 팔뚝 방향으로 추정 배치.
  late final three.Mesh _bat;
  late final three.Mesh _batKnob;
  late final three.Mesh _pelvis;
  late final three.Mesh _head;
  late final three.Mesh _neck;
  bool _sceneBuilt = false;
  String? _error;
  Timer? _startupTimer;
  Size? _lastSize;

  double get _scale => widget.bodyScale.isFinite && widget.bodyScale > 0
      ? widget.bodyScale
      : 1.0;

  @override
  void initState() {
    super.initState();
    _camera = three.PerspectiveCamera(42, 1, .01, 100);
    _three = _ReportingThreeJS(
      onFailure: _handleError,
      settings: three.Settings(
        clearColor: MannequinStyle.background,
        clearAlpha: 1,
        alpha: false,
        antialias: true,
        enableShadowMap: true,
        toneMapping: three.NoToneMapping,
        screenResolution: 1.0,
      ),
      setup: _setup,
      onSetupComplete: _handleReady,
      loadingWidget: const ColoredBox(
        color: Color(0xFF000000 | MannequinStyle.background),
        child: Center(
          child: CircularProgressIndicator(
            color: Color(0xFF000000 | MannequinStyle.body),
          ),
        ),
      ),
    );
    // Initialize these late-final fields even if platform initialization fails.
    _three.scene = three.Scene();
    _three.camera = _camera;
    _startupTimer = Timer(const Duration(seconds: 25), () {
      if (mounted && !_sceneBuilt && _error == null) {
        _handleError('3D 초기화가 완료되지 않았습니다. WebGL2 지원과 로컬 바인딩을 확인하세요.');
      }
    });
  }

  three.Material _material(
    int color, {
    double opacity = 1,
    bool wireframe = false,
  }) {
    final result = three.MeshStandardMaterial.fromMap({
      'color': color,
      'roughness': .72,
      'metalness': .02,
      'transparent': opacity < 1,
      'opacity': opacity,
      'depthWrite': opacity >= 1,
      'side': three.DoubleSide,
      'wireframe': wireframe,
    });
    _materials.add(result);
    return result;
  }

  three.Mesh _mesh(three.BufferGeometry geometry, three.Material material) {
    final result = three.Mesh(geometry, material);
    result.visible = false;
    result.castShadow = true;
    _three.scene.add(result);
    return result;
  }

  Future<void> _setup() async {
    if (!mounted) return;
    _sphere = three.SphereGeometry(1, 20, 14);
    _cylinder = three.CylinderGeometry(1, 1, 1, 16);
    // 각 사지 = 양 끝 관절 반경으로 테이퍼진 원뿔대. 로컬 +Y 끝(top)=자식관절(b), -Y(bottom)=부모(a).
    for (final (a, b, _) in _edges) {
      _limbGeo.add(three.CylinderGeometry(_jointRadii[b], _jointRadii[a], 1, 18));
    }
    _ivory = _material(MannequinStyle.body);
    _cyan = _material(MannequinStyle.body);
    _warning = _material(MannequinStyle.inactive);
    _estimated = _material(MannequinStyle.body);
    _rawGhost = _material(MannequinStyle.ghost, opacity: .30);
    _directionColor = _material(MannequinStyle.direction);

    // With NoToneMapping, avoid light levels that clip the displayed channels.
    // Lower diffuse light preserves colour and shading on curved/side faces.
    _three.scene.add(
      three.HemisphereLight(
        MannequinStyle.skyLight,
        MannequinStyle.groundLight,
        .40,
      ),
    );
    final keyLight = three.DirectionalLight(MannequinStyle.keyLight, 1.20);
    keyLight.position.setValues(3, 5, 4);
    // compare3d 처럼 접지 그림자를 드리운다.
    keyLight.castShadow = true;
    keyLight.shadow!.mapSize.setValues(1024, 1024);
    keyLight.shadow!.bias = -0.0009;
    final shadowCam = keyLight.shadow!.camera! as three.OrthographicCamera;
    shadowCam.near = 0.5;
    shadowCam.far = 25;
    shadowCam.left = -2;
    shadowCam.right = 2;
    shadowCam.top = 2.4;
    shadowCam.bottom = -2.4;
    shadowCam.updateProjectionMatrix();
    _three.scene.add(keyLight);
    // 그림자를 받는 바닥(그림자만 보이는 투명 재질). 가이드 그리드와 같은 평면에 둔다.
    final groundMaterial = three.ShadowMaterial();
    groundMaterial.opacity = .30;
    groundMaterial.transparent = true;
    _materials.add(groundMaterial);
    final ground = three.Mesh(three.PlaneGeometry(12, 12), groundMaterial);
    ground.rotation.x = -math.pi / 2;
    ground.receiveShadow = true;
    _guide.add(ground);
    final rimLight = three.DirectionalLight(MannequinStyle.rimLight, .65);
    rimLight.position.setValues(-3, 2, -4);
    _three.scene.add(rimLight);
    final fillLight = three.DirectionalLight(MannequinStyle.fillLight, .22);
    fillLight.position.setValues(3, 0, -2);
    _three.scene.add(fillLight);

    for (var j = 0; j < 12; j++) {
      _joints.add(_mesh(_sphere, _ivory));
      _rawJoints.add(_mesh(_sphere, _rawGhost));
    }
    for (var j = 0; j < _edges.length; j++) {
      _limbs.add(_mesh(_limbGeo[j], _cyan));
      _rawLimbs.add(_mesh(_cylinder, _rawGhost));
    }
    // 가슴 넓고 허리 좁고 골반 넓은 프로파일(x=반경 m, y=0 골반→1 어깨)을 회전시킨 단일 몸통.
    _torsoLathe = three.LatheGeometry(
      <three.Vector>[
        three.Vector2(0.025, 0.00),
        three.Vector2(0.120, 0.05),
        three.Vector2(0.155, 0.15),
        three.Vector2(0.145, 0.28),
        three.Vector2(0.125, 0.42),
        three.Vector2(0.140, 0.55),
        three.Vector2(0.165, 0.70),
        three.Vector2(0.158, 0.82),
        three.Vector2(0.115, 0.92),
        three.Vector2(0.060, 0.99),
        three.Vector2(0.028, 1.03),
      ],
      segments: 24,
    );
    _torso = _mesh(_torsoLathe, _ivory);
    // 배트: 로컬 +Y 끝(top)=배럴(두꺼움), -Y(bottom)=손잡이(가늘음).
    _bat = _mesh(three.CylinderGeometry(.042, .016, 1, 16), _ivory);
    _batKnob = _mesh(_sphere, _ivory);
    _pelvis = _mesh(_sphere, _cyan);
    _head = _mesh(_sphere, _estimated);
    _neck = _mesh(_cylinder, _estimated);
    for (var j = 0; j < 2; j++) {
      _hands.add(_mesh(_sphere, _estimated));
      _feet.add(_mesh(_sphere, _estimated));
    }
    _headColor = _material(MannequinStyle.head);
    _neutralColor = _material(MannequinStyle.inactive);
    final darkFace = _material(MannequinStyle.faceDetail);
    final backMark = _material(MannequinStyle.backDetail);
    _face.add(_mesh(_sphere, _headColor)); // nose, local +Z
    _face.add(_mesh(_sphere, darkFace));
    _face.add(_mesh(_sphere, darkFace));
    _face.add(_mesh(_sphere, backMark)); // occipital marker, local -Z
    for (final color in [MannequinStyle.body, MannequinStyle.direction]) {
      final material = _material(color);
      _axisLines.add(_mesh(_cylinder, material));
      _axisTips.add(_mesh(_sphere, material));
    }
    _createGuide();
    _sceneBuilt = true;
    _syncScene();
  }

  void _createGuide() {
    final gridMaterial = _material(MannequinStyle.grid, opacity: .22);
    for (var i = -6; i <= 6; i++) {
      for (var axis = 0; axis < 2; axis++) {
        final line = three.Mesh(_cylinder, gridMaterial);
        final start = axis == 0
            ? three.Vector3(i * .25, 0, -1.5)
            : three.Vector3(-1.5, 0, i * .25);
        final end = axis == 0
            ? three.Vector3(i * .25, 0, 1.5)
            : three.Vector3(1.5, 0, i * .25);
        _placeSegment(line, start, end, .0018);
        _guide.add(line);
      }
    }
    _three.scene.add(_guide);
  }

  three.Vector3? _point(List<List<double>?>? positions, int j) {
    if (positions == null || j >= positions.length) return null;
    final p = positions[j];
    if (p == null || p.length < 3 || !p.take(3).every((v) => v.isFinite)) {
      return null;
    }
    return three.Vector3(p[0], p[1], p[2]);
  }

  bool _warn(int j) =>
      j < widget.jointWarnings.length && widget.jointWarnings[j];

  void _placeSegment(
    three.Mesh mesh,
    three.Vector3? a,
    three.Vector3? b,
    double radius,
  ) {
    if (a == null || b == null) {
      mesh.visible = false;
      return;
    }
    final delta = b.clone().sub(a);
    final length = delta.length;
    if (!length.isFinite || length < 1e-7) {
      mesh.visible = false;
      return;
    }
    mesh.visible = true;
    mesh.position.setFrom(a.clone().add(b).scale(.5));
    mesh.scale.setValues(radius, length, radius);
    mesh.quaternion.setFromUnitVectors(
      three.Vector3(0, 1, 0),
      delta.scale(1 / length),
    );
  }

  // 테이퍼 사지 배치: 반경은 geom 에 baked 되어 있으므로 길이만(그리고 bodyScale 만) 스케일.
  void _placeLimb(three.Mesh mesh, three.Vector3? a, three.Vector3? b) {
    if (a == null || b == null) {
      mesh.visible = false;
      return;
    }
    final delta = b.clone().sub(a);
    final length = delta.length;
    if (!length.isFinite || length < 1e-7) {
      mesh.visible = false;
      return;
    }
    mesh.visible = true;
    mesh.position.setFrom(a.clone().add(b).scale(.5));
    mesh.scale.setValues(_scale, length, _scale);
    mesh.quaternion.setFromUnitVectors(
      three.Vector3(0, 1, 0),
      delta.scale(1 / length),
    );
  }

  // 단일 Lathe 몸통을 골반→어깨 척추축에 세운다. basis: 로컬 +Y=up, +Z=forward 로 매핑하는 기저.
  // (앞뒤는 _torsoFlatten 으로 눌러 사람 단면처럼.)
  void _placeLatheTorso(
    three.Vector3 shoulders,
    three.Vector3 hips,
    three.Quaternion basis,
  ) {
    final spineLen = shoulders.clone().sub(hips).length;
    if (!widget.torsoVisible || !spineLen.isFinite || spineLen < 1e-6) {
      _torso.visible = false;
      return;
    }
    _torso.visible = true;
    _torso.position.setFrom(hips);
    _torso.scale.setValues(_scale, spineLen, _scale * _torsoFlatten);
    _torso.quaternion.setFrom(basis);
  }

  // 배트를 양 손목 중점(그립)에서 팔뚝 평균 방향으로 뻗어 배치(손 추정 방식).
  void _placeBat(List<three.Vector3?> p) {
    _bat.visible = false;
    _batKnob.visible = false;
    final lw = p[4], rw = p[5];
    if (lw == null || rw == null) return;
    final grip = lw.clone().add(rw).scale(.5);
    // 팔뚝 방향(손목 - 팔꿈치)의 평균. 결측 팔은 건너뛴다.
    final dir = three.Vector3(0, 0, 0);
    if (p[2] != null) {
      final la = lw.clone().sub(p[2]!);
      if (la.length > 1e-6) dir.add(la.normalize());
    }
    if (p[3] != null) {
      final ra = rw.clone().sub(p[3]!);
      if (ra.length > 1e-6) dir.add(ra.normalize());
    }
    if (dir.length < 1e-5) return;
    dir.normalize();
    // 배트 길이는 어깨폭에 비례(실제 배트 ≈ 어깨폭 2.3배).
    final shoulderW = (p[0] != null && p[1] != null)
        ? p[0]!.distanceTo(p[1]!)
        : .35;
    final len = (2.3 * shoulderW).clamp(.40, 1.20).toDouble();
    final barrel = grip.clone().addScaled(dir, len);
    final knobEnd = grip.clone().addScaled(dir, -.05);
    final center = knobEnd.clone().add(barrel).scale(.5);
    _bat.visible = true;
    _bat.position.setFrom(center);
    _bat.scale.setValues(_scale, knobEnd.distanceTo(barrel), _scale);
    _bat.quaternion.setFromUnitVectors(three.Vector3(0, 1, 0), dir);
    _batKnob.visible = true;
    _batKnob.position.setFrom(knobEnd);
    _batKnob.scale.setValues(.03 * _scale, .03 * _scale, .03 * _scale);
    // 양손 그립: 배트를 쥔 양손을 그립(손목 중점)으로 모아 손잡이에 포개 쥐게 한다.
    for (final hand in _hands) {
      if (!hand.visible) continue;
      hand.position.addScaled(grip.clone().sub(hand.position), .5);
    }
  }

  void _syncScene() {
    if (!_sceneBuilt || !mounted) return;
    final p = List.generate(12, (j) => _point(widget.positions, j));
    final raw = List.generate(12, (j) => _point(widget.rawPositions, j));
    for (var j = 0; j < 12; j++) {
      final mesh = _joints[j];
      mesh.visible = p[j] != null;
      if (p[j] != null) {
        mesh.position.setFrom(p[j]!);
        final radius = _jointRadii[j] * _scale;
        mesh.scale.setValues(radius, radius, radius);
        mesh.material = _warn(j) ? _warning : _ivory;
      }
      _rawJoints[j].visible = raw[j] != null;
      if (raw[j] != null) {
        _rawJoints[j].position.setFrom(raw[j]!);
        _rawJoints[j].scale.setValues(
          .024 * _scale,
          .024 * _scale,
          .024 * _scale,
        );
      }
    }
    for (var j = 0; j < _edges.length; j++) {
      final (a, b, _) = _edges[j];
      _placeLimb(_limbs[j], p[a], p[b]);
      _limbs[j].visible =
          _limbs[j].visible &&
          (widget.edgeVisible == null || widget.edgeVisible![j]);
      // 몸통이 Lathe 로 그려질 때는 어깨선·몸통옆·골반 뼈(0,5,6,7)를 숨겨
      // compare3d 처럼 매끈한 단일 몸통만 보이게 한다.
      if (widget.torsoVisible && _torsoEdges.contains(j)) {
        _limbs[j].visible = false;
      }
      _limbs[j].material = _warn(a) || _warn(b) ? _warning : _cyan;
      _placeSegment(_rawLimbs[j], raw[a], raw[b], .012 * _scale);
    }
    _syncTorsoAndEstimates(p);
    if (widget.showEstimates) {
      _placeBat(p);
    } else {
      _bat.visible = false;
      _batKnob.visible = false;
    }
    if (!widget.torsoVisible) {
      _torso.visible = false;
      _pelvis.visible = false;
      _head.visible = false;
      _neck.visible = false;
    }
    if (widget.edgeVisible != null) {
      _hands[0].visible = _hands[0].visible && widget.edgeVisible![2];
      _hands[1].visible = _hands[1].visible && widget.edgeVisible![4];
    }
    _guide.scale.setValues(_scale, _scale, _scale);
    _guide.position.y = -1.05 * _scale;
    _syncCamera();
    if (widget.onDiagnostics != null) {
      final headForward = three.Vector3(
        0,
        0,
        1,
      ).applyQuaternion(_head.quaternion);
      widget.onDiagnostics!({
        'joint_world_positions': [
          for (final j in _joints)
            j.visible ? [j.position.x, j.position.y, j.position.z] : null,
        ],
        'head_forward': [headForward.x, headForward.y, headForward.z],
        'head_front_features_visible': _face[0].visible,
        'nose_position': _face[0].visible
            ? [_face[0].position.x, _face[0].position.y, _face[0].position.z]
            : null,
        'head_center': _head.visible
            ? [_head.position.x, _head.position.y, _head.position.z]
            : null,
        'head_visible': _head.visible,
        'head_policy_mode': widget.headPose?['mode'] ?? 'H0',
        'edge_visible': [for (final limb in _limbs) limb.visible],
        'torso_visible': _torso.visible,
        'feet_visible': [for (final f in _feet) f.visible],
        'foot_forward': [
          for (final f in _feet)
            (() {
              final v = three.Vector3(0, 0, 1).applyQuaternion(f.quaternion);
              return [v.x, v.y, v.z];
            })(),
        ],
        'camera': {
          'yaw': widget.yaw,
          'pitch': widget.pitch,
          'distance': widget.distance,
          'target_y': widget.cameraTargetY,
          'position': [
            _camera.position.x,
            _camera.position.y,
            _camera.position.z,
          ],
        },
      });
    }
  }

  three.Vector3? _orientationAxis(dynamic frame, String name) {
    if (frame is! Map || frame[name] == null) return null;
    return _point([frame[name]], 0);
  }

  three.Quaternion? _orientationBasis(dynamic frame) {
    final x = _orientationAxis(frame, 'x');
    final up = _orientationAxis(frame, 'up');
    final forward = _orientationAxis(frame, 'forward');
    if (x == null || up == null || forward == null) return null;
    return three.Quaternion().setFromRotationMatrix(
      three.Matrix4().makeBasis(x, up, forward),
    );
  }

  void _syncTorsoAndEstimates(List<three.Vector3?> p) {
    for (final mesh in [
      _torso,
      _pelvis,
      _head,
      _neck,
      ..._hands,
      ..._feet,
      ..._face,
      ..._axisLines,
      ..._axisTips,
    ]) {
      mesh.visible = false;
    }
    final orientation = widget.orientation;
    if (orientation == null) {
      // Preserve original/P0 geometry with the same shared display palette.
      _torso.material = _ivory;
      _pelvis.material = _cyan;
      _head.material = _headColor;
      for (final foot in _feet) {
        foot.material = _estimated;
      }
      _syncLegacyTorsoAndEstimates(p);
      return;
    }
    final sf = _orientationAxis(orientation['shoulder'], 'forward');
    final pf = _orientationAxis(orientation['pelvis'], 'forward');
    final up = _orientationAxis(orientation['shoulder'], 'up');
    final sx = _orientationAxis(orientation['shoulder'], 'x');
    final sq = _orientationBasis(orientation['shoulder']);
    final pq = _orientationBasis(orientation['pelvis']);
    if (p[0] != null &&
        p[1] != null &&
        p[6] != null &&
        p[7] != null &&
        sf != null &&
        pf != null &&
        up != null &&
        sx != null &&
        sq != null &&
        pq != null) {
      final shoulders = p[0]!.clone().add(p[1]!).scale(.5);
      final hips = p[6]!.clone().add(p[7]!).scale(.5);
      // 측정된 어깨 기저(로컬 +Y=up, +Z=forward)에 매끈한 Lathe 몸통을 세운다.
      _placeLatheTorso(shoulders, hips, sq);
      _torso.material = orientation['body_mode'] == 'directional'
          ? _ivory
          : _neutralColor;
      // 골반은 단일 몸통 프로파일(아래가 넓음)에 포함되므로 별도 구를 숨긴다.
      _pelvis.visible = false;
      if (widget.showEstimates && widget.torsoVisible) {
        final headCenter = shoulders.clone().addScaled(up, .200 * _scale);
        _head.visible = true;
        _head.position.setFrom(headCenter);
        _head.scale.setValues(.090 * _scale, .114 * _scale, .090 * _scale);
        final suppliedAxes = widget.headPose?['axes'];
        final headAxes = validHeadAxes(suppliedAxes) ? suppliedAxes : null;
        final hq = _orientationBasis(headAxes) ?? sq;
        final hf = _orientationAxis(headAxes, 'forward') ?? sf;
        final hx = _orientationAxis(headAxes, 'x') ?? sx;
        final hu = _orientationAxis(headAxes, 'up') ?? up;
        // The supplied basis already maps local +Z to the chosen world head
        // forward. Applying the shoulder rotation again would rotate twice.
        _head.quaternion.setFrom(hq);
        final directional = widget.headPose == null
            ? orientation['head_mode'] == 'torso_proxy'
            : widget.headPose!['display_features'] == true && headAxes != null;
        _head.material = directional ? _headColor : _neutralColor;
        _placeSegment(
          _neck,
          shoulders,
          shoulders.clone().addScaled(up, .13 * _scale),
          .044 * _scale,
        );
        if (directional && _showFaceFeatures) {
          for (var i = 0; i < 4; i++) {
            _face[i].visible = true;
            _face[i].quaternion.setFrom(hq);
          }
          _face[0].position.setFrom(
            headCenter.clone().addScaled(hf, .108 * _scale),
          );
          _face[0].scale.setValues(.024 * _scale, .024 * _scale, .040 * _scale);
          for (var i = 1; i <= 2; i++) {
            _face[i].position.setFrom(
              headCenter
                  .clone()
                  .addScaled(hf, .092 * _scale)
                  .addScaled(hx, (i == 1 ? 1 : -1) * .038 * _scale)
                  .addScaled(hu, .027 * _scale),
            );
            _face[i].scale.setValues(
              .012 * _scale,
              .014 * _scale,
              .012 * _scale,
            );
          }
          _face[3].position.setFrom(
            headCenter.clone().addScaled(hf, -.098 * _scale),
          );
          _face[3].scale.setValues(.044 * _scale, .063 * _scale, .014 * _scale);
        }
      }
      if (widget.showAxes) {
        for (var i = 0; i < 2; i++) {
          final start = i == 0 ? shoulders : hips;
          final forward = i == 0 ? sf : pf;
          final end = start.clone().addScaled(forward, .38 * _scale);
          _placeSegment(_axisLines[i], start, end, .009 * _scale);
          _axisTips[i].visible = true;
          _axisTips[i].position.setFrom(end);
          _axisTips[i].scale.setValues(
            .025 * _scale,
            .025 * _scale,
            .025 * _scale,
          );
        }
      }
    }
    if (!widget.showEstimates) return;
    for (var side = 0; side < 2; side++) {
      final elbow = p[2 + side], wrist = p[4 + side];
      if (elbow != null && wrist != null && wrist.distanceTo(elbow) > 1e-6) {
        final direction = wrist.clone().sub(elbow).normalize();
        final hand = _hands[side];
        hand.visible = true;
        hand.position.setFrom(
          wrist.clone().addScaled(direction, .055 * _scale),
        );
        hand.scale.setValues(.042 * _scale, .072 * _scale, .028 * _scale);
        hand.quaternion.setFromUnitVectors(three.Vector3(0, 1, 0), direction);
      }
      final ankle = p[10 + side];
      final footData = orientation['feet'][side] as Map<String, dynamic>;
      if (ankle == null || footData['mode'] == 'missing') continue;
      final foot = _feet[side];
      foot.visible = true;
      final direction = _point([footData['direction']], 0);
      final fq = _orientationBasis(footData['axes']);
      if (footData['mode'] == 'directional' &&
          direction != null &&
          fq != null) {
        foot.position.setFrom(
          ankle.clone().addScaled(direction, .065 * _scale),
        );
        foot.position.y -= .025 * _scale;
        foot.scale.setValues(.055 * _scale, .040 * _scale, .14 * _scale);
        foot.quaternion.setFrom(fq);
        foot.material = _directionColor;
      } else {
        foot.position.setFrom(ankle);
        foot.scale.setValues(.055 * _scale, .040 * _scale, .055 * _scale);
        foot.quaternion.identity();
        foot.material = _neutralColor;
      }
    }
  }

  void _syncLegacyTorsoAndEstimates(List<three.Vector3?> p) {
    _torso.visible = false;
    _pelvis.visible = false;
    _head.visible = false;
    _neck.visible = false;
    for (final mesh in [..._hands, ..._feet]) {
      mesh.visible = false;
    }
    three.Vector3? forward;
    three.Quaternion? basis;
    if (p[0] != null && p[1] != null && p[6] != null && p[7] != null) {
      final shoulders = p[0]!.clone().add(p[1]!).scale(.5);
      final hips = p[6]!.clone().add(p[7]!).scale(.5);
      final up = shoulders.clone().sub(hips);
      final across = p[1]!.clone().sub(p[0]!);
      if (up.length > 1e-6 && across.length > 1e-6) {
        up.normalize();
        final normal = across.clone().cross(up);
        if (normal.length > 1e-6) {
          normal.normalize();
          final right = up.clone().cross(normal).normalize();
          forward = normal;
          basis = three.Quaternion().setFromRotationMatrix(
            three.Matrix4().makeBasis(right, up, normal),
          );
          _placeLatheTorso(shoulders, hips, basis);
          _torso.material = [0, 1, 6, 7].any(_warn) ? _warning : _ivory;
          // 골반구는 단일 Lathe 몸통에 포함되므로 숨긴다.
          _pelvis.visible = false;
          if (widget.showEstimates) {
            _head.visible = true;
            _head.position.setFrom(
              shoulders.clone().addScaled(up, .200 * _scale),
            );
            _head.scale.setValues(.090 * _scale, .114 * _scale, .090 * _scale);
            _head.quaternion.setFrom(basis);
            _placeSegment(
              _neck,
              shoulders,
              shoulders.clone().addScaled(up, .13 * _scale),
              .044 * _scale,
            );
          }
        }
      }
    }
    if (!widget.showEstimates) return;
    for (var side = 0; side < 2; side++) {
      final elbow = p[2 + side];
      final wrist = p[4 + side];
      if (elbow != null && wrist != null && wrist.distanceTo(elbow) > 1e-6) {
        final direction = wrist.clone().sub(elbow).normalize();
        final hand = _hands[side];
        hand.visible = true;
        hand.position.setFrom(
          wrist.clone().addScaled(direction, .055 * _scale),
        );
        hand.scale.setValues(.042 * _scale, .072 * _scale, .028 * _scale);
        hand.quaternion.setFromUnitVectors(three.Vector3(0, 1, 0), direction);
      }
      final ankle = p[10 + side];
      if (ankle != null && forward != null && basis != null) {
        final foot = _feet[side];
        foot.visible = true;
        foot.position.setFrom(ankle.clone().addScaled(forward, .065 * _scale));
        foot.position.y -= .025 * _scale;
        foot.scale.setValues(.055 * _scale, .040 * _scale, .14 * _scale);
        foot.quaternion.setFrom(basis);
      }
    }
  }

  void _syncCamera() {
    final yaw = widget.yaw.isFinite ? widget.yaw : 0.45;
    final pitch = widget.pitch.isFinite ? widget.pitch.clamp(-1.35, 1.35) : .12;
    final distance = widget.distance.isFinite
        ? widget.distance.clamp(.5, 20.0)
        : 3.6;
    final target = three.Vector3(0, widget.cameraTargetY, 0);
    _camera.position.setValues(
      math.sin(yaw) * math.cos(pitch) * distance,
      target.y + math.sin(pitch) * distance,
      math.cos(yaw) * math.cos(pitch) * distance,
    );
    _camera.lookAt(target);
    if (_three.screenSize != null && _three.height > 0) {
      _camera.aspect = _three.width / _three.height;
      _camera.updateProjectionMatrix();
    }
  }

  void _handleReady() {
    if (!mounted) return;
    _startupTimer?.cancel();
    _syncScene();
    setState(() => _error = null);
    widget.onReady?.call();
  }

  void _handleError(String message) {
    if (!mounted || _error != null) return;
    _startupTimer?.cancel();
    setState(() => _error = message);
    widget.onError?.call(message);
  }

  @override
  void didUpdateWidget(covariant MannequinView oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncScene();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = Size(constraints.maxWidth, constraints.maxHeight);
        if (!size.width.isFinite ||
            !size.height.isFinite ||
            size.width <= 0 ||
            size.height <= 0) {
          return const SizedBox.shrink();
        }
        if (_lastSize != size) {
          final wasSized = _lastSize != null;
          _lastSize = size;
          if (wasSized) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _three.didChangeMetrics();
            });
          }
        }
        return ClipRect(
          child: MediaQuery(
            data: MediaQuery.of(context).copyWith(size: size),
            child: Stack(
              fit: StackFit.expand,
              children: [
                _three.build(),
                if (_error != null)
                  ColoredBox(
                    color: const Color(0xF0101C2B),
                    child: Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          '3D 렌더러를 시작하지 못했습니다.\n$_error',
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Color(0xFFFFCA86)),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  @override
  void dispose() {
    _startupTimer?.cancel();
    _three.dispose();
    // Materials not currently assigned after a warning toggle still need release.
    for (final material in _materials) {
      material.dispose();
    }
    super.dispose();
  }
}

/// Report platform/GPU failures through the embedding UI instead of a silent
/// loading spinner. No package cache modifications or fallback fake 3D view.
class _ReportingThreeJS extends three.ThreeJS {
  _ReportingThreeJS({
    required this.onFailure,
    required super.setup,
    required super.onSetupComplete,
    required super.settings,
    super.loadingWidget,
  });

  final ValueChanged<String> onFailure;

  @override
  Future<void> initPlatformState() async {
    try {
      await super.initPlatformState();
    } catch (error) {
      onFailure(error.toString());
    }
  }

  @override
  Future<void> animate(Duration duration) async {
    try {
      await super.animate(duration);
    } catch (error) {
      onFailure(error.toString());
    }
  }
}
