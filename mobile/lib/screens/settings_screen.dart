import 'package:flutter/material.dart';

import '../app_state.dart';
import '../settings.dart';
import 'ai_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.state});

  final AppState state;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _url;
  late final TextEditingController _token;
  late final TextEditingController _backendUrl;
  late final TextEditingController _backendToken;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: widget.state.settings.baseUrl);
    _token = TextEditingController(text: widget.state.settings.token);
    _backendUrl = TextEditingController(text: widget.state.settings.backendUrl);
    _backendToken = TextEditingController(text: widget.state.settings.backendToken);
  }

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    _backendUrl.dispose();
    _backendToken.dispose();
    super.dispose();
  }

  Future<void> _save({bool forgetToken = false}) async {
    // Saving changes the settings, which rebuilds this screen (see HomeShell), so keep the
    // messenger and don't rely on this State staying mounted.
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _saving = true);
    final url = _url.text.trim().isEmpty ? defaultBaseUrl : _url.text.trim();
    final backendUrl = _backendUrl.text.trim().isEmpty ? defaultBackendUrl : _backendUrl.text.trim();
    final token = forgetToken ? '' : _token.text.trim();
    final backendToken = forgetToken ? '' : _backendToken.text.trim();
    if (forgetToken) {
      _token.clear();
      _backendToken.clear();
    }
    await widget.state.updateSettings(
      Settings(baseUrl: url, token: token, backendUrl: backendUrl, backendToken: backendToken),
    );
    messenger.showSnackBar(
      SnackBar(content: Text(forgetToken ? 'Token silindi' : 'Kaydedildi')),
    );
    if (mounted) setState(() => _saving = false);
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(state.connected ? Icons.check_circle : Icons.error_outline),
          title: Text(state.connected ? 'Bağlı: ${state.me}' : (state.error ?? 'Bağlı değil')),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _url,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'Hub adresi',
            helperText: 'Emülatörde http://10.0.2.2:8765 bilgisayardaki Hub\'a çıkar.',
            helperMaxLines: 2,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _token,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'Token (X-WACC-Token)',
            helperText: 'Telefonda güvenli depoda saklanır. Panel için user tokenını kullan.',
            helperMaxLines: 2,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 20),
        Text('Backend (onaylar)', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        TextField(
          controller: _backendUrl,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'Backend adresi',
            helperText: 'Emülatörde http://10.0.2.2:8800 bilgisayardaki Backend\'e çıkar.',
            helperMaxLines: 2,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _backendToken,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'Backend tokenı (ajan, salt okuma)',
            helperText: 'Onay listesini görmek için. Onaylamak için kullanıcı tokenı Onaylar '
                'sekmesinde ayrıca girilir ve hiçbir yere kaydedilmez.',
            helperMaxLines: 3,
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _saving ? null : () => _save(),
          child: const Text('Kaydet ve bağlan'),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: _saving ? null : () => _save(forgetToken: true),
          child: const Text('Tokenı sil'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('openAi'),
          icon: const Icon(Icons.psychology_outlined),
          label: const Text('Yapay zeka hesapları'),
          onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
            builder: (_) => AiScreen(state: state.ai, approvals: state.approvals),
          )),
        ),
        const SizedBox(height: 16),
        Text(
          'Hub varsayılan olarak yalnızca bilgisayarın 127.0.0.1 adresinde dinler. Gerçek bir '
          'telefondan bağlanmak için Hub\'ı kimlik doğrulamalı bir tünelin (Tailscale, '
          'Cloudflare Tunnel) arkasında aç; korumasız internete açma.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}
