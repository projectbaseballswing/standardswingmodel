import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';
// 모드 전환(P0 비교) 검증 보류로 현재 미사용 — 토글 복구 시 함께 복구.
// import 'package:swing_analysis/features/swing_3d/domain/stabilizer.dart';
import 'synthetic_pose_fixture.dart';
import 'package:swing_analysis/features/swing_3d/swing_3d_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late SwingSceneState scene;
  late SwingClip clip;
  var created = 0, disposed = 0;

  Future<void> open(WidgetTester tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1100, 1100);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    // Asset bundle decoding uses real asynchronous work; keep it outside the
    // widget fake clock before testing the timestamp-driven player.
    clip = await loadSyntheticClip();
    created = disposed = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Swing3dScreen(
          loader: () async => clip,
          sceneBuilder: (_, value) {
            scene = value;
            return _Scene(
              onReady: value.onReady,
              onCreate: () => created++,
              onDispose: () => disposed++,
            );
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> seek(WidgetTester tester, int index) async {
    tester
        .widget<Slider>(find.byKey(const Key('swing-3d-timeline')))
        .onChanged!(clip.timestamps[index]);
    await tester.pump();
  }

  testWidgets(
    'synthetic final mode passes S2, P2, O1, F1 and H4 at all timestamps',
    (tester) async {
      await open(tester);
      final motion = clip.finalMotion!;
      expect(find.textContaining('분석 좌표 · Synthetic left60'), findsOneWidget);
      expect(find.textContaining('개선 P2 + O1 + F1 + S2 + H4'), findsOneWidget);
      expect(scene.mode, SwingDisplayMode.improved);
      for (var i = 0; i < clip.frameCount; i++) {
        await seek(tester, i);
        // 표시 좌표 = S2 소스에 표시 전용 ±N 가우시안 평활(결측 보존)을 얹은 값.
        final expectedPositions = gaussianSmoothedPositions(
          motion.positionsAt,
          i,
          clip.frameCount,
          kDefaultSwingSmoothWindow,
        ).map((p) => p?.toList()).toList();
        expect(scene.positions, expectedPositions);
        expect(
          scene.orientation,
          gaussianSmoothedOrientation(
            motion.directional.frameAt,
            i,
            clip.frameCount,
            kDefaultSwingSmoothWindow,
          ),
        );
        expect(scene.headPose, motion.headAt(i));
        expect(scene.edgeVisible, motion.directional.edgesAt(i));
        expect(scene.torsoVisible, motion.directional.torsoAt(i));
        expect(scene.bodyScale, motion.referenceScale);
        expect(scene.distance, closeTo(3.6 * motion.referenceScale, 1e-12));
        expect(
          scene.cameraTargetY,
          closeTo(-.1 * motion.referenceScale, 1e-12),
        );
      }
      expect(created, 1);
      expect(disposed, 0);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'frame 54, 71 and 89 head stays world-fixed under orbit and zoom; raw/P0 retained',
    (tester) async {
      await open(tester);
      // 모드 전환 검증용(P0 비교) — 토글 복구 시 함께 복구.
      // final p0 = PoseStabilizer(clip);
      for (final index in [54, 71, 89]) {
        await seek(tester, index);
        final head = scene.headPose;
        final body = scene.positions;
        final yaw = scene.yaw;
        await tester.drag(
          find.byKey(const Key('swing-3d-orbit')),
          const Offset(65, 20),
        );
        await tester.pump();
        expect(scene.yaw, isNot(yaw));
        expect(scene.headPose, head);
        expect(scene.positions, body);
        await tester.tap(find.byTooltip('확대'));
        await tester.pump();
        expect(scene.headPose, head);
        // 모드 토글 보류(S2 단일 표시)로 P0/원본/개선 전환 검증은 일시 중단.
        // 토글 복구 시 camera 캡처와 아래 전환 검증 블록을 함께 복구할 것.
        // final camera = [
        //   scene.yaw, scene.pitch, scene.distance, scene.cameraTargetY,
        // ];
        // await tester.tap(find.text('안정화 P0').first);
        // await tester.pump();
        // expect([scene.yaw, scene.pitch, scene.distance, scene.cameraTargetY], camera);
        // expect(scene.headPose, isNull);
        // expect(scene.positions,
        //     p0.frameAt(index).positions.map((p) => p?.toList()).toList());
        // await tester.tap(find.text('원본 좌표').first);
        // await tester.pump();
        // expect([scene.yaw, scene.pitch, scene.distance, scene.cameraTargetY], camera);
        // expect(scene.headPose, isNull);
        // expect(scene.positions,
        //     p0.frameAt(index).rawPositions.map((p) => p?.toList()).toList());
        // await tester.tap(find.text('개선 시연').first);
        // await tester.pump();
        // expect([scene.yaw, scene.pitch, scene.distance, scene.cameraTargetY], camera);
        // expect(scene.headPose, head);
        // expect(scene.positions, body);
      }
      expect(created, 1);
      expect(disposed, 0);
    },
  );

  testWidgets(
    'final animation uses elapsed timestamps and speed; seek, pause and dispose are deterministic',
    (tester) async {
      await open(tester);
      tester
          .widget<DropdownButton<double>>(
            find.byKey(const Key('swing-3d-speed')),
          )
          .onChanged!(.5);
      await tester.pump();
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.textContaining('프레임 15 / 99'), findsOneWidget);
      await seek(tester, 71);
      expect(find.text('재생'), findsOneWidget);
      final head = scene.headPose;
      await tester.pump(const Duration(seconds: 1));
      expect(scene.headPose, head);
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      await tester.pump(const Duration(seconds: 2));
      expect(find.textContaining('프레임 99 / 99'), findsOneWidget);
      expect(find.text('재생'), findsOneWidget);
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      expect(find.textContaining('프레임 0 / 99'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      expect(disposed, 1);
      await tester.pump(const Duration(seconds: 1));
      expect(tester.takeException(), isNull);
    },
  );
}

class _Scene extends StatefulWidget {
  const _Scene({
    required this.onReady,
    required this.onCreate,
    required this.onDispose,
  });
  final VoidCallback onReady, onCreate, onDispose;
  @override
  State<_Scene> createState() => _SceneState();
}

class _SceneState extends State<_Scene> {
  @override
  void initState() {
    super.initState();
    widget.onCreate();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onReady();
    });
  }

  @override
  Widget build(BuildContext context) => const ColoredBox(color: Colors.black);
  @override
  void dispose() {
    widget.onDispose();
    super.dispose();
  }
}
