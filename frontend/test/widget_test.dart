
import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/main.dart';
import 'package:frontend/screens/login_screen.dart';

void main() {
  testWidgets('Shows LoginScreen on start', (WidgetTester tester) async {
    // Build the app
    await tester.pumpWidget(const ResaleHubApp());

    // Verify that the LoginScreen is shown
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.text('Login'), findsOneWidget);
  });
}
