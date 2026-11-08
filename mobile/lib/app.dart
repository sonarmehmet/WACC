import 'package:flutter/material.dart';

import 'app_state.dart';
import 'jarvis.dart';
import 'screens/agents_screen.dart';
import 'screens/approvals_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/projects_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/tasks_screen.dart';

class WaccApp extends StatefulWidget {
  const WaccApp({super.key, required this.state});

  final AppState state;

  @override
  State<WaccApp> createState() => _WaccAppState();
}

class _WaccAppState extends State<WaccApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.state.start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.state.dispose();
    super.dispose();
  }

  /// The approval token must not survive the app going to the background.
  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    if (lifecycle == AppLifecycleState.paused || lifecycle == AppLifecycleState.detached) {
      widget.state.approvals.forgetApprovalToken();
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'WACC',
      debugShowCheckedModeBanner: false,
      theme: jarvisTheme(),
      darkTheme: jarvisTheme(),
      themeMode: ThemeMode.dark,
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
  static const int _approvalsIndex = 4;
  int _index = 0;

  @override
  void dispose() {
    widget.state.approvals.watching = false;
    super.dispose();
  }

  void _select(int i) {
    setState(() => _index = i);
    widget.state.approvals.watching = i == _approvalsIndex;
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return ListenableBuilder(
      listenable: Listenable.merge([state, state.approvals, state.projects]),
      builder: (context, _) {
        final screens = <Widget>[
          AgentsScreen(state: state),
          ProjectsScreen(state: state),
          ChatScreen(state: state),
          TasksScreen(state: state),
          ApprovalsScreen(state: state.approvals),
          // New key when the stored settings are (re)loaded, so the fields show them.
          SettingsScreen(
            key: ValueKey(Object.hash(
              state.settings.baseUrl,
              state.settings.token,
              state.settings.backendUrl,
              state.settings.backendToken,
            )),
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
            onDestinationSelected: _select,
            destinations: [
              const NavigationDestination(icon: Icon(Icons.smart_toy_outlined), label: 'Ajanlar'),
              const NavigationDestination(icon: Icon(Icons.folder_outlined), label: 'Projeler'),
              const NavigationDestination(icon: Icon(Icons.forum_outlined), label: 'Sohbet'),
              const NavigationDestination(icon: Icon(Icons.checklist), label: 'Görevler'),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: state.approvals.pendingCount > 0,
                  label: Text('${state.approvals.pendingCount}'),
                  child: const Icon(Icons.verified_user_outlined),
                ),
                label: 'Onaylar',
              ),
              const NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Ayarlar'),
            ],
          ),
        );
      },
    );
  }
}
