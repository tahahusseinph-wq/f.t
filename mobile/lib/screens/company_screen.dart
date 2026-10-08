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
    ('invoice_footer', 'عبارة أسفل الفاتورة', Icons.short_text, false),
  ];

  final Map<String, TextEditingController> _c = {
    for (final k in [
      'name',
      'name_en',
      'address',
      'phone',
      'email',
      'invoice_footer',
      'invoice_details',
      'facebook_url',
      'shamcash_account',
    ])
      k: TextEditingController(),
  };
  // تصميم الفاتورة وقياساتها (تُحفظ على الكمبيوتر وتُطبق على كل الفواتير)
  static const _flags = <(String, String)>[
    ('show_code', 'عمود كود الصنف'),
    ('show_unit', 'الوحدة مع الكمية'),
    ('show_seller', 'اسم البائع'),
    ('show_qr', 'رمز QR للفاتورة'),
    ('show_signatures', 'خانات التوقيع'),
    ('show_stamp', 'خانة الختم'),
    ('show_warranty', 'عمود الكفالة'),
  ];
  final Map<String, TextEditingController> _iv = {
    for (final k in ['sale_title', 'quotation_title', 'terms', 'payment_info']) k: TextEditingController(),
  };
  final Map<String, bool> _flagValues = {};
  List<Map<String, dynamic>> _sizes = [];
  double _margin = 12;
  bool _invoiceLoaded = false;

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
    for (final c in [..._c.values, ..._iv.values]) {
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
      if (ref.read(sessionProvider).can('settings.manage')) {
        try {
          final iv = await ref.read(sessionProvider).api!.get<Map<String, dynamic>>('/settings/invoice');
          for (final e in _iv.entries) {
            e.value.text = '${iv[e.key] ?? ''}';
          }
          for (final f in _flags) {
            _flagValues[f.$1] = iv[f.$1] != false;
          }
          _sizes = ((iv['sizes'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
          _margin = ((iv['margin_mm'] as num?) ?? 12).toDouble();
          _invoiceLoaded = true;
        } on ApiException catch (_) {
          // سيرفر قديم بدون إعدادات التصميم — نعرض بيانات المنشأة فقط
        }
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
      final api = ref.read(sessionProvider).api!;
      await api.put('/settings/company', {for (final e in _c.entries) e.key: e.value.text.trim()});
      if (_invoiceLoaded) {
        await api.put('/settings/invoice', {
          for (final e in _iv.entries) e.key: e.value.text.trim(),
          ..._flagValues,
          for (final sz in _sizes) '${sz['key']}': (sz['value'] as num).round(),
          'margin_mm': _margin.round(),
        });
      }
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

  Widget _ivField(String key, String label, IconData icon, {int lines = 1}) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: _iv[key],
      minLines: lines,
      maxLines: lines == 1 ? 1 : lines + 3,
      decoration: InputDecoration(labelText: label, prefixIcon: Icon(icon)),
    ),
  );

  Widget _sizeSlider(Map<String, dynamic> sz) {
    final min = (sz['min'] as num).toDouble();
    final max = (sz['max'] as num).toDouble();
    final value = (sz['value'] as num).toDouble().clamp(min, max);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(children: [
          Expanded(child: Text('${sz['label']}')),
          Text('${value.round()}%', style: const TextStyle(fontWeight: FontWeight.w700)),
        ]),
        Slider(
          min: min,
          max: max,
          divisions: ((max - min) / 5).round(),
          value: value,
          onChanged: (v) => setState(() => sz['value'] = v.round()),
        ),
      ],
    );
  }

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
              _field('shamcash_account', 'رمز حساب شام كاش (يُطبع QR على الفاتورة)', Icons.account_balance_wallet_outlined),
              Text('الشعار يُغيَّر من إعدادات برنامج الكمبيوتر.', style: TextStyle(color: clay.muted, fontSize: 12)),
            ],
          ),
        ),
        if (_invoiceLoaded) ...[
          const SizedBox(height: 14),
          SectionCard(
            title: 'قياسات الفاتورة',
            icon: Icons.format_size_rounded,
            trailing: TextButton(
              onPressed: () => setState(() {
                for (final sz in _sizes) {
                  sz['value'] = sz['default'];
                }
                _margin = 12;
              }),
              child: const Text('الافتراضي'),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final sz in _sizes) _sizeSlider(sz),
                Row(children: [
                  const Expanded(child: Text('هوامش الورقة')),
                  Text('${_margin.round()} مم', style: const TextStyle(fontWeight: FontWeight.w700)),
                ]),
                Slider(min: 3, max: 30, divisions: 27, value: _margin.clamp(3, 30), onChanged: (v) => setState(() => _margin = v)),
                Text('100% = الحجم الأساسي. كبّر «اسم المنشأة» لتكبير اسم المحل على الفاتورة.',
                    style: TextStyle(color: clay.muted, fontSize: 12)),
              ],
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: 'تصميم الفاتورة',
            icon: Icons.receipt_long_rounded,
            child: Column(
              children: [
                _ivField('sale_title', 'عنوان فاتورة البيع', Icons.title),
                _ivField('quotation_title', 'عنوان عرض السعر', Icons.request_quote_outlined),
                _ivField('terms', 'الشروط والأحكام (كل سطر بند)', Icons.gavel_rounded, lines: 3),
                _ivField('payment_info', 'معلومات الدفع', Icons.account_balance_outlined, lines: 2),
                for (final f in _flags)
                  SwitchListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: _flagValues[f.$1] ?? true,
                    onChanged: (v) => setState(() => _flagValues[f.$1] = v),
                    title: Text(f.$2),
                  ),
              ],
            ),
          ),
        ],
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
