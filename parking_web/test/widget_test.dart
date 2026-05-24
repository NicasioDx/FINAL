import 'package:flutter_test/flutter_test.dart';

import 'package:parking_web/main.dart';

void main() {
  testWidgets('shows login screen by default', (WidgetTester tester) async {
    await tester.pumpWidget(const ParkingAIApp());
    await tester.pumpAndSettle();

    expect(find.text('เข้าสู่ระบบ'), findsWidgets);
  });
}
