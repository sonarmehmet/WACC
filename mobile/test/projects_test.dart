import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wacc_mobile/api/hub_client.dart';
import 'package:wacc_mobile/approvals_state.dart';
import 'package:wacc_mobile/models.dart';
import 'package:wacc_mobile/projects_state.dart';
import 'package:wacc_mobile/settings.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// A fake Backend with the user-only rule of the real one.
class FakeProjectsBackend extends BackendClient {
  FakeProjectsBackend(this.rows, this.log, String token)
      : super(baseUrl: 'http://backend.test', token: token);

  final List<Map<String, dynamic>> rows;
  final List<String> log;

  void _needUser() {
    if (token != 'tok-human') throw const HubException('forbidden', statusCode: 403);
  }

  @override
  Future<List<ApprovalItem>> approvals({String? status, int limit = 50}) async => const [];

  @override
  Future<List<Workspace>> workspaces() async => rows.map(Workspace.fromJson).toList();

  @override
  Future<void> addWorkspace(String title, String folder) async {
    _needUser();
    log.add('add:$title|$folder');
    rows.add({'name': title.toLowerCase(), 'title': title, 'folder': folder.isEmpty ? '/auto/$title' : folder, 'agents': <String>[], 'exists': true});
  }

  @override
  Future<void> removeWorkspace(String name) async {
    _needUser();
    log.add('remove:$name');
    rows.removeWhere((r) => r['name'] == name);
  }

  @override
  Future<void> assignWorkspaceAgent(String name, String agent) async {
    _needUser();
    log.add('assign:$name:$agent');
    (rows.firstWhere((r) => r['name'] == name)['agents'] as List).add(agent);
  }

  @override
  Future<void> unassignWorkspaceAgent(String name, String agent) async {
    _needUser();
    log.add('unassign:$name:$agent');
    (rows.firstWhere((r) => r['name'] == name)['agents'] as List).remove(agent);
  }
}

void main() {
  test('Workspace parses and tolerates odd values', () {
    final w = Workspace.fromJson({'name': 'site', 'title': 'Site', 'folder': r'C:\p\site', 'agents': ['claude1'], 'exists': true});
    expect([w.name, w.title, w.folder, w.exists], ['site', 'Site', r'C:\p\site', true]);
    expect(w.agents, ['claude1']);
    final odd = Workspace.fromJson({'name': 'x', 'agents': 'nope'});
    expect([odd.title, odd.exists], ['x', false]);
    expect(odd.agents, isEmpty);
  });

  test('BackendClient project calls use the project routes with the token in a header', () async {
    final seen = <http.Request>[];
    final client = BackendClient(
      baseUrl: 'http://b.test:8800',
      token: 'tok-human',
      client: MockClient((request) async {
        seen.add(request);
        return _json(request.method == 'GET' ? [] : {'ok': true}, request.method == 'POST' ? 201 : 200);
      }),
    );
    await client.workspaces();
    await client.addWorkspace('Site', r'C:\p\site');
    await client.assignWorkspaceAgent('site', 'claude1');
    await client.unassignWorkspaceAgent('site', 'claude1');
    await client.removeWorkspace('site');
    expect(seen.map((r) => '${r.method} ${r.url.path}').toList(), [
      'GET /workspaces',
      'POST /workspaces',
      'POST /workspaces/site/agents',
      'DELETE /workspaces/site/agents/claude1',
      'DELETE /workspaces/site',
    ]);
    expect(jsonDecode(seen[1].body), {'title': 'Site', 'folder': r'C:\p\site'});
    expect(seen.every((r) => r.headers['X-WACC-Token'] == 'tok-human'), isTrue);
  });

  group('ProjectsState', () {
    late List<Map<String, dynamic>> rows;
    late List<String> log;
    late ApprovalsState approvals;
    late ProjectsState projects;

    setUp(() {
      rows = [
        {'name': 'site', 'title': 'Site', 'folder': '/p/site', 'agents': <String>['claude1'], 'exists': true},
      ];
      log = [];
      approvals = ApprovalsState(factory: (url, token) => FakeProjectsBackend(rows, log, token));
      approvals.configure(const Settings(backendToken: 'tok-agent'));
      projects = ProjectsState(approvals);
    });

    tearDown(() {
      projects.dispose();
      approvals.dispose();
    });

    Future<void> settle() async {
      for (var i = 0; i < 6; i++) {
        await Future<void>.delayed(Duration.zero);
      }
      await projects.refresh();
    }

    test('reads with the Backend token, cannot change, and knows each agent\'s projects', () async {
      await settle();
      expect(projects.list.single.title, 'Site');
      expect(projects.projectsOf('claude1'), ['Site']);
      expect(projects.projectsOf('claude2'), isEmpty);
      expect(projects.canChange, isFalse);
      expect(await projects.add('Yeni', ''), 'Önce kullanıcı tokenını gir');
      expect(log, isEmpty);
    });

    test('an agent token used as the user token gets the 403 message', () async {
      approvals.setApprovalToken('tok-agent');
      await settle();
      expect(await projects.add('Yeni', ''), contains('kullanıcı tokenı gerekir'));
      expect(log, isEmpty);
    });

    test('with the user token: create, assign, unassign and remove', () async {
      approvals.setApprovalToken('tok-human');
      await settle();
      expect(await projects.add('A', ''), 'Proje adı en az 2 karakter olmalı');
      expect(await projects.add('Mobil', r'C:\Users\sen\Belgeler\mobil'), isNull);
      final mobil = projects.list.firstWhere((w) => w.name == 'mobil');
      expect(mobil.folder, r'C:\Users\sen\Belgeler\mobil');
      expect(await projects.assign(mobil, 'claude2'), isNull);
      expect(projects.projectsOf('claude2'), ['Mobil']);
      expect(await projects.unassign(mobil, 'claude2'), isNull);
      expect(projects.projectsOf('claude2'), isEmpty);
      expect(await projects.remove(mobil), isNull);
      expect(projects.list.map((w) => w.name), ['site']);
      expect(log, [r'add:Mobil|C:\Users\sen\Belgeler\mobil', 'assign:mobil:claude2', 'unassign:mobil:claude2', 'remove:mobil']);
    });
  });
}
