import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wacc_mobile/api/hub_client.dart';
import 'package:wacc_mobile/app.dart';
import 'package:wacc_mobile/app_state.dart';
import 'package:wacc_mobile/approvals_state.dart';
import 'package:wacc_mobile/models.dart';
import 'package:wacc_mobile/settings.dart';

Map<String, dynamic> _approval({int id = 7, String status = 'PENDING', String cls = 'DELETE'}) => {
      'id': id,
      'requested_by': 'claude2',
      'action_class': cls,
      'action': {'type': 'shell', 'command': 'rm -rf build'},
      'action_hash': 'a' * 64,
      'risk_summary': 'deletes files',
      'status': status,
      'created_at': '2026-10-31T12:00:00Z',
      'expires_at': '2026-10-31T12:10:00Z',
    };

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// A fake Backend: the user token may decide, every other token gets 403.
class FakeBackend extends BackendClient {
  FakeBackend(this.log, String token, this.pendingItems)
      : super(baseUrl: 'http://backend.test', token: token);

  final List<String> log;
  final List<Map<String, dynamic>> pendingItems;

  bool get _isUser => token == 'tok-human';

  @override
  Future<List<ApprovalItem>> approvals({String? status, int limit = 50}) async {
    final rows = status == 'PENDING' ? pendingItems : [...pendingItems, _approval(id: 3, status: 'APPROVED')];
    return rows.map(ApprovalItem.fromJson).toList();
  }

  @override
  Future<ExecStatus> execStatus() async => const ExecStatus(emergencyStop: false, roots: ['/work']);

  @override
  Future<List<AuditEntry>> audit({int limit = 50}) async => const [];

  @override
  Future<void> approve(int id) async {
    if (!_isUser) throw const HubException('forbidden', statusCode: 403);
    log.add('approve:$id');
    pendingItems.removeWhere((a) => a['id'] == id);
  }

  @override
  Future<void> deny(int id) async {
    if (!_isUser) throw const HubException('forbidden', statusCode: 403);
    log.add('deny:$id');
    pendingItems.removeWhere((a) => a['id'] == id);
  }
}

