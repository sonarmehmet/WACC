import 'package:flutter/material.dart';

import '../approvals_state.dart';
import '../models.dart';

/// Approve or deny what agents ask to run. Everything shown here (actions, risk text, agent
/// names) comes from the Backend/agents: it is untrusted text and is only shown with Text
/// widgets. The raw action is what the user decides on.
class ApprovalsScreen extends StatefulWidget {
  const ApprovalsScreen({super.key, required this.state});

  final ApprovalsState state;

  @override
  State<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends State<ApprovalsScreen> {
  final _token = TextEditingController();

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  void _snack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  void _useToken() {
    final value = _token.text;
    _token.clear(); // do not leave the secret in the text field
    FocusScope.of(context).unfocus();
    widget.state.setApprovalToken(value);
  }

  Future<void> _decide(ApprovalItem item, {required bool approve}) async {
    if (approve) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => ApproveDialog(item: item),
      );
      if (ok != true) return;
    }
    final err = await widget.state.decide(item, approve: approve);
    _snack(err ?? (approve ? '#${item.id} onaylandı' : '#${item.id} reddedildi'));
  }

  Future<void> _stop() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Yürütmeyi durdur'),
        content: const Text('Yürütme backend\'i (ve Hub\'ın paylaşılan durdurma bayrağı) durdurulsun mu?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Durdur')),
        ],
      ),
    );
    if (ok != true) return;
    final err = await widget.state.stopExec();
    _snack(err ?? 'Yürütme durduruldu');
  }

  Future<void> _resume() async {
    final err = await widget.state.resumeExec();
    _snack(err ?? 'Yürütme devam ettirildi');
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final status = state.execStatus;
    return RefreshIndicator(
      onRefresh: state.refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          _tokenCard(context),
          if (status != null) _execCard(context, status),
          if (!state.connected && state.error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Center(child: Text(state.error!, textAlign: TextAlign.center)),
            ),
          if (state.connected || state.pending.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
              child: Text(
                'Bekleyen onaylar (${state.pending.length})',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            if (state.pending.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Center(child: Text('Bekleyen onay yok.')),
              ),
            for (final item in state.pending) _pendingCard(context, item),
          ],
          if (state.history.isNotEmpty)
            ExpansionTile(
              title: const Text('Son kararlar'),
              children: [for (final item in state.history.take(20)) _historyTile(item)],
            ),
          if (state.audit.isNotEmpty)
            ExpansionTile(
              title: const Text('Denetim kaydı'),
              children: [for (final row in state.audit.take(30)) _auditTile(row)],
            ),
        ],
      ),
    );
  }

  Widget _tokenCard(BuildContext context) {
    final state = widget.state;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Onay tokenı', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(
              'Onaylamak için backend penceresinde yazan kullanıcı tokenı gerekir. Bu uygulama onu '
              'hiçbir yere kaydetmez: yalnızca bellekte tutar, 5 dakika işlem yapmazsan veya '
              'uygulama arka plana geçince unutur. Tokensız yalnızca görüntülersin.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _token,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              onSubmitted: (_) => _useToken(),
              decoration: const InputDecoration(
                labelText: 'Kullanıcı tokenı',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                FilledButton(onPressed: _useToken, child: const Text('Kullan')),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: state.hasApprovalToken ? state.forgetApprovalToken : null,
                  child: const Text('Sil'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    state.hasApprovalToken
                        ? 'Onay tokenı bellekte'
                        : 'Onay tokenı yok: yalnızca görüntüleme',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _execCard(BuildContext context, ExecStatus status) {
    final state = widget.state;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('Yürütme: ', style: Theme.of(context).textTheme.titleSmall),
                Text(
                  status.emergencyStop ? 'DURDURULDU' : 'açık',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: status.emergencyStop ? Theme.of(context).colorScheme.error : null,
                  ),
                ),
              ],
            ),
            if (status.roots.isNotEmpty)
              Text('İzinli kök: ${status.roots.join(', ')}', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            if (status.emergencyStop)
              FilledButton(
                onPressed: state.hasApprovalToken ? _resume : null,
                child: Text(state.hasApprovalToken ? 'Devam ettir' : 'Devam ettirmek için onay tokenı'),
              )
            else
              FilledButton.tonal(onPressed: _stop, child: const Text('Yürütmeyi durdur')),
          ],
        ),
      ),
    );
  }

  Widget _pendingCard(BuildContext context, ApprovalItem item) {
    final scheme = Theme.of(context).colorScheme;
    final canDecide = widget.state.hasApprovalToken;
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: item.isRisky ? scheme.error : scheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 2,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('#${item.id}', style: const TextStyle(fontWeight: FontWeight.w700)),
                Text(
                  item.actionClass,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: item.isRisky ? scheme.error : Colors.orange.shade800,
                  ),
                ),
                Text('isteyen: ${item.requestedBy}'),
                Text(remainingText(item.expiresAt), style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Ham eylem (backend\'in doğruladığı biçim; çalışacak olan budur):',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            _RawAction(text: item.prettyAction),
            Text(
              'Eylem özeti SHA-256: ${item.shortHash}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            Text(
              'Backend risk özeti: ${item.riskSummary}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            Text(
              'Ajanın açıklamasına güvenme; yalnızca ham eyleme bak.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                FilledButton(
                  onPressed: canDecide ? () => _decide(item, approve: true) : null,
                  child: const Text('Onayla'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: canDecide ? () => _decide(item, approve: false) : null,
                  child: const Text('Reddet'),
                ),
                if (!canDecide) ...[
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text('önce onay tokenını gir', style: Theme.of(context).textTheme.bodySmall),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _historyTile(ApprovalItem item) {
    return ListTile(
      dense: true,
      title: Text('#${item.id} ${item.status} · ${item.actionClass} · ${item.requestedBy}'),
      subtitle: Text('${item.decidedBy ?? '-'} · ${shortTime(item.decidedAt ?? item.createdAt)}\n${item.shortAction}'),
      isThreeLine: true,
    );
  }

  Widget _auditTile(AuditEntry row) {
    return ListTile(
      dense: true,
      title: Text('${row.outcome} · ${row.actionClass} · ${row.agent}'),
      subtitle: Text('${shortTime(row.ts)} · ${row.summary}'),
    );
  }
}

/// What the user reads before approving must be exactly what runs: show every character, and show anything
/// that is not plain printable ASCII (direction marks, zero-width characters, look-alike letters) as \u{code}.
String visibleText(String text) {
  final b = StringBuffer();
  for (final r in text.runes) {
    if (r == 10 || (r >= 32 && r < 127)) {
      b.writeCharCode(r);
    } else {
      b.write('\\u{${r.toRadixString(16)}}');
    }
  }
  return b.toString();
}

class _RawAction extends StatelessWidget {
  const _RawAction({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final shown = visibleText(text); // never cut: the backend refuses actions too long to be reviewed in full
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(8),
      constraints: const BoxConstraints(maxHeight: 220),
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(6),
      ),
      child: SingleChildScrollView(
        child: SelectableText(shown, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
      ),
    );
  }
}

/// Asks for a final yes, showing exactly what will run.
class ApproveDialog extends StatelessWidget {
  const ApproveDialog({super.key, required this.item});

  final ApprovalItem item;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Bu eylemi onaylıyor musun?'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Sınıf: ${item.actionClass}'),
            Text('İsteyen: ${item.requestedBy}'),
            const SizedBox(height: 8),
            _RawAction(text: item.prettyAction),
            Text('SHA-256: ${item.shortHash}', style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Vazgeç')),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Onayla')),
      ],
    );
  }
}
