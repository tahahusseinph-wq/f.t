import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/storage.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'pairing_screen.dart';

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
  bool _searching = false;

  static const _notFound = 'تعذر العثور على السيرفر. تأكد أن الموبايل على نفس الواي فاي وأن برنامج الأدمن مفتوح، أو اتصل يدوياً من الأسفل.';

  @override
  void initState() {
    super.initState();
    if (!ref.read(sessionProvider).paired) _find();
  }

  /// بحث تلقائي عن السيرفر بدون أي تدخل من المستخدم.
  Future<bool> _find() async {
    setState(() => _searching = true);
    final ok = await ref.read(sessionProvider).autoConnect();
    if (mounted) setState(() => _searching = false);
    return ok;
  }

  Future<void> _login() async {
    final session = ref.read(sessionProvider);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (!session.paired && !await _find()) {
        setState(() => _error = _notFound);
        return;
      }
      try {
        await session.login(_user.text.trim(), _pass.text, 'Android');
      } on ApiException catch (e) {
        // قد يكون عنوان الكمبيوتر تغيّر: نبحث من جديد ونعيد المحاولة مرة واحدة
        if (!e.offline) rethrow;
        if (!await _find()) throw ApiException(_notFound, offline: true);
        await session.login(_user.text.trim(), _pass.text, 'Android');
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final scheme = Theme.of(context).colorScheme;
    final clay = Clay.of(context);
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 30),
          Center(
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: clay.raised(radius: 80, depth: 1.2),
              child: Image.asset('assets/images/logo.png', width: 110),
            ),
          ),
          const SizedBox(height: 14),
          const Text('تسجيل الدخول', textAlign: TextAlign.center, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          Text(session.server?.name.isNotEmpty == true ? session.server!.name : 'مجموعة الطعمة التجارية',
              textAlign: TextAlign.center, style: TextStyle(color: scheme.outline)),
          if (_searching)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('جارِ البحث عن السيرفر في الشبكة...', textAlign: TextAlign.center, style: TextStyle(color: scheme.outline, fontSize: 12)),
            ),
          const SizedBox(height: 28),
          ClayCard(
            radius: 28,
            padding: const EdgeInsets.all(18),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
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
            ]),
          ),
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const PairingScreen())),
            icon: const Icon(Icons.settings_ethernet, size: 18),
            label: Text(session.paired ? 'متصل بـ ${session.server?.primaryHost ?? ''} — تغيير' : 'اتصال يدوي بالسيرفر'),
          ),
        ]),
      ),
    );
  }
}
