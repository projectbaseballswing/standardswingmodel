import 'package:go_router/go_router.dart';

import 'models/feedback.dart';
import 'screens/joint_analysis_screen.dart';
import 'screens/login_screen.dart';
import 'screens/overall_feedback_screen.dart';
import 'screens/profile_screen.dart';
import 'screens/signup_screen.dart';
import 'screens/swing_camera_screen.dart';
import 'screens/swing_list_screen.dart';

final router = GoRouter(
  initialLocation: '/login',
  routes: [
    GoRoute(
      path: '/login',
      builder: (context, state) => const LoginScreen(),
    ),
    GoRoute(
      path: '/signup',
      builder: (context, state) => const SignupScreen(),
    ),
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
    // 쿼리 first=1 이면 비교 대상이 없는 첫 피드백으로 보여준다.
    GoRoute(
      path: '/analyses/:id',
      builder: (context, state) => OverallFeedbackScreen(
        analysisId: state.pathParameters['id']!,
        firstTime: state.uri.queryParameters['first'] == '1',
        // 방금 촬영한 로컬 영상 경로(있으면). 촬영 흐름에서 extra 로 넘긴다.
        videoPath: state.extra as String?,
      ),
    ),
    // 관절별 분석(상세 피드백). 종합 피드백 결과를 extra 로 넘겨 받는다.
    GoRoute(
      path: '/joint-analysis',
      builder: (context, state) =>
          JointAnalysisScreen(feedback: state.extra as OverallFeedback),
    ),
  ],
);
