import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// بيانات السيرفر المقترن.
class ServerInfo {
  ServerInfo({required this.hosts, required this.port, this.id = '', this.name = ''});

  final List<String> hosts;
  final int port;
  final String id;
  final String name;

  String get primaryHost => hosts.first;
  String get baseUrl => 'http://$primaryHost:$port/api/v1';

  Map<String, dynamic> toJson() => {'h': hosts, 'p': port, 'id': id, 'n': name};

  factory ServerInfo.fromJson(Map<String, dynamic> j) {
    final h = j['h'];
    final hosts = h is List ? h.map((e) => '$e').toList() : ['$h'];
    return ServerInfo(hosts: hosts, port: (j['p'] as num?)?.toInt() ?? 8765, id: '${j['id'] ?? ''}', name: '${j['n'] ?? ''}');
  }

  ServerInfo withPrimary(String host) => ServerInfo(hosts: [host, ...hosts.where((x) => x != host)], port: port, id: id, name: name);

  /// يقبل محتوى QR من تطبيق الأدمن، أو عنواناً يدوياً مثل 192.168.1.5:8765
  static ServerInfo? parse(String raw) {
    final text = raw.trim();
    if (text.startsWith('{')) {
      try {
        final j = jsonDecode(text) as Map<String, dynamic>;
        if (j['t'] == 'ft') return ServerInfo.fromJson(j);
      } catch (_) {}
      return null;
    }
    final m = RegExp(r'^(?:https?://)?([\w.\-]+)(?::(\d+))?').firstMatch(text);
    if (m == null) return null;
    return ServerInfo(hosts: [m.group(1)!], port: int.tryParse(m.group(2) ?? '') ?? 8765);
  }
}

class AppStorage {
  static const _secure = FlutterSecureStorage();
  static late SharedPreferences prefs;

  static Future<void> init() async {
    prefs = await SharedPreferences.getInstance();
  }

  static ServerInfo? get server {
    final raw = prefs.getString('server');
    if (raw == null) return null;
    try {
      return ServerInfo.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  static Future<void> setServer(ServerInfo? s) async {
    if (s == null) {
      await prefs.remove('server');
    } else {
      await prefs.setString('server', jsonEncode(s.toJson()));
    }
  }

  static Future<String?> get token => _secure.read(key: 'token');
  static Future<void> setToken(String? t) => t == null ? _secure.delete(key: 'token') : _secure.write(key: 'token', value: t);

  static Map<String, dynamic>? get user {
    final raw = prefs.getString('user');
    return raw == null ? null : jsonDecode(raw) as Map<String, dynamic>;
  }

  static Future<void> setUser(Map<String, dynamic>? u) async {
    if (u == null) {
      await prefs.remove('user');
    } else {
      await prefs.setString('user', jsonEncode(u));
    }
  }

  static String? get lastUsername => prefs.getString('last_username');
  static Future<void> setLastUsername(String u) => prefs.setString('last_username', u);

  static List<String> get recentSearches => prefs.getStringList('recent') ?? [];
  static Future<void> addRecent(String code) async {
    final list = recentSearches..remove(code);
    list.insert(0, code);
    await prefs.setStringList('recent', list.take(15).toList());
  }

  static bool get darkMode => prefs.getBool('dark') ?? false;
  static Future<void> setDarkMode(bool v) => prefs.setBool('dark', v);

  static String? get currency => prefs.getString('currency');
  static Future<void> setCurrency(String? c) async {
    if (c == null) {
      await prefs.remove('currency');
    } else {
      await prefs.setString('currency', c);
    }
  }
}
