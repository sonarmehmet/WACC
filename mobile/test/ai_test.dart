import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wacc_mobile/ai_state.dart';
import 'package:wacc_mobile/api/hub_client.dart';
import 'package:wacc_mobile/app.dart';
import 'package:wacc_mobile/app_state.dart';
import 'package:wacc_mobile/approvals_state.dart';
import 'package:wacc_mobile/models.dart';
import 'package:wacc_mobile/settings.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

const _secret = 'sk-test-secret-123456';

/// A fake Backend: only the user token may change accounts (everyone else gets 403). It never
/// returns an API key, like the real one, and remembers the keys it was given.
class FakeAiBackend extends BackendClient {
  FakeAiBackend(this.store, String token) : super(baseUrl: 'http://backend.test', token: token);

  final FakeAiStore store;

  bool get _isUser => token == 'tok-human';

  void _needUser() {
    if (!_isUser) throw const HubException('forbidden', statusCode: 403);
  }

  @override
  Future<List<ApprovalItem>> approvals({String? status, int limit = 50}) async => const [];

  @override
  Future<List<AiProvider>> aiProviders() async => store.rows.map(AiProvider.fromJson).toList();

  @override
  Future<AiUsage> aiUsage() async => const AiUsage(budgetUsd: 5, spentUsd: 0.1234);

  @override
  Future<void> addAiAccount(Map<String, Object?> account) async {
    _needUser();
    store.log.add('add:${account['name']}');
    if (account['api_key'] != null) store.keys[account['name']! as String] = account['api_key']! as String;
    store.rows.add({
      'name': account['name'],
      'kind': account['kind'],
      'model': account['model'],
      'enabled': account['enabled'],
      'source': 'account',
      'price_in_per_1k': account['price_in_per_1k'] ?? 0,
      'price_out_per_1k': account['price_out_per_1k'] ?? 0,
    });
  }

  @override
  Future<void> removeAiAccount(String name) async {
    _needUser();
    store.log.add('remove:$name');
    store.rows.removeWhere((r) => r['name'] == name);
  }

  @override
  Future<void> setAiEnabled(String name, bool enabled) async {
    _needUser();
    store.log.add('enabled:$name=$enabled');
    store.rows.firstWhere((r) => r['name'] == name)['enabled'] = enabled;
  }

  @override
  Future<AiTestResult> testAiProvider(String name) async {
    _needUser();
    store.log.add('test:$name');
    return const AiTestResult(ok: true, reply: 'OK', latencyMs: 12);
  }
}

class FakeAiStore {
  final log = <String>[];
  final keys = <String, String>{};
  final rows = <Map<String, dynamic>>[
    {
      'name': 'mock',
      'kind': 'local',
      'model': 'mock-1',
      'enabled': true,
      'source': 'env',
      'price_in_per_1k': 0,
      'price_out_per_1k': 0,
    },
  ];
}

