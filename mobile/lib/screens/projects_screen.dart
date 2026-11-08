import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';

/// Projects: a local folder on the computer per project, and the agents allowed to work in it. Everything here is
/// done by the user token; the folder and its files are never deleted by removing a project.
class ProjectsScreen extends StatefulWidget {
  const ProjectsScreen({super.key, required this.state});

  final AppState state;

  @override
  State<ProjectsScreen> createState() => _ProjectsScreenState();
}

class _ProjectsScreenState extends State<ProjectsScreen> {
  final _title = TextEditingController();
  final _folder = TextEditingController();
  bool _busy = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    // not synchronously: refresh() may notify listeners and this runs while the tree is being built
    Future<void>.microtask(widget.state.projects.refresh);
  }

  @override
  void dispose() {
    _title.dispose();
    _folder.dispose();
    super.dispose();
  }

  void _snack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _create() async {
    setState(() {
      _busy = true;
      _message = null;
    });
    final err = await widget.state.projects.add(_title.text, _folder.text);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _message = err ?? 'Proje oluşturuldu.';
    });
    if (err == null) {
      _title.clear();
      _folder.clear();
    }
  }

  Future<void> _remove(Workspace w) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("'${w.title}' kaldırılsın mı?"),
        content: const Text('Proje listeden çıkar. Klasör ve dosyalar SİLİNMEZ.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Kaldır')),
        ],
      ),
    );
    if (ok != true) return;
    final err = await widget.state.projects.remove(w);
    if (err != null) _snack(err);
  }

  Future<void> _addAgent(Workspace w) async {
    final free = [
      for (final a in widget.state.agents)
        if (a.id != 'user' && !w.agents.contains(a.id)) a.id
    ];
    if (free.isEmpty) {
      _snack('Eklenecek başka ajan yok');
      return;
    }
    final pick = await showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('Hangi ajan çalışsın?'),
        children: [
          for (final id in free) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, id), child: Text(id)),
        ],
      ),
    );
    if (pick == null) return;
    final err = await widget.state.projects.assign(w, pick);
    _snack(err ?? '$pick projeye eklendi');
  }

  Future<void> _removeAgent(Workspace w, String agent) async {
    final err = await widget.state.projects.unassign(w, agent);
    if (err != null) _snack(err);
  }

  Widget _card(Workspace w, bool can) {
    return Card(
      key: Key('project-${w.name}'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(child: Text(w.title, style: Theme.of(context).textTheme.titleMedium)),
              if (!w.exists) const Chip(label: Text('klasör yok')),
            ]),
            SelectableText(w.folder, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            if (w.agents.isEmpty)
              Text('Bu projede ajan yok.', style: Theme.of(context).textTheme.bodySmall)
            else
              Wrap(
                spacing: 6,
                children: [
                  for (final a in w.agents)
                    InputChip(
                      key: Key('agent-${w.name}-$a'),
                      label: Text(a),
                      onDeleted: can ? () => _removeAgent(w, a) : null,
                    ),
                ],
              ),
            Wrap(
              spacing: 8,
              children: [
                TextButton(
                  key: Key('assign-${w.name}'),
                  onPressed: can ? () => _addAgent(w) : null,
                  child: const Text('Ajanı projeye ekle'),
                ),
                TextButton(
                  key: Key('remove-${w.name}'),
                  onPressed: can ? () => _remove(w) : null,
                  child: const Text('Projeyi kaldır'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state.projects;
    return ListenableBuilder(
      listenable: Listenable.merge([s, widget.state]),
      builder: (context, _) {
        final can = s.canChange;
        return RefreshIndicator(
          onRefresh: s.refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(12),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Yeni proje', style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 4),
                      Text(
                        'Her projenin bilgisayarda kendi klasörü olur. Projeye eklenen ajanlar yalnızca o klasörde '
                        'çalışır; silme, paket kurma ve git push her zaman senin onayını ister.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        key: const Key('projectTitle'),
                        controller: _title,
                        decoration: const InputDecoration(labelText: 'Proje adı', border: OutlineInputBorder()),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        key: const Key('projectFolder'),
                        controller: _folder,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Klasör (boş bırakırsan WACC açar)',
                          hintText: r'C:\Users\sen\Belgeler\proje',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 8),
                      FilledButton(
                        key: const Key('projectAdd'),
                        onPressed: (can && !_busy) ? _create : null,
                        child: const Text('Proje oluştur'),
                      ),
                      if (!can)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text('Değiştirmek için Onaylar sekmesinde kullanıcı tokenını gir.',
                              style: Theme.of(context).textTheme.bodySmall),
                        ),
                      if (_message != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(_message!, key: const Key('projectMessage')),
                        ),
                    ],
                  ),
                ),
              ),
              if (s.list.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 32),
                  child: Center(
                    child: Text(
                      s.loaded ? (s.error ?? 'Henüz proje yok. Yukarıdan ilkini oluştur.') : 'Yükleniyor…',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              for (final w in s.list) _card(w, can),
            ],
          ),
        );
      },
    );
  }
}
