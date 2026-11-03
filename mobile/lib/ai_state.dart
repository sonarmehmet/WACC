import 'package:flutter/foundation.dart';

import 'api/hub_client.dart';
import 'approvals_state.dart';
import 'models.dart';

final RegExp aiNamePattern = RegExp(r'^[a-z0-9][a-z0-9_-]{1,30}$');

/// State of the AI accounts screen (Backend: /ai/providers, /ai/usage, /ai/accounts).
///
/// SECURITY: reading uses whatever Backend token is available; adding, removing, switching and
/// testing need the user's token, which lives only in [ApprovalsState] (memory, 5-minute idle
/// drop). This class never sees or keeps it. The API key of a new account is passed straight to
/// the request in [add] and is not stored in a field, a log or the result.
class AiState extends ChangeNotifier {
  AiState(this._approvals) {
    _approvals.addListener(_tokensChanged);
  }

  final ApprovalsState _approvals;

  List<AiProvider> providers = const [];
  AiUsage? usage;
  final Map<String, AiTestResult?> tests = {}; // null = running
  bool connected = false;
  bool loaded = false;
  String? error;

  bool _refreshing = false;
  bool _again = false;
  bool _disposed = false;
  bool _hadUserToken = false;
  bool _hadAnyToken = false;

  bool get canChange => _approvals.hasApprovalToken;

  void _tokensChanged() {
    // The user token or the Backend settings changed: forget what the old token could see.
    final user = _approvals.hasApprovalToken;
    final any = _approvals.hasAnyToken;
    if (user == _hadUserToken && any == _hadAnyToken) return;
    _hadUserToken = user;
    _hadAnyToken = any;
    providers = const [];
    usage = null;
    tests.clear();
    connected = false;
    loaded = false;
    error = null;
    notifyListeners();
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
        connected = false;
        providers = const [];
        error = 'Ayarlardan Backend tokenı gir veya kullanıcı tokenını yaz';
        return;
      }
      try {
        final list = await client.aiProviders();
        final spent = await client.aiUsage();
        providers = list;
        usage = spent;
        connected = true;
        error = null;
      } on HubException catch (e) {
        connected = false;
        providers = const [];
        error = e.message;
      } on Exception {
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

  /// Adds an account. [apiKey] is optional for local accounts and required for cloud ones.
  Future<String?> add({
    required String name,
    required String kind,
    required String baseUrl,
    required String model,
    String apiKey = '',
    double? priceIn,
    double? priceOut,
    bool enabled = true,
  }) {
    final id = name.trim().toLowerCase();
    if (!aiNamePattern.hasMatch(id)) {
      return Future.value('Ad 2-31 karakter olmalı: a-z, 0-9, - veya _');
    }
    if (kind == 'cloud' && apiKey.isEmpty) {
      return Future.value('Bulut hesabı için API anahtarı gerekli');
    }
    final body = <String, Object?>{
      'name': id,
      'kind': kind,
      'base_url': baseUrl.trim(),
      'model': model.trim(),
      'enabled': enabled,
      if (apiKey.isNotEmpty) 'api_key': apiKey,
      if (priceIn != null) 'price_in_per_1k': priceIn,
      if (priceOut != null) 'price_out_per_1k': priceOut,
    };
    return _change((c) => c.addAiAccount(body));
  }

  Future<String?> remove(AiProvider p) {
    tests.remove(p.name);
    return _change((c) => c.removeAiAccount(p.name));
  }

  Future<String?> toggle(AiProvider p) => _change((c) => c.setAiEnabled(p.name, !p.enabled));

  Future<String?> test(AiProvider p) async {
    final client = _approvals.userClient;
    if (client == null) return 'Önce kullanıcı tokenını gir';
    tests[p.name] = null;
    notifyListeners();
    try {
      tests[p.name] = await client.testAiProvider(p.name);
      _approvals.keepTokenAlive();
    } on HubException catch (e) {
      tests[p.name] = AiTestResult(ok: false, error: _friendly(e));
    }
    notifyListeners();
    refresh();
    return null;
  }

  @override
  void dispose() {
    _disposed = true;
    _approvals.removeListener(_tokensChanged);
    super.dispose();
  }
}
