import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../state/cart.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'invoices_screen.dart';
import 'scanner_screen.dart';

/// البيع من الموبايل: مسح المنتجات، اختيار الزبون، الدفع، وإصدار فاتورة.
class PosScreen extends ConsumerStatefulWidget {
  const PosScreen({super.key});

  @override
  ConsumerState<PosScreen> createState() => _PosScreenState();
}

class _PosScreenState extends ConsumerState<PosScreen> {
  final _search = TextEditingController();
  bool _busy = false;

  Future<String?> _addByCode(String code) async {
    try {
      final (p, _) = await ref.read(syncProvider).lookup(code);
      if (p == null) return 'لا يوجد منتج بالكود $code';
      if (p['sale_price'] == null) return 'لا يمكن بيع هذا المنتج (السعر مخفي)';
      ref.read(cartProvider).add(p);
      return '✓ ${p['name']}';
    } on ApiException catch (e) {
      return e.message;
    }
  }

  Future<void> _scan() async {
    await Navigator.push(context, MaterialPageRoute(
      builder: (_) => ScannerScreen(title: 'امسح المنتجات (متواصل)', continuous: true, onCode: _addByCode),
    ));
  }

  Future<void> _submitSearch(String text) async {
    if (text.trim().isEmpty) return;
    final msg = await _addByCode(text.trim());
    if (mounted && msg != null && !msg.startsWith('✓')) showMsg(context, msg, error: true);
    _search.clear();
  }

  Future<void> _pickCustomer() async {
    final session = ref.read(sessionProvider);
    final picked = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _CustomerPicker(api: session.api!, canAdd: session.can('customers.manage')),
    );
    if (picked != null) {
      final cart = ref.read(cartProvider);
      cart.customer = picked;
      cart.update();
    }
  }

  Future<void> _checkout({bool quotation = false}) async {
    final cart = ref.read(cartProvider);
    final session = ref.read(sessionProvider);
    final sync = ref.read(syncProvider);
    if (cart.isEmpty) return;
    if (!quotation && cart.paymentMethod != 'cash' && cart.customer == null) {
      showMsg(context, 'البيع الآجل يحتاج اختيار زبون', error: true);
      return;
    }
    final opId = sync.newOpId();
    final payload = cart.toPayload(session.currency, priceOverride: session.can('sales.discount'));
    if (quotation) payload['kind'] = 'quotation';
    setState(() => _busy = true);
    try {
      final inv = await session.api!.post<Map<String, dynamic>>('/sales', {...payload, 'client_op_id': opId});
      cart.clear();
      if (mounted) {
        Navigator.push(context, MaterialPageRoute(builder: (_) => InvoiceScreen(invoiceId: inv['id'] as int)));
      }
    } on ApiException catch (e) {
      if (e.offline && !quotation) {
        await sync.queue('sale', payload, 'بيع ${fmtMoney(cart.total, session.currencySymbol)}', opId: opId);
        cart.clear();
        if (mounted) showMsg(context, 'لا يوجد اتصال — حُفظت الفاتورة وستُرسل تلقائياً عند عودة الاتصال');
      } else if (mounted) {
        showMsg(context, e.message, error: true);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editNumber(String title, double current, void Function(double) apply) async {
    final ctl = TextEditingController(text: current == 0 ? '' : fmtQty(current));
    final res = await showDialog<double>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: TextField(controller: ctl, autofocus: true, keyboardType: const TextInputType.numberWithOptions(decimal: true)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, double.tryParse(ctl.text.replaceAll(',', '')) ?? 0), child: const Text('حفظ')),
        ],
      ),
    );
    if (res != null) apply(res);
  }

  @override
  Widget build(BuildContext context) {
    final cart = ref.watch(cartProvider);
    final session = ref.watch(sessionProvider);
    final sym = session.currencySymbol;
    final canDiscount = session.can('sales.discount');
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _search,
              decoration: const InputDecoration(hintText: 'كود المنتج ثم إدخال', prefixIcon: Icon(Icons.search)),
              onSubmitted: _submitSearch,
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            height: 50,
            child: FilledButton.icon(onPressed: _scan, icon: const Icon(Icons.qr_code_scanner), label: const Text('مسح')),
          ),
        ]),
      ),
      Expanded(
        child: cart.isEmpty
            ? const EmptyState(icon: Icons.shopping_cart_outlined, text: 'السلة فارغة\nامسح باركود المنتجات لإضافتها')
            : ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: cart.lines.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (_, i) {
                  final l = cart.lines[i];
                  return Dismissible(
                    key: ValueKey(l.productId),
                    onDismissed: (_) => cart.remove(l),
                    background: Container(color: Brand.danger, alignment: Alignment.center, child: const Icon(Icons.delete, color: Colors.white)),
                    child: Card(
                      child: Padding(
                        padding: const EdgeInsets.all(10),
                        child: Row(children: [
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(l.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
                              InkWell(
                                onTap: canDiscount ? () => _editNumber('سعر القطعة', l.price, (v) { l.price = v; cart.update(); }) : null,
                                child: Text('${fmtMoney(l.price, sym)}${l.discount > 0 ? ' • خصم ${fmtMoney(l.discount, sym)}' : ''}',
                                    style: TextStyle(color: Theme.of(context).colorScheme.outline)),
                              ),
                            ]),
                          ),
                          IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => cart.setQty(l, l.quantity - 1)),
                          InkWell(
                            onTap: () => _editNumber('الكمية', l.quantity, (v) => cart.setQty(l, v)),
                            child: Text(fmtQty(l.quantity), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                          ),
                          IconButton(icon: const Icon(Icons.add_circle_outline), onPressed: () => cart.setQty(l, l.quantity + 1)),
                          SizedBox(
                            width: 84,
                            child: Text(fmtMoney(l.total, sym), textAlign: TextAlign.end, style: const TextStyle(fontWeight: FontWeight.w700)),
                          ),
                        ]),
                      ),
                    ),
                  );
                },
              ),
      ),
      _CheckoutPanel(
        cart: cart,
        symbol: sym,
        canDiscount: canDiscount,
        busy: _busy,
        onCustomer: _pickCustomer,
        onDiscount: () => _editNumber('خصم على الفاتورة', cart.discount, (v) { cart.discount = v; cart.update(); }),
        onPaid: () => _editNumber('المبلغ المدفوع', cart.paid, (v) { cart.paid = v; cart.update(); }),
        onCheckout: () => _checkout(),
        onQuotation: () => _checkout(quotation: true),
      ),
    ]);
  }
}

