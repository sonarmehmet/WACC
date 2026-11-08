import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wacc_mobile/jarvis.dart';

void main() {
  test('JARVIS theme is dark with the control-room colours', () {
    final t = jarvisTheme();
    expect(t.brightness, Brightness.dark);
    expect(t.scaffoldBackgroundColor, jarvisBg);
    expect(t.colorScheme.primary, jarvisAccent);
  });

  testWidgets('radar orb draws and animates without errors', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: RadarOrb(color: jarvisAccent))));
    await tester.pumpAndSettle();
    expect(find.byType(RadarOrb), findsOneWidget);
  });
}
