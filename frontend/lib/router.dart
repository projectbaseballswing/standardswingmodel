import 'package:go_router/go_router.dart';
import 'features/swing_3d/user_swing_3d_screen.dart';

import 'models/feedback.dart';
import 'route_observer.dart';
import 'screens/joint_analysis_screen.dart';
import 'screens/login_screen.dart';
import 'screens/overall_feedback_screen.dart';
import 'screens/phase_feedback_screen.dart';
import 'screens/profile_screen.dart';
import 'screens/signup_screen.dart';
import 'screens/swing_camera_screen.dart';
import 'screens/swing_list_screen.dart';

final router = GoRouter(
  initialLocation: '/login',
  observers: [swingRouteObserver],
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
    GoRoute(path: '/signup', builder: (context, state) => const SignupScreen()),
    GoRoute(
      path: '/swings',
      builder: (context, state) => const SwingListScreen(),
    ),
    GoRoute(
      path: '/swings/camera',
      builder: (context, state) => const SwingCameraScreen(),
    ),
    GoRoute(
      path: '/profile',
      builder: (context, state) => const ProfileScreen(),
    ),
    // 종합 피드백. 분석 id 로 결과를 조회한다.
    // 쿼리 first=1 이면 새 업로드 분석 완료를 polling한다. 과거 기록은 한 번 조회한다.
    GoRoute(
      path: '/analyses/:id/pose-3d',
      builder: (context, state) =>
          UserSwing3dScreen(analysisId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/analyses/:id',
      builder: (context, state) => OverallFeedbackScreen(
        analysisId: state.pathParameters['id']!,
        firstTime: state.uri.queryParameters['first'] == '1',
        // 새 영상의 로컬 경로/웹 Blob URL. 결과 화면이 Blob의 해제를 맡는다.
        videoPath: state.extra as String?,
      ),
    ),
    // 관절별 분석(상세 피드백). 종합 피드백 결과를 extra 로 넘겨 받는다.
    GoRoute(
      path: '/joint-analysis',
      builder: (context, state) =>
          JointAnalysisScreen(feedback: state.extra as OverallFeedback),
    ),
    // 구간별 피드백. 종합 피드백 결과를 extra 로 넘겨 받는다.
    GoRoute(
      path: '/phase-feedback',
      builder: (context, state) =>
          PhaseFeedbackScreen(feedback: state.extra as OverallFeedback),
    ),
  ],
);
