import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';

final usersProvider = FutureProvider.autoDispose<List<dynamic>>((ref) async {
  return ref.watch(sessionProvider).api!.get<List<dynamic>>('/users');
});

/// قائمة الصلاحيات وافتراضيات كل دور (من السيرفر).
final permissionsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  return ref.watch(sessionProvider).api!.get<Map<String, dynamic>>('/permissions');
});

const _roles = {'admin': 'أدمن', 'manager': 'مدير', 'seller': 'بائع', 'viewer': 'مستخدم (بحث فقط)'};

class UsersScreen extends ConsumerWidget {
  const UsersScreen({super.key, this.embedded = false});

  final bool embedded;

  Future<void> _edit(BuildContext context, WidgetRef ref, Map<String, dynamic>? user) async {
    final saved = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => UserEditScreen(user: user)));
    if (saved == true) ref.invalidate(usersProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(usersProvider);
    return Scaffold(
      appBar: embedded ? null : AppBar(title: const Text('المستخدمون')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _edit(context, ref, null),
        icon: const Icon(Icons.person_add),
        label: const Text('مستخدم'),
      ),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(usersProvider)),
        data: (rows) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(usersProvider),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 90),
            children: [
              for (final u in rows.cast<Map<String, dynamic>>())
                Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: CircleAvatar(child: Text('${u['full_name']}'.characters.firstOrNull ?? '?')),
                    title: Text('${u['full_name']}'),
                    subtitle: Text('${u['username']} • ${u['role_label']}'),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          u['is_active'] == true ? Icons.check_circle : Icons.block,
                          color: u['is_active'] == true ? Brand.success : Brand.danger,
                          size: 20,
                        ),
                        const SizedBox(width: 4),
                        const Icon(Icons.chevron_left),
                      ],
                    ),
                    onTap: () => _edit(context, ref, u),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// إنشاء مستخدم أو تعديله بالكامل: البيانات، الدور، كلمة السر، العمولة، الحالة، والصلاحيات.
class UserEditScreen extends ConsumerStatefulWidget {
  const UserEditScreen({super.key, this.user});

  final Map<String, dynamic>? user;

  @override
  ConsumerState<UserEditScreen> createState() => _UserEditScreenState();
}

class _UserEditScreenState extends ConsumerState<UserEditScreen> {
  late final _username = TextEditingController(text: '${widget.user?['username'] ?? ''}');
  late final _name = TextEditingController(text: '${widget.user?['full_name'] ?? ''}');
  late final _phone = TextEditingController(text: '${widget.user?['phone'] ?? ''}');
  late final _commission = TextEditingController(text: '${widget.user?['commission_rate'] ?? 0}');
  final _password = TextEditingController();
  late String _role = '${widget.user?['role'] ?? 'viewer'}';
  late bool _active = widget.user?['is_active'] != false;
  late Map<String, bool> _overrides = {
    for (final e in ((widget.user?['overrides'] as Map?) ?? {}).entries) '${e.key}': e.value == true,
  };
  bool _saving = false;

  bool get _isNew => widget.user == null;

