import 'package:go_router/go_router.dart';

import 'screens/login_screen.dart';
import 'screens/signup_screen.dart';
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
  ],
);
