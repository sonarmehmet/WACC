import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Android emulator -> the host computer's 127.0.0.1. On a real phone enter the tunnel/VPN
/// address of the Hub instead (the Hub only listens on 127.0.0.1 by default).
const String defaultBaseUrl = 'http://10.0.2.2:8765';

/// Same idea for the Backend (execution/approval API), which listens on port 8800.
const String defaultBackendUrl = 'http://10.0.2.2:8800';

class Settings {
  const Settings({
    this.baseUrl = defaultBaseUrl,
    this.token = '',
    this.backendUrl = defaultBackendUrl,
    this.backendToken = '',
  });

  final String baseUrl;
  final String token;
  final String backendUrl;

  /// The Backend's agent token (read access). The user's approval token is NOT part of the
  /// settings: it is never stored anywhere (see ApprovalsState).
  final String backendToken;

  bool get hasToken => token.isNotEmpty;
  bool get hasBackendToken => backendToken.isNotEmpty;

  Settings copyWith({String? baseUrl, String? token, String? backendUrl, String? backendToken}) => Settings(
        baseUrl: baseUrl ?? this.baseUrl,
        token: token ?? this.token,
        backendUrl: backendUrl ?? this.backendUrl,
        backendToken: backendToken ?? this.backendToken,
      );
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
  static const _backendUrlKey = 'wacc.backend_url';
  static const _backendTokenKey = 'wacc.backend_token';

  final FlutterSecureStorage _secure;

  @override
  Future<Settings> load() async {
    String url = defaultBaseUrl;
    String backendUrl = defaultBackendUrl;
    String token = '';
    String backendToken = '';
    try {
      final prefs = await SharedPreferences.getInstance();
      url = prefs.getString(_urlKey) ?? defaultBaseUrl;
      backendUrl = prefs.getString(_backendUrlKey) ?? defaultBackendUrl;
    } on Exception {
      // fall back to the default addresses
    }
    try {
      token = await _secure.read(key: _tokenKey) ?? '';
      backendToken = await _secure.read(key: _backendTokenKey) ?? '';
    } on Exception {
      // secure storage can fail on some devices; the user can re-enter the tokens
    }
    return Settings(baseUrl: url, token: token, backendUrl: backendUrl, backendToken: backendToken);
  }

  @override
  Future<void> save(Settings settings) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_urlKey, settings.baseUrl);
    await prefs.setString(_backendUrlKey, settings.backendUrl);
    await _storeSecret(_tokenKey, settings.token);
    await _storeSecret(_backendTokenKey, settings.backendToken);
  }

  Future<void> _storeSecret(String key, String value) async {
    if (value.isEmpty) {
      await _secure.delete(key: key);
    } else {
      await _secure.write(key: key, value: value);
    }
  }
}
