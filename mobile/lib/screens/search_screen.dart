import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/format.dart';
import '../core/offline_db.dart';
import '../core/storage.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'import_screen.dart';
import 'product_edit_screen.dart';
import 'product_screen.dart';
import 'scanner_screen.dart';

/// الشاشة الرئيسية للمستخدم: البحث بكود المنتج أو مسح الباركود.
class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _ctl = TextEditingController();
  Timer? _debounce;
  List<Map<String, dynamic>> _results = [];
  bool _loading = false;

  Future<void> _open(String code) async {
    code = code.trim();
    if (code.isEmpty) return;
    setState(() => _loading = true);
    try {
      var result = await ref.read(syncProvider).lookup(code);
      if (!mounted) return;
      if (result.$1 == null) {
        // ليس كوداً: نبحث بالاسم
        final found = await _search(code);
        if (!mounted) return;
        if (found.length == 1 && found.first['code'] != null) {
          result = await ref.read(syncProvider).lookup('${found.first['code']}');
          if (!mounted) return;
        }
        if (result.$1 == null) {
          showMsg(context, found.isEmpty ? 'لا يوجد منتج بهذا الاسم أو الكود «$code»' : 'اختر المنتج من النتائج (${found.length})',
              error: found.isEmpty);
          return;
        }
      }
      final Map<String, dynamic> product = result.$1!;
      final offline = result.$2;
      await AppStorage.addRecent(code);
      if (!mounted) return;
      Navigator.push(context, MaterialPageRoute(builder: (_) => ProductScreen(product: product, offline: offline)));
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _onChanged(String text) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => _search(text));
  }

  /// البحث بالاسم أو الكود أو الماركة (كل كلمة تُطابق بأي ترتيب).
  Future<List<Map<String, dynamic>>> _search(String text) async {
    if (text.trim().length < 2) {
      if (mounted) setState(() => _results = []);
      return [];
    }
    final session = ref.read(sessionProvider);
    var found = <Map<String, dynamic>>[];
    try {
      final res = await session.api!.get<Map<String, dynamic>>('/products', query: {
        'q': text.trim(), 'limit': 40, if (session.currency != null) 'currency': session.currency,
      });
      found = (res['items'] as List).cast<Map<String, dynamic>>();
    } on ApiException catch (e) {
      if (!e.offline) return [];
      found = await OfflineDb.search(text.trim());
    }
    if (mounted) setState(() => _results = found);
    return found;
  }

  Future<void> _scan() async {
    final code = await ScannerScreen.scan(context);
    if (code != null) {
      _ctl.text = code;
      await _open(code);
    }
  }

  Future<void> _newProduct() async {
    final res = await Navigator.push<Map<String, dynamic>>(context, MaterialPageRoute(builder: (_) => const ProductEditScreen()));
    if (res != null && res['code'] != null && mounted) {
      _ctl.text = '${res['code']}';
      await _open('${res['code']}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final scheme = Theme.of(context).colorScheme;
    final recent = AppStorage.recentSearches;
    return ListView(padding: const EdgeInsets.all(16), children: [
      if (session.can('products.edit'))
        Align(
          alignment: AlignmentDirectional.centerEnd,
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            OutlinedButton.icon(
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ImportScreen())),
              icon: const Icon(Icons.table_view_rounded),
              label: const Text('استيراد Excel'),
            ),
            FilledButton.tonalIcon(onPressed: _newProduct, icon: const Icon(Icons.add), label: const Text('منتج جديد')),
          ]),
        ),
      Text('أهلاً ${session.displayName} 👋', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      Text('ابحث عن أي منتج بالاسم أو الكود، أو امسح الباركود', style: TextStyle(color: scheme.outline)),
      const SizedBox(height: 16),
      Row(children: [
        Expanded(
          child: TextField(
            controller: _ctl,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: 'كود المنتج أو اسمه',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _loading ? const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator(strokeWidth: 2)) : null,
            ),
            onChanged: _onChanged,
            onSubmitted: _open,
          ),
        ),
        const SizedBox(width: 10),
        SizedBox(
          height: 52,
          width: 56,
          child: FilledButton(onPressed: _scan, style: FilledButton.styleFrom(padding: EdgeInsets.zero), child: const Icon(Icons.qr_code_scanner, size: 28)),
        ),
      ]),
      const SizedBox(height: 12),
      if (_results.isNotEmpty)
        SectionCard(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(children: [
            for (final p in _results)
              ListTile(
                leading: ProductImage(api: session.api, name: p['image'] as String?, size: 44),
                title: Text('${p['name']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Row(children: [
                  Flexible(child: Text('${p['code']}', textDirection: TextDirection.ltr, overflow: TextOverflow.ellipsis)),
                  if (p['quantity'] != null) ...[
                    const SizedBox(width: 8),
                    _StockBadge(quantity: asNum(p['quantity']), unit: '${p['unit'] ?? ''}'),
                  ],
                ]),
                trailing: p['sale_price'] == null
                    ? null
                    : Text(fmtMoney(asNum(p['sale_price']), '${p['currency_symbol'] ?? ''}'), style: const TextStyle(fontWeight: FontWeight.w700)),
                onTap: () => _open('${p['code']}'),
              ),
          ]),
        )
      else if (recent.isNotEmpty) ...[
        Text('عمليات البحث الأخيرة', style: TextStyle(color: scheme.outline)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final r in recent) ActionChip(label: Text(r), avatar: const Icon(Icons.history, size: 16), onPressed: () => _open(r)),
        ]),
      ] else
        const Padding(
          padding: EdgeInsets.only(top: 60),
          child: EmptyState(icon: Icons.qr_code_2_rounded, text: 'امسح باركود المنتج لمعرفة سعره وتفاصيله'),
        ),
    ]);
  }
}


/// الكمية المتبقية في المستودع (أحمر إذا نفدت).
class _StockBadge extends StatelessWidget {
  const _StockBadge({required this.quantity, required this.unit});

  final num quantity;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final out = quantity <= 0;
    final color = out ? Colors.red : Colors.green.shade700;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(10)),
      child: Text(out ? 'نفدت الكمية' : 'باقي ${fmtQty(quantity)} $unit'.trim(),
          style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}
