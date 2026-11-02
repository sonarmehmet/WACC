// Data classes for the Communication Hub API. Everything that comes from the Hub is
// untrusted agent text: it is only ever shown with Text widgets, never interpreted.

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
