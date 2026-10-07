import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// بيانات المنشأة التي تظهر على الفاتورة: التفاصيل، صفحة الفيسبوك (QR)، وحساب شام كاش.
class CompanyScreen extends ConsumerStatefulWidget {
  const CompanyScreen({super.key});

  @override
  ConsumerState<CompanyScreen> createState() => _CompanyScreenState();
}

class _CompanyScreenState extends ConsumerState<CompanyScreen> {
  static const _fields = <(String, String, IconData, bool)>[
    ('name', 'اسم المنشأة', Icons.storefront_outlined, false),
    ('name_en', 'الاسم بالإنكليزية', Icons.translate, true),
    ('address', 'العنوان', Icons.place_outlined, false),
    ('phone', 'الهاتف', Icons.phone_outlined, true),
    ('email', 'البريد', Icons.alternate_email, true),
    ('tax_number', 'الرقم الضريبي', Icons.numbers, true),
    ('invoice_footer', 'عبارة أسفل الفاتورة', Icons.short_text, false),
  ];

  final Map<String, TextEditingController> _c = {
    for (final k in [
      'name',
      'name_en',
      'address',
      'phone',
      'email',
      'tax_number',
      'invoice_footer',
      'invoice_details',
      'facebook_url',
      'shamcash_account',
    ])
      k: TextEditingController(),
  };
  Object? _error;
  bool _loading = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final data = await ref.read(sessionProvider).api!.get<Map<String, dynamic>>('/settings/company');
      for (final e in _c.entries) {
        e.value.text = '${data[e.key] ?? ''}';
      }
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(sessionProvider).api!.put('/settings/company', {for (final e in _c.entries) e.key: e.value.text.trim()});
      if (mounted) showMsg(context, 'تم الحفظ — تظهر التعديلات في الفواتير الجديدة');
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _field(String key, String label, IconData icon, {bool ltr = false, int lines = 1, String? hint}) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: _c[key],
      minLines: lines,
      maxLines: lines == 1 ? 1 : lines + 2,
      textDirection: ltr ? TextDirection.ltr : null,
      decoration: InputDecoration(labelText: label, hintText: hint, prefixIcon: Icon(icon)),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorView(error: _error!, onRetry: _load);
    final clay = Clay.of(context);
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
      children: [
        SectionCard(
          title: 'بيانات المنشأة (تظهر على الفواتير)',
          icon: Icons.storefront_rounded,
          child: Column(children: [for (final f in _fields) _field(f.$1, f.$2, f.$3, ltr: f.$4)]),
        ),
        const SizedBox(height: 14),
        SectionCard(
          title: 'تفاصيل إضافية على الفاتورة',
          icon: Icons.notes_rounded,
          child: _field(
            'invoice_details',
            'كل سطر يظهر تحت اسم المحل',
            Icons.edit_note,
            lines: 3,
            hint: 'مثال: سجل تجاري رقم ...\nواتساب: 09xxxxxxxx',
          ),
        ),
        const SizedBox(height: 14),
        SectionCard(
          title: 'الفيسبوك وشام كاش',
          icon: Icons.qr_code_2_rounded,
          child: Column(
            children: [
              _field('facebook_url', 'صفحة الفيسبوك (تُطبع كرمز QR)', Icons.facebook, ltr: true, hint: 'https://facebook.com/YourPage'),
              _field('shamcash_account', 'حساب شام كاش لاستلام الدفعات', Icons.account_balance_wallet_outlined),
              Text('الشعار يُغيَّر من إعدادات برنامج الكمبيوتر.', style: TextStyle(color: clay.muted, fontSize: 12)),
            ],
          ),
        ),
        const SizedBox(height: 18),
        FilledButton.icon(
          onPressed: _saving ? null : _save,
          icon: _saving
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.check_rounded),
          label: const Text('حفظ'),
        ),
      ],
    );
  }
}