void main() {
  group('AI models', () {
    test('AiProvider parses; only accounts are removable', () {
      final account = AiProvider.fromJson({
        'name': 'groq',
        'kind': 'cloud',
        'model': 'llama',
        'enabled': 1,
        'source': 'account',
        'price_in_per_1k': 0.001,
        'price_out_per_1k': '0.002',
      });
      expect(account.enabled, isTrue);
      expect(account.isCloud, isTrue);
      expect(account.removable, isTrue);
      expect(account.priceOut, 0.002);
      final env = AiProvider.fromJson({'name': 'mock', 'kind': 'local', 'model': 'm', 'enabled': false, 'source': 'env'});
      expect(env.removable, isFalse);
      expect(env.enabled, isFalse);
    });

    test('AiUsage and AiTestResult tolerate odd values', () {
      final usage = AiUsage.fromJson({'budget_usd': 5, 'spent_usd': 'x'});
      expect(usage.budgetUsd, 5);
      expect(usage.spentUsd, 0);
      final bad = AiTestResult.fromJson({'ok': false, 'error': 'boom', 'latency_ms': 7});
      expect(bad.ok, isFalse);
      expect(bad.error, 'boom');
      expect(bad.latencyMs, 7);
    });
  });

  group('BackendClient AI calls', () {
    test('add posts the key in the body only; remove uses DELETE; token is a header', () async {
      final seen = <http.Request>[];
      final client = BackendClient(
        baseUrl: 'http://b.test:8800/',
        token: 'tok-human',
        client: MockClient((request) async {
          seen.add(request);
          return _json({'ok': true}, request.method == 'POST' ? 201 : 200);
        }),
      );
      await client.addAiAccount({'name': 'groq', 'kind': 'cloud', 'api_key': _secret});
      await client.removeAiAccount('groq');
      await client.setAiEnabled('groq', false);
      expect(seen[0].method, 'POST');
      expect(seen[0].url.path, '/ai/accounts');
      expect(jsonDecode(seen[0].body)['api_key'], _secret);
      expect(seen[0].url.toString(), isNot(contains(_secret)));
      expect(seen[0].headers['X-WACC-Token'], 'tok-human');
      expect(seen[1].method, 'DELETE');
      expect(seen[1].url.path, '/ai/accounts/groq');
      expect(seen[2].url.path, '/ai/providers/groq/enabled');
      expect(jsonDecode(seen[2].body), {'enabled': false});
    });

    test('providers, usage and test are parsed; an agent token gets a HubException 403', () async {
      final client = BackendClient(
        baseUrl: 'http://b.test:8800',
        token: 'agent',
        client: MockClient((request) async {
          if (request.url.path == '/ai/providers') {
            return _json([
              {'name': 'mock', 'kind': 'local', 'model': 'm', 'enabled': true, 'source': 'env'},
            ]);
          }
          if (request.url.path == '/ai/usage') return _json({'budget_usd': 2, 'spent_usd': 0.5});
          return _json({'detail': 'forbidden'}, 403);
        }),
      );
      expect((await client.aiProviders()).single.name, 'mock');
      expect((await client.aiUsage()).spentUsd, 0.5);
      await expectLater(
        client.testAiProvider('mock'),
        throwsA(isA<HubException>().having((e) => e.statusCode, 'statusCode', 403)),
      );
    });

    test('an account name is URL-encoded', () async {
      late http.Request seen;
      final client = BackendClient(
        baseUrl: 'http://b.test',
        token: 't',
        client: MockClient((request) async {
          seen = request;
          return _json({'removed': true});
        }),
      );
      await client.removeAiAccount('a/../b');
      expect(seen.url.path, '/ai/accounts/a%2F..%2Fb');
    });
  });

  group('AiState', () {
    late FakeAiStore store;
    late ApprovalsState approvals;
    late AiState ai;

    setUp(() {
      store = FakeAiStore();
      approvals = ApprovalsState(factory: (url, token) => FakeAiBackend(store, token));
      approvals.configure(const Settings(backendToken: 'tok-agent'));
      ai = AiState(approvals);
    });

    tearDown(() {
      ai.dispose();
      approvals.dispose();
    });

    Future<void> settle() async {
      for (var i = 0; i < 6; i++) {
        await Future<void>.delayed(Duration.zero);
      }
      await ai.refresh();
    }

    test('reads with the Backend token but cannot change anything', () async {
      await settle();
      expect(ai.connected, isTrue);
      expect(ai.providers.single.name, 'mock');
      expect(ai.usage!.budgetUsd, 5);
      expect(ai.canChange, isFalse);
      expect(await ai.toggle(ai.providers.single), 'Önce kullanıcı tokenını gir');
      expect(store.log, isEmpty);
    });

    test('with an agent token used as the user token the Backend answers 403', () async {
      approvals.setApprovalToken('tok-agent');
      await settle();
      final err = await ai.toggle(ai.providers.single);
      expect(err, contains('kullanıcı tokenı gerekir'));
      expect(store.log, isEmpty);
    });

    test('add validates name and cloud key before sending anything', () async {
      approvals.setApprovalToken('tok-human');
      await settle();
      expect(await ai.add(name: 'Bad Name!', kind: 'local', baseUrl: 'http://127.0.0.1:1/v1', model: 'm'),
          contains('Ad 2-31'));
      expect(await ai.add(name: 'cloudy', kind: 'cloud', baseUrl: 'https://x.test/v1', model: 'm'),
          contains('API anahtarı gerekli'));
      expect(store.log, isEmpty);
    });

    test('add, test, switch and remove work with the user token; the key is not kept', () async {
      approvals.setApprovalToken('tok-human');
      await settle();
      expect(
        await ai.add(
          name: 'Groq',
          kind: 'cloud',
          baseUrl: 'https://api.groq.test/v1',
          model: 'llama',
          apiKey: _secret,
          priceIn: 0.001,
        ),
        isNull,
      );
      expect(store.log, ['add:groq']);
      expect(store.keys['groq'], _secret);
      final groq = ai.providers.firstWhere((p) => p.name == 'groq');
      expect(groq.removable, isTrue);
      expect(ai.providers.map((p) => p.toString()).join(), isNot(contains(_secret)));

      await ai.test(groq);
      expect(ai.tests['groq']!.ok, isTrue);
      expect(await ai.toggle(groq), isNull);
      await settle();
      expect(ai.providers.firstWhere((p) => p.name == 'groq').enabled, isFalse);
      expect(await ai.remove(groq), isNull);
      await settle();
      expect(ai.providers.any((p) => p.name == 'groq'), isFalse);
      expect(ai.tests.containsKey('groq'), isFalse);
      expect(store.log, ['add:groq', 'test:groq', 'enabled:groq=false', 'remove:groq']);
    });

    test('forgetting the user token locks changes again and clears test results', () async {
      approvals.setApprovalToken('tok-human');
      await settle();
      await ai.test(ai.providers.single);
      expect(ai.tests, isNotEmpty);
      approvals.forgetApprovalToken();
      await settle();
      expect(ai.canChange, isFalse);
      expect(ai.tests, isEmpty);
    });
  });

  group('AI screen', () {
    late FakeAiStore store;

    Future<AppState> pump(WidgetTester tester) async {
      store = FakeAiStore();
      tester.view.physicalSize = const Size(800, 3000); // tall: every list item gets built
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final state = AppState(
        store: MemorySettingsStore(const Settings(token: 'tok', backendToken: 'tok-agent')),
        clientFactory: (url, t) => _NoHub(),
        backendFactory: (url, t) => FakeAiBackend(store, t),
        pollInterval: null,
      );
      await tester.pumpWidget(WaccApp(state: state));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Ayarlar'));
      await tester.pumpAndSettle();
      final open = find.byKey(const Key('openAi'));
      await tester.ensureVisible(open);
      await tester.pumpAndSettle();
      await tester.tap(open);
      await tester.pumpAndSettle();
      return state;
    }

    Future<void> useToken(WidgetTester tester, String token) async {
      await tester.enterText(find.byKey(const Key('aiToken')), token);
      await tester.tap(find.text('Kullan'));
      await tester.pumpAndSettle();
    }

    testWidgets('read-only without the user token; env providers have no Sil', (tester) async {
      await pump(tester);
      expect(find.byKey(const Key('provider-mock')), findsOneWidget);
      expect(find.byKey(const Key('remove-mock')), findsNothing);
      expect(tester.widget<TextButton>(find.byKey(const Key('toggle-mock'))).onPressed, isNull);
      expect(find.byKey(const Key('aiUsage')), findsOneWidget);
    });

    testWidgets('adding an account empties the key field and never shows the key', (tester) async {
      await pump(tester);
      await useToken(tester, 'tok-human');
      expect(tester.widget<TextField>(find.byKey(const Key('aiToken'))).controller!.text, '');

      await tester.enterText(find.byKey(const Key('aiName')), 'ui-local');
      await tester.enterText(find.byKey(const Key('aiUrl')), 'http://127.0.0.1:11434/v1');
      await tester.enterText(find.byKey(const Key('aiModel')), 'llama3');
      await tester.enterText(find.byKey(const Key('aiKey')), _secret);
      final add = find.byKey(const Key('aiAddBtn'));
      await tester.ensureVisible(add);
      await tester.pumpAndSettle();
      await tester.tap(add);
      await tester.pumpAndSettle();

      expect(store.log, ['add:ui-local']);
      expect(store.keys['ui-local'], _secret);
      expect(tester.widget<TextField>(find.byKey(const Key('aiKey'))).controller!.text, '');
      expect(find.textContaining(_secret), findsNothing);
      expect(find.byKey(const Key('provider-ui-local')), findsOneWidget);
      expect(find.byKey(const Key('remove-ui-local')), findsOneWidget);
    });

    testWidgets('Test shows the result; Sil asks first and removes', (tester) async {
      final app = await pump(tester);
      await useToken(tester, 'tok-human');

      await tester.tap(find.byKey(const Key('testbtn-mock')));
      await tester.pumpAndSettle();
      expect(find.textContaining('OK · 12 ms'), findsOneWidget);

      store.rows.add({
        'name': 'extra',
        'kind': 'local',
        'model': 'm',
        'enabled': true,
        'source': 'account',
      });
      await app.ai.refresh();
      await tester.pumpAndSettle();
      final remove = find.byKey(const Key('remove-extra'));
      await tester.ensureVisible(remove);
      await tester.pumpAndSettle();
      await tester.tap(remove);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Vazgeç'));
      await tester.pumpAndSettle();
      expect(store.log, ['test:mock']);
      await tester.tap(remove);
      await tester.pumpAndSettle();
      await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Sil')));
      await tester.pumpAndSettle();
      expect(store.log, ['test:mock', 'remove:extra']);
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