class _CheckoutPanel extends StatelessWidget {
  const _CheckoutPanel({
    required this.cart, required this.symbol, required this.canDiscount, required this.busy, required this.onCustomer,
    required this.onDiscount, required this.onPaid, required this.onCheckout, required this.onQuotation,
  });

  final Cart cart;
  final String symbol;
  final bool canDiscount;
  final bool busy;
  final VoidCallback onCustomer, onDiscount, onPaid, onCheckout, onQuotation;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      elevation: 8,
      color: scheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: onCustomer,
                  icon: const Icon(Icons.person_outline, size: 18),
                  label: Text(cart.customer == null ? 'زبون نقدي' : '${cart.customer!['name']}', overflow: TextOverflow.ellipsis),
                ),
              ),
              if (canDiscount) ...[
                const SizedBox(width: 8),
                OutlinedButton(onPressed: onDiscount, child: Text(cart.discount > 0 ? 'خصم ${fmtMoney(cart.discount)}' : 'خصم')),
              ],
            ]),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'cash', label: Text('نقدي')),
                ButtonSegment(value: 'credit', label: Text('آجل')),
                ButtonSegment(value: 'partial', label: Text('جزئي')),
              ],
              selected: {cart.paymentMethod},
              onSelectionChanged: (s) {
                cart.paymentMethod = s.first;
                if (s.first == 'credit') cart.paid = 0;
                cart.update();
              },
            ),
            if (cart.paymentMethod == 'partial')
              TextButton(onPressed: onPaid, child: Text('المدفوع: ${fmtMoney(cart.paid, symbol)} — اضغط للتعديل')),
            const SizedBox(height: 6),
            Row(children: [
              const Text('الإجمالي', style: TextStyle(fontSize: 16)),
              const Spacer(),
              Text(fmtMoney(cart.total, symbol), style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: scheme.primary)),
            ]),
            const SizedBox(height: 8),
            Row(children: [
              OutlinedButton(onPressed: cart.isEmpty || busy ? null : onQuotation, child: const Text('عرض سعر')),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton.icon(
                  onPressed: cart.isEmpty || busy ? null : onCheckout,
                  icon: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.check),
                  label: const Text('إتمام البيع'),
                ),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

class _CustomerPicker extends StatefulWidget {
  const _CustomerPicker({required this.api, required this.canAdd});

  final ApiClient api;
  final bool canAdd;

  @override
  State<_CustomerPicker> createState() => _CustomerPickerState();
}

class _CustomerPickerState extends State<_CustomerPicker> {
  List<Map<String, dynamic>> _items = [];
  final _q = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await widget.api.get<List<dynamic>>('/customers', query: {'q': _q.text});
      if (mounted) setState(() => _items = res.cast<Map<String, dynamic>>());
    } catch (_) {}
  }

  Future<void> _add() async {
    final name = TextEditingController();
    final phone = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('زبون جديد'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: name, decoration: const InputDecoration(labelText: 'الاسم')),
          const SizedBox(height: 8),
          TextField(controller: phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'الهاتف')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('إضافة')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final c = await widget.api.post<Map<String, dynamic>>('/customers', {'name': name.text, 'phone': phone.text});
      if (mounted) Navigator.pop(context, c);
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SizedBox(
          height: MediaQuery.of(context).size.height * 0.7,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _q,
                    decoration: const InputDecoration(hintText: 'بحث بالاسم أو الهاتف', prefixIcon: Icon(Icons.search)),
                    onChanged: (_) => _load(),
                  ),
                ),
                if (widget.canAdd) IconButton.filled(onPressed: _add, icon: const Icon(Icons.person_add)),
              ]),
            ),
            ListTile(leading: const Icon(Icons.person_off_outlined), title: const Text('زبون نقدي (بدون اسم)'), onTap: () => Navigator.pop(context)),
            Expanded(
              child: ListView(children: [
                for (final c in _items)
                  ListTile(
                    leading: const Icon(Icons.person),
                    title: Text('${c['name']}'),
                    subtitle: Text('${c['phone']}'),
                    trailing: c['balance'] != null && asNum(c['balance']) > 0
                        ? Text('دين ${fmtMoney(asNum(c['balance']))}', style: const TextStyle(color: Brand.danger))
                        : null,
                    onTap: () => Navigator.pop(context, c),
                  ),
              ]),
            ),
          ]),
        ),
      );
}
