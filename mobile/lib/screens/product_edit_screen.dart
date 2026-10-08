import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// إضافة منتج أو تعديله من الموبايل (للأدمن ومن لديه صلاحية تعديل المنتجات).
/// الأسعار بالعملة الأساسية للبرنامج.
class ProductEditScreen extends ConsumerStatefulWidget {
  const ProductEditScreen({super.key, this.productId});

  final int? productId;

  @override
  ConsumerState<ProductEditScreen> createState() => _ProductEditScreenState();
}

class _ProductEditScreenState extends ConsumerState<ProductEditScreen> {
  static const _text = ['name', 'code', 'barcode', 'brand', 'model', 'location', 'warranty', 'details', 'notes'];
  static const _nums = ['cost_price', 'margin', 'sale_price', 'min_stock', 'initial_quantity'];

  final Map<String, TextEditingController> _c = {
    for (final k in [..._text, ..._nums]) k: TextEditingController(),
  };
  int? _categoryId;
  String _unit = 'قطعة';
  bool _priceLocked = false;
  bool _loading = true;
  bool _saving = false;
  Object? _error;
  String _baseCurrency = '';
  XFile? _photo;
  String _photoMime = 'image/jpeg';
  bool _attachPhoto = true;
  bool _aiBusy = false;

  bool get _isNew => widget.productId == null;

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

  String _numText(dynamic v) {
    if (v == null) return '';
    final n = v is num ? v : num.tryParse('$v');
    if (n == null) return '';
    return n == n.roundToDouble() ? n.toInt().toString() : n.toString();
  }

