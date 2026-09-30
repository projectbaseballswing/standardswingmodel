// 앱이 정상적으로 뜨고 로그인 화면이 보이는지 확인하는 기본 스모크 테스트.

import 'package:flutter_test/flutter_test.dart';

import 'package:swing_analysis/main.dart';

void main() {
  testWidgets('앱이 로그인 화면으로 시작한다', (WidgetTester tester) async {
    await tester.pumpWidget(const SwingAnalysisApp());
    await tester.pumpAndSettle();

    // 로그인 화면의 타이틀과 버튼이 보여야 한다.
    expect(find.text('SWING\nANALYSIS'), findsOneWidget);
    expect(find.text('로그인'), findsOneWidget);
  });
}
