import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/main.dart';
import 'package:frontend/screens/login_screen.dart';

void main() {
  testWidgets('Shows LoginScreen on start', (WidgetTester tester) async {
    // Build the app
    // [수정됨] ResaleHubApp -> MyApp (main.dart에 정의된 클래스 이름과 일치해야 함)
    await tester.pumpWidget(const MyApp());

    // Verify that the LoginScreen is shown
    expect(find.byType(LoginScreen), findsOneWidget);
    
    // 화면에 'Login'이라는 텍스트가 있는지 확인 (제목이나 버튼 등)
    // 만약 'Login' 글자가 여러 개라면 findsWidgets로 바꿔야 할 수도 있음
    expect(find.text('Login'), findsAtLeastNWidgets(1)); 
  });
}