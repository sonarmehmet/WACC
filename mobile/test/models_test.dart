import 'package:flutter_test/flutter_test.dart';
import 'package:wacc_mobile/models.dart';

void main() {
  test('Agent.fromJson reads the /agents row', () {
    final agent = Agent.fromJson({
      'agent_id': 'claude2',
      'role': 'BACKEND_CORE',
      'status': 'ACTIVE',
      'current_task': 'T-0001',
      'last_seen': '2026-10-31T12:24:42.702547Z',
      'last_commit': 'abcdef1234567890',
      'online': true,
      'unread': 3,
      'pending_responses': 1,
      'awaiting_reply': 2,
      'active_tasks': 4,
      'blocked_tasks': 0,
      'last_sent': {'subject': 'hello', 'receiver': 'user', 'timestamp': 'x'},
    });
    expect(agent.id, 'claude2');
    expect(agent.online, isTrue);
    expect(agent.unread, 3);
    expect(agent.pendingResponses, 1);
    expect(agent.activeTasks, 4);
    expect(agent.lastSentSubject, 'hello');
    expect(agent.lastSentReceiver, 'user');
  });

  test('Agent.fromJson tolerates nulls and missing keys', () {
    final agent = Agent.fromJson({'agent_id': 'gemini', 'last_sent': null});
    expect(agent.status, 'OFFLINE');
    expect(agent.online, isFalse);
    expect(agent.unread, 0);
    expect(agent.lastSentSubject, isNull);
  });

  test('FeedMessage treats response_required 0/1 as bool', () {
    final yes = FeedMessage.fromJson({'response_required': 1, 'message_type': 'SYSTEM_ALERT'});
    final no = FeedMessage.fromJson({'response_required': 0});
    expect(yes.responseRequired, isTrue);
    expect(yes.isAlert, isTrue);
    expect(no.responseRequired, isFalse);
  });

  test('HubTask.fromJson reads lists and nullable fields', () {
    final task = HubTask.fromJson({
      'task_id': 'T-0005',
      'title': 'Web panel',
      'status': 'ASSIGNED',
      'priority': 'HIGH',
      'owner': 'claude3',
      'affected_files': ['web'],
      'dependencies': ['T-0001'],
      'commit_hash': null,
    });
    expect(task.id, 'T-0005');
    expect(task.files, ['web']);
    expect(task.dependencies, ['T-0001']);
    expect(task.commit, isNull);
  });

  test('ago and shortTime handle missing and bad values', () {
    expect(ago(null), 'hiç');
    expect(shortTime('not a date'), '-');
    final now = DateTime.utc(2026, 10, 31, 12, 10);
    expect(ago('2026-10-31T12:00:00Z', now: now), '10 dk önce');
    expect(ago('2026-10-31T12:09:50Z', now: now), '10 sn önce');
  });
}
