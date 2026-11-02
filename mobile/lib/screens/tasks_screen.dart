import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';

const Map<String, String> _statusLabels = {
  'BLOCKED': 'Engelli',
  'REVIEW': 'İncelemede',
  'IN_PROGRESS': 'Devam ediyor',
  'ACCEPTED': 'Kabul edildi',
  'ASSIGNED': 'Atandı',
  'BACKLOG': 'Bekleyen',
  'COMPLETED': 'Tamamlandı',
  'CANCELLED': 'İptal',
};

class TasksScreen extends StatelessWidget {
  const TasksScreen({super.key, required this.state});

  final AppState state;

  void _openCreate(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
        child: TaskComposer(state: state),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final groups = <Widget>[];
    for (final status in taskStatusOrder) {
      final list = state.tasks.where((t) => t.status == status).toList();
      if (list.isEmpty) continue;
      groups.add(Padding(
        padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
        child: Text(
          '${_statusLabels[status] ?? status} (${list.length})',
          style: Theme.of(context).textTheme.titleSmall,
        ),
      ));
      groups.addAll(list.map((t) => TaskCard(task: t, state: state)));
    }
    return Scaffold(
      backgroundColor: Colors.transparent,
      floatingActionButton: state.isLeader
          ? FloatingActionButton.extended(
              onPressed: () => _openCreate(context),
              icon: const Icon(Icons.add_task),
              label: const Text('Görev ver'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: state.refresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 88),
          children: groups.isEmpty
              ? [
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 48),
                    child: Center(
                      child: Text(
                        state.firstLoadDone ? (state.error ?? 'Henüz görev yok.') : 'Yükleniyor…',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ]
              : groups,
        ),
      ),
    );
  }
}

class TaskCard extends StatelessWidget {
  const TaskCard({super.key, required this.task, required this.state});

  final HubTask task;
  final AppState state;

  Future<void> _run(BuildContext context, Future<String?> Function() action) async {
    final err = await action();
    if (err != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final meta = [
      if (task.branch != null) 'dal: ${task.branch}',
      if (task.commit != null) 'commit: ${task.commit!.length > 10 ? task.commit!.substring(0, 10) : task.commit}',
      if (task.dependencies.isNotEmpty) 'bağımlı: ${task.dependencies.join(', ')}',
      if (task.files.isNotEmpty) 'dosyalar: ${task.files.join(', ')}',
    ].join(' · ');
    final canAct = state.me != null && (task.owner == state.me || state.isLeader);
    return Card(
      child: ExpansionTile(
        title: Text('${task.id}  ${task.title}'),
        subtitle: Text(
          '${task.owner == null ? 'sahipsiz' : '→ ${task.owner}'}'
          '${task.priority == 'NORMAL' ? '' : ' · ${task.priority}'}',
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (meta.isNotEmpty) Text(meta, style: Theme.of(context).textTheme.bodySmall),
          if (task.note != null) Text('Not: ${task.note}'),
          if (task.description.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(task.description),
          ],
          if (task.acceptance.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Kabul: ${task.acceptance}', style: Theme.of(context).textTheme.bodySmall),
          ],
          if (task.testCriteria.isNotEmpty)
            Text('Test: ${task.testCriteria}', style: Theme.of(context).textTheme.bodySmall),
          if (canAct) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                if (task.owner == state.me && task.status == 'ASSIGNED')
                  FilledButton.tonal(
                    onPressed: () => _run(context, () => state.acceptTask(task.id)),
                    child: const Text('Kabul et'),
                  ),
                PopupMenuButton<String>(
                  tooltip: 'Durumu değiştir',
                  onSelected: (status) => _run(context, () => state.setTaskStatus(task.id, status)),
                  itemBuilder: (_) => [
                    for (final s in taskStatusOrder)
                      PopupMenuItem(value: s, child: Text(_statusLabels[s] ?? s)),
                  ],
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    child: Text('Durumu değiştir'),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class TaskComposer extends StatefulWidget {
  const TaskComposer({super.key, required this.state});

  final AppState state;

  @override
  State<TaskComposer> createState() => _TaskComposerState();
}

class _TaskComposerState extends State<TaskComposer> {
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _files = TextEditingController();
  final _acceptance = TextEditingController();
  final _tests = TextEditingController();
  String _owner = '';
  String _priority = 'NORMAL';
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _files.dispose();
    _acceptance.dispose();
    _tests.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final title = _title.text.trim();
    if (title.isEmpty) {
      setState(() => _error = 'Başlık gerekli');
      return;
    }
    setState(() {
      _sending = true; // the task API has no idempotency key: block double taps
      _error = null;
    });
    final err = await widget.state.createTask(
      title: title,
      description: _description.text,
      owner: _owner.isEmpty ? null : _owner,
      priority: _priority,
      files: _files.text.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList(),
      acceptance: _acceptance.text.trim(),
      testCriteria: _tests.text.trim(),
    );
    if (!mounted) return;
    if (err == null) {
      Navigator.of(context).pop();
    } else {
      setState(() {
        _sending = false;
        _error = err;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Görev ver', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          TextField(
            controller: _title,
            decoration: const InputDecoration(labelText: 'Başlık', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _description,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Açıklama', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _owner, // ignore: deprecated_member_use
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Sahip', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem(value: '', child: Text('Sahipsiz (BACKLOG)')),
              for (final w in workerIds) DropdownMenuItem(value: w, child: Text(w)),
            ],
            onChanged: (v) => setState(() => _owner = v ?? ''),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _priority, // ignore: deprecated_member_use
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Öncelik', border: OutlineInputBorder()),
            items: [for (final p in priorities) DropdownMenuItem(value: p, child: Text(p))],
            onChanged: (v) => setState(() => _priority = v ?? 'NORMAL'),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _files,
            decoration: const InputDecoration(
              labelText: 'Dosyalar (virgülle ayır)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _acceptance,
            decoration: const InputDecoration(labelText: 'Kabul ölçütü', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _tests,
            decoration: const InputDecoration(labelText: 'Test ölçütü', border: OutlineInputBorder()),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _sending ? null : _create,
            child: Text(_sending ? 'Oluşturuluyor…' : 'Oluştur'),
          ),
        ],
      ),
    );
  }
}
