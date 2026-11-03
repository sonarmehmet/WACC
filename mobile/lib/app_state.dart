import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api/hub_client.dart';
import 'ai_state.dart';
import 'approvals_state.dart';
import 'models.dart';
import 'settings.dart';

/// Holds everything the screens show and talks to the Hub. Screens only read from here and
/// call the action methods; the action methods return an error text (or null on success)
/// so the UI can show it.
class AppState extends ChangeNotifier {
  AppState({
    required this.store,
    HubClientFactory? clientFactory,
    BackendClientFactory? backendFactory,
    this.pollInterval = const Duration(seconds: 5),
    Duration approvalIdleTimeout = const Duration(minutes: 5),
  })  : _factory = clientFactory ?? ((url, token) => HubClient(baseUrl: url, token: token)),
        approvals = ApprovalsState(factory: backendFactory, idleTimeout: approvalIdleTimeout) {
    ai = AiState(approvals);
  }

  /// AI accounts (Backend). Reads with the Backend token; changes need the user token.
  late final AiState ai;

  /// Approval requests and decisions (Backend). Owned here so settings changes reach it.
  final ApprovalsState approvals;

  final SettingsStore store;
  final HubClientFactory _factory;

  /// `null` turns polling off (tests).
  final Duration? pollInterval;

  Settings settings = const Settings();
  String? me;
  bool connected = false;
  bool emergencyStop = false;
  bool firstLoadDone = false;
  String? error;
  String? conversationFilter;

  List<Agent> agents = const [];
  List<FeedMessage> feed = const [];
  List<HubTask> tasks = const [];

  HubClient? _client;
  Timer? _timer;
  bool _refreshing = false;
  bool _disposed = false;

  bool get isLeader => me != null && leaderIds.contains(me);
  bool get isUser => me == 'user';

  Future<void> start() async {
    settings = await store.load();
    _rebuildClient();
    approvals.configure(settings);
    await refresh();
    final interval = pollInterval;
    if (interval != null && !_disposed) {
      _timer?.cancel();
      _timer = Timer.periodic(interval, (_) {
        refresh();
        approvals.refresh();
      });
    }
  }

  void _rebuildClient() {
    _client?.close();
    _client = settings.hasToken ? _factory(settings.baseUrl, settings.token) : null;
  }

  Future<void> updateSettings(Settings next) async {
    await store.save(next);
    settings = next;
    me = null;
    connected = false;
    firstLoadDone = false;
    agents = const [];
    feed = const [];
    tasks = const [];
    conversationFilter = null;
    _rebuildClient();
    approvals.configure(next);
    notifyListeners();
    await refresh();
  }

  Future<void> refresh() async {
    if (_refreshing || _disposed) return;
    final client = _client;
    if (client == null) {
      connected = false;
      error = 'Ayarlardan token gir';
      _notify();
      return;
    }
    _refreshing = true;
    try {
      final health = await client.health();
      emergencyStop = health['emergency_stop'] == true;
      me = await client.whoami();
      agents = await client.agents();
      feed = await client.feed(conversationId: conversationFilter);
      tasks = await client.tasks();
      connected = true;
      error = null;
    } on HubException catch (e) {
      connected = false;
      error = e.message;
      if (e.unauthorized) me = null;
    } on Exception {
      connected = false;
      error = 'Beklenmeyen hata';
    } finally {
      firstLoadDone = true;
      _refreshing = false;
      _notify();
    }
  }

  Future<void> setConversationFilter(String? id) async {
    conversationFilter = (id == null || id.isEmpty) ? null : id;
    notifyListeners();
    await refresh();
  }

  Future<String?> sendMessage({
    required String receiver,
    required String messageType,
    required String subject,
    String content = '',
    String priority = 'NORMAL',
    bool responseRequired = false,
  }) {
    return _run((c) => c.sendMessage(
          receiver: receiver,
          messageType: messageType,
          subject: subject,
          content: content,
          priority: priority,
          responseRequired: responseRequired,
          conversationId: conversationFilter,
          idempotencyKey: '${DateTime.now().microsecondsSinceEpoch}-${subject.hashCode}',
        ));
  }

  Future<String?> createTask({
    required String title,
    String description = '',
    String? owner,
    String priority = 'NORMAL',
    List<String> files = const [],
    String acceptance = '',
    String testCriteria = '',
  }) {
    return _run((c) => c.createTask(
          title: title,
          description: description,
          owner: owner,
          priority: priority,
          files: files,
          acceptance: acceptance,
          testCriteria: testCriteria,
        ));
  }

  Future<String?> acceptTask(String taskId) => _run((c) => c.acceptTask(taskId));

  Future<String?> setTaskStatus(String taskId, String status, {String? commit, String? note}) =>
      _run((c) => c.setTaskStatus(taskId, status, commit: commit, note: note));

  Future<String?> stopAll() => _run((c) => c.emergencyStop('mobile app: manual stop'));

  Future<String?> resumeAll() => _run((c) => c.resume());

  Future<String?> _run(Future<void> Function(HubClient client) action) async {
    final client = _client;
    if (client == null) return 'Ayarlardan token gir';
    try {
      await action(client);
    } on HubException catch (e) {
      return e.message;
    }
    await refresh();
    return null;
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _client?.close();
    ai.dispose();
    approvals.dispose();
    super.dispose();
  }
}
