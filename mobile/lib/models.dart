// Data classes for the Communication Hub API. Everything that comes from the Hub is
// untrusted agent text: it is only ever shown with Text widgets, never interpreted.

import 'dart:convert';

const List<String> agentIds = ['claude1', 'claude2', 'claude3', 'gemini', 'user'];
const List<String> workerIds = ['claude1', 'claude2', 'claude3', 'gemini'];
const List<String> leaderIds = ['claude1', 'user'];
const String broadcastId = 'ALL';

const List<String> messageTypes = [
  'TASK_ASSIGNMENT',
  'TASK_ACCEPTED',
  'TASK_COMPLETED',
  'TASK_BLOCKED',
  'HELP_REQUEST',
  'HELP_RESPONSE',
  'CODE_READY',
  'REVIEW_REQUEST',
  'REVIEW_RESULT',
  'BUG_REPORT',
  'BUG_FIXED',
  'INTEGRATION_REQUEST',
  'INTEGRATION_RESULT',
  'TECHNICAL_DECISION',
  'HANDOFF',
  'STATUS_UPDATE',
  'SYSTEM_ALERT',
];
const List<String> priorities = ['LOW', 'NORMAL', 'HIGH', 'CRITICAL'];
const List<String> taskStatusOrder = [
  'BLOCKED',
  'REVIEW',
  'IN_PROGRESS',
  'ACCEPTED',
  'ASSIGNED',
  'BACKLOG',
  'COMPLETED',
  'CANCELLED',
];

String? _str(Object? v) => v?.toString();
int _int(Object? v) => v is num ? v.toInt() : (int.tryParse('$v') ?? 0);
bool _bool(Object? v) => v == true || v == 1;
List<String> _strList(Object? v) =>
    v is List ? v.map((e) => e.toString()).toList() : const <String>[];

class Agent {
  const Agent({
    required this.id,
    required this.role,
    required this.status,
    required this.online,
    this.currentTask,
    this.lastSeen,
    this.lastCommit,
    this.unread = 0,
    this.pendingResponses = 0,
    this.awaitingReply = 0,
    this.activeTasks = 0,
    this.blockedTasks = 0,
    this.lastSentSubject,
    this.lastSentReceiver,
    this.kind = 'builtin',
    this.enabled = true,
  });

  factory Agent.fromJson(Map<String, dynamic> j) {
    final lastSent = j['last_sent'];
    return Agent(
      id: _str(j['agent_id']) ?? '?',
      role: _str(j['role']) ?? '',
      status: _str(j['status']) ?? 'OFFLINE',
      online: _bool(j['online']),
      currentTask: _str(j['current_task']),
      lastSeen: _str(j['last_seen']),
      lastCommit: _str(j['last_commit']),
      unread: _int(j['unread']),
      pendingResponses: _int(j['pending_responses']),
      awaitingReply: _int(j['awaiting_reply']),
      activeTasks: _int(j['active_tasks']),
      blockedTasks: _int(j['blocked_tasks']),
      lastSentSubject: lastSent is Map ? _str(lastSent['subject']) : null,
      lastSentReceiver: lastSent is Map ? _str(lastSent['receiver']) : null,
      kind: _str(j['kind']) ?? 'builtin',
      enabled: j['enabled'] == null ? true : _bool(j['enabled']),
    );
  }

  final String id;
  final String role;
  final String status;
  final bool online;
  final String? currentTask;
  final String? lastSeen;
  final String? lastCommit;
  final int unread;
  final int pendingResponses;
  final int awaitingReply;
  final int activeTasks;
  final int blockedTasks;
  final String? lastSentSubject;
  final String? lastSentReceiver;
  final String kind;
  final bool enabled;

  /// Dynamic accounts (added by the user) can be removed; built-in ones can only be switched off.
  bool get removable => kind != 'builtin';
}

class FeedMessage {
  const FeedMessage({
    required this.id,
    required this.conversationId,
    required this.sender,
    required this.receiver,
    required this.timestamp,
    required this.type,
    required this.priority,
    required this.subject,
    required this.content,
    required this.status,
    required this.responseRequired,
    this.taskId,
  });

  factory FeedMessage.fromJson(Map<String, dynamic> j) => FeedMessage(
        id: _str(j['message_id']) ?? '',
        conversationId: _str(j['conversation_id']) ?? '',
        sender: _str(j['sender']) ?? '?',
        receiver: _str(j['receiver']) ?? '?',
        timestamp: _str(j['timestamp']) ?? '',
        type: _str(j['message_type']) ?? '',
        priority: _str(j['priority']) ?? 'NORMAL',
        subject: _str(j['subject']) ?? '',
        content: _str(j['content']) ?? '',
        status: _str(j['status']) ?? '',
        responseRequired: _bool(j['response_required']),
        taskId: _str(j['task_id']),
      );

