import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';
import 'package:swing_analysis/features/swing_3d/domain/stabilizer.dart';
import 'synthetic_pose_fixture.dart';
import 'package:swing_analysis/features/swing_3d/swing_3d_screen.dart';

Map<String, dynamic> integratedJson() => syntheticDirectionalJson();

void main() {
  test(
    'all synthetic source frames preserve original joints and timestamp selection',
    () {
      final json = integratedJson();
      final clip = SwingClip.fromJson(json);
      expect(clip.frameCount, 100);
      expect(clip.isSample, isFalse);
      for (var i = 0; i < 100; i++) {
        expect(
          clip.frames[i].positions.map((v) => v?.toList()).toList(),
          json['frames'][i]['positions'],
        );
        expect(
          clip.directional!.clip.frames[i].positions
              .map((v) => v?.toJson())
              .toList(),
          json['frames'][i]['positions'],
        );
        expect(clip.frameIndexAt(clip.timestamps[i]), i);
      }
      for (final n in [71, 89]) {
        final f = clip.directional!.frameAt(n);
        expect(
          f['feet'][0]['direction'],
          isNot(equals(f['feet'][1]['direction'])),
        );
      }
    },
  );

  test(
    'synthetic analysis binds complete final and direction contracts',
    () async {
      TestWidgetsFlutterBinding.ensureInitialized();
      final clip = await loadSyntheticClip();
      expect(clip.directional, isNotNull);
      expect(clip.directional!.hasP2, isTrue);
      expect(clip.frameCount, 100);
      expect(clip.analysisId, 'synthetic-left60');
    },
  );

  test(
    'sidecar identity, coordinate restoration, count and timestamp mismatches reject',
    () {
      for (final mutate in <void Function(Map<String, dynamic>)>[
        (j) => j['orientation_data']['binding']['clip_id'] = 'another',
        (j) => j['orientation_data']['source_provenance']['source_sha256'] =
            'different',
        (j) => j['orientation_data']['source_oriented'] = false,
        (j) => j['orientation_data']['mirrored_input'] = false,
        (j) => j['orientation_data']['handedness'] = 'right',
        (j) => j['orientation_data']['frames'].removeLast(),
        (j) => j['orientation_data']['frames'][1]['timestamp_s'] = .02,
        (j) => j['orientation_data']['frames'][1]['positions'][4][0] += .001,
        (j) => j['orientation_data']['frames'][1].remove('p2'),
        (j) => j['orientation_data']['display_policy']['id'] = 'P0',
      ]) {
        final json = integratedJson();
        mutate(json);
        expect(() => SwingClip.fromJson(json), throwsFormatException);
      }
    },
  );

  test(
    'absent feet fall back independently without changing ankles or knees',
    () {
      final json = integratedJson();
      for (final f in json['orientation_data']['frames']) {
        f.remove('feet');
        f.remove('foot_visibility');
        f.remove('legacy_feet');
      }
      json['orientation_data'].remove('foot_joint_names');
      final clip = SwingClip.fromJson(json);
      expect(clip.directional!.frameAt(71)['feet'].map((f) => f['mode']), [
        'neutral',
        'neutral',
      ]);
      for (final j in [8, 9, 10, 11]) {
        expect(
          clip.frames[71].positions[j]!.toList(),
          json['frames'][71]['positions'][j],
        );
      }
    },
  );

  test(
    'future analysis identity is explicit and never silently becomes sample',
    () {
      final json = integratedJson();
      json['data_kind'] = 'analysis';
      json.remove('analysis_id');
      expect(() => SwingClip.fromJson(json), throwsFormatException);
      json['analysis_id'] = 'new-user-analysis';
      json['id'] = 'new-clip';
      json['title'] = 'new swing';
      json['orientation_data']['binding']['clip_id'] = 'new-clip';
      final clip = SwingClip.fromJson(json);
      expect(clip.isSample, isFalse);
      expect(clip.analysisId, 'new-user-analysis');
      expect(
        clip.directional!.result,
        SwingClip.fromJson(integratedJson()).directional!.result,
      );
      json['data_kind'] = 'sample';
      expect(() => SwingClip.fromJson(json), throwsFormatException);
    },
  );

  test('missing P2 is explicit and does not invent a stabilized policy', () {
    final json = integratedJson();
    for (final f in json['orientation_data']['frames']) {
      f.remove('p2');
    }
    final clip = SwingClip.fromJson(json);
    expect(clip.directional!.hasP2, isFalse);
    expect(clip.directional!.edgesAt(0), isNull);
    expect(clip.directional!.frameAt(0)['head_mode'], 'torso_proxy');
  });

  late SwingSceneState scene;
  late int creations, disposals;
  Future<void> open(WidgetTester tester, {Map<String, dynamic>? json}) async {
    creations = 0;
    disposals = 0;
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1100);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Swing3dScreen(
          loader: () =>
              Future.value(SwingClip.fromJson(json ?? integratedJson())),
          sceneBuilder: (_, s) {
            scene = s;
            return _Scene(
              onReady: s.onReady,
              onCreate: () => creations++,
              onDispose: () => disposals++,
            );
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  void seek(WidgetTester tester, double t) => tester
      .widget<Slider>(find.byKey(const Key('swing-3d-timeline')))
      .onChanged!(t);

  testWidgets(
    'improved default, P0/raw comparison keep frame camera and mounted scene',
    (tester) async {
      await open(tester);
      expect(find.text('분석 좌표 · Synthetic left60'), findsOneWidget);
      final clip = SwingClip.fromJson(integratedJson());
      final p0 = PoseStabilizer(clip);
      expect(scene.mode, SwingDisplayMode.improved);
      expect(scene.orientation, isNotNull);
      await tester.drag(
        find.byKey(const Key('swing-3d-orbit')),
        const Offset(65, 10),
      );
      await tester.pump();
      final yaw = scene.yaw;
      for (final n in [71, 89]) {
        seek(tester, clip.timestamps[n]);
        await tester.pump();
        for (final label in ['안정화 P0', '원본 좌표', '개선 시연']) {
          await tester.tap(find.text(label).first);
          await tester.pump();
          expect(scene.yaw, yaw);
          expect(find.textContaining('프레임 $n / 99'), findsOneWidget);
          final expected = label == '안정화 P0'
              ? p0.frameAt(n).positions
              : label == '원본 좌표'
              ? p0.frameAt(n).rawPositions
              : clip.frames[n].positions;
          expect(scene.positions, expected.map((v) => v?.toList()).toList());
          expect(
            scene.orientation,
            label == '개선 시연' ? clip.directional!.frameAt(n) : null,
          );
        }
      }
      expect(creations, 1);
      expect(disposals, 0);
      await tester.pumpWidget(const SizedBox());
      expect(disposals, 1);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('P2 can omit all connections while 12 observed joints remain', (
    tester,
  ) async {
    final json = integratedJson();
    final f = json['orientation_data']['frames'][0];
    f['p2']['edge_visible'] = List.filled(12, false);
    f['p2']['torso_visible'] = false;
    await open(tester, json: json);
    expect(scene.positions.where((v) => v != null).length, 12);
    expect(scene.edgeVisible, List.filled(12, false));
    expect(scene.torsoVisible, isFalse);
    expect(find.textContaining('몸통 표시 생략'), findsOneWidget);
    expect(find.byKey(const Key('swing-3d-torso-omitted')), findsOneWidget);
    expect(find.byKey(const Key('swing-3d-empty')), findsNothing);
  });

  testWidgets(
    'all missing data is explicit; next valid observation can render',
    (tester) async {
      final json = integratedJson();
      json['frames'][0]['positions'] = List.filled(12, null);
      json['frames'][0]['observed_valid'] = List.filled(12, false);
      json['orientation_data']['frames'][0]['positions'] = List.filled(
        12,
        null,
      );
      await open(tester, json: json);
      expect(find.textContaining('원시 관절 좌표가 없어'), findsOneWidget);
      expect(scene.orientation!['head_mode'], 'neutral');
      expect(scene.positions.every((v) => v == null), isTrue);
      await tester.tap(find.byTooltip('다음 프레임'));
      await tester.pump();
      expect(find.byKey(const Key('swing-3d-empty')), findsNothing);
      expect(scene.positions.every((v) => v != null), isTrue);
    },
  );

  testWidgets(
    'playback speed uses actual timestamps and mode switch does not reset time',
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
      await tester.tap(find.text('안정화 P0').first);
      await tester.pump();
      expect(find.text('일시정지'), findsOneWidget);
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      final label = tester
          .widget<Text>(find.byKey(const Key('swing-3d-frame')))
          .data;
      await tester.pump(const Duration(seconds: 1));
      expect(
        tester.widget<Text>(find.byKey(const Key('swing-3d-frame'))).data,
        label,
      );
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
