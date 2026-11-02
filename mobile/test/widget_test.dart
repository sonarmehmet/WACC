import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wacc_mobile/api/hub_client.dart';
import 'package:wacc_mobile/app.dart';
import 'package:wacc_mobile/app_state.dart';
import 'package:wacc_mobile/models.dart';
import 'package:wacc_mobile/settings.dart';

class FakeHub extends HubClient {
  FakeHub({this.me = 'user', this.stopped = false, this.fail = false})
      : super(baseUrl: 'http://fake.test', token: 'tok');

  final String me;
  final bool stopped;
  final bool fail;
  final List<String> sent = [];

  void _maybeFail() {
    if (fail) throw const HubException('Hub\'a ulaşılamıyor', code: 'UNREACHABLE');
  }

  @override
  Future<Map<String, dynamic>> health() async {
    _maybeFail();
    return {'ok': true, 'emergency_stop': stopped};
  }

  @override
  Future<String> whoami() async => me;

  @override
  Future<List<Agent>> agents() async => const [
        Agent(
          id: 'claude2',
          role: 'BACKEND_CORE',
          status: 'ACTIVE',
          online: true,
          unread: 2,
          activeTasks: 3,
        ),
        Agent(id: 'gemini', role: 'VISUAL_OPERATOR', status: 'OFFLINE', online: false),
      ];

  @override
  Future<List<FeedMessage>> feed({int limit = 200, String? conversationId}) async => const [
        FeedMessage(
          id: 'M-1',
          conversationId: 'CONV-1',
          sender: 'claude2',
          receiver: 'user',
          timestamp: '2026-10-31T12:00:00Z',
          type: 'HELP_REQUEST',
          priority: 'NORMAL',
          subject: '<b>not html</b>',
          content: 'body',
          status: 'DELIVERED',
          responseRequired: true,
        ),
      ];

  @override
  Future<List<HubTask>> tasks({String? owner, String? status}) async => const [
        HubTask(id: 'T-0005', title: 'Web panel', status: 'ASSIGNED', priority: 'NORMAL', owner: 'claude3'),
      ];

  @override
  Future<void> sendMessage({
    required String receiver,
    required String messageType,
    required String subject,
    String content = '',
    String priority = 'NORMAL',
    bool responseRequired = false,
    String? conversationId,
    String? idempotencyKey,
  }) async {
    sent.add('$receiver:$subject');
  }
}

Future<AppState> _pumpApp(WidgetTester tester, FakeHub hub, {String token = 'tok'}) async {
  final state = AppState(
    store: MemorySettingsStore(Settings(baseUrl: 'http://fake.test', token: token)),
    clientFactory: (url, t) => hub,
    pollInterval: null,
  );
  await tester.pumpWidget(WaccApp(state: state));
  await tester.pumpAndSettle();
  return state;
}

void main() {
  testWidgets('Agents screen shows status from /agents', (tester) async {
    await _pumpApp(tester, FakeHub());
    expect(find.text('Bağlı: user'), findsOneWidget);
    expect(find.text('claude2'), findsOneWidget);
    expect(find.text('gemini'), findsOneWidget);
    expect(find.text('Okunmamış 2'), findsOneWidget);
    expect(find.text('Aktif görev 3'), findsOneWidget);
    expect(find.text('Acil durdur'), findsOneWidget); // the user may stop everything
  });

  testWidgets('Chat screen shows /feed and renders agent text literally', (tester) async {
    await _pumpApp(tester, FakeHub());
    await tester.tap(find.text('Sohbet'));
    await tester.pumpAndSettle();
    expect(find.text('<b>not html</b>'), findsOneWidget);
    expect(find.text('claude2 → user'), findsOneWidget);
    expect(find.text('yanıt gerekli'), findsOneWidget);
  });

  testWidgets('Sending a message goes through the client', (tester) async {
    final hub = FakeHub();
    await _pumpApp(tester, hub);
    await tester.tap(find.text('Sohbet'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Mesaj yaz'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Konu'), 'ping');
    await tester.tap(find.text('Gönder'));
    await tester.pumpAndSettle();
    expect(hub.sent, ['claude1:ping']);
  });

  testWidgets('Tasks screen lists tasks; only leaders can give tasks', (tester) async {
    await _pumpApp(tester, FakeHub());
    await tester.tap(find.text('Görevler'));
    await tester.pumpAndSettle();
    expect(find.text('T-0005  Web panel'), findsOneWidget);
    expect(find.text('Görev ver'), findsOneWidget);

    await _pumpApp(tester, FakeHub(me: 'claude3'));
    await tester.tap(find.text('Görevler'));
    await tester.pumpAndSettle();
    expect(find.text('Görev ver'), findsNothing);
  });

  testWidgets('Emergency stop banner is shown', (tester) async {
    await _pumpApp(tester, FakeHub(stopped: true));
    expect(find.text('ACİL DURDURMA AÇIK'), findsOneWidget);
    expect(find.text('Devam ettir'), findsOneWidget);
  });

  testWidgets('Without a token the app asks for one', (tester) async {
    await _pumpApp(tester, FakeHub(), token: '');
    expect(find.text('Ayarlardan token gir'), findsWidgets);
  });

  testWidgets('An unreachable Hub is reported', (tester) async {
    await _pumpApp(tester, FakeHub(fail: true));
    expect(find.text('Hub\'a ulaşılamıyor'), findsWidgets);
  });
}
