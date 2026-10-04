import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/discovery.dart';
import '../core/storage.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'scanner_screen.dart';

/// ربط التطبيق بكمبيوتر الأدمن: مسح QR، بحث تلقائي، أو إدخال يدوي.
class PairingScreen extends ConsumerStatefulWidget {
  const PairingScreen({super.key});

  @override
  ConsumerState<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends ConsumerState<PairingScreen> {
  final _manual = TextEditingController();
  bool _busy = false;
  List<ServerInfo> _found = [];
  bool _searching = false;

  Future<void> _connect(ServerInfo? s) async {
    if (s == null) {
      showMsg(context, 'رمز أو عنوان غير صالح', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(sessionProvider).pair(s);
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _scan() async {
    final code = await ScannerScreen.scan(context, title: 'امسح رمز الربط من شاشة الكمبيوتر');
    if (code != null) await _connect(ServerInfo.parse(code));
  }

  Future<void> _discover() async {
    setState(() {
      _searching = true;
      _found = [];
    });
    final list = await discoverServers();
    if (!mounted) return;
    setState(() {
      _found = list;
      _searching = false;
    });
    if (list.isEmpty) showMsg(context, 'لم يتم العثور على سيرفر. جرّب مسح رمز QR.');
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 24),
          Center(child: Image.asset('assets/images/logo.png', width: 130)),
          const SizedBox(height: 16),
          const Text('مجموعة فاروق الطعمة التجارية', textAlign: TextAlign.center, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          Text('اربط التطبيق ببرنامج الأدمن على الكمبيوتر', textAlign: TextAlign.center, style: TextStyle(color: scheme.outline)),
          const SizedBox(height: 28),
          FilledButton.icon(
            onPressed: _busy ? null : _scan,
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('مسح رمز QR من الكمبيوتر'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _busy || _searching ? null : _discover,
            icon: _searching ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.wifi_find),
            label: Text(_searching ? 'جارِ البحث في الشبكة...' : 'بحث تلقائي في الشبكة'),
          ),
          for (final s in _found)
            Card(
              child: ListTile(
                leading: const Icon(Icons.computer),
                title: Text('سيرفر ${s.id}'),
                subtitle: Text('${s.primaryHost}:${s.port}'),
                trailing: const Icon(Icons.chevron_left),
                onTap: () => _connect(s),
              ),
            ),
          const SizedBox(height: 24),
          Text('أو أدخل العنوان يدوياً', style: TextStyle(color: scheme.outline)),
          const SizedBox(height: 8),
          TextField(
            controller: _manual,
            textDirection: TextDirection.ltr,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(hintText: '192.168.1.10:8765', prefixIcon: Icon(Icons.lan_outlined)),
            onSubmitted: (v) => _connect(ServerInfo.parse(v)),
          ),
          const SizedBox(height: 10),
          OutlinedButton(onPressed: _busy ? null : () => _connect(ServerInfo.parse(_manual.text)), child: const Text('اتصال')),
          if (_busy) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
          const SizedBox(height: 24),
          Text(
            'تأكد أن الموبايل متصل بنفس الواي فاي (نفس الراوتر) الموصول عليه الكمبيوتر، وأن برنامج الأدمن مفتوح.',
            textAlign: TextAlign.center,
            style: TextStyle(color: scheme.outline, fontSize: 12),
          ),
        ]),
      ),
    );
  }
}
