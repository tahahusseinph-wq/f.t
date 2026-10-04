import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/storage.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _user = TextEditingController(text: AppStorage.lastUsername ?? '');
  final _pass = TextEditingController();
  bool _busy = false;
  bool _hide = true;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider).login(_user.text.trim(), _pass.text, 'Android');
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 30),
          Center(child: Image.asset('assets/images/logo.png', width: 120)),
          const SizedBox(height: 14),
          const Text('تسجيل الدخول', textAlign: TextAlign.center, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          Text(session.server?.name.isNotEmpty == true ? session.server!.name : 'مجموعة فاروق الطعمة التجارية',
              textAlign: TextAlign.center, style: TextStyle(color: scheme.outline)),
          const SizedBox(height: 28),
          TextField(
            controller: _user,
            textDirection: TextDirection.ltr,
            decoration: const InputDecoration(labelText: 'اسم المستخدم', prefixIcon: Icon(Icons.person_outline)),
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _pass,
            obscureText: _hide,
            decoration: InputDecoration(
              labelText: 'كلمة السر',
              prefixIcon: const Icon(Icons.lock_outline),
              suffixIcon: IconButton(icon: Icon(_hide ? Icons.visibility : Icons.visibility_off), onPressed: () => setState(() => _hide = !_hide)),
            ),
            onSubmitted: (_) => _login(),
          ),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: scheme.error))),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _login,
            child: _busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('دخول'),
          ),
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: () async {
              if (await confirmDialog(context, 'إلغاء ربط هذا الكمبيوتر وربط سيرفر آخر؟')) {
                await ref.read(sessionProvider).unpair();
              }
            },
            icon: const Icon(Icons.link_off, size: 18),
            label: Text('متصل بـ ${session.server?.primaryHost ?? ''} — تغيير'),
          ),
        ]),
      ),
    );
  }
}
