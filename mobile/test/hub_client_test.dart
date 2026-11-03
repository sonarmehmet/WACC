import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wacc_mobile/api/hub_client.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

HubClient _client(MockClient mock, {String url = 'http://hub.test:8765/'}) =>
    HubClient(baseUrl: url, token: 'secret-token', client: mock);

void main() {
  test('sends the token header and trims the trailing slash', () async {
    late http.Request seen;
    final client = _client(MockClient((request) async {
      seen = request;
      return _json({'agent': 'user'});
    }));
    expect(await client.whoami(), 'user');
    expect(seen.url.toString(), 'http://hub.test:8765/whoami');
    expect(seen.headers['X-WACC-Token'], 'secret-token');
  });

  test('token never appears in the URL', () async {
    late Uri seen;
    final client = _client(MockClient((request) async {
      seen = request.url;
      return _json(<Object>[]);
    }));
    await client.feed(conversationId: 'CONV-1');
    expect(seen.toString(), isNot(contains('secret-token')));
    expect(seen.queryParameters['conversation_id'], 'CONV-1');
    expect(seen.queryParameters['limit'], '200');
  });

  test('agents() parses the overview', () async {
    final client = _client(MockClient((request) async => _json([
          {'agent_id': 'claude1', 'role': 'TEAM_LEADER', 'status': 'ACTIVE', 'online': true},
          {'agent_id': 'gemini', 'role': 'VISUAL_OPERATOR', 'status': 'OFFLINE', 'online': false},
        ])));
    final agents = await client.agents();
    expect(agents.map((a) => a.id), ['claude1', 'gemini']);
    expect(agents.first.online, isTrue);
  });

  test('sendMessage posts JSON with the idempotency key', () async {
    late http.Request seen;
    final client = _client(MockClient((request) async {
      seen = request;
      return _json({'message_id': 'M-1'});
    }));
    await client.sendMessage(
      receiver: 'claude2',
      messageType: 'HELP_REQUEST',
      subject: 'hi',
      content: 'body',
      priority: 'HIGH',
      responseRequired: true,
      idempotencyKey: 'k1',
    );
    expect(seen.method, 'POST');
    expect(seen.url.path, '/messages');
    expect(seen.headers['Content-Type'], contains('application/json'));
    final body = jsonDecode(seen.body) as Map<String, dynamic>;
    expect(body['receiver'], 'claude2');
    expect(body['response_required'], true);
    expect(body['idempotency_key'], 'k1');
    expect(body.containsKey('conversation_id'), isFalse);
  });

  test('401 becomes an unauthorized HubException', () async {
    final client = _client(MockClient((request) async => _json({'detail': 'Invalid'}, 401)));
    expect(
      client.whoami(),
      throwsA(isA<HubException>().having((e) => e.unauthorized, 'unauthorized', isTrue)),
    );
  });

  test('Hub error code and message are passed through', () async {
    final client = _client(MockClient((request) async => _json({
          'detail': {'code': 'FORBIDDEN', 'message': 'Only claude1 or the user can create/assign tasks'},
        }, 403)));
    expect(
      client.createTask(title: 'x'),
      throwsA(isA<HubException>()
          .having((e) => e.code, 'code', 'FORBIDDEN')
          .having((e) => e.statusCode, 'statusCode', 403)),
    );
  });

  test('network failure becomes UNREACHABLE', () async {
    final client = _client(MockClient((request) async => throw http.ClientException('boom')));
    expect(
      client.health(),
      throwsA(isA<HubException>().having((e) => e.code, 'code', 'UNREACHABLE')),
    );
  });

  test('a non-list response where a list is expected is rejected', () async {
    final client = _client(MockClient((request) async => _json({'oops': true})));
    expect(
      client.tasks(),
      throwsA(isA<HubException>().having((e) => e.code, 'code', 'BAD_RESPONSE')),
    );
  });

  test('agent management: token comes back once, names are encoded, token only in the header', () async {
    final seen = <http.Request>[];
    final client = _client(MockClient((request) async {
      seen.add(request);
      return _json({'agent': {'agent_id': 'gpt1'}, 'token': 'new-agent-token'}, request.method == 'POST' ? 201 : 200);
    }));
    expect(await client.registerAgent(name: 'gpt1', kind: 'chatgpt', provider: 'acc'), 'new-agent-token');
    await client.setAgentEnabled('gpt1', false);
    await client.removeAgent('a/b');
    expect(seen[0].url.path, '/agents');
    expect(jsonDecode(seen[0].body), {'name': 'gpt1', 'kind': 'chatgpt', 'role': '', 'provider': 'acc'});
    expect(seen[1].url.path, '/agents/gpt1/enabled');
    expect(jsonDecode(seen[1].body), {'enabled': false});
    expect(seen[2].method, 'DELETE');
    expect(seen[2].url.toString(), 'http://hub.test:8765/agents/a%2Fb');
    expect(seen[0].headers['X-WACC-Token'], 'secret-token');
  });
}
