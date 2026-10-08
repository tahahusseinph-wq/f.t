import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';

import '../core/api.dart';
import '../core/discovery.dart';
import '../core/offline_db.dart';
import '../core/storage.dart';

/// حالة الجلسة: السيرفر المقترن، المستخدم، الصلاحيات، والبيانات المرجعية.
class Session extends ChangeNotifier {
  Session() {
    server = AppStorage.server;
    user = AppStorage.user;
  }

  ServerInfo? server;
  Map<String, dynamic>? user;
  Map<String, dynamic> meta = {};
  ApiClient? api;
  bool ready = false;
  bool online = true;
  bool darkMode = AppStorage.darkMode;

  bool get paired => server != null;
  bool get loggedIn => api?.token != null && user != null;
  String get displayName => '${user?['full_name'] ?? user?['username'] ?? ''}';
  String get roleLabel => '${user?['role_label'] ?? ''}';
  bool get isAdmin => user?['role'] == 'admin' || user?['role'] == 'manager';

  bool get isOwner => user?['role'] == 'admin';

  /// الأدمن يملك كل الصلاحيات دائماً (ما عدا «البيع بأكثر من المتوفر» التي تُفعَّل يدوياً).
  bool can(String perm) =>
      (isOwner && perm != 'sales.oversell') || ((user?['permissions'] as List?)?.contains(perm) ?? false);

  String? get currency => AppStorage.currency ?? meta['display_currency'] as String?;

  Map<String, dynamic>? get currencyInfo {
    final list = (meta['currencies'] as List?) ?? [];
    for (final c in list) {
      if (c['code'] == currency) return Map<String, dynamic>.from(c as Map);
    }
    return null;
  }

  String get currencySymbol => '${currencyInfo?['symbol'] ?? ''}';
  int get currencyDecimals => (currencyInfo?['decimals'] as num?)?.toInt() ?? 2;

  Future<void> restore() async {
    if (server != null) {
      final token = await AppStorage.token;
      api = ApiClient(server!, token: token);
      if (token != null && user != null) {
        try {
          final me = await api!.get<Map<String, dynamic>>('/auth/me');
          user = me;
          await AppStorage.setUser(me);
          await loadMeta();
          online = true;
        } on ApiException catch (e) {
          if (e.unauthorized) {
            await _clearLogin();
          } else {
            online = false; // نكمل بوضع بدون اتصال بالبيانات المحفوظة
          }
        }
      }
    }
    ready = true;
    notifyListeners();
  }

  Future<void> pair(ServerInfo s) async {
    final (resolved, _) = await ApiClient.probe(s);
    if (server != null && server!.id != resolved.id) {
      await OfflineDb.clearAll();
      await _clearLogin();
    }
    server = resolved;
    api = ApiClient(resolved, token: await AppStorage.token);
    await AppStorage.setServer(resolved);
    notifyListeners();
  }

  /// بحث تلقائي عن سيرفر الأدمن في الشبكة والاتصال بأول سيرفر يستجيب.
  Future<bool> autoConnect() async {
    final found = await discoverServers();
    for (final s in found) {
      try {
        await pair(s);
        return true;
      } on ApiException {
        continue;
      }
    }
    return false;
  }

  /// إذا تغيّر عنوان الكمبيوتر (DHCP) نحاول بقية العناوين المعروفة.
  Future<bool> reconnect() async {
    if (server == null) return false;
    try {
      final (resolved, _) = await ApiClient.probe(server!);
      server = resolved;
      final token = api?.token;
      api = ApiClient(resolved, token: token);
      await AppStorage.setServer(resolved);
      online = true;
      notifyListeners();
      return true;
    } catch (_) {
      online = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> login(String username, String password, String deviceName) async {
    final client = ApiClient(server!);
    final res = await client.post<Map<String, dynamic>>('/auth/login', {
      'username': username, 'password': password, 'device_name': deviceName,
    });
    client.token = res['token'] as String;
    api = client;
    user = Map<String, dynamic>.from(res['user'] as Map);
    await AppStorage.setToken(client.token);
    await AppStorage.setUser(user);
    await AppStorage.setLastUsername(username);
    await loadMeta();
    online = true;
    notifyListeners();
  }

  Future<void> loadMeta() async {
    try {
      meta = await api!.get<Map<String, dynamic>>('/meta');
      await OfflineDb.setMeta('meta', null);
    } catch (_) {}
  }

  Future<void> logout() async {
    try {
      await api?.post('/auth/logout');
    } catch (_) {}
    await _clearLogin();
    notifyListeners();
  }

  Future<void> unpair() async {
    await logout();
    await OfflineDb.clearAll();
    server = null;
    api = null;
    await AppStorage.setServer(null);
    notifyListeners();
  }

  Future<void> _clearLogin() async {
    user = null;
    api?.token = null;
    await AppStorage.setToken(null);
    await AppStorage.setUser(null);
  }

  void setOnline(bool v) {
    if (online != v) {
      online = v;
      notifyListeners();
    }
  }

  Future<void> setCurrency(String? code) async {
    await AppStorage.setCurrency(code);
    notifyListeners();
  }

  Future<void> toggleDark() async {
    darkMode = !darkMode;
    await AppStorage.setDarkMode(darkMode);
    notifyListeners();
  }

  void refresh() => notifyListeners();

  // ---------------- تحديث الصلاحيات مباشرة ----------------
  Timer? _liveTimer;

  /// يعيد قراءة المستخدم وصلاحياته من الكمبيوتر دورياً، فأي تعديل من الأدمن يتفعّل فوراً بدون تسجيل دخول.
  void startLiveRefresh() {
    _liveTimer?.cancel();
    _liveTimer = Timer.periodic(const Duration(seconds: 15), (_) => refreshMe());
  }

  void stopLiveRefresh() {
    _liveTimer?.cancel();
    _liveTimer = null;
  }

  bool _refreshing = false;

  Future<void> refreshMe() async {
    if (_refreshing || api?.token == null || user == null) return;
    _refreshing = true;
    try {
      final me = await api!.get<Map<String, dynamic>>('/auth/me');
      final changed = '${me['permissions']}' != '${user?['permissions']}' ||
          me['role'] != user?['role'] ||
          me['full_name'] != user?['full_name'];
      user = me;
      await AppStorage.setUser(me);
      if (!online) online = true;
      if (changed) {
        await loadMeta();
        notifyListeners();
      }
    } on ApiException catch (e) {
      if (e.unauthorized) {
        await _clearLogin();
        notifyListeners();
      }
    } finally {
      _refreshing = false;
    }
  }
}

final sessionProvider = ChangeNotifierProvider<Session>((ref) => Session());
