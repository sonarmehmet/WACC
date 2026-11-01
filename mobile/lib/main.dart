import 'package:flutter/material.dart';

import 'app.dart';
import 'app_state.dart';
import 'settings.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(WaccApp(state: AppState(store: DeviceSettingsStore())));
}
