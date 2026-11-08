import 'package:flutter/foundation.dart';

import 'api/hub_client.dart';
import 'approvals_state.dart';
import 'models.dart';

/// State of the Projeler screen (Backend: /workspaces). Reading uses whatever Backend token is available; adding,
/// removing and assigning agents need the user token, which lives only in [ApprovalsState].
class ProjectsState extends ChangeNotifier {
  ProjectsState(this._approvals) {
    _approvals.addListener(_tokensChanged);
  }

  final ApprovalsState _approvals;

  List<Workspace> list = const [];
  bool loaded = false;
  String? error;

  bool _refreshing = false;
  bool _again = false;
  bool _disposed = false;
  bool _hadUserToken = false;
  bool _hadAnyToken = false;

  bool get canChange => _approvals.hasApprovalToken;

  /// Names of the projects an agent works in (for the agent card).
  List<String> projectsOf(String agent) =>
      [for (final w in list) if (w.agents.contains(agent)) w.title];

  void _tokensChanged() {
    final user = _approvals.hasApprovalToken;
    final any = _approvals.hasAnyToken;
    if (user == _hadUserToken && any == _hadAnyToken) return;
    _hadUserToken = user;
    _hadAnyToken = any;
    refresh();
  }

  Future<void> refresh() async {
    if (_disposed) return;
    if (_refreshing) {
      _again = true;
      return;
    }
    _refreshing = true;
    try {
      final client = _approvals.readClient;
      if (client == null) {
        list = const [];
        error = 'Ayarlardan Backend tokenı gir veya kullanıcı tokenını yaz';
        return;
      }
      try {
        list = await client.workspaces();
        error = null;
      } on HubException catch (e) {
        list = const [];
        error = e.message;
      } on Exception {
        list = const [];
        error = 'Projeler okunamadı';
      }
    } finally {
      loaded = true;
      _refreshing = false;
      if (!_disposed) notifyListeners();
      if (_again) {
        _again = false;
        refresh();
      }
    }
  }

  String _friendly(HubException e) {
    if (e.statusCode == 403) return 'Bu token değiştiremez: kullanıcı tokenı gerekir';
    if (e.unauthorized) return 'Token geçersiz';
    return e.message;
  }

  /// Runs a change with the user's client. Returns an error text, or null on success.
  Future<String?> _change(Future<void> Function(BackendClient c) action) async {
    final client = _approvals.userClient;
    if (client == null) return 'Önce kullanıcı tokenını gir';
    try {
      await action(client);
    } on HubException catch (e) {
      await refresh();
      return _friendly(e);
    }
    _approvals.keepTokenAlive();
    await refresh();
    return null;
  }

  Future<String?> add(String title, String folder) {
    if (title.trim().length < 2) return Future.value('Proje adı en az 2 karakter olmalı');
    return _change((c) => c.addWorkspace(title.trim(), folder.trim()));
  }

  Future<String?> remove(Workspace w) => _change((c) => c.removeWorkspace(w.name));

  Future<String?> assign(Workspace w, String agent) => _change((c) => c.assignWorkspaceAgent(w.name, agent));

  Future<String?> unassign(Workspace w, String agent) => _change((c) => c.unassignWorkspaceAgent(w.name, agent));

  @override
  void dispose() {
    _disposed = true;
    _approvals.removeListener(_tokensChanged);
    super.dispose();
  }
}
