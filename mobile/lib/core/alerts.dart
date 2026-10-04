import 'dart:async';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../state/session.dart';

/// إشعارات على الموبايل للمنتجات التي قاربت على النفاد (أثناء عمل التطبيق).
class AlertsWatcher {
  AlertsWatcher(this.session);

  final Session session;
  final _plugin = FlutterLocalNotificationsPlugin();
  final Set<int> _seen = {};
  Timer? _timer;
  bool _initialized = false;
  int unread = 0;
  void Function(int unread)? onUnread;

  Future<void> start() async {
    if (!_initialized) {
      await _plugin.initialize(settings: const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')));
      await _plugin
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
      _initialized = true;
    }
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => poll());
    await poll(firstRun: true);
  }

  void stop() => _timer?.cancel();

  Future<void> poll({bool firstRun = false}) async {
    if (!session.loggedIn || !(session.can('dashboard.view') || session.can('inventory.view'))) return;
    try {
      final res = await session.api!.get<Map<String, dynamic>>('/notifications', query: {'unread_only': true});
      unread = (res['unread'] as num?)?.toInt() ?? 0;
      onUnread?.call(unread);
      for (final n in (res['items'] as List).cast<Map<String, dynamic>>()) {
        final id = n['id'] as int;
        if (_seen.add(id) && !firstRun) {
          await _plugin.show(
            id: id,
            title: '${n['title']}',
            body: '${n['body']}',
            notificationDetails: const NotificationDetails(
              android: AndroidNotificationDetails('ft_alerts', 'تنبيهات المخزون',
                  channelDescription: 'نقص المخزون والصلاحية والفواتير الكبيرة',
                  importance: Importance.high, priority: Priority.high),
            ),
          );
        }
      }
    } catch (_) {}
  }
}
