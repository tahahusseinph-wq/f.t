import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../state/cart.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'product_edit_screen.dart';

/// تفاصيل المنتج: يعرض فقط ما سمح به السيرفر حسب صلاحيات المستخدم.
class ProductScreen extends ConsumerStatefulWidget {
  const ProductScreen({super.key, required this.product, this.offline = false});

  final Map<String, dynamic> product;
  final bool offline;

  @override
  ConsumerState<ProductScreen> createState() => _ProductScreenState();
}

class _ProductScreenState extends ConsumerState<ProductScreen> {
  late Map<String, dynamic> p = widget.product;

  Future<void> _reload() async {
    final session = ref.read(sessionProvider);
    try {
      final fresh = await session.api!.get<Map<String, dynamic>>('/products/${p['id']}', query: {
        if (session.currency != null) 'currency': session.currency,
      });
      if (mounted) setState(() => p = fresh);
    } on ApiException catch (_) {}
  }

  Future<void> _edit() async {
    final res = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(builder: (_) => ProductEditScreen(productId: p['id'] as int)),
    );
    if (res == null || !mounted) return;
    if (res['deleted'] == true) {
      Navigator.pop(context);
      return;
    }
    await _reload();
  }

  Future<void> _adjustStock() async {
    final ctl = TextEditingController(text: fmtQty(asNum(p['quantity'])));
    final reason = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('تعديل الكمية'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: ctl, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'الكمية الجديدة')),
          const SizedBox(height: 10),
          TextField(controller: reason, decoration: const InputDecoration(labelText: 'السبب')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('حفظ')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final qty = double.tryParse(ctl.text.replaceAll(',', ''));
    if (qty == null) return;
    final sync = ref.read(syncProvider);
    final opId = sync.newOpId();
    final body = {'quantity': qty, 'reason': reason.text.isEmpty ? 'تعديل من الموبايل' : reason.text, 'client_op_id': opId};
    try {
      await ref.read(sessionProvider).api!.patch('/products/${p['id']}/stock', body);
      if (mounted) showMsg(context, 'تم تعديل الكمية');
      await _reload();
    } on ApiException catch (e) {
      if (e.offline) {
        await sync.queue('stock', {'product_id': p['id'], ...body}..remove('client_op_id'), 'تعديل كمية ${p['name']}', opId: opId);
        if (mounted) showMsg(context, 'لا يوجد اتصال — حُفظت العملية وستُرسل تلقائياً');
      } else if (mounted) {
        showMsg(context, e.message, error: true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final scheme = Theme.of(context).colorScheme;
    final symbol = '${p['currency_symbol'] ?? ''}';
    final promo = p['promotion'] as Map?;
    final images = (p['images'] as List?)?.cast<String>() ?? (p['image'] != null ? [p['image'] as String] : <String>[]);
    final fields = (p['fields'] as List?)?.cast<Map>() ?? [];
    final variants = (p['variants'] as List?)?.cast<Map>() ?? [];

    return Scaffold(
      appBar: AppBar(
        title: const Text('تفاصيل المنتج'),
        actions: [
          if (session.can('products.edit') && !widget.offline)
            IconButton(tooltip: 'تعديل المنتج', icon: const Icon(Icons.edit_outlined), onPressed: _edit),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (widget.offline)
            const Padding(
              padding: EdgeInsets.only(bottom: 10),
              child: Text('⚠ معروض من النسخة المحلية (بدون اتصال) وقد لا يكون محدثاً', style: TextStyle(color: Brand.warning)),
            ),
          if (images.isNotEmpty)
            SizedBox(
              height: 200,
              child: PageView(children: [
                for (final img in images) Center(child: ProductImage(api: session.api, name: img, size: 200)),
              ]),
            ),
          const SizedBox(height: 12),
          Text('${p['name']}', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Row(children: [
            Icon(Icons.qr_code, size: 16, color: scheme.outline),
            const SizedBox(width: 4),
            SelectableText('${p['code']}', style: TextStyle(color: scheme.outline)),
            const Spacer(),
            if (p['stock_status'] != null) StatusChip(status: p['stock_status'] as String?),
          ]),
          const SizedBox(height: 14),
          if (p['sale_price'] != null)
            Card(
              color: scheme.primary,
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(children: [
                  const Text('السعر', style: TextStyle(color: Colors.white70)),
                  Text(fmtMoney(asNum(p['sale_price']), symbol, session.currencyDecimals),
                      style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w700)),
                  if (promo != null)
                    Text('بدلاً من ${fmtMoney(asNum(p['base_price']), symbol)} — ${promo['name']} (خصم ${promo['percent']}%)',
                        style: const TextStyle(color: Colors.white, fontSize: 13)),
                ]),
              ),
            ),
          if (p['warranty'] != null) ...[
            const SizedBox(height: 10),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: Chip(
                avatar: Icon(
                  p['warranty'] == 'بدون كفالة' ? Icons.gpp_bad_outlined : Icons.verified_user_outlined,
                  size: 18,
                  color: p['warranty'] == 'بدون كفالة' ? scheme.outline : Brand.success,
                ),
                label: Text('${p['warranty']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              ),
            ),
          ],
          if (p['quantity'] != null) ...[
            const SizedBox(height: 10),
            KpiTile(label: 'الكمية المتوفرة', value: '${fmtQty(asNum(p['quantity']))} ${p['unit'] ?? ''}', icon: Icons.warehouse_outlined, color: Brand.success),
          ],
          const SizedBox(height: 10),
          if (fields.isNotEmpty)
            SectionCard(
              title: 'التفاصيل',
              icon: Icons.info_outline,
              child: Column(children: [for (final f in fields) _FieldRow(field: f, symbol: symbol)]),
            ),
          if (variants.isNotEmpty) ...[
            const SizedBox(height: 10),
            SectionCard(
              title: 'المتغيرات المتوفرة',
              icon: Icons.palette_outlined,
              child: Column(children: [
                for (final v in variants)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text((v['attrs'] as Map).values.join(' / ')),
                    subtitle: Text('${v['code']}'),
                    trailing: v['quantity'] == null ? null : Text(fmtQty(asNum(v['quantity']))),
                  ),
              ]),
            ),
          ],
          const SizedBox(height: 16),
          if (session.can('sales.create') && p['sale_price'] != null)
            FilledButton.icon(
              onPressed: () {
                ref.read(cartProvider).add(p);
                showMsg(context, 'أُضيف إلى سلة البيع');
              },
              icon: const Icon(Icons.add_shopping_cart),
              label: const Text('إضافة إلى سلة البيع'),
            ),
          if (session.can('inventory.adjust')) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: _adjustStock, icon: const Icon(Icons.edit_note), label: const Text('تعديل الكمية')),
          ],
          if (session.can('products.edit') && !widget.offline) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: _edit, icon: const Icon(Icons.edit_outlined), label: const Text('تعديل بيانات المنتج والأسعار')),
          ],
        ]),
      ),
    );
  }
}

class _FieldRow extends StatelessWidget {
  const _FieldRow({required this.field, required this.symbol});

  final Map field;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final value = field['value'];
    final type = field['type'];
    String text;
    if (type == 'money') {
      text = fmtMoney(asNum(value), symbol);
    } else if (type == 'percent') {
      text = '${fmtQty(asNum(value))}%';
    } else if (type == 'map' && value is Map) {
      text = value.entries.map((e) => '${e.key}: ${e.value}').join('\n');
    } else {
      text = '$value';
    }
    final long = type == 'longtext' || type == 'map';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: long
          ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${field['label']}', style: TextStyle(color: Theme.of(context).colorScheme.outline, fontSize: 13)),
              const SizedBox(height: 2),
              Text(text),
            ])
          : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 120, child: Text('${field['label']}', style: TextStyle(color: Theme.of(context).colorScheme.outline, fontSize: 13))),
              Expanded(child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600))),
            ]),
    );
  }
}
