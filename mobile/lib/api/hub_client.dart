import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models.dart';

/// Error from the Hub or from reaching it. [message] is safe to show to the user.
class HubException implements Exception {
  const HubException(this.message, {this.statusCode, this.code = 'ERROR'});

  final String message;
  final int? statusCode;
  final String code;

  bool get unauthorized => statusCode == 401;

  @override
  String toString() => 'HubException($code, $statusCode): $message';
}

/// Thin client for the Hub HTTP API (see hub/wacc_hub/api.py).
///
/// The token is sent in the `X-WACC-Token` header and decides which agent is acting.
/// It is never logged or put into a URL.
class HubClient {
  HubClient({
    required String baseUrl,
    required this.token,
    http.Client? client,
    this.timeout = const Duration(seconds: 10),
  })  : baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  final String baseUrl;
  final String token;
  final Duration timeout;
  final http.Client _client;

  Future<Map<String, dynamic>> health() async => _map(await _send('GET', '/health'));

  /// Name of the agent that owns the token.
  Future<String> whoami() async {
    final data = _map(await _send('GET', '/whoami'));
    return data['agent']?.toString() ?? '?';
  }

  Future<List<Agent>> agents() async =>
      _list(await _send('GET', '/agents')).map(Agent.fromJson).toList();

  Future<List<FeedMessage>> feed({int limit = 200, String? conversationId}) async {
    final query = <String, String>{'limit': '$limit'};
    if (conversationId != null && conversationId.isNotEmpty) {
      query['conversation_id'] = conversationId;
    }
    final data = await _send('GET', '/feed', query: query);
    return _list(data).map(FeedMessage.fromJson).toList();
  }

  Future<List<HubTask>> tasks({String? owner, String? status}) async {
    final query = <String, String>{};
    if (owner != null) query['owner'] = owner;
    if (status != null) query['status'] = status;
    final data = await _send('GET', '/tasks', query: query.isEmpty ? null : query);
    return _list(data).map(HubTask.fromJson).toList();
  }

  Future<void> sendMessage({
    required String receiver,
    required String messageType,
    required String subject,
    String content = '',
    String priority = 'NORMAL',
    bool responseRequired = false,
    String? conversationId,
    String? idempotencyKey,
  }) async {
    await _send('POST', '/messages', body: {
      'receiver': receiver,
      'message_type': messageType,
      'subject': subject,
      'content': content,
      'priority': priority,
      'response_required': responseRequired,
      if (conversationId != null && conversationId.isNotEmpty) 'conversation_id': conversationId,
      if (idempotencyKey != null) 'idempotency_key': idempotencyKey,
    });
  }

  Future<HubTask> createTask({
    required String title,
    String description = '',
    String? owner,
    String priority = 'NORMAL',
    List<String> files = const [],
    String acceptance = '',
    String testCriteria = '',
  }) async {
    final data = await _send('POST', '/tasks', body: {
      'title': title,
      'description': description,
      'owner': owner,
      'priority': priority,
      'affected_files': files,
      'acceptance': acceptance,
      'test_criteria': testCriteria,
    });
    return HubTask.fromJson(_map(data));
  }

  Future<void> acceptTask(String taskId) async {
    await _send('POST', '/tasks/${Uri.encodeComponent(taskId)}/accept');
  }

  Future<void> setTaskStatus(String taskId, String status, {String? commit, String? note}) async {
    await _send('POST', '/tasks/${Uri.encodeComponent(taskId)}/status', body: {
      'status': status,
      'commit': commit,
      'note': note,
    });
  }

  Future<void> emergencyStop(String reason) async {
    await _send('POST', '/system/stop', body: {'reason': reason});
  }

  Future<void> resume() async {
    await _send('POST', '/system/resume');
  }

  void close() => _client.close();

  // ------------------------------------------------------------------ plumbing

  Future<dynamic> _send(
    String method,
    String path, {
    Map<String, String>? query,
    Object? body,
  }) async {
    final res = await _dispatch(method, path, query, body);
    dynamic decoded;
    if (res.bodyBytes.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(res.bodyBytes));
      } on FormatException {
        decoded = null;
      }
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw _errorFrom(res.statusCode, decoded);
    }
    return decoded;
  }

  Future<http.Response> _dispatch(
    String method,
    String path,
    Map<String, String>? query,
    Object? body,
  ) async {
    try {
      final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
      final headers = <String, String>{'X-WACC-Token': token};
      if (method == 'GET') {
        return await _client.get(uri, headers: headers).timeout(timeout);
      }
      headers['Content-Type'] = 'application/json';
      return await _client
          .post(uri, headers: headers, body: body == null ? null : jsonEncode(body))
          .timeout(timeout);
    } on TimeoutException {
      throw const HubException('Hub zamanında yanıt vermedi', code: 'TIMEOUT');
    } on FormatException {
      throw const HubException('Hub adresi geçersiz', code: 'BAD_URL');
    } on Exception {
      throw HubException("Hub'a ulaşılamıyor ($baseUrl)", code: 'UNREACHABLE');
    }
  }

  static HubException _errorFrom(int status, dynamic decoded) {
    var code = 'HTTP_$status';
    var message = 'İstek başarısız ($status)';
    if (decoded is Map && decoded['detail'] != null) {
      final detail = decoded['detail'];
      if (detail is Map) {
        code = detail['code']?.toString() ?? code;
        message = detail['message']?.toString() ?? message;
      } else {
        message = detail.toString();
      }
    }
    if (status == 401) message = 'Token geçersiz';
    return HubException(message, statusCode: status, code: code);
  }

  static Map<String, dynamic> _map(dynamic data) {
    if (data is Map<String, dynamic>) return data;
    throw const HubException('Beklenmeyen yanıt biçimi', code: 'BAD_RESPONSE');
  }

  static List<Map<String, dynamic>> _list(dynamic data) {
    if (data is List) return data.whereType<Map<String, dynamic>>().toList();
    throw const HubException('Beklenmeyen yanıt biçimi', code: 'BAD_RESPONSE');
  }
}

typedef HubClientFactory = HubClient Function(String baseUrl, String token);
