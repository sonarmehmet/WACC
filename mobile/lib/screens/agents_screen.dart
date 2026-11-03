import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';

class AgentsScreen extends StatelessWidget {
  const AgentsScreen({super.key, required this.state});

  final AppState state;

  Future<void> _confirmStop(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Acil durdurma'),
        content: const Text('Tüm ajanlar için ACİL DURDURMA açılsın mı?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Durdur')),
        ],
      ),
    );
    if (ok != true) return;
    final err = await state.stopAll();
    if (err != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  Future<void> _resume(BuildContext context) async {
    final err = await state.resumeAll();
    if (err != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  void _snack(BuildContext context, String text) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _toggle(BuildContext context, Agent agent) async {
    final err = await state.toggleAgent(agent);
    _snack(context, err ?? '${agent.id} ${agent.enabled ? 'kapatıldı' : 'açıldı'}');
  }

  Future<void> _remove(BuildContext context, Agent agent) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ajanı sil'),
        content: Text("'${agent.id}' silinsin mi? Tokenı iptal olur, görevleri BACKLOG'a döner."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sil')),
        ],
      ),
    );
    if (ok != true) return;
    final err = await state.removeAgent(agent);
    _snack(context, err ?? '${agent.id} silindi');
  }

  Future<void> _add(BuildContext context) async {
    final created = await showDialog<NewAgent>(
      context: context,
      builder: (ctx) => AddAgentDialog(state: state),
    );
    if (created == null || !context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${created.name} eklendi'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Token bir daha gösterilmez, şimdi kaydet:'),
            const SizedBox(height: 8),
            SelectableText(created.token, key: const Key('newAgentToken')),
          ],
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Tamam'))],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final agents = state.agents;
    return RefreshIndicator(
      onRefresh: state.refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          if (state.emergencyStop)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: ListTile(
                leading: const Icon(Icons.warning_amber_rounded),
                title: const Text('ACİL DURDURMA AÇIK'),
                subtitle: const Text('Kullanıcı dışındaki tüm yazma işlemleri reddedilir.'),
                trailing: state.isUser
                    ? FilledButton(
                        onPressed: () => _resume(context),
                        child: const Text('Devam ettir'),
                      )
                    : null,
              ),
            )
          else if (state.isLeader)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: () => _confirmStop(context),
                icon: const Icon(Icons.stop_circle_outlined),
                label: const Text('Acil durdur'),
              ),
            ),
          if (state.isUser)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                key: const Key('addAgent'),
                onPressed: () => _add(context),
                icon: const Icon(Icons.person_add_alt_1_outlined),
                label: const Text('Ajan ekle'),
              ),
            ),
          if (agents.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 48),
              child: Center(
                child: Text(
                  state.firstLoadDone
                      ? (state.error ?? 'Henüz ajan yok.')
                      : 'Yükleniyor…',
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          for (final agent in agents)
            AgentCard(
              agent: agent,
              onToggle: state.isUser ? () => _toggle(context, agent) : null,
              onRemove: state.isUser && agent.removable ? () => _remove(context, agent) : null,
            ),
        ],
      ),
    );
  }
}

class AgentCard extends StatelessWidget {
  const AgentCard({super.key, required this.agent, this.onToggle, this.onRemove});

  final Agent agent;

  /// Only given to the user: switch the account on or off / remove it.
  final VoidCallback? onToggle;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final lastSent = agent.lastSentSubject == null
        ? null
        : 'Son mesaj → ${agent.lastSentReceiver ?? '?'}: ${agent.lastSentSubject}';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.circle,
                  size: 12,
                  color: agent.online ? Colors.green : scheme.outline,
                  semanticLabel: agent.online ? 'çevrimiçi' : 'çevrimdışı',
                ),
                const SizedBox(width: 8),
                Text(agent.id, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    agent.role,
                    style: Theme.of(context).textTheme.bodySmall,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Durum: ${agent.status}'
              '${agent.currentTask == null ? '' : ' · ${agent.currentTask}'}',
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                _Pill('Okunmamış ${agent.unread}', warn: agent.unread > 0),
                _Pill('Yanıtlanacak ${agent.pendingResponses}', warn: agent.pendingResponses > 0),
                _Pill('Yanıt bekliyor ${agent.awaitingReply}'),
                _Pill('Aktif görev ${agent.activeTasks}'),
                _Pill('Engelli ${agent.blockedTasks}', bad: agent.blockedTasks > 0),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Son görülme: ${ago(agent.lastSeen)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (agent.lastCommit != null)
              Text(
                'Son commit: ${agent.lastCommit!.length > 10 ? agent.lastCommit!.substring(0, 10) : agent.lastCommit}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            if (lastSent != null)
              Text(lastSent, style: Theme.of(context).textTheme.bodySmall),
            if (!agent.enabled)
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text('kapalı', style: TextStyle(fontWeight: FontWeight.w600)),
              ),
            if (onToggle != null || onRemove != null)
              Wrap(
                spacing: 8,
                children: [
                  if (onToggle != null)
                    TextButton(
                      key: Key('agent-toggle-${agent.id}'),
                      onPressed: onToggle,
                      child: Text(agent.enabled ? 'Kapat' : 'Aç'),
                    ),
                  if (onRemove != null)
                    TextButton(
                      key: Key('agent-remove-${agent.id}'),
                      onPressed: onRemove,
                      child: const Text('Sil'),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill(this.text, {this.warn = false, this.bad = false});

  final String text;
  final bool warn;
  final bool bad;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = bad ? scheme.error : (warn ? Colors.orange.shade800 : scheme.outline);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(text, style: TextStyle(fontSize: 12, color: color)),
    );
  }
}

/// Form for a new agent account. Pops the [NewAgent] (with its one-time token) on success.
class AddAgentDialog extends StatefulWidget {
  const AddAgentDialog({super.key, required this.state});

  final AppState state;

  @override
  State<AddAgentDialog> createState() => _AddAgentDialogState();
}

class _AddAgentDialogState extends State<AddAgentDialog> {
  final _name = TextEditingController();
  final _role = TextEditingController();
  final _provider = TextEditingController();
  String _kind = 'claude';
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _role.dispose();
    _provider.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final (err, created) = await widget.state.addAgent(
      name: _name.text,
      kind: _kind,
      role: _role.text,
      provider: _provider.text,
    );
    if (!mounted) return;
    if (created != null) {
      Navigator.pop(context, created);
      return;
    }
    setState(() {
      _busy = false;
      _error = err;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Ajan ekle'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const Key('agName'),
              controller: _name,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Ad (a-z, 0-9, -, _)'),
            ),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              key: const Key('agKind'),
              segments: const [
                ButtonSegment(value: 'claude', label: Text('claude')),
                ButtonSegment(value: 'gemini', label: Text('gemini')),
                ButtonSegment(value: 'chatgpt', label: Text('chatgpt')),
                ButtonSegment(value: 'other', label: Text('diğer')),
              ],
              selected: {_kind},
              onSelectionChanged: (v) => setState(() => _kind = v.first),
            ),
            TextField(
              key: const Key('agRole'),
              controller: _role,
              decoration: const InputDecoration(labelText: 'Rol (isteğe bağlı)'),
            ),
            TextField(
              key: const Key('agProvider'),
              controller: _provider,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Yapay zeka hesabı adı (isteğe bağlı)'),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error!, key: const Key('agError'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Vazgeç')),
        FilledButton(key: const Key('agSubmit'), onPressed: _busy ? null : _submit, child: const Text('Ekle')),
      ],
    );
  }
}
