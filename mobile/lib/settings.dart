import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Android emulator -> the host computer's 127.0.0.1. On a real phone enter the tunnel/VPN
/// address of the Hub instead (the Hub only listens on 127.0.0.1 by default).
const String defaultBaseUrl = 'http://10.0.2.2:8765';

class Settings {
  const Settings({this.baseUrl = defaultBaseUrl, this.token = ''});

  final String baseUrl;
  final String token;

  bool get hasToken => token.isNotEmpty;

  Settings copyWith({String? baseUrl, String? token}) =>
      Settings(baseUrl: baseUrl ?? this.baseUrl, token: token ?? this.token);
}

abstract class SettingsStore {
  Future<Settings> load();
  Future<void> save(Settings settings);
}

/// Used by tests and as a fallback; keeps everything in memory only.
class MemorySettingsStore implements SettingsStore {
  MemorySettingsStore([this._settings = const Settings()]);

  Settings _settings;

  @override
  Future<Settings> load() async => _settings;

  @override
  Future<void> save(Settings settings) async => _settings = settings;
}

/// The Hub address lives in shared preferences; the token lives in the platform's secure
/// storage (Android Keystore) and is never written anywhere else.
class DeviceSettingsStore implements SettingsStore {
  DeviceSettingsStore({FlutterSecureStorage? secure})
      : _secure = secure ?? const FlutterSecureStorage();

  static const _urlKey = 'wacc.hub_url';
  static const _tokenKey = 'wacc.token';

  final FlutterSecureStorage _secure;

  @override
  Future<Settings> load() async {
    String url = defaultBaseUrl;
    String token = '';
    try {
      final prefs = await SharedPreferences.getInstance();
      url = prefs.getString(_urlKey) ?? defaultBaseUrl;
    } on Exception {
      // fall back to the default address
    }
    try {
      token = await _secure.read(key: _tokenKey) ?? '';
    } on Exception {
      // secure storage can fail on some devices; the user can re-enter the token
    }
    return Settings(baseUrl: url, token: token);
  }

  @override
  Future<void> save(Settings settings) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_urlKey, settings.baseUrl);
    if (settings.token.isEmpty) {
      await _secure.delete(key: _tokenKey);
    } else {
      await _secure.write(key: _tokenKey, value: settings.token);
    }
  }
}