  final String id;
  final String conversationId;
  final String sender;
  final String receiver;
  final String timestamp;
  final String type;
  final String priority;
  final String subject;
  final String content;
  final String status;
  final bool responseRequired;
  final String? taskId;

  bool get isAlert => type == 'SYSTEM_ALERT';
}

class HubTask {
  const HubTask({
    required this.id,
    required this.title,
    required this.status,
    required this.priority,
    this.description = '',
    this.owner,
    this.creator,
    this.acceptance = '',
    this.testCriteria = '',
    this.branch,
    this.commit,
    this.note,
    this.files = const [],
    this.dependencies = const [],
  });

  factory HubTask.fromJson(Map<String, dynamic> j) => HubTask(
        id: _str(j['task_id']) ?? '?',
        title: _str(j['title']) ?? '',
        status: _str(j['status']) ?? '',
        priority: _str(j['priority']) ?? 'NORMAL',
        description: _str(j['description']) ?? '',
        owner: _str(j['owner']),
        creator: _str(j['creator']),
        acceptance: _str(j['acceptance']) ?? '',
        testCriteria: _str(j['test_criteria']) ?? '',
        branch: _str(j['branch']),
        commit: _str(j['commit_hash']),
        note: _str(j['note']),
        files: _strList(j['affected_files']),
        dependencies: _strList(j['dependencies']),
      );

  final String id;
  final String title;
  final String status;
  final String priority;
  final String description;
  final String? owner;
  final String? creator;
  final String acceptance;
  final String testCriteria;
  final String? branch;
  final String? commit;
  final String? note;
  final List<String> files;
  final List<String> dependencies;
}

/// "2026-10-31T12:24:42.702547Z" -> "31.10 15:24" (local time); "-" when unparsable.
String shortTime(String? iso) {
  final parsed = iso == null ? null : DateTime.tryParse(iso);
  if (parsed == null) return '-';
  final t = parsed.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.day)}.${two(t.month)} ${two(t.hour)}:${two(t.minute)}';
}

/// "3 dk önce" style age; "hiç" when there is no timestamp.
String ago(String? iso, {DateTime? now}) {
  final parsed = iso == null ? null : DateTime.tryParse(iso);
  if (parsed == null) return 'hiç';
  final seconds = (now ?? DateTime.now()).difference(parsed).inSeconds;
  if (seconds < 60) return '${seconds < 0 ? 0 : seconds} sn önce';
  if (seconds < 3600) return '${seconds ~/ 60} dk önce';
  if (seconds < 86400) return '${seconds ~/ 3600} sa önce';
  return '${seconds ~/ 86400} gün önce';
}

/// Action classes that deserve extra care when approving (docs/EXECUTION_SECURITY.md).
const List<String> riskyActionClasses = [
  'DELETE',
  'SYSTEM_CHANGE',
  'PUBLISH',
  'PERSONAL_FILES',
  'FINANCIAL',
  'SECRET_EXPORT',
];

/// A request by an agent that needs the user's approval (Backend `/exec/approvals`).
class ApprovalItem {
  const ApprovalItem({
    required this.id,
    required this.requestedBy,
    required this.actionClass,
    required this.action,
    required this.actionHash,
    required this.riskSummary,
    required this.status,
    required this.createdAt,
    required this.expiresAt,
    this.decidedBy,
    this.decidedAt,
  });

  factory ApprovalItem.fromJson(Map<String, dynamic> j) {
    final raw = j['action'];
    return ApprovalItem(
      id: _int(j['id']),
      requestedBy: _str(j['requested_by']) ?? '?',
      actionClass: _str(j['action_class']) ?? '?',
      action: raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{'raw': _str(raw) ?? ''},
      actionHash: _str(j['action_hash']) ?? '',
      riskSummary: _str(j['risk_summary']) ?? '',
      status: _str(j['status']) ?? '',
      createdAt: _str(j['created_at']) ?? '',
      expiresAt: _str(j['expires_at']) ?? '',
      decidedBy: _str(j['decided_by']),
      decidedAt: _str(j['decided_at']),
    );
  }

  final int id;
  final String requestedBy;
  final String actionClass;

  /// The normalized action exactly as the Backend will run it. This is what the user must read.
  final Map<String, dynamic> action;
  final String actionHash;

  /// Backend's own risk text. Helpful, but the raw [action] is what counts.
  final String riskSummary;
  final String status;
  final String createdAt;
  final String expiresAt;
  final String? decidedBy;
  final String? decidedAt;

  bool get isRisky => riskyActionClasses.contains(actionClass);

  String get prettyAction => const JsonEncoder.withIndent('  ').convert(action);

  /// One line, clipped, for dialogs and lists.
  String get shortAction {
    final text = jsonEncode(action);
    return text.length > 300 ? '${text.substring(0, 300)}…' : text;
  }

