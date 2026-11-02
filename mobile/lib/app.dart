import 'package:flutter/material.dart';

import 'app_state.dart';
import 'screens/agents_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/tasks_screen.dart';

class WaccApp extends StatefulWidget {
  const WaccApp({super.key, required this.state});

  final AppState state;

  @override
  State<WaccApp> createState() => _WaccAppState();
}

class _WaccAppState extends State<WaccApp> {
  @override
  void initState() {
    super.initState();
    widget.state.start();
  }

  @override
  void dispose() {
    widget.state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'WACC',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: const Color(0xFF2557D6), useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF6C93FF),
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: HomeShell(state: widget.state),
    );
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.state});

  final AppState state;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return ListenableBuilder(
      listenable: state,
      builder: (context, _) {
        final screens = <Widget>[
          AgentsScreen(state: state),
          ChatScreen(state: state),
          TasksScreen(state: state),
          // New key when the stored settings are (re)loaded, so the fields show them.
          SettingsScreen(
            key: ValueKey(Object.hash(state.settings.baseUrl, state.settings.token)),
            state: state,
          ),
        ];
        return Scaffold(
          appBar: AppBar(
            title: const Text('WACC'),
            actions: [
              Padding(
                padding: const EdgeInsets.only(right: 16),
                child: Center(
                  child: Text(
                    state.connected ? 'Bağlı: ${state.me}' : (state.error ?? 'Bağlanıyor…'),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ),
            ],
          ),
          body: IndexedStack(index: _index, children: screens),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: const [
              NavigationDestination(icon: Icon(Icons.smart_toy_outlined), label: 'Ajanlar'),
              NavigationDestination(icon: Icon(Icons.forum_outlined), label: 'Sohbet'),
              NavigationDestination(icon: Icon(Icons.checklist), label: 'Görevler'),
              NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Ayarlar'),
            ],
          ),
        );
      },
    );
  }
}
