import 'dart:async';
import 'dart:convert';
import 'synthetic_pose_fixture.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/features/swing_3d/domain/pose.dart';
import 'package:swing_analysis/features/swing_3d/domain/stabilizer.dart';
import 'package:swing_analysis/features/swing_3d/swing_3d_screen.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'feedback_fixture.dart';

Map<String, dynamic> sampleJson() => syntheticRawJson();

void main() {
  late SwingSceneState scene;
  final clip = SwingClip.fromJson(sampleJson());
  Widget fakeScene(BuildContext context, SwingSceneState value) {
    scene = value;
    WidgetsBinding.instance.addPostFrameCallback((_) => value.onReady());
    return const ColoredBox(color: Colors.black);
  }

  void viewport(WidgetTester tester, {Size size = const Size(430, 960)}) {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = size;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
  }

  Future<void> open(WidgetTester tester, {SwingClipLoader? loader}) async {
    viewport(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: Swing3dScreen(
          loader: loader ?? () async => clip,
          sceneBuilder: fakeScene,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'synthetic observations default to exact P0 and drives playback/seek',
    (tester) async {
      await open(tester);
      expect(find.text('분석 좌표 · Synthetic left60'), findsOneWidget);
      expect(clip.frameCount, 100);
      final p0 = PoseStabilizer(clip);
      expect(
        scene.positions,
        p0.frameAt(0).positions.map((v) => v?.toList()).toList(),
      );
      final original = scene.positions;
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(scene.positions, isNot(equals(original)));
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      final paused = tester
          .widget<Text>(find.byKey(const Key('swing-3d-frame')))
          .data;
      await tester.pump(const Duration(milliseconds: 500));
      expect(
        tester.widget<Text>(find.byKey(const Key('swing-3d-frame'))).data,
        paused,
      );
      tester
          .widget<Slider>(find.byKey(const Key('swing-3d-timeline')))
          .onChanged!(clip.timestamps[71]);
      await tester.pump();
      expect(find.textContaining('프레임 71 / 99'), findsOneWidget);
      await tester.tap(find.text('원본 좌표').first);
      await tester.pump();
      expect(
        scene.positions,
        p0.frameAt(71).rawPositions.map((v) => v?.toList()).toList(),
      );
      await tester.tap(find.byTooltip('다음 프레임'));
      await tester.pump();
      expect(find.textContaining('프레임 72 / 99'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('drag, two-finger pinch, zoom and reset update camera only', (
    tester,
  ) async {
    await open(tester);
    final points = scene.positions;
    final yaw = scene.yaw;
    await tester.drag(
      find.byKey(const Key('swing-3d-orbit')),
      const Offset(70, 20),
    );
    await tester.pump();
    expect(scene.yaw, isNot(yaw));
    final centre = tester.getCenter(find.byKey(const Key('swing-3d-orbit')));
    final first = await tester.startGesture(
      centre - const Offset(25, 0),
      pointer: 1,
    );
    final second = await tester.startGesture(
      centre + const Offset(25, 0),
      pointer: 2,
    );
    final distance = scene.distance;
    await first.moveBy(const Offset(-25, 0));
    await second.moveBy(const Offset(25, 0));
    await tester.pump();
    expect(scene.distance, lessThan(distance));
    await first.up();
    await second.up();
    final zoomed = scene.distance;
    await tester.tap(find.byTooltip('축소'));
    await tester.pump();
    expect(scene.distance, greaterThan(zoomed));
    await tester.tap(find.byTooltip('카메라 초기화'));
    await tester.pump();
    expect(scene.yaw, .25);
    expect(scene.distance, 3.6);
    expect(scene.positions, points);
  });

  testWidgets(
    'P0 all suppression remains explicit and raw switch restores observations',
    (tester) async {
      final json = sampleJson();
      final frame = (json['frames'] as List).first as Map<String, dynamic>;
      frame['image_quality_render']['combined_missing'] = List.filled(12, true);
      await open(tester, loader: () async => SwingClip.fromJson(json));
      expect(scene.positions.where((p) => p != null), isEmpty);
      expect(find.textContaining('안정화 표시 정책이 모든 관절을 생략'), findsOneWidget);
      await tester.tap(find.text('원본 좌표').first);
      await tester.pump();
      expect(scene.positions.where((p) => p != null).length, 12);
      expect(find.byKey(const Key('swing-3d-empty')), findsNothing);
    },
  );

  testWidgets('missing raw frame and invalid root are not renderer failures', (
    tester,
  ) async {
    final json = sampleJson();
    final frame = (json['frames'] as List).first as Map<String, dynamic>;
    frame['positions'] = List.filled(12, null);
    frame['observed_valid'] = List.filled(12, false);
    final noRoot = json['frames'][1] as Map<String, dynamic>;
    noRoot['positions'][6] = null;
    noRoot['observed_valid'][6] = false;
    await open(tester, loader: () async => SwingClip.fromJson(json));
    expect(find.textContaining('원시 관절 좌표가 없어'), findsOneWidget);
    expect(find.byKey(const Key('swing-3d-render-error')), findsNothing);
    await tester.tap(find.byTooltip('다음 프레임'));
    await tester.pump();
    expect(find.textContaining('골반 기준점이 없어'), findsOneWidget);
    expect(scene.positions.where((p) => p != null), isEmpty);
    expect(find.byKey(const Key('swing-3d-render-error')), findsNothing);
    await tester.tap(find.byTooltip('다음 프레임'));
    await tester.pump();
    expect(scene.positions.where((p) => p != null), isNotEmpty);
    expect(find.byKey(const Key('swing-3d-empty')), findsNothing);
  });

  testWidgets('invalid JSON contract and GPU failure disable unsafe playback', (
    tester,
  ) async {
    await open(
      tester,
      loader: () async {
        final json = sampleJson();
        json['frames'].removeLast();
        return SwingClip.fromJson(json);
      },
    );
    expect(find.byKey(const Key('swing-3d-load-error')), findsOneWidget);
    expect(find.byKey(const Key('swing-3d-play')), findsNothing);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      MaterialApp(
        home: Swing3dScreen(loader: () async => clip, sceneBuilder: fakeScene),
      ),
    );
    await tester.pumpAndSettle();
    scene.onError('Synthetic GPU failure');
    await tester.pump();
    expect(find.byKey(const Key('swing-3d-render-error')), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('swing-3d-play')))
          .onPressed,
      isNull,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('backgrounding pauses and disposing during loading is safe', (
    tester,
  ) async {
    await open(tester);
    await tester.tap(find.byKey(const Key('swing-3d-play')));
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    expect(find.text('재생'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(const SizedBox());
    final pending = Completer<SwingClip>();
    await tester.pumpWidget(
      MaterialApp(
        home: Swing3dScreen(
          loader: () => pending.future,
          sceneBuilder: fakeScene,
        ),
      ),
    );
    await tester.pumpWidget(const SizedBox());
    pending.complete(clip);
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'feedback entry and return preserve score, video and old detail buttons',
    (tester) async {
      viewport(tester);
      var requests = 0;
      final repo = FeedbackRepository(
        api: AnalysisApi(
          client: MockClient((request) async {
            requests++;
            expect(request.url.path, '/api/analyses/saved-analysis');
            return http.Response(
              jsonEncode(storedAnalysis()),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        ),
      );
      addTearDown(repo.dispose);
      final router = GoRouter(
        initialLocation: '/analyses/saved-analysis',
        observers: [swingRouteObserver],
        routes: [
          GoRoute(
            path: '/analyses/:id',
            builder: (_, state) => OverallFeedbackScreen(
              analysisId: state.pathParameters['id']!,
              repository: repo,
            ),
          ),
          GoRoute(
            path: '/analyses/:id/pose-3d',
            builder: (_, state) {
              expect(state.pathParameters['id'], 'saved-analysis');
              return Swing3dScreen(
                loader: () async => clip,
                sceneBuilder: fakeScene,
              );
            },
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      await tester.pumpAndSettle();
      expect(find.text('77.3'), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('open-swing-3d')));
      await tester.tap(find.byKey(const Key('open-swing-3d')));
      await tester.pumpAndSettle();
      expect(find.text('분석 좌표 · Synthetic left60'), findsOneWidget);
      await tester.tap(find.byKey(const Key('swing-3d-play')));
      await tester.pump();
      await tester.tap(find.byTooltip('피드백으로 돌아가기'));
      await tester.pumpAndSettle();
      expect(find.text('종합 피드백'), findsOneWidget);
      expect(find.text('77.3'), findsOneWidget);
      expect(find.text('상세 피드백 보기'), findsOneWidget);
      expect(find.text('구간별 피드백 보기'), findsOneWidget);
      expect(requests, 1);
      expect(tester.takeException(), isNull);
    },
  );
}
