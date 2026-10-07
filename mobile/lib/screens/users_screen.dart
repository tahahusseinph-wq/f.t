import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';

final usersProvider = FutureProvider.autoDispose<List<dynamic>>((ref) async {
  return ref.watch(sessionProvider).api!.get<List<dynamic>>('/users');
});

const _roles = {'admin': 'أدمن', 'manager': 'مدير', 'seller': 'بائع', 'viewer': 'مستخدم (بحث فقط)'};

class UsersScreen extends ConsumerWidget {
  const UsersScreen({super.key, this.embedded = false});

  final bool embedded;

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final user = TextEditingController();
    final name = TextEditingController();
    final pass = TextEditingController();
    String role = 'viewer';
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('مستخدم جديد'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: user, textDirection: TextDirection.ltr, decoration: const InputDecoration(labelText: 'اسم المستخدم')),
              const SizedBox(height: 8),
              TextField(controller: name, decoration: const InputDecoration(labelText: 'الاسم الكامل')),
              const SizedBox(height: 8),
              TextField(controller: pass, obscureText: true, decoration: const InputDecoration(labelText: 'كلمة السر (8 أحرف وأرقام)')),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'الدور'),
                items: [for (final e in _roles.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                onChanged: (v) => set(() => role = v ?? role),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('إضافة')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(sessionProvider).api!.post('/users', {'username': user.text.trim(), 'full_name': name.text, 'password': pass.text, 'role': role});
      ref.invalidate(usersProvider);
      if (context.mounted) showMsg(context, 'تمت إضافة المستخدم');
    } on ApiException catch (e) {
      if (context.mounted) showMsg(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(usersProvider);
    return Scaffold(
      appBar: embedded ? null : AppBar(title: const Text('المستخدمون')),
      floatingActionButton: FloatingActionButton.extended(onPressed: () => _add(context, ref), icon: const Icon(Icons.person_add), label: const Text('مستخدم')),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(usersProvider)),
        data: (rows) => ListView(padding: const EdgeInsets.all(12), children: [
          for (final u in rows.cast<Map<String, dynamic>>())
            Card(
              margin: const EdgeInsets.only(bottom: 8),
              child: SwitchListTile(
                secondary: CircleAvatar(child: Text('${u['full_name']}'.characters.first)),
                title: Text('${u['full_name']}'),
                subtitle: Text('${u['username']} • ${u['role_label']}'),
                value: u['is_active'] == true,
                activeThumbColor: Brand.success,
                onChanged: (v) async {
                  try {
                    await ref.read(sessionProvider).api!.patch('/users/${u['id']}', {'is_active': v});
                    ref.invalidate(usersProvider);
                  } on ApiException catch (e) {
                    if (context.mounted) showMsg(context, e.message, error: true);
                  }
                },
              ),
            ),
        ]),
      ),
    );
  }
}
