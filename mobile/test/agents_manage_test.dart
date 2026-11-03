import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wacc_mobile/api/hub_client.dart';
import 'package:wacc_mobile/app.dart';
import 'package:wacc_mobile/app_state.dart';
import 'package:wacc_mobile/models.dart';
import 'package:wacc_mobile/settings.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// Fake Hub with a mutable agent list. Only the user may manage agents (others get 403).
class ManagingHub extends HubClient {
  ManagingHub(this.me, this.rows, this.log) : super(baseUrl: 'http://fake.test', token: 'tok');

  final String me;
  final List<Agent> rows;
  final List<String> log;

  void _needUser() {
    if (me != 'user') throw const HubException('forbidden', statusCode: 403);
  }

  @override
  Future<Map<String, dynamic>> health() async => {'ok': true, 'emergency_stop': false};

  @override
  Future<String> whoami() async => me;

  @override
  Future<List<Agent>> agents() async => List.of(rows);

  @override
  Future<List<FeedMessage>> feed({int limit = 200, String? conversationId}) async => const [];

  @override
  Future<List<HubTask>> tasks({String? owner, String? status}) async => const [];

  @override
  Future<NewAgent> addAgent({required String name, required String kind, String role = '', String? provider}) async {
    _needUser();
    log.add('add:$name:$kind:$role:${provider ?? ''}');
    rows.add(Agent(id: name, role: role, status: 'OFFLINE', online: false, kind: kind));
    return NewAgent(name: name, token: 'new-token-abc');
  }

  @override
  Future<void> setAgentEnabled(String name, bool enabled) async {
    _needUser();
    log.add('enabled:$name=$enabled');
    final i = rows.indexWhere((a) => a.id == name);
    final a = rows[i];
    rows[i] = Agent(id: a.id, role: a.role, status: a.status, online: a.online, kind: a.kind, enabled: enabled);
  }

  @override
  Future<void> removeAgent(String name) async {
    _needUser();
    log.add('remove:$name');
    rows.removeWhere((a) => a.id == name);
  }
}

