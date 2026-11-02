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
          for (final agent in agents) AgentCard(agent: agent),
        ],
      ),
    );
  }
}

class AgentCard extends StatelessWidget {
  const AgentCard({super.key, required this.agent});

  final Agent agent;

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
