import 'package:flutter_test/flutter_test.dart';
import 'package:wacc_mobile/screens/approvals_screen.dart';

void main() {
  test('plain ASCII and newlines are shown as they are', () {
    expect(visibleText('pip install requests\n{"a": 1}'), 'pip install requests\n{"a": 1}');
  });

  test('direction marks, zero-width and look-alike characters are made visible', () {
    expect(visibleText('re\u202equests'), r're\u{202e}quests');
    expect(visibleText('re\u200bquests'), r're\u{200b}quests');
    expect(visibleText('re\u0430quests'), r're\u{430}quests');
  });

  test('long text is never cut', () {
    final long = 'a' * 6000;
    expect(visibleText(long).length, 6000);
  });
}