  Future<void> _load() async {
    final session = ref.read(sessionProvider);
    if (session.meta.isEmpty) await session.loadMeta();
    final base = ((session.meta['currencies'] as List?) ?? []).cast<Map>().where((c) => c['is_base'] == true);
    _baseCurrency = base.isEmpty ? '' : '${base.first['symbol'] ?? base.first['code']}';
    if (_isNew) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    try {
      final p = await session.api!.get<Map<String, dynamic>>('/products/${widget.productId}/edit');
      for (final k in _text) {
        _c[k]!.text = '${p[k] ?? ''}';
      }
      for (final k in _nums) {
        _c[k]!.text = _numText(p[k]);
      }
      _categoryId = p['category_id'] as int?;
      _unit = '${p['unit'] ?? 'قطعة'}';
      _priceLocked = p['price_locked'] == true;
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _loading = false;
        });
      }
    }
  }

  double? _num(String k) {
    final t = _c[k]!.text.replaceAll(',', '').trim();
    return t.isEmpty ? null : double.tryParse(t);
  }

  Future<void> _save() async {
    if (_c['name']!.text.trim().isEmpty) {
      showMsg(context, 'أدخل اسم المنتج', error: true);
      return;
    }
    setState(() => _saving = true);
    final body = <String, dynamic>{
      for (final k in _text) k: _c[k]!.text.trim(),
      'category_id': _categoryId,
      'unit': _unit,
      'cost_price': _num('cost_price') ?? 0,
      'margin': _num('margin'),
      'sale_price': _num('sale_price') ?? 0,
      'min_stock': _num('min_stock'),
      'price_locked': _priceLocked,
      if (_isNew) 'initial_quantity': _num('initial_quantity') ?? 0,
    };
    try {
      final api = ref.read(sessionProvider).api!;
      final res = _isNew
          ? await api.post<Map<String, dynamic>>('/products', body)
          : await api.put<Map<String, dynamic>>('/products/${widget.productId}', body);
      if (_photo != null && _attachPhoto && res['id'] != null) {
        try {
          final bytes = await _photo!.readAsBytes();
          await api.post('/products/${res['id']}/image', {'image_base64': base64Encode(bytes), 'mime': _photoMime});
        } on ApiException catch (e) {
          if (mounted) showMsg(context, 'تم حفظ المنتج لكن تعذر رفع الصورة: ${e.message}', error: true);
        }
      }
      if (!mounted) return;
      showMsg(context, _isNew ? 'تمت إضافة المنتج' : 'تم حفظ التعديلات');
      Navigator.pop(context, res);
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// يصوّر المنتج (أو يختار صورته) ويجلب كل تفاصيله بالذكاء الاصطناعي.
  Future<void> _fromImage() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('صورة المنتج', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('تصوير بالكاميرا'),
            onTap: () => Navigator.pop(c, ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library_outlined),
            title: const Text('اختيار من المعرض'),
            onTap: () => Navigator.pop(c, ImageSource.gallery),
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
    if (source == null) return;
    final XFile? file;
    try {
      file = await ImagePicker().pickImage(source: source, maxWidth: 1600, maxHeight: 1600, imageQuality: 85);
    } catch (e) {
      if (mounted) showMsg(context, 'تعذر فتح الكاميرا أو المعرض: $e', error: true);
      return;
    }
    if (file == null) return;
    final bytes = await file.readAsBytes();
    final mime = file.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';
    setState(() {
      _photo = file;
      _photoMime = mime;
      _aiBusy = true;
    });
    try {
      final api = ref.read(sessionProvider).api!;
      final info = await api.post<Map<String, dynamic>>('/ai/product-from-image', {
        'image_base64': base64Encode(bytes),
        'mime': mime,
        'hint': _c['name']!.text.trim(),
      });
      if (!mounted) return;
      void put(String key, dynamic value, {bool onlyIfEmpty = false}) {
        final text = '${value ?? ''}'.trim();
        if (text.isEmpty) return;
        if (onlyIfEmpty && _c[key]!.text.trim().isNotEmpty) return;
        _c[key]!.text = text;
      }

      setState(() {
        put('name', info['name']);
        put('brand', info['brand']);
        put('model', info['model']);
        put('barcode', info['barcode'], onlyIfEmpty: true);
        put('warranty', info['warranty'], onlyIfEmpty: true);
        put('details', info['details']);
        final unit = '${info['unit'] ?? ''}'.trim();
        if (unit.isNotEmpty) _unit = unit;
        if (info['category_id'] != null) _categoryId = info['category_id'] as int;
        final price = asNum(info['estimated_price']);
        if (price > 0 && _c['sale_price']!.text.trim().isEmpty) {
          _c['sale_price']!.text = _numText(price);
          _priceLocked = true;
        }
      });
      final cat = '${info['suggested_category'] ?? ''}';
      showMsg(context, 'تمت تعبئة تفاصيل المنتج من الصورة — راجعها قبل الحفظ'
          '${info['category_id'] == null && cat.isNotEmpty ? ' (القسم المقترح: $cat)' : ''}');
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _aiBusy = false);
    }
  }

  Future<void> _delete() async {
    final ok = await confirmDialog(
      context,
      'حذف المنتج «${_c['name']!.text}»؟\nإذا كان له مبيعات سابقة سيتم إيقافه بدل حذفه.',
      yes: 'حذف',
      danger: true,
    );
    if (!ok || !mounted) return;
    try {
      final res = await ref.read(sessionProvider).api!.delete<Map<String, dynamic>>('/products/${widget.productId}');
      if (!mounted) return;
      showMsg(context, res['result'] == 'deleted' ? 'تم حذف المنتج' : 'المنتج له مبيعات سابقة فتم إيقافه');
      Navigator.pop(context, <String, dynamic>{'deleted': true});
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  Widget _field(
    String key,
    String label, {
    IconData? icon,
    bool number = false,
    bool ltr = false,
    int lines = 1,
    String? hint,
    ValueChanged<String>? onChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: _c[key],
        minLines: lines,
        maxLines: lines == 1 ? 1 : lines + 3,
        keyboardType: number ? const TextInputType.numberWithOptions(decimal: true) : null,
        textDirection: ltr ? TextDirection.ltr : null,
        onChanged: onChanged,
        decoration: InputDecoration(labelText: label, hintText: hint, prefixIcon: icon == null ? null : Icon(icon)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final cats = ((session.meta['categories'] as List?) ?? []).cast<Map>();
    final units = ((session.meta['units'] as List?) ?? const ['قطعة']).map((e) => '$e').toList();
    if (!units.contains(_unit)) units.insert(0, _unit);
    final cur = _baseCurrency.isEmpty ? '' : ' ($_baseCurrency)';
    return Scaffold(
      appBar: AppBar(
        title: Text(_isNew ? 'منتج جديد' : 'تعديل المنتج'),
        actions: [
          if (!_isNew && session.can('products.delete'))
            IconButton(tooltip: 'حذف المنتج', icon: const Icon(Icons.delete_outline), onPressed: _delete),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? ErrorView(error: _error!, onRetry: _load)
          : ListView(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 30),
              children: [
                SectionCard(
                  title: 'البحث عن تفاصيل المنتج بالصورة',
                  icon: Icons.auto_awesome_rounded,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_photo != null) ...[
                        ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: Image.file(File(_photo!.path), height: 160, fit: BoxFit.cover),
                        ),
                        CheckboxListTile(
                          contentPadding: EdgeInsets.zero,
                          value: _attachPhoto,
                          onChanged: (v) => setState(() => _attachPhoto = v ?? true),
                          title: const Text('إضافة هذه الصورة لصور المنتج'),
                        ),
                      ],
                      FilledButton.tonalIcon(
                        onPressed: _aiBusy ? null : _fromImage,
                        icon: _aiBusy
                            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.photo_camera_outlined),
                        label: Text(_aiBusy ? 'جارِ التعرف على المنتج...' : 'صوّر المنتج واملأ التفاصيل تلقائياً'),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'يتعرف الذكاء الاصطناعي (Gemini) على المنتج من صورته ويعبّي الاسم والماركة والموديل والتفاصيل والكفالة.',
                        style: TextStyle(fontSize: 12),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                SectionCard(
                  title: 'المعلومات الأساسية',
                  icon: Icons.inventory_2_outlined,
                  child: Column(
                    children: [
                      _field('name', 'اسم المنتج *', icon: Icons.label_outline),
                      _field('code', 'الكود', icon: Icons.qr_code, ltr: true, hint: 'اتركه فارغاً ليُولَّد تلقائياً'),
                      _field('barcode', 'الباركود', icon: Icons.qr_code_scanner, ltr: true),
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: DropdownButtonFormField<int?>(
                          initialValue: cats.any((c) => c['id'] == _categoryId) ? _categoryId : null,
                          isExpanded: true,
                          decoration: const InputDecoration(labelText: 'القسم', prefixIcon: Icon(Icons.category_outlined)),
                          items: [
                            const DropdownMenuItem<int?>(value: null, child: Text('بدون قسم')),
                            for (final c in cats)
                              DropdownMenuItem<int?>(
                                value: c['id'] as int,
                                child: Text(
                                  '${'  ' * ((c['depth'] as num?)?.toInt() ?? 0)}${c['name']}',
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                          ],
                          onChanged: (v) => setState(() => _categoryId = v),
                        ),
                      ),
                      _field('brand', 'الماركة', icon: Icons.sell_outlined),
                      _field('model', 'الموديل', icon: Icons.tag),
                      DropdownButtonFormField<String>(
                        initialValue: _unit,
                        decoration: const InputDecoration(labelText: 'الوحدة', prefixIcon: Icon(Icons.straighten)),
                        items: [for (final u in units) DropdownMenuItem(value: u, child: Text(u))],
                        onChanged: (v) => setState(() => _unit = v ?? _unit),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                SectionCard(
                  title: 'الأسعار$cur',
                  icon: Icons.payments_outlined,
                  child: Column(
                    children: [
                      _field('cost_price', 'سعر التكلفة', icon: Icons.shopping_bag_outlined, number: true),
                      _field('margin', 'نسبة الربح %', icon: Icons.percent, number: true, hint: 'فارغ = نسبة القسم'),
                      _field(
                        'sale_price',
                        'سعر البيع',
                        icon: Icons.sell,
                        number: true,
                        onChanged: (_) => setState(() => _priceLocked = true),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: _priceLocked,
                        onChanged: (v) => setState(() => _priceLocked = v),
                        title: const Text('سعر البيع يدوي'),
                        subtitle: const Text('عند الإيقاف يُحسب السعر من التكلفة ونسبة الربح'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                SectionCard(
                  title: 'المخزون والكفالة',
                  icon: Icons.warehouse_outlined,
                  child: Column(
                    children: [
                      if (_isNew) _field('initial_quantity', 'الكمية الابتدائية', icon: Icons.add_box_outlined, number: true),
                      _field('min_stock', 'حد التنبيه', icon: Icons.notifications_active_outlined, number: true, hint: 'فارغ = الافتراضي'),
                      _field('location', 'الموقع في المستودع', icon: Icons.place_outlined),
                      _field('warranty', 'مدة الكفالة', icon: Icons.verified_user_outlined, hint: 'مثال: سنة — فارغ = بدون كفالة'),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                SectionCard(
                  title: 'تفاصيل وملاحظات',
                  icon: Icons.notes_rounded,
                  child: Column(children: [_field('details', 'التفاصيل', lines: 3), _field('notes', 'ملاحظات', lines: 2)]),
                ),
                const SizedBox(height: 18),
                FilledButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.check_rounded),
                  label: Text(_isNew ? 'إضافة المنتج' : 'حفظ التعديلات'),
                ),
              ],
            ),
    );
  }
}
