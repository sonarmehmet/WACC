import 'package:flutter_test/flutter_test.dart';
import 'package:wacc_mobile/models.dart';

ApprovalItem _item(Map<String, dynamic> action) => ApprovalItem.fromJson({
      'id': 1,
      'requested_by': 'claude2',
      'action_class': 'INSTALL',
      'action': action,
      'action_hash': 'a' * 64,
      'status': 'PENDING',
    });

void main() {
  group('revealText', () {
    test('bidi override, zero width and control characters become visible escapes', () {
      final r = revealText('a‮b​c\u0007d');
      expect(r.text, 'a\\u202eb\\u200bc\\u0007d');
      expect(r.hidden, 3);
      expect(r.warning, contains('3 gizli'));
    });

    test('plain ASCII text is untouched and raises no warning', () {
      final r = revealText('pip install requests==2.32.0\nline two\ttab');
      expect(r.text, 'pip install requests==2.32.0\nline two\ttab');
      expect(r.hidden, 0);
      expect(r.nonAscii, isFalse);
      expect(r.warning, isEmpty);
    });

    test('look-alike letters are flagged', () {
      final r = revealText('reqυests'); // Greek upsilon
      expect(r.nonAscii, isTrue);
      expect(r.warning, contains('ASCII dışı'));
    });

    test('a lone surrogate is escaped', () {
      expect(revealText('x\ud800y').text, 'x\\ud800y');
    });
  });

  group('ApprovalItem display', () {
    test('prettyAction hides nothing and warns', () {
      final item = _item({
        'type': 'run',
        'argv': ['pip', 'install', 'reque‮stsx']
      });
      expect(item.prettyAction, startsWith('DİKKAT'));
      expect(item.prettyAction, contains('\\u202e'));
      expect(item.prettyAction, isNot(contains('‮')));
    });

    test('a file write shows its content preview separately, with escapes', () {
      final item = _item({
        'type': 'write_file',
        'path': 'conftest.py',
        'content_preview': "import os\nos.system('x')​",
        'content_preview_truncated': 120,
      });
      expect(item.prettyAction, isNot(contains('os.system')));
      expect(item.contentPreview, contains("os.system('x')"));
      expect(item.contentPreview, contains('\\u200b'));
      expect(item.contentPreview, contains('120 karakter daha var'));
    });

    test('other actions have no content preview', () {
      expect(_item({'type': 'delete_path', 'path': 'a.txt'}).contentPreview, isEmpty);
    });

    test('shortAction says when it is cut, and still escapes', () {
      final long = _item({
        'type': 'run',
        'argv': List.generate(60, (i) => 'package-$i') + ['TAIL‮']
      });
      expect(long.shortAction, contains('devamı var'));
      expect(long.shortAction, isNot(contains('‮')));
    });
  });
}
