import 'dart:async';
import 'dart:convert';
import 'synthetic_pose_fixture.dart';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/auth_api.dart';
import 'package:swing_analysis/api/pose_3d_api.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/features/swing_3d/user_swing_3d_screen.dart';
import 'package:swing_analysis/features/swing_3d/rendering/mannequin_style.dart';

Map<String, dynamic> userPacket({
  String id = 'own-analysis',
  String user = 'owner',
}) {
  final clip = syntheticClipJson();
  clip['id'] = id;
  clip['title'] = '업로드 영상';
  clip['data_kind'] = 'analysis';
  clip['analysis_id'] = id;
  clip['orientation_data']['binding']['clip_id'] = id;
  clip['final_display_data']['binding']['clip_id'] = id;
  return {
    'analysis_id': id,
    'user_id': user,
    'status': 'ready',
    'contract_version': 'EXP008-pose3d-v1',
    'frame_count': 100,
    'handedness': 'left',
    'warnings': ['가림 관절 검토 필요'],
    'clip': clip,
  };
}

http.Response response(dynamic body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void main() {
  setUp(
    () => Session.instance.signIn(
      'owner',
      accessToken: 'test-server-issued-token',
    ),
  );
  tearDown(Session.instance.clear);

  test(
    'real login requires server token, and token expires or clears',
    () async {
      final api = AuthApi(
        client: MockClient(
          (r) async => response({
            'success': true,
            'user': 'owner',
            'access_token': 'opaque-token',
            'token_type': 'bearer',
            'expires_in': 28800,
          }),
        ),
      );
      final result = await api.login(id: 'owner', password: 'password');
      Session.instance.signIn(
        result.userId,
        accessToken: result.accessToken,
        expiresIn: result.expiresIn,
      );
      expect(Session.instance.authorizationHeaders, {
        'Authorization': 'Bearer opaque-token',
      });
      Session.instance.signIn('owner', accessToken: 'expired', expiresIn: -1);
      expect(Session.instance.isLoggedIn, isFalse);
      expect(Session.instance.authorizationHeaders, isEmpty);
      final legacy = AuthApi(
        client: MockClient(
          (r) async => response({'success': true, 'user': 'owner'}),
        ),
      );
      await expectLater(
        legacy.login(id: 'owner', password: 'password'),
        throwsA(isA<ApiException>()),
      );
      api.dispose();
      legacy.dispose();
    },
  );

  test(
    'pose request binds Bearer owner, exact analysis ID and actual data kind',
    () async {
      final api = Pose3dApi(
        client: MockClient((r) async {
          expect(r.url.path, '/api/analyses/own-analysis/pose-3d');
          expect(r.headers['Authorization'], 'Bearer test-server-issued-token');
          expect(r.url.queryParameters, isEmpty);
          return response(userPacket());
        }),
      );
      final loaded = await api.fetch('own-analysis');
      expect(loaded.clip!.analysisId, 'own-analysis');
      expect(loaded.clip!.isSample, isFalse);
      expect(loaded.clip!.finalMotion, isNotNull);
      expect(loaded.warnings, ['가림 관절 검토 필요']);
      api.dispose();
    },
  );

  test(
    'missing or expired session never sends an unauthenticated pose request',
    () async {
      var requests = 0;
      final api = Pose3dApi(
        client: MockClient((r) async {
          requests++;
          return response(userPacket());
        }),
      );
      Session.instance.clear();
      await expectLater(
        api.fetch('own-analysis'),
        throwsA(
          isA<Pose3dException>().having(
            (e) => e.code,
            'code',
            'unauthenticated',
          ),
        ),
      );
      expect(requests, 0);
      api.dispose();
    },
  );

  test(
    'forbidden, missing, processing and failed do not fall back to sample',
    () async {
      for (final status in [401, 403, 404, 422, 503]) {
        final api = Pose3dApi(
          client: MockClient(
            (r) async =>
                response({'detail': 'server-private-path token'}, status),
          ),
        );
        await expectLater(
          api.fetch('own-analysis'),
          throwsA(
            isA<Pose3dException>().having(
              (e) => e.message,
              'safe',
              isNot(contains('server-private-path')),
            ),
          ),
        );
        api.dispose();
      }
      for (final state in ['pending', 'processing']) {
        final api = Pose3dApi(
          client: MockClient(
            (r) async => response({
              'analysis_id': 'own-analysis',
              'user_id': 'owner',
              'status': state,
              'contract_version': 'EXP008-pose3d-v1',
            }, 202),
          ),
        );
        final result = await api.fetch('own-analysis');
        expect(result.pending, isTrue);
        expect(result.clip, isNull);
        api.dispose();
      }
    },
  );

  test(
    'wrong analysis, owner, sample, contract and missing final data are rejected',
    () async {
      for (final mutate in <void Function(Map<String, dynamic>)>[
        (p) => p['analysis_id'] = 'other',
        (p) => p['user_id'] = 'other',
        (p) => p['contract_version'] = 'wrong',
        (p) => p['clip']['data_kind'] = 'sample',
        (p) => p['clip']['analysis_id'] = 'other',
        (p) => p['clip'].remove('final_display_data'),
        (p) => p['frame_count'] = 99,
      ]) {
        final packet = userPacket();
        mutate(packet);
        final api = Pose3dApi(
          client: MockClient((r) async => response(packet)),
        );
        await expectLater(
          api.fetch('own-analysis'),
          throwsA(
            isA<Pose3dException>().having(
              (e) => e.code,
              'code',
              'invalid_response',
            ),
          ),
        );
        api.dispose();
      }
    },
  );

  test('response arriving after account change is never displayed', () async {
    final gate = Completer<http.Response>();
    final api = Pose3dApi(client: MockClient((r) => gate.future));
    final pending = api.fetch('own-analysis');
    Session.instance.signIn('other', accessToken: 'other-token');
    gate.complete(response(userPacket()));
    await expectLater(
      pending,
      throwsA(
        isA<Pose3dException>().having((e) => e.code, 'code', 'session_changed'),
      ),
    );
    api.dispose();
  });

  testWidgets(
    'processing then own clip renders with no sample label and polling stops on dispose',
    (tester) async {
      var calls = 0;
      final api = Pose3dApi(
        client: MockClient((r) async {
          calls++;
          return calls == 1
              ? response({
                  'analysis_id': 'own-analysis',
                  'user_id': 'owner',
                  'status': 'processing',
                  'contract_version': 'EXP008-pose3d-v1',
                }, 202)
              : response(userPacket());
        }),
      );
      tester.view.physicalSize = const Size(1100, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: UserSwing3dScreen(
            analysisId: 'own-analysis',
            api: api,
            pollInterval: const Duration(milliseconds: 100),
            sceneBuilder: (_, scene) {
              WidgetsBinding.instance.addPostFrameCallback(
                (_) => scene.onReady(),
              );
              return const ColoredBox(color: Colors.black);
            },
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('3D 스윙을 생성'), findsOneWidget);
      expect(find.textContaining('권동진'), findsNothing);
      await tester.pump(const Duration(milliseconds: 110));
      await tester.pumpAndSettle();
      expect(find.text('분석 좌표 · 업로드 영상'), findsOneWidget);
      expect(find.textContaining('샘플 시연'), findsNothing);
      expect(find.byKey(const Key('swing-3d-play')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 5));
      expect(calls, 2);
      api.dispose();
    },
  );

  testWidgets('logout removes already displayed own coordinates', (
    tester,
  ) async {
    final api = Pose3dApi(
      client: MockClient((r) async => response(userPacket())),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: UserSwing3dScreen(
          analysisId: 'own-analysis',
          api: api,
          sceneBuilder: (_, scene) => const SizedBox(height: 200),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('swing-3d-mode')), findsOneWidget);
    Session.instance.clear();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('swing-3d-mode')), findsNothing);
    expect(find.textContaining('로그인 세션이 없습니다'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    api.dispose();
  });

  test(
    'palette has high body/head/direction contrast on shared background',
    () {
      double luminance(int rgb) {
        double f(int shift) {
          final s = ((rgb >> shift) & 255) / 255;
          return s <= .04045
              ? s / 12.92
              : math.pow((s + .055) / 1.055, 2.4).toDouble();
        }

        return .2126 * f(16) + .7152 * f(8) + .0722 * f(0);
      }

      for (final value in [
        MannequinStyle.body,
        MannequinStyle.head,
        MannequinStyle.direction,
        MannequinStyle.inactive,
      ]) {
        expect(
          (luminance(value) + .05) /
              (luminance(MannequinStyle.background) + .05),
          greaterThan(4.5),
        );
      }
      expect(
        luminance(MannequinStyle.head),
        greaterThan(luminance(MannequinStyle.body)),
      );
    },
  );
}
