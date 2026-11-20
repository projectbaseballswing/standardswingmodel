// Offline review entry point. Not part of the production router or login flow.
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:swing_analysis/api/analysis_api.dart';
import 'package:swing_analysis/data/feedback_repository.dart';
import 'package:swing_analysis/data/session.dart';
import 'package:swing_analysis/models/feedback.dart';
import 'package:swing_analysis/route_observer.dart';
import 'package:swing_analysis/screens/overall_feedback_screen.dart';
import 'package:swing_analysis/screens/joint_analysis_screen.dart';
import 'package:swing_analysis/screens/phase_feedback_screen.dart';
import 'package:swing_analysis/theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    final response = await http.get(Uri.base.resolve('review-fixtures.json'));
    if (response.statusCode != 200) {
      throw StateError('Local fixtures unavailable');
    }
    final rows = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    Session.instance.signIn('offline-language-fixture');
    runApp(ReviewApp(rows: rows.cast<Map<String, dynamic>>()));
  } catch (_) {
    runApp(
      const MaterialApp(
        home: Scaffold(body: Center(child: Text('로컬 검토 자료를 불러오지 못했습니다.'))),
      ),
    );
  }
}

class ReviewApp extends StatefulWidget {
  const ReviewApp({super.key, required this.rows});
  final List<Map<String, dynamic>> rows;
  @override
  State<ReviewApp> createState() => _ReviewAppState();
}

class _ReviewAppState extends State<ReviewApp> {
  late final FeedbackRepository repo;
  late final GoRouter router;
  String selected = 'low_drop';
  @override
  void initState() {
    super.initState();
    repo = FeedbackRepository(
      api: AnalysisApi(
        client: MockClient((request) async {
          final segments = request.url.pathSegments;
          final index = segments.indexOf('analyses');
          final id = index >= 0 && index + 1 < segments.length
              ? segments[index + 1]
              : '';
          final row = widget.rows.where((r) => r['id'] == id).firstOrNull;
          Object data = {'detail': 'Offline review has no source video'};
          var status = 404;
          if (row != null &&
              request.method == 'GET' &&
              !request.url.path.endsWith('/video')) {
            data = request.url.path.endsWith('/comparison')
                ? row['comparison'] ?? {'has_previous': false}
                : row['body'];
            status = 200;
          }
          return http.Response(
            jsonEncode(data),
            status,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      ),
    );
    router = GoRouter(
      initialLocation: '/analyses/low_drop',
      observers: [swingRouteObserver],
      routes: [
        ShellRoute(
          builder: (context, state, child) => Scaffold(
            body: SafeArea(
              child: Column(
                children: [
                  Container(
                    width: double.infinity,
                    color: const Color(0xffe9f2ed),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    child: Column(
                      children: [
                        const Text(
                          '오프라인 문구 검토 · 저장 리포트 + 합성 비교값',
                          style: TextStyle(fontSize: 12),
                        ),
                        DropdownButton<String>(
                          isExpanded: true,
                          value: selected,
                          items: [
                            for (final r in widget.rows)
                              DropdownMenuItem(
                                value: r['id'] as String,
                                child: Text(
                                  r['label'] as String,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                          ],
                          onChanged: (v) {
                            if (v != null) {
                              setState(() => selected = v);
                              router.go('/analyses/$v');
                            }
                          },
                        ),
                      ],
                    ),
                  ),
                  Expanded(child: child),
                ],
              ),
            ),
          ),
          routes: [
            GoRoute(
              path: '/analyses/:id',
              builder: (_, s) => OverallFeedbackScreen(
                analysisId: s.pathParameters['id']!,
                repository: repo,
              ),
            ),
            GoRoute(
              path: '/joint-analysis',
              builder: (_, s) => JointAnalysisScreen(
                feedback: s.extra as OverallFeedback,
                videoBuilder: (_) => const SizedBox(
                  height: 50,
                  child: Center(child: Text('영상 재생은 이번 문구 검토에서 제외')),
                ),
              ),
            ),
            GoRoute(
              path: '/phase-feedback',
              builder: (_, s) => PhaseFeedbackScreen(
                feedback: s.extra as OverallFeedback,
                videoBuilder: () => const SizedBox(
                  height: 50,
                  child: Center(child: Text('영상 재생은 이번 문구 검토에서 제외')),
                ),
              ),
            ),
            GoRoute(path: '/swings', redirect: (_, s) => '/analyses/$selected'),
            GoRoute(
              path: '/analyses/:id/pose-3d',
              builder: (_, s) => const Scaffold(
                body: Center(
                  child: Text('이 화면은 피드백 문구 검토용입니다. 3D는 기존 서비스에서 제공됩니다.'),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  @override
  void dispose() {
    router.dispose();
    repo.dispose();
    Session.instance.clear();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp.router(
    title: '피드백 문구 검토',
    debugShowCheckedModeBanner: false,
    theme: buildAppTheme(),
    routerConfig: router,
  );
}
