import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';

final invoicesProvider = FutureProvider.autoDispose.family<List<dynamic>, String>((ref, kind) async {
  return ref.watch(sessionProvider).api!.get<List<dynamic>>('/invoices', query: {'kind': kind});
});

class InvoicesScreen extends ConsumerStatefulWidget {
  const InvoicesScreen({super.key});

  @override
  ConsumerState<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends ConsumerState<InvoicesScreen> {
  String kind = 'sale';

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(invoicesProvider(kind));
    return Scaffold(
      appBar: AppBar(title: const Text('الفواتير')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'sale', label: Text('مبيعات')),
              ButtonSegment(value: 'return', label: Text('مرتجعات')),
              ButtonSegment(value: 'quotation', label: Text('عروض أسعار')),
            ],
            selected: {kind},
            onSelectionChanged: (s) => setState(() => kind = s.first),
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async => ref.invalidate(invoicesProvider(kind)),
            child: data.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(invoicesProvider(kind))),
              data: (rows) => rows.isEmpty
                  ? const EmptyState(icon: Icons.receipt_long, text: 'لا توجد فواتير')
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      itemCount: rows.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (_, i) {
                        final inv = rows[i] as Map<String, dynamic>;
                        return ListTile(
                          title: Text('${inv['number']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                          subtitle: Text('${inv['customer_name'] == '' ? 'زبون نقدي' : inv['customer_name']} • ${fmtDate(inv['created_at'] as String?)}'),
                          trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                            Text(fmtMoney(asNum(inv['total']), '${inv['currency_symbol']}'), style: const TextStyle(fontWeight: FontWeight.w700)),
                            if (asNum(inv['remaining']) > 0 && inv['kind'] == 'sale')
                              Text('متبقي ${fmtMoney(asNum(inv['remaining']))}', style: const TextStyle(color: Brand.danger, fontSize: 12)),
                            if (inv['status'] == 'cancelled') const Text('ملغاة', style: TextStyle(color: Brand.danger, fontSize: 12)),
                          ]),
                          onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => InvoiceScreen(invoiceId: inv['id'] as int))),
                        );
                      },
                    ),
            ),
          ),
        ),
      ]),
    );
  }
}

class InvoiceScreen extends ConsumerStatefulWidget {
  const InvoiceScreen({super.key, required this.invoiceId});

  final int invoiceId;

  @override
  ConsumerState<InvoiceScreen> createState() => _InvoiceScreenState();
}

class _InvoiceScreenState extends ConsumerState<InvoiceScreen> {
  Map<String, dynamic>? inv;
  Object? error;
  bool sharing = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await ref.read(sessionProvider).api!.get<Map<String, dynamic>>('/invoices/${widget.invoiceId}');
      setState(() => inv = res);
    } catch (e) {
      setState(() => error = e);
    }
  }

  Future<void> _share(String paper) async {
    setState(() => sharing = true);
    try {
      final file = await ref.read(sessionProvider).api!.downloadPdf(widget.invoiceId, '${inv!['number']}', paper: paper);
      await SharePlus.instance.share(ShareParams(
        files: [XFile(file.path, mimeType: 'application/pdf')],
        text: 'فاتورة ${inv!['number']} — الإجمالي ${fmtMoney(asNum(inv!['total']), '${inv!['currency_symbol']}')}',
      ));
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => sharing = false);
    }
  }

  Future<void> _convert() async {
    try {
      final res = await ref.read(sessionProvider).api!.post<Map<String, dynamic>>('/invoices/${widget.invoiceId}/convert');
      if (mounted) Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => InvoiceScreen(invoiceId: res['id'] as int)));
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final i = inv;
    final sym = '${i?['currency_symbol'] ?? ''}';
    final title = switch (i?['kind']) { 'return' => 'مرتجع', 'quotation' => 'عرض سعر', _ => 'فاتورة' };
    return Scaffold(
      appBar: AppBar(title: Text(i == null ? 'الفاتورة' : '$title ${i['number']}')),
      body: i == null
          ? (error != null ? ErrorView(error: error!, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : ListView(padding: const EdgeInsets.all(16), children: [
              Center(child: Image.asset('assets/images/logo.png', width: 70)),
              const SizedBox(height: 8),
              SectionCard(
                child: Column(children: [
                  _row('الرقم', '${i['number']}'),
                  _row('التاريخ', fmtDate(i['created_at'] as String?)),
                  _row('الزبون', i['customer_name'] == '' ? 'زبون نقدي' : '${i['customer_name']}'),
                  _row('البائع', '${i['seller']}'),
                ]),
              ),
              const SizedBox(height: 10),
              SectionCard(
                title: 'الأصناف',
                child: Column(children: [
                  for (final it in (i['items'] as List).cast<Map<String, dynamic>>())
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      title: Text('${it['name']}'),
                      subtitle: Text('${fmtQty(asNum(it['quantity']))} × ${fmtMoney(asNum(it['unit_price']))}'),
                      trailing: Text(fmtMoney(asNum(it['total']), sym), style: const TextStyle(fontWeight: FontWeight.w700)),
                    ),
                ]),
              ),
              const SizedBox(height: 10),
              SectionCard(
                child: Column(children: [
                  _row('المجموع', fmtMoney(asNum(i['subtotal']), sym)),
                  if (asNum(i['discount']) > 0) _row('الخصم', fmtMoney(asNum(i['discount']), sym)),
                  if (asNum(i['tax']) > 0) _row('الضريبة', fmtMoney(asNum(i['tax']), sym)),
                  _row('الإجمالي', fmtMoney(asNum(i['total']), sym), bold: true),
                  if (i['kind'] == 'sale') _row('المدفوع', fmtMoney(asNum(i['paid']), sym)),
                  if (i['kind'] == 'sale' && asNum(i['remaining']) > 0) _row('المتبقي (دين)', fmtMoney(asNum(i['remaining']), sym), color: Brand.danger),
                ]),
              ),
              const SizedBox(height: 16),
              Row(children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: sharing ? null : () => _share('A4'),
                    icon: const Icon(Icons.share),
                    label: const Text('مشاركة PDF (واتساب)'),
                  ),
                ),
                const SizedBox(width: 8),
                OutlinedButton(onPressed: sharing ? null : () => _share('80mm'), child: const Text('إيصال 80mm')),
              ]),
              if (i['kind'] == 'quotation' && i['status'] == 'open') ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(onPressed: _convert, icon: const Icon(Icons.transform), label: const Text('تحويل إلى فاتورة بيع')),
              ],
            ]),
    );
  }

  Widget _row(String k, String v, {bool bold = false, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Text(k, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
          const Spacer(),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.w700 : FontWeight.w500, fontSize: bold ? 18 : 14, color: color)),
        ]),
      );
}
