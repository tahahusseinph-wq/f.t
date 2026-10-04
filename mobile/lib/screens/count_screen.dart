import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'scanner_screen.dart';

/// الجرد بالموبايل: امسح المنتج فيُضاف للكمية المعدودة في جلسة الجرد المفتوحة.
class CountScreen extends ConsumerStatefulWidget {
  const CountScreen({super.key});

  @override
  ConsumerState<CountScreen> createState() => _CountScreenState();
}

class _CountScreenState extends ConsumerState<CountScreen> {
  List<Map<String, dynamic>> counts = [];
  Map<String, dynamic>? current;
  Object? error;
  bool loading = true;
  bool askQty = false;

  ApiClient get api => ref.read(sessionProvider).api!;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      counts = (await api.get<List<dynamic>>('/counts')).cast<Map<String, dynamic>>();
      if (counts.isNotEmpty) {
        final id = current?['id'] ?? counts.first['id'];
        current = await api.get<Map<String, dynamic>>('/counts/$id');
      } else {
        current = null;
      }
      error = null;
    } catch (e) {
      error = e;
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> _start() async {
    try {
      current = await api.post<Map<String, dynamic>>('/counts', {'notes': 'جرد من الموبايل'});
      await _load();
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    }
  }

  Future<String?> _scanned(String code) async {
    if (current == null) return 'ابدأ جلسة جرد أولاً';
    double qty = 1;
    if (askQty && mounted) {
      final ctl = TextEditingController(text: '1');
      final v = await showDialog<double>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text('الكمية للكود $code'),
          content: TextField(controller: ctl, autofocus: true, keyboardType: const TextInputType.numberWithOptions(decimal: true)),
          actions: [FilledButton(onPressed: () => Navigator.pop(c, double.tryParse(ctl.text) ?? 1), child: const Text('إضافة'))],
        ),
      );
      if (v == null) return null;
      qty = v;
    }
    final sync = ref.read(syncProvider);
    final opId = sync.newOpId();
    final body = {'code': code, 'quantity': qty, 'mode': 'add'};
    try {
      final line = await api.post<Map<String, dynamic>>('/counts/${current!['id']}/lines', {...body, 'client_op_id': opId});
      _load();
      return '✓ ${line['name']} — المعدود ${fmtQty(asNum(line['counted_qty']))}';
    } on ApiException catch (e) {
      if (e.offline) {
        await sync.queue('count_line', {'count_id': current!['id'], ...body}, 'جرد $code', opId: opId);
        return 'حُفظ بدون اتصال: $code';
      }
      return e.message;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading && current == null && error == null) return const Center(child: CircularProgressIndicator());
    if (error != null) return ErrorView(error: error!, onRetry: _load);
    if (current == null) {
      return EmptyState(
        icon: Icons.inventory_outlined,
        text: 'لا توجد جلسة جرد مفتوحة',
        action: FilledButton.icon(onPressed: _start, icon: const Icon(Icons.add), label: const Text('بدء جرد جديد')),
      );
    }
    final lines = (current!['lines'] as List).cast<Map<String, dynamic>>();
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          if (counts.length > 1)
            DropdownButtonFormField<int>(
              initialValue: current!['id'] as int,
              items: [for (final c in counts) DropdownMenuItem(value: c['id'] as int, child: Text('جرد #${c['id']} — ${c['warehouse']}'))],
              onChanged: (v) async {
                current = await api.get<Map<String, dynamic>>('/counts/$v');
                setState(() {});
              },
            )
          else
            Text('جرد #${current!['id']} — ${current!['warehouse']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('اسأل عن الكمية عند كل مسح'),
            subtitle: const Text('عند الإيقاف: كل مسح = قطعة واحدة'),
            value: askQty,
            onChanged: (v) => setState(() => askQty = v),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.push(context, MaterialPageRoute(
              builder: (_) => ScannerScreen(title: 'جرد — امسح المنتجات', continuous: true, onCode: _scanned),
            )).then((_) => _load()),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('ابدأ المسح'),
          ),
        ]),
      ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _load,
          child: lines.isEmpty
              ? ListView(children: const [SizedBox(height: 60), EmptyState(icon: Icons.qr_code, text: 'لم يتم عد أي منتج بعد')])
              : ListView.separated(
                  itemCount: lines.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (_, i) {
                    final l = lines[i];
                    final diff = asNum(l['difference']);
                    return ListTile(
                      title: Text('${l['name']}'),
                      subtitle: Text('${l['code']} • في النظام ${fmtQty(asNum(l['system_qty']))}'),
                      trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                        Text(fmtQty(asNum(l['counted_qty'])), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                        Text(diff == 0 ? 'مطابق' : (diff > 0 ? '+${fmtQty(diff)}' : fmtQty(diff)),
                            style: TextStyle(color: diff == 0 ? Brand.success : Brand.danger, fontSize: 12)),
                      ]),
                    );
                  },
                ),
        ),
      ),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Text('تطبيق نتيجة الجرد يتم من برنامج الأدمن على الكمبيوتر بعد المراجعة.',
            textAlign: TextAlign.center, style: TextStyle(color: Theme.of(context).colorScheme.outline, fontSize: 12)),
      ),
    ]);
  }
}