void main() {
  group('Agent model', () {
    test('kind and enabled are parsed; built-ins are not removable', () {
      final builtin = Agent.fromJson({'agent_id': 'claude1', 'kind': 'builtin', 'enabled': 1, 'role': 'LEAD'});
      expect(builtin.removable, isFalse);
      expect(builtin.enabled, isTrue);
      final added = Agent.fromJson({'agent_id': 'helper', 'kind': 'chatgpt', 'enabled': 0});
      expect(added.removable, isTrue);
      expect(added.enabled, isFalse);
      expect(Agent.fromJson({'agent_id': 'old'}).kind, 'builtin'); // older Hub: no fields
    });

    test('NewAgent reads the one-time token', () {
      final n = NewAgent.fromJson({
        'agent': {'agent_id': 'helper'},
        'token': 'abc'
      });
      expect(n.name, 'helper');
      expect(n.token, 'abc');
    });
  });

  group('HubClient agent calls', () {
    test('add posts the body, enabled posts, remove uses DELETE; token only in the header', () async {
      final seen = <http.Request>[];
      final client = HubClient(
        baseUrl: 'http://h.test:8765',
        token: 'tok-user',
        client: MockClient((request) async {
          seen.add(request);
          if (request.url.path == '/agents' && request.method == 'POST') {
            return _json({
              'agent': {'agent_id': 'helper'},
              'token': 'fresh'
            }, 201);
          }
          return _json({'ok': true});
        }),
      );
      final created = await client.addAgent(name: 'helper', kind: 'claude', role: 'QA', provider: 'groq');
      await client.setAgentEnabled('helper', false);
      await client.removeAgent('helper');
      expect(created.token, 'fresh');
      expect(jsonDecode(seen[0].body), {'name': 'helper', 'kind': 'claude', 'role': 'QA', 'provider': 'groq'});
      expect(seen[0].headers['X-WACC-Token'], 'tok-user');
      expect(seen[1].url.path, '/agents/helper/enabled');
      expect(jsonDecode(seen[1].body), {'enabled': false});
      expect(seen[2].method, 'DELETE');
      expect(seen[2].url.path, '/agents/helper');
      for (final r in seen) {
        expect(r.url.toString(), isNot(contains('tok-user')));
      }
    });

    test('empty role and provider are not sent', () async {
      late http.Request seen;
      final client = HubClient(
        baseUrl: 'http://h.test',
        token: 't',
        client: MockClient((request) async {
          seen = request;
          return _json({'agent': {'agent_id': 'x1'}, 'token': 'z'}, 201);
        }),
      );
      await client.addAgent(name: 'x1', kind: 'other');
      expect(jsonDecode(seen.body), {'name': 'x1', 'kind': 'other'});
    });
  });

  group('agents screen', () {
    late List<Agent> rows;
    late List<String> log;

    Future<AppState> pump(WidgetTester tester, {String me = 'user'}) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      rows = [
        const Agent(id: 'claude1', role: 'LEAD', status: 'ACTIVE', online: true),
        const Agent(id: 'helper', role: 'QA', status: 'OFFLINE', online: false, kind: 'claude'),
      ];
      log = [];
      final state = AppState(
        store: MemorySettingsStore(const Settings(token: 'tok')),
        clientFactory: (url, t) => ManagingHub(me, rows, log),
        pollInterval: null,
      );
      await tester.pumpWidget(WaccApp(state: state));
      await tester.pumpAndSettle();
      return state;
    }

    testWidgets('the user can switch built-ins but only remove added accounts', (tester) async {
      await pump(tester);
      expect(find.byKey(const Key('agent-toggle-claude1')), findsOneWidget);
      expect(find.byKey(const Key('agent-remove-claude1')), findsNothing);
      expect(find.byKey(const Key('agent-remove-helper')), findsOneWidget);

      await tester.tap(find.byKey(const Key('agent-toggle-claude1')));
      await tester.pumpAndSettle();
      expect(log, ['enabled:claude1=false']);
      expect(find.text('kapalı'), findsOneWidget);
      expect(find.text('Aç'), findsOneWidget);
    });

    testWidgets('remove asks first', (tester) async {
      await pump(tester);
      await tester.tap(find.byKey(const Key('agent-remove-helper')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Vazgeç'));
      await tester.pumpAndSettle();
      expect(log, isEmpty);
      await tester.tap(find.byKey(const Key('agent-remove-helper')));
      await tester.pumpAndSettle();
      await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Sil')));
      await tester.pumpAndSettle();
      expect(log, ['remove:helper']);
      expect(find.byKey(const Key('agent-remove-helper')), findsNothing);
    });

    testWidgets('adding shows the token once and does not keep it', (tester) async {
      final state = await pump(tester);
      await tester.tap(find.byKey(const Key('addAgent')));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('agName')), 'Bad Name');
      await tester.tap(find.byKey(const Key('agSubmit')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('agError')), findsOneWidget);
      expect(log, isEmpty);

      await tester.enterText(find.byKey(const Key('agName')), 'Newbie');
      await tester.tap(find.text('gemini'));
      await tester.enterText(find.byKey(const Key('agRole')), 'REVIEW');
      await tester.tap(find.byKey(const Key('agSubmit')));
      await tester.pumpAndSettle();
      expect(log, ['add:newbie:gemini:REVIEW:']);
      expect(find.byKey(const Key('newAgentToken')), findsOneWidget);
      expect(find.text('new-token-abc'), findsOneWidget);

      await tester.tap(find.text('Tamam'));
      await tester.pumpAndSettle();
      expect(find.text('new-token-abc'), findsNothing);
      expect(state.agents.any((a) => a.id == 'newbie'), isTrue);
      expect(state.toString(), isNot(contains('new-token-abc')));
    });

    testWidgets('without the user token there are no management controls', (tester) async {
      await pump(tester, me: 'claude2');
      expect(find.byKey(const Key('addAgent')), findsNothing);
      expect(find.byKey(const Key('agent-toggle-claude1')), findsNothing);
      expect(find.byKey(const Key('agent-remove-helper')), findsNothing);
    });
  });
}