void main() {
  group('models', () {
    test('ApprovalItem parses and flags risky classes', () {
      final item = ApprovalItem.fromJson(_approval());
      expect(item.id, 7);
      expect(item.isRisky, isTrue);
      expect(item.prettyAction, contains('rm -rf build'));
      expect(item.shortHash.length, 17);
      expect(ApprovalItem.fromJson(_approval(cls: 'READ_ONLY')).isRisky, isFalse);
    });

    test('remainingText', () {
      final now = DateTime.utc(2026, 10, 31, 12, 0, 55);
      expect(remainingText('2026-10-31T12:10:00Z', now: now), '9 dk 05 sn kaldı');
      expect(remainingText('2026-10-31T11:00:00Z', now: now), 'süresi doldu');
      expect(remainingText('garbage', now: now), '-');
    });
  });

  group('BackendClient', () {
    test('sends the token header and parses approvals', () async {
      late http.Request seen;
      final client = BackendClient(
        baseUrl: 'http://b.test:8800/',
        token: 'secret',
        client: MockClient((request) async {
          seen = request;
          return _json([_approval()]);
        }),
      );
      final list = await client.approvals(status: 'PENDING');
      expect(list.single.id, 7);
      expect(seen.url.path, '/exec/approvals');
      expect(seen.url.queryParameters['status'], 'PENDING');
      expect(seen.headers['X-WACC-Token'], 'secret');
      expect(seen.url.toString(), isNot(contains('secret')));
    });

    test('approve posts to the decision endpoint; 403 becomes HubException', () async {
      final paths = <String>[];
      final client = BackendClient(
        baseUrl: 'http://b.test:8800',
        token: 'agent',
        client: MockClient((request) async {
          paths.add('${request.method} ${request.url.path}');
          return _json({'detail': 'forbidden'}, 403);
        }),
      );
      await expectLater(
        client.approve(7),
        throwsA(isA<HubException>().having((e) => e.statusCode, 'statusCode', 403)),
      );
      expect(paths, ['POST /exec/approvals/7/approve']);
    });
  });

  group('ApprovalsState', () {
    ApprovalsState build(List<String> log, List<Map<String, dynamic>> items, {Duration? idle}) {
      return ApprovalsState(
        factory: (url, token) => FakeBackend(log, token, items),
        idleTimeout: idle ?? const Duration(minutes: 5),
      );
    }

    test('lists pending with the settings token; cannot decide without the user token', () async {
      final log = <String>[];
      final state = build(log, [_approval()]);
      state.configure(const Settings(backendToken: 'tok-agent'));
      await state.refresh();
      expect(state.pending.single.id, 7);
      expect(state.pendingCount, 1);
      expect(state.hasApprovalToken, isFalse);
      expect(await state.decide(state.pending.single, approve: true), isNotNull);
      expect(log, isEmpty);
      state.dispose();
    });

    test('an agent token used as approval token is refused with a clear message', () async {
      final log = <String>[];
      final state = build(log, [_approval()]);
      state.configure(const Settings(backendToken: 'tok-agent'));
      state.setApprovalToken('tok-agent');
      await state.refresh();
      final err = await state.decide(state.pending.single, approve: true);
      expect(err, contains('kullanıcı tokenı'));
      expect(log, isEmpty);
      state.dispose();
    });

    test('the user token approves and the list refreshes', () async {
      final log = <String>[];
      final state = build(log, [_approval()]);
      state.configure(const Settings());
      state.setApprovalToken('tok-human');
      await state.refresh();
      expect(await state.decide(state.pending.single, approve: true), isNull);
      expect(log, ['approve:7']);
      expect(state.pending, isEmpty);
      state.dispose();
    });

    test('the approval token is forgotten on request', () async {
      final state = build([], []);
      state.configure(const Settings());
      state.setApprovalToken('tok-human');
      expect(state.hasApprovalToken, isTrue);
      state.forgetApprovalToken();
      expect(state.hasApprovalToken, isFalse);
      state.dispose();
    });

    testWidgets('the approval token is forgotten after the idle timeout', (tester) async {
      final state = build([], [], idle: const Duration(seconds: 30));
      state.configure(const Settings());
      state.setApprovalToken('tok-human');
      await tester.pump(const Duration(seconds: 29));
      expect(state.hasApprovalToken, isTrue);
      await tester.pump(const Duration(seconds: 2));
      expect(state.hasApprovalToken, isFalse);
      state.dispose();
    });
  });

  group('approvals screen', () {
    Future<(AppState, List<String>)> pump(WidgetTester tester) async {
      final log = <String>[];
      final items = [_approval()];
      final state = AppState(
        store: MemorySettingsStore(const Settings(token: 'tok', backendToken: 'tok-agent')),
        clientFactory: (url, t) => _NoHub(),
        backendFactory: (url, t) => FakeBackend(log, t, items),
        pollInterval: null,
      );
      await tester.pumpWidget(WaccApp(state: state));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Onaylar'));
      await tester.pumpAndSettle();
      return (state, log);
    }

    Future<void> tapVisible(WidgetTester tester, Finder finder) async {
      await tester.ensureVisible(finder);
      await tester.pumpAndSettle();
      await tester.tap(finder);
      await tester.pumpAndSettle();
    }

    testWidgets('shows the raw action; buttons are disabled without the user token', (tester) async {
      await pump(tester);
      expect(find.textContaining('rm -rf build'), findsWidgets);
      expect(find.text('önce onay tokenını gir'), findsOneWidget);
      final approve = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Onayla'));
      expect(approve.onPressed, isNull);
    });

    testWidgets('approving with the user token asks for confirmation and clears the field', (tester) async {
      final (state, log) = await pump(tester);
      await tester.enterText(find.widgetWithText(TextField, 'Kullanıcı tokenı'), 'tok-human');
      await tester.tap(find.text('Kullan'));
      await tester.pumpAndSettle();
      expect(state.approvals.hasApprovalToken, isTrue);
      expect(find.widgetWithText(TextField, 'Kullanıcı tokenı'), findsOneWidget);
      expect(tester.widget<TextField>(find.widgetWithText(TextField, 'Kullanıcı tokenı')).controller!.text, '');

      await tapVisible(tester, find.widgetWithText(FilledButton, 'Onayla'));
      expect(find.text('Bu eylemi onaylıyor musun?'), findsOneWidget);
      await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Onayla')));
      await tester.pumpAndSettle();
      expect(log, ['approve:7']);
      expect(find.text('Bekleyen onay yok.'), findsOneWidget);
    });

    testWidgets('denying needs no confirmation', (tester) async {
      final (_, log) = await pump(tester);
      await tester.enterText(find.widgetWithText(TextField, 'Kullanıcı tokenı'), 'tok-human');
      await tester.tap(find.text('Kullan'));
      await tester.pumpAndSettle();
      await tapVisible(tester, find.widgetWithText(OutlinedButton, 'Reddet'));
      expect(log, ['deny:7']);
    });

    testWidgets('an agent token used for approval shows the 403 message', (tester) async {
      final (_, log) = await pump(tester);
      await tester.enterText(find.widgetWithText(TextField, 'Kullanıcı tokenı'), 'tok-agent');
      await tester.tap(find.text('Kullan'));
      await tester.pumpAndSettle();
      await tapVisible(tester, find.widgetWithText(OutlinedButton, 'Reddet'));
      expect(find.textContaining('ajan tokenı onaylayamaz'), findsOneWidget);
      expect(log, isEmpty);
    });
  });
}

class _NoHub extends HubClient {
  _NoHub() : super(baseUrl: 'http://fake.test', token: 'tok');

  @override
  Future<Map<String, dynamic>> health() async => {'ok': true, 'emergency_stop': false};

  @override
  Future<String> whoami() async => 'user';

  @override
  Future<List<Agent>> agents() async => const [];

  @override
  Future<List<FeedMessage>> feed({int limit = 200, String? conversationId}) async => const [];

  @override
  Future<List<HubTask>> tasks({String? owner, String? status}) async => const [];
}