  String get shortHash => actionHash.length > 16 ? '${actionHash.substring(0, 16)}…' : actionHash;
}

class ExecStatus {
  const ExecStatus({required this.emergencyStop, this.roots = const []});

  factory ExecStatus.fromJson(Map<String, dynamic> j) => ExecStatus(
        emergencyStop: _bool(j['emergency_stop']),
        roots: _strList(j['roots']),
      );

  final bool emergencyStop;
  final List<String> roots;
}

class AuditEntry {
  const AuditEntry({
    required this.ts,
    required this.agent,
    required this.actionClass,
    required this.outcome,
    required this.summary,
    this.durationMs = 0,
  });

  factory AuditEntry.fromJson(Map<String, dynamic> j) => AuditEntry(
        ts: _str(j['ts']) ?? '',
        agent: _str(j['agent']) ?? '?',
        actionClass: _str(j['action_class']) ?? '?',
        outcome: _str(j['outcome']) ?? '',
        summary: _str(j['summary']) ?? '',
        durationMs: _int(j['duration_ms']),
      );

  final String ts;
  final String agent;
  final String actionClass;
  final String outcome;
  final String summary;
  final int durationMs;
}

/// "9 dk 05 sn kaldı", or "süresi doldu" once [expiresIso] has passed; "-" when unparsable.
String remainingText(String? expiresIso, {DateTime? now}) {
  final parsed = expiresIso == null ? null : DateTime.tryParse(expiresIso);
  if (parsed == null) return '-';
  final seconds = parsed.difference(now ?? DateTime.now()).inSeconds;
  if (seconds <= 0) return 'süresi doldu';
  return '${seconds ~/ 60} dk ${(seconds % 60).toString().padLeft(2, '0')} sn kaldı';
}

double _double(Object? v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);

/// An AI provider known to the Backend (an account added by the user, or one from llm.env).
/// All text comes from the Backend: show it with Text widgets only. The API key is never part
/// of this object: the Backend does not return it.
class AiProvider {
  const AiProvider({
    required this.name,
    required this.kind,
    required this.model,
    required this.enabled,
    required this.source,
    this.priceIn = 0,
    this.priceOut = 0,
  });

  factory AiProvider.fromJson(Map<String, dynamic> j) => AiProvider(
        name: j['name']?.toString() ?? '?',
        kind: j['kind']?.toString() ?? '?',
        model: j['model']?.toString() ?? '',
        enabled: _bool(j['enabled']),
        source: j['source']?.toString() ?? 'env',
        priceIn: _double(j['price_in_per_1k']),
        priceOut: _double(j['price_out_per_1k']),
      );

  final String name;
  final String kind; // local | cloud
  final String model;
  final bool enabled;
  final String source; // account | env
  final double priceIn;
  final double priceOut;

  /// Only accounts can be removed; environment providers can only be switched on or off.
  bool get removable => source == 'account';
  bool get isCloud => kind == 'cloud';
}

class AiUsage {
  const AiUsage({required this.budgetUsd, required this.spentUsd});

  factory AiUsage.fromJson(Map<String, dynamic> j) =>
      AiUsage(budgetUsd: _double(j['budget_usd']), spentUsd: _double(j['spent_usd']));

  final double budgetUsd;
  final double spentUsd;
}

class AiTestResult {
  const AiTestResult({
    required this.ok,
    this.reply = '',
    this.error = '',
    this.latencyMs = 0,
    this.model = '',
    this.category = '',
    this.hint = '',
  });

  factory AiTestResult.fromJson(Map<String, dynamic> j) => AiTestResult(
        ok: _bool(j['ok']),
        reply: j['reply']?.toString() ?? '',
        error: j['error']?.toString() ?? '',
        latencyMs: _int(j['latency_ms']),
        model: j['model']?.toString() ?? '',
        category: j['category_label']?.toString() ?? '',
        hint: j['hint']?.toString() ?? '',
      );

  final bool ok;
  final String reply;
  final String error;
  final int latencyMs;
  final String model; // the model that was really called
  final String category; // why it failed: API anahtarı / Kredi-lisans / Model adı / ...
  final String hint; // what to do about it
}

/// A project: one local folder on the computer plus the agents allowed to work in it (Backend /workspaces).
class Workspace {
  const Workspace({
    required this.name,
    required this.title,
    required this.folder,
    required this.agents,
    required this.exists,
  });

  factory Workspace.fromJson(Map<String, dynamic> j) => Workspace(
        name: j['name']?.toString() ?? '?',
        title: j['title']?.toString() ?? j['name']?.toString() ?? '?',
        folder: j['folder']?.toString() ?? '',
        agents: _strList(j['agents']),
        exists: _bool(j['exists']),
      );

  final String name;
  final String title;
  final String folder;
  final List<String> agents;
  final bool exists;
}
