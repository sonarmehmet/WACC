import 'package:flutter/material.dart';

import '../ai_state.dart';
import '../approvals_state.dart';
import '../models.dart';

/// AI accounts: list, add, switch on/off, test and remove. Everything that comes from the
/// Backend (names, models, errors, replies) is untrusted text and is shown with Text widgets
/// only. The API key field is emptied the moment the form is submitted and the key is never
/// stored or shown again.
class AiScreen extends StatefulWidget {
  const AiScreen({super.key, required this.state, required this.approvals});

  final AiState state;
  final ApprovalsState approvals;

  @override
  State<AiScreen> createState() => _AiScreenState();
}

class _AiScreenState extends State<AiScreen> {
  final _token = TextEditingController();
  final _name = TextEditingController();
  final _url = TextEditingController();
  final _model = TextEditingController();
  final _key = TextEditingController();
  final _priceIn = TextEditingController();
  final _priceOut = TextEditingController();
  String _kind = 'local';
  bool _enabled = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    widget.state.refresh();
  }

  @override
  void dispose() {
    for (final c in [_token, _name, _url, _model, _key, _priceIn, _priceOut]) {
      c.dispose();
    }
    super.dispose();
  }

  void _snack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  void _useToken() {
    final value = _token.text;
    _token.clear();
    FocusScope.of(context).unfocus();
    widget.approvals.setApprovalToken(value);
  }

  Future<bool> _confirm(String title, String text, String action) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(text),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(action)),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _toggle(AiProvider p) async {
    final err = await widget.state.toggle(p);
    _snack(err ?? '${p.name} ${p.enabled ? 'kapatıldı' : 'açıldı'}');
  }

  Future<void> _remove(AiProvider p) async {
    if (!await _confirm('Hesabı sil', "'${p.name}' silinsin mi? Kayıtlı API anahtarı da silinir.", 'Sil')) return;
    final err = await widget.state.remove(p);
    _snack(err ?? '${p.name} silindi');
  }

  Future<void> _test(AiProvider p) async {
    if (p.isCloud &&
        !await _confirm('Bulut testi',
            "'${p.name}' bulut sağlayıcıya küçük bir gerçek istek gönderilecek (günlük bütçeye sayılır).", 'Test et')) {
      return;
    }
    final err = await widget.state.test(p);
    if (err != null) _snack(err);
  }

  Future<void> _add() async {
    final key = _key.text;
    _key.clear(); // the secret leaves the field before anything is sent, success or not
    FocusScope.of(context).unfocus();
    setState(() => _busy = true);
    final err = await widget.state.add(
      name: _name.text,
      kind: _kind,
      baseUrl: _url.text,
      model: _model.text,
      apiKey: key,
      priceIn: double.tryParse(_priceIn.text.trim()),
      priceOut: double.tryParse(_priceOut.text.trim()),
      enabled: _enabled,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (err == null) {
      _name.clear();
      _url.clear();
      _model.clear();
      _priceIn.clear();
      _priceOut.clear();
      setState(() {
        _kind = 'local';
        _enabled = true;
      });
    }
    _snack(err ?? 'Hesap eklendi');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Yapay zeka hesapları')),
      body: ListenableBuilder(
        listenable: Listenable.merge([widget.state, widget.approvals]),
        builder: (context, _) {
          final s = widget.state;
          return RefreshIndicator(
            onRefresh: s.refresh,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              children: [
                _tokenCard(context),
                if (s.usage != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      'Bugün harcanan: \$${s.usage!.spentUsd.toStringAsFixed(4)} / '
                      'bütçe: \$${s.usage!.budgetUsd.toStringAsFixed(2)}',
                      key: const Key('aiUsage'),
                    ),
                  ),
                if (!s.connected && s.error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Center(child: Text(s.error!, textAlign: TextAlign.center)),
                  ),
                for (final p in s.providers) _providerCard(context, p),
                _addCard(context),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _tokenCard(BuildContext context) {
    final a = widget.approvals;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Hesap eklemek, silmek, açıp kapatmak ve test için kullanıcı tokenı gerekir '
              '(yalnızca bellekte tutulur). Tokensız yalnızca görüntülersin.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('aiToken'),
              controller: _token,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              onSubmitted: (_) => _useToken(),
              decoration: const InputDecoration(labelText: 'Kullanıcı tokenı', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                FilledButton(onPressed: _useToken, child: const Text('Kullan')),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: a.hasApprovalToken ? a.forgetApprovalToken : null,
                  child: const Text('Unut'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    a.hasApprovalToken ? 'Token bellekte' : 'Yalnızca görüntüleme',
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

  Widget _providerCard(BuildContext context, AiProvider p) {
    final s = widget.state;
    final can = s.canChange;
    final hasTest = s.tests.containsKey(p.name);
    final t = s.tests[p.name];
    return Card(
      key: Key('provider-${p.name}'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(p.name, style: Theme.of(context).textTheme.titleSmall),
            Text('${p.kind} · ${p.model}'),
            Text(
              '${p.enabled ? 'açık' : 'kapalı'} · ${p.removable ? 'hesap' : 'ortam (llm.env)'} · '
              '\$${p.priceIn.toStringAsFixed(4)} / \$${p.priceOut.toStringAsFixed(4)} (1k token)',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (hasTest)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  t == null
                      ? 'Test sürüyor…'
                      : (t.ok ? 'OK · ${t.latencyMs} ms · yanıt: ${t.reply}' : 'Hata: ${t.error}'),
                  key: Key('test-${p.name}'),
                ),
              ),
            Wrap(
              spacing: 8,
              children: [
                TextButton(
                  key: Key('toggle-${p.name}'),
                  onPressed: can ? () => _toggle(p) : null,
                  child: Text(p.enabled ? 'Kapat' : 'Aç'),
                ),
                TextButton(
                  key: Key('testbtn-${p.name}'),
                  onPressed: can ? () => _test(p) : null,
                  child: const Text('Test'),
                ),
                if (p.removable)
                  TextButton(
                    key: Key('remove-${p.name}'),
                    onPressed: can ? () => _remove(p) : null,
                    child: const Text('Sil'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _addCard(BuildContext context) {
    final can = widget.state.canChange;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Hesap ekle', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            TextField(
              key: const Key('aiName'),
              controller: _name,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Ad (a-z, 0-9, -, _)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              key: const Key('aiKind'),
              segments: const [
                ButtonSegment(value: 'local', label: Text('Yerel (loopback)')),
                ButtonSegment(value: 'cloud', label: Text('Bulut (https)')),
              ],
              selected: {_kind},
              onSelectionChanged: (v) => setState(() => _kind = v.first),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('aiUrl'),
              controller: _url,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: 'Adres (base URL)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('aiModel'),
              controller: _model,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Model', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('aiKey'),
              controller: _key,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              decoration: const InputDecoration(labelText: 'API anahtarı (kaydedilir, geri gösterilmez)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('aiPriceIn'),
                    controller: _priceIn,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Giriş \$/1k', border: OutlineInputBorder()),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    key: const Key('aiPriceOut'),
                    controller: _priceOut,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Çıkış \$/1k', border: OutlineInputBorder()),
                  ),
                ),
              ],
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Eklenince açık'),
              value: _enabled,
              onChanged: (v) => setState(() => _enabled = v),
            ),
            FilledButton(
              key: const Key('aiAddBtn'),
              onPressed: can && !_busy ? _add : null,
              child: const Text('Ekle'),
            ),
          ],
        ),
      ),
    );
  }
}
