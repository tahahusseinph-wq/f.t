import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/format.dart';
import '../core/offline_db.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';

class MoreScreen extends ConsumerStatefulWidget {
  const MoreScreen({super.key});

  @override
  ConsumerState<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends ConsumerState<MoreScreen> {
  List<Map<String, dynamic>> ops = [];

  @override
  void initState() {
    super.initState();
    _loadOps();
  }

  Future<void> _loadOps() async {
    final list = await OfflineDb.pendingOps();
    if (mounted) setState(() => ops = list);
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final sync = ref.watch(syncProvider);
    final currencies = (session.meta['currencies'] as List?)?.cast<Map>() ?? [];
    return ListView(padding: const EdgeInsets.fromLTRB(12, 4, 12, 24), children: [
      ClayCard(
        padding: EdgeInsets.zero,
        child: ListTile(
          leading: CircleAvatar(backgroundColor: Brand.primary, child: Text(session.displayName.characters.firstOrNull ?? '؟', style: const TextStyle(color: Colors.white))),
          title: Text(session.displayName, style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(session.roleLabel),
        ),
      ),
      const SizedBox(height: 12),
      SectionCard(
        title: 'المزامنة والعمل بدون اتصال',
        icon: Icons.sync,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('منتجات محفوظة على الجهاز: ${sync.cachedProducts}'),
          Text('آخر مزامنة: ${sync.lastSync == null ? '—' : fmtDate(sync.lastSync!.toIso8601String())}'),
          Text('عمليات بانتظار الإرسال: ${sync.pending}'),
          if (sync.lastError != null) Text(sync.lastError!, style: const TextStyle(color: Brand.danger, fontSize: 12)),
          for (final o in ops)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(o['error'] == null ? Icons.schedule : Icons.error_outline, color: o['error'] == null ? Brand.warning : Brand.danger),
              title: Text('${o['title']}'),
              subtitle: Text(o['error'] == null ? fmtDate(o['created_at'] as String?) : 'رفض السيرفر: ${o['error']}'),
              trailing: IconButton(
                icon: const Icon(Icons.delete_outline),
                onPressed: () async {
                  if (await confirmDialog(context, 'حذف هذه العملية المعلقة نهائياً؟', danger: true)) {
                    await sync.discardOp(o['op_id'] as String);
                    _loadOps();
                  }
                },
              ),
            ),
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: sync.syncing ? null : () async {
              await sync.syncAll();
              await _loadOps();
              if (context.mounted) showMsg(context, sync.lastError ?? 'تمت المزامنة', error: sync.lastError != null);
            },
            icon: const Icon(Icons.sync),
            label: Text(sync.syncing ? 'جارِ المزامنة...' : 'مزامنة الآن'),
          ),
        ]),
      ),
      const SizedBox(height: 12),
      SectionCard(
        title: 'الإعدادات',
        icon: Icons.settings_outlined,
        child: Column(children: [
          if (currencies.length > 1)
            DropdownButtonFormField<String>(
              initialValue: session.currency,
              decoration: const InputDecoration(labelText: 'عملة عرض الأسعار'),
              items: [for (final c in currencies) DropdownMenuItem(value: '${c['code']}', child: Text('${c['name']} (${c['symbol']})'))],
              onChanged: (v) async {
                await session.setCurrency(v);
                await OfflineDb.setMeta('products_since', null);
                sync.syncAll();
              },
            ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('الوضع الليلي'),
            value: session.darkMode,
            onChanged: (_) => session.toggleDark(),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.computer),
            title: const Text('السيرفر'),
            subtitle: Text('${session.server?.primaryHost}:${session.server?.port} ${session.online ? '• متصل' : '• غير متصل'}'),
          ),
        ]),
      ),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        onPressed: () async {
          if (await confirmDialog(context, 'تسجيل الخروج؟')) await session.logout();
        },
        icon: const Icon(Icons.logout),
        label: const Text('تسجيل الخروج'),
      ),
      TextButton(
        onPressed: () async {
          if (await confirmDialog(context, 'إلغاء ربط الجهاز بالكمبيوتر وحذف البيانات المحلية؟', danger: true)) await session.unpair();
        },
        child: const Text('إلغاء ربط الجهاز', style: TextStyle(color: Brand.danger)),
      ),
      const SizedBox(height: 8),
      Center(child: Text('مجموعة الطعمة التجارية • الإصدار 1.0.0', style: TextStyle(color: Theme.of(context).colorScheme.outline, fontSize: 12))),
    ]);
  }
}
