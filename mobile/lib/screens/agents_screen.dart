import 'package:flutter/material.dart';

import '../app_state.dart';
import '../jarvis.dart';
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
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _add(BuildContext context) async {
    final name = TextEditingController();
    final role = TextEditingController();
    final provider = TextEditingController();
    var kind = 'claude';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Ajan ekle'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  decoration: const InputDecoration(labelText: 'Ad (a-z, 0-9, - veya _)'),
                ),
                DropdownButton<String>(
                  value: kind,
                  isExpanded: true,
                  items: const [
                    DropdownMenuItem(value: 'claude', child: Text('Claude')),
                    DropdownMenuItem(value: 'gemini', child: Text('Gemini')),
                    DropdownMenuItem(value: 'chatgpt', child: Text('ChatGPT')),
                    DropdownMenuItem(value: 'other', child: Text('Diğer')),
                  ],
                  onChanged: (v) => setLocal(() => kind = v ?? kind),
                ),
                TextField(controller: role, decoration: const InputDecoration(labelText: 'Rol (opsiyonel)')),
                TextField(
                  controller: provider,
                  decoration: const InputDecoration(labelText: 'Bağlı AI hesabı (opsiyonel)'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Ekle')),
          ],
        ),
      ),
    );
    final n = name.text.trim().toLowerCase();
    final r = role.text.trim();
    final p = provider.text.trim();
    name.dispose();
    role.dispose();
    provider.dispose();
    if (ok != true) return;
    final (err, token) = await state.addAgent(n, kind, r, p);
    if (!context.mounted) return;
    if (err != null) {
      _snack(context, err);
      return;
    }
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('$n eklendi'),
        content: SelectableText('Token (bir daha gösterilmez, şimdi kaydet):\n\n$token'),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Tamam'))],
      ),
    );
  }

  Future<void> _toggle(BuildContext context, Agent a) async {
    final err = await state.setAgentEnabled(a.id, !a.enabled);
    if (err != null && context.mounted) _snack(context, err);
  }

  Future<void> _remove(BuildContext context, Agent a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("'${a.id}' silinsin mi?"),
        content: const Text('Token iptal olur, görevleri BACKLOG\'a döner. Geçmiş kalır.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sil')),
        ],
      ),
    );
    if (ok != true) return;
    final err = await state.removeAgent(a.id);
    if (err != null && context.mounted) _snack(context, err);
  }

  Widget _statusOrb(BuildContext context) {
    final Color color;
    final String label;
    if (!state.connected) {
      color = const Color(0xFF56666A);
      label = 'BAĞLANTI YOK';
    } else if (state.emergencyStop) {
      color = jarvisBad;
      label = 'ACİL DURDURMA AKTİF';
    } else {
      color = jarvisAccent;
      label = 'BEKLEMEDE';
    }
    final online = state.agents.where((a) => a.online).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          RadarOrb(color: color, size: 72),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: TextStyle(color: color, letterSpacing: 2, fontWeight: FontWeight.w600)),
                Text('$online/${state.agents.length} ajan çevrimiçi', style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ],
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
          _statusOrb(context),
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
                onPressed: () => _add(context),
                icon: const Icon(Icons.person_add_alt_1),
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
              onToggle: state.isUser && agent.id != 'user' ? () => _toggle(context, agent) : null,
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
                if (!agent.enabled) const Padding(padding: EdgeInsets.only(left: 6), child: _Pill('kapalı', warn: true)),
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
            if (onToggle != null || onRemove != null)
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  if (onToggle != null)
                    TextButton(onPressed: onToggle, child: Text(agent.enabled ? 'Kapat' : 'Aç')),
                  if (onRemove != null) TextButton(onPressed: onRemove, child: const Text('Sil')),
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
