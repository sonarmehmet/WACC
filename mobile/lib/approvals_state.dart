import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api/hub_client.dart';
import 'models.dart';
import 'settings.dart';

/// State of the approval screen: what agents ask to run, and the user's decisions.
///
/// SECURITY (docs/EXECUTION_SECURITY.md, section 4):
/// * Only the user's own token may approve, deny or resume. It is held ONLY in this object's
///   memory: never written to storage, dropped after [idleTimeout] without use, when the app
///   goes to the background (see WaccApp) and on [forgetApprovalToken].
/// * Without it the screen is read-only and uses the Backend (agent) token from the settings
///   just to list requests. The Backend, not this app, enforces who may decide.
class ApprovalsState extends ChangeNotifier {
  ApprovalsState({
    BackendClientFactory? factory,
    this.idleTimeout = const Duration(minutes: 5),
  }) : _factory = factory ?? ((url, token) => BackendClient(baseUrl: url, token: token));

  final BackendClientFactory _factory;
  final Duration idleTimeout;

  Settings _settings = const Settings();
  BackendClient? _viewClient; // Backend (agent) token from the settings: read only
  BackendClient? _approvalClient; // user token, memory only
  String _approvalToken = '';
  Timer? _idleTimer;

  List<ApprovalItem> pending = const [];
  List<ApprovalItem> history = const [];
  List<AuditEntry> audit = const [];
  ExecStatus? execStatus;
  bool connected = false;
  bool loaded = false;
  String? error;

  int _generation = 0;
  bool _refreshing = false;
  bool _again = false;
  bool _disposed = false;
  bool _watching = false;

  int get pendingCount => pending.length;
  bool get hasApprovalToken => _approvalToken.isNotEmpty;
  bool get hasAnyToken => _approvalClient != null || _viewClient != null;

  BackendClient? get _active => _approvalClient ?? _viewClient;

  /// For the AI accounts screen: the client to read with, the user's client (memory-only
  /// token) for changes, and a way to keep the token alive while it is being used.
  BackendClient? get readClient => _active;
  BackendClient? get userClient => _approvalClient;
  void keepTokenAlive() => _touch();

  /// True while the approvals screen is on screen: then history, audit and status are fetched
  /// too; otherwise only the pending count is polled.
  bool get watching => _watching;

  set watching(bool value) {
    if (_watching == value) return;
    _watching = value;
    if (value) refresh();
  }

  /// Called by AppState when the settings are loaded or changed.
  void configure(Settings settings) {
    _settings = settings;
    _viewClient?.close();
    _viewClient = settings.hasBackendToken ? _factory(settings.backendUrl, settings.backendToken) : null;
    _approvalClient?.close();
    _approvalClient = hasApprovalToken ? _factory(settings.backendUrl, _approvalToken) : null;
    _reset();
    refresh();
  }

  void setApprovalToken(String token) {
    final value = token.trim();
    _idleTimer?.cancel();
    _approvalClient?.close();
    _approvalToken = value;
    _approvalClient = value.isEmpty ? null : _factory(_settings.backendUrl, value);
    if (value.isNotEmpty) _startIdleTimer();
    _reset();
    notifyListeners();
    refresh();
  }

  void forgetApprovalToken() {
    if (!hasApprovalToken) return;
    setApprovalToken('');
  }

  void _startIdleTimer() {
    _idleTimer?.cancel();
    _idleTimer = Timer(idleTimeout, forgetApprovalToken);
  }

  void _touch() {
    if (hasApprovalToken) _startIdleTimer();
  }

  void _reset() {
    _generation += 1;
    pending = const [];
    history = const [];
    audit = const [];
    execStatus = null;
    connected = false;
    loaded = false;
    error = null;
  }

  Future<void> refresh() async {
    if (_disposed) return;
    if (_refreshing) {
      _again = true;
      return;
    }
    _refreshing = true;
    final generation = _generation;
    try {
      final client = _active;
      if (client == null) {
        connected = false;
        error = 'Ayarlardan Backend tokenı gir veya onay tokenını yaz';
        return;
      }
      try {
        final list = await client.approvals(status: 'PENDING');
        if (generation != _generation) return;
        pending = list;
        if (_watching) {
          final status = await client.execStatus();
          final recent = await client.approvals(limit: 30);
          final log = await client.audit();
          if (generation != _generation) return;
          execStatus = status;
          history = recent.where((a) => a.status != 'PENDING').toList();
          audit = log;
        }
        connected = true;
        error = null;
      } on HubException catch (e) {
        if (generation != _generation) return;
        connected = false;
        pending = const [];
        error = e.message;
      } on Exception {
        if (generation != _generation) return;
        connected = false;
        error = 'Beklenmeyen hata';
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

  /// Approve or deny. Returns an error text, or null on success.
  Future<String?> decide(ApprovalItem item, {required bool approve}) async {
    final client = _approvalClient;
    if (client == null) return 'Önce onay tokenını gir';
    try {
      if (approve) {
        await client.approve(item.id);
      } else {
        await client.deny(item.id);
      }
    } on HubException catch (e) {
      return _friendly(e);
    }
    _touch();
    await refresh();
    return null;
  }

  /// The Backend answers 403 when the token is not the user's (agent tokens cannot decide).
  String _friendly(HubException e) {
    if (e.statusCode == 403) {
      return 'Bu token onay veremez: kullanıcı tokenı gerekir (ajan tokenı onaylayamaz)';
    }
    if (e.unauthorized) return 'Token geçersiz';
    return e.message;
  }

  /// Stop execution. Any Backend token may stop; only the user token may resume.
  Future<String?> stopExec() async {
    final client = _active;
    if (client == null) return 'Token gerekli';
    try {
      await client.stopExec('mobile app: manual stop');
    } on HubException catch (e) {
      return _friendly(e);
    }
    await refresh();
    return null;
  }

  Future<String?> resumeExec() async {
    final client = _approvalClient;
    if (client == null) return 'Devam ettirmek için onay tokenı gerekir';
    try {
      await client.resumeExec();
    } on HubException catch (e) {
      return _friendly(e);
    }
    _touch();
    await refresh();
    return null;
  }

  @override
  void dispose() {
    _disposed = true;
    _idleTimer?.cancel();
    _viewClient?.close();
    _approvalClient?.close();
    super.dispose();
  }
}
