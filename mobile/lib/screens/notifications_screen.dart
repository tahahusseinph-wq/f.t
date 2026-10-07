import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/format.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'product_screen.dart';

final notificationsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  return ref.watch(sessionProvider).api!.get<Map<String, dynamic>>('/notifications');
});

class AlertTile extends ConsumerWidget {
  const AlertTile({super.key, required this.alert});

  final Map<String, dynamic> alert;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final color = switch (alert['severity']) { 'danger' => Brand.danger, 'warning' => Brand.warning, _ => Brand.primary };
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: CircleAvatar(
        backgroundColor: color.withValues(alpha: 0.12),
        child: Icon(alert['severity'] == 'info' ? Icons.info_outline : Icons.warning_amber_rounded, color: color),
      ),
      title: Text('${alert['title']}', style: TextStyle(fontWeight: alert['is_read'] == true ? FontWeight.normal : FontWeight.w700)),
      subtitle: Text('${alert['body']}\n${fmtDate(alert['created_at'] as String?)}', style: const TextStyle(fontSize: 12)),
      isThreeLine: true,
      onTap: () async {
        final session = ref.read(sessionProvider);
        try {
          await session.api!.post('/notifications/${alert['id']}/read');
        } catch (_) {}
        if (alert['entity'] == 'product' && alert['entity_id'] != null && context.mounted) {
          try {
            final p = await session.api!.get<Map<String, dynamic>>('/products/${alert['entity_id']}');
            if (context.mounted) Navigator.push(context, MaterialPageRoute(builder: (_) => ProductScreen(product: p)));
          } catch (_) {}
        }
      },
    );
  }
}

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key, this.embedded = false});

  /// داخل الهيكل الرئيسي (بدون شريط عنوان خاص)
  final bool embedded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(notificationsProvider);
    Future<void> readAll() async {
      await ref.read(sessionProvider).api!.post('/notifications/read-all');
      ref.invalidate(notificationsProvider);
    }

    return Scaffold(
      appBar: embedded
          ? null
          : AppBar(title: const Text('الإشعارات'), actions: [
              IconButton(tooltip: 'تحديد الكل كمقروء', icon: const Icon(Icons.done_all), onPressed: readAll),
            ]),
      floatingActionButton: embedded
          ? FloatingActionButton.extended(onPressed: readAll, icon: const Icon(Icons.done_all), label: const Text('تحديد الكل كمقروء'))
          : null,
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(notificationsProvider),
        child: data.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(notificationsProvider)),
          data: (d) {
            final items = (d['items'] as List).cast<Map<String, dynamic>>();
            if (items.isEmpty) return const EmptyState(icon: Icons.notifications_none, text: 'لا توجد إشعارات');
            return ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, i) => AlertTile(alert: items[i]),
            );
          },
        ),
      ),
    );
  }
}
