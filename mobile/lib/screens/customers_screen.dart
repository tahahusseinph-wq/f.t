import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../state/cart.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'home_shell.dart';

/// الزبائن: البحث، الديون، استلام دفعة، إضافة زبون، والبيع لزبون محدد.
class CustomersScreen extends ConsumerStatefulWidget {
  const CustomersScreen({super.key});

  @override
  ConsumerState<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends ConsumerState<CustomersScreen> {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _items = [];
  Object? _error;
  bool _loading = true;
  bool _debtOnly = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await ref.read(sessionProvider).api!.get<List<dynamic>>('/customers', query: {'q': _q.text.trim()});
      if (!mounted) return;
      setState(() {
        _items = res.cast<Map<String, dynamic>>();
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  /// أرصدة الزبائن محفوظة بالعملة الأساسية.
  String get _baseSymbol {
    final list = (ref.read(sessionProvider).meta['currencies'] as List?) ?? [];
    for (final c in list) {
      if (c['is_base'] == true) return '${c['symbol']}';
    }
    return '';
  }

  Future<void> _add() async {
    final name = TextEditingController();
    final phone = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('زبون جديد'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'الاسم'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: phone,
              keyboardType: TextInputType.phone,
              textDirection: TextDirection.ltr,
              decoration: const InputDecoration(labelText: 'الهاتف'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('إضافة')),
        ],
      ),
    );
    if (ok != true || name.text.trim().isEmpty) return;
    try {
      await ref.read(sessionProvider).api!.post('/customers', {'name': name.text.trim(), 'phone': phone.text.trim()});
      if (mounted) showMsg(context, 'تمت إضافة الزبون');
      _load();
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  Future<void> _receive(Map<String, dynamic> c) async {
    final amount = TextEditingController();
    final notes = TextEditingController();
    final balance = asNum(c['balance']);
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text('استلام دفعة من ${c['name']}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'الرصيد المستحق: ${fmtMoney(balance, _baseSymbol)}',
              style: const TextStyle(color: Brand.danger, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: amount,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: 'المبلغ ($_baseSymbol)'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: notes,
              decoration: const InputDecoration(labelText: 'ملاحظات (مثلاً: عبر شام كاش)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('تسجيل الدفعة')),
        ],
      ),
    );
    final value = double.tryParse(amount.text.replaceAll(',', '')) ?? 0;
    if (ok != true || value <= 0) return;
    try {
      await ref.read(sessionProvider).api!.post('/customers/${c['id']}/payments', {'amount': value, 'notes': notes.text.trim()});
      if (mounted) showMsg(context, 'تم تسجيل الدفعة');
      _load();
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  void _sellTo(Map<String, dynamic> c) {
    final cart = ref.read(cartProvider);
    cart.customer = c;
    cart.update();
    ref.read(shellPageProvider.notifier).state = 'pos';
  }

  @override
  Widget build(BuildContext context) {
    final clay = Clay.of(context);
    final rows = _debtOnly ? _items.where((c) => asNum(c['balance']) > 0).toList() : _items;
    final totalDebt = _items.fold<num>(0, (s, c) => s + asNum(c['balance']));
    final canSell = ref.watch(sessionProvider).can('sales.create');
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _add,
        icon: const Icon(Icons.person_add_alt_1),
        label: const Text('زبون'),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: TextField(
              controller: _q,
              decoration: const InputDecoration(hintText: 'بحث بالاسم أو الهاتف', prefixIcon: Icon(Icons.search)),
              onChanged: (_) => _load(),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Row(
              children: [
                FilterChip(label: const Text('أصحاب الديون فقط'), selected: _debtOnly, onSelected: (v) => setState(() => _debtOnly = v)),
                const Spacer(),
                if (totalDebt > 0)
                  Text(
                    'إجمالي الديون: ${fmtMoney(totalDebt, _baseSymbol)}',
                    style: const TextStyle(color: Brand.danger, fontWeight: FontWeight.w700),
                  ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _load,
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                  ? ErrorView(error: _error!, onRetry: _load)
                  : rows.isEmpty
                  ? const EmptyState(icon: Icons.people_outline, text: 'لا يوجد زبائن')
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(12, 4, 12, 90),
                      itemCount: rows.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 10),
                      itemBuilder: (_, i) {
                        final c = rows[i];
                        final debt = asNum(c['balance']);
                        return ClayCard(
                          radius: 20,
                          padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
                          child: Row(
                            children: [
                              CircleAvatar(
                                backgroundColor: clay.primarySoft,
                                child: Text(
                                  '${c['name']}'.characters.firstOrNull ?? '؟',
                                  style: TextStyle(color: clay.primary, fontWeight: FontWeight.w700),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('${c['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                                    if ('${c['phone'] ?? ''}'.isNotEmpty)
                                      Text(
                                        '${c['phone']}',
                                        textDirection: TextDirection.ltr,
                                        style: TextStyle(color: clay.muted, fontSize: 12),
                                      ),
                                    Text(
                                      debt > 0 ? 'عليه ${fmtMoney(debt, _baseSymbol)}' : 'لا يوجد دين',
                                      style: TextStyle(
                                        color: debt > 0 ? Brand.danger : Brand.success,
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (debt > 0)
                                IconButton(
                                  tooltip: 'استلام دفعة',
                                  icon: const Icon(Icons.payments_outlined, color: Brand.success),
                                  onPressed: () => _receive(c),
                                ),
                              if (canSell)
                                IconButton(
                                  tooltip: 'بيع لهذا الزبون',
                                  icon: Icon(Icons.add_shopping_cart_rounded, color: clay.primary),
                                  onPressed: () => _sellTo(c),
                                ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
          ),
        ],
      ),
    );
  }
}