  @override
  void dispose() {
    for (final c in [_username, _name, _phone, _commission, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Set<String> _defaults(Map<String, dynamic> meta) =>
      {...((meta['defaults'] as Map?)?[_role] as List? ?? []).map((e) => '$e')};

  bool _granted(String perm, Map<String, dynamic> meta) => _overrides[perm] ?? _defaults(meta).contains(perm);

  void _toggle(String perm, bool value, Map<String, dynamic> meta) {
    setState(() {
      if (value == _defaults(meta).contains(perm)) {
        _overrides.remove(perm);
      } else {
        _overrides[perm] = value;
      }
    });
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final api = ref.read(sessionProvider).api!;
    final commission = double.tryParse(_commission.text.replaceAll(',', '').trim()) ?? 0;
    try {
      if (_isNew) {
        await api.post('/users', {
          'username': _username.text.trim(),
          'password': _password.text,
          'role': _role,
          'full_name': _name.text.trim(),
          'phone': _phone.text.trim(),
          'commission_rate': commission,
          'permissions': _overrides,
          'is_active': _active,
        });
      } else {
        await api.patch('/users/${widget.user!['id']}', {
          'full_name': _name.text.trim(),
          'phone': _phone.text.trim(),
          'role': _role,
          'is_active': _active,
          'commission_rate': commission,
          'permissions': _overrides,
          if (_password.text.isNotEmpty) 'password': _password.text,
        });
      }
      if (!mounted) return;
      showMsg(context, _isNew ? 'تمت إضافة المستخدم' : 'تم حفظ التعديلات');
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete() async {
    final ok = await confirmDialog(context, 'حذف المستخدم «${widget.user!['username']}»؟', yes: 'حذف', danger: true);
    if (!ok || !mounted) return;
    try {
      await ref.read(sessionProvider).api!.delete('/users/${widget.user!['id']}');
      if (!mounted) return;
      showMsg(context, 'تم حذف المستخدم');
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  Widget _field(TextEditingController c, String label, IconData icon,
      {bool ltr = false, bool obscure = false, bool number = false, bool enabled = true, String? hint}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: c,
        enabled: enabled,
        obscureText: obscure,
        textDirection: ltr ? TextDirection.ltr : null,
        keyboardType: number ? const TextInputType.numberWithOptions(decimal: true) : null,
        decoration: InputDecoration(labelText: label, hintText: hint, prefixIcon: Icon(icon)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final meta = ref.watch(permissionsProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(_isNew ? 'مستخدم جديد' : 'تعديل مستخدم'),
        actions: [
          if (!_isNew) IconButton(tooltip: 'حذف المستخدم', icon: const Icon(Icons.delete_outline), onPressed: _delete),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 30),
        children: [
          SectionCard(
            title: 'الحساب',
            icon: Icons.person_outline,
            child: Column(
              children: [
                _field(_username, 'اسم المستخدم', Icons.alternate_email, ltr: true, enabled: _isNew),
                _field(_name, 'الاسم الكامل', Icons.badge_outlined),
                _field(_phone, 'الهاتف', Icons.phone_outlined, ltr: true),
                _field(
                  _password,
                  _isNew ? 'كلمة السر (8 أحرف وأرقام)' : 'كلمة سر جديدة',
                  Icons.lock_outline,
                  obscure: true,
                  hint: _isNew ? null : 'اتركها فارغة لعدم التغيير',
                ),
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: DropdownButtonFormField<String>(
                    initialValue: _role,
                    decoration: const InputDecoration(labelText: 'الدور', prefixIcon: Icon(Icons.admin_panel_settings_outlined)),
                    items: [for (final e in _roles.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                    onChanged: (v) => setState(() {
                      _role = v ?? _role;
                      _overrides = {}; // الصلاحيات تعود لافتراضيات الدور الجديد
                    }),
                  ),
                ),
                _field(_commission, 'نسبة العمولة %', Icons.percent, number: true),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _active,
                  onChanged: (v) => setState(() => _active = v),
                  title: const Text('الحساب فعّال'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'الصلاحيات',
            icon: Icons.verified_user_outlined,
            child: meta.when(
              loading: () => const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
              error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(permissionsProvider)),
              data: (m) {
                final perms = ((m['permissions'] as Map?) ?? {}).cast<String, dynamic>();
                final optIn = {...((m['opt_in'] as List?) ?? []).map((e) => '$e')};
                return Column(
                  children: [
                    for (final e in perms.entries)
                      CheckboxListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: _role == 'admin' && !optIn.contains(e.key) ? true : _granted(e.key, m),
                        onChanged: _role == 'admin' && !optIn.contains(e.key) ? null : (v) => _toggle(e.key, v ?? false, m),
                        title: Text('${e.value}${optIn.contains(e.key) ? ' ⚠' : ''}'),
                      ),
                    Text(
                      _role == 'admin'
                          ? 'الأدمن يملك كل الصلاحيات تلقائياً.'
                          : 'الصلاحيات تُضبط تلقائياً حسب الدور، ويمكنك تخصيصها لهذا المستخدم.',
                      style: TextStyle(color: Theme.of(context).colorScheme.outline, fontSize: 12),
                    ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.check_rounded),
            label: Text(_isNew ? 'إضافة المستخدم' : 'حفظ التعديلات'),
          ),
        ],
      ),
    );
  }
}
