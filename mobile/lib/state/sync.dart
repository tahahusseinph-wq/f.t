import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:uuid/uuid.dart';

import '../core/api.dart';
import '../core/offline_db.dart';
import 'session.dart';

/// مزامنة المنتجات وطابور العمليات المؤجلة عند انقطاع الاتصال.
class SyncService extends ChangeNotifier {
  SyncService(this.session);

  final Session session;
  final _uuid = const Uuid();
  Timer? _timer;
  bool syncing = false;
  int pending = 0;
  int cachedProducts = 0;
  DateTime? lastSync;
  String? lastError;

  void start() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(minutes: 2), (_) => syncAll());
    syncAll();
  }

  void stop() => _timer?.cancel();

  String newOpId() => _uuid.v4();

  Future<void> syncAll() async {
    if (syncing || !session.loggedIn) return;
    syncing = true;
    notifyListeners();
    try {
      if (!session.online) await session.reconnect();
      await flushQueue();
      await pullProducts();
      session.setOnline(true);
      lastError = null;
      lastSync = DateTime.now();
    } on ApiException catch (e) {
      if (e.offline) session.setOnline(false);
      lastError = e.message;
    } finally {
      syncing = false;
      pending = (await OfflineDb.pendingOps()).length;
      cachedProducts = await OfflineDb.productCount();
      notifyListeners();
    }
  }

  Future<void> pullProducts({bool full = false}) async {
    final api = session.api!;
    final since = full ? null : await OfflineDb.meta('products_since');
    final res = await api.get<Map<String, dynamic>>('/sync/products', query: {
      if (since != null) 'since': since,
      if (session.currency != null) 'currency': session.currency,
    });
    final items = (res['items'] as List).cast<Map<String, dynamic>>();
    await OfflineDb.upsertProducts(items, replaceAll: res['full'] == true);
    await OfflineDb.removeProducts((res['removed'] as List).cast<int>());
    await OfflineDb.setMeta('products_since', res['server_time'] as String);
  }

  /// يرسل العمليات المحفوظة دفعة واحدة؛ السيرفر يتجاهل المكرر بفضل client_op_id.
  Future<List<Map<String, dynamic>>> flushQueue() async {
    final ops = await OfflineDb.pendingOps();
    if (ops.isEmpty) return [];
    final res = await session.api!.post<Map<String, dynamic>>('/sync/ops', {
      'ops': [for (final o in ops) {'client_op_id': o['op_id'], 'type': o['type'], 'payload': o['payload']}],
    });
    final results = (res['results'] as List).cast<Map<String, dynamic>>();
    for (final r in results) {
      if (r['ok'] == true) {
        await OfflineDb.removeOp(r['client_op_id'] as String);
      } else {
        await OfflineDb.markOpError(r['client_op_id'] as String, '${r['error']}');
      }
    }
    pending = (await OfflineDb.pendingOps()).length;
    notifyListeners();
    return results;
  }

  Future<void> queue(String type, Map<String, dynamic> payload, String title, {String? opId}) async {
    await OfflineDb.enqueue(opId ?? newOpId(), type, payload, title);
    pending = (await OfflineDb.pendingOps()).length;
    notifyListeners();
  }

  Future<void> discardOp(String opId) async {
    await OfflineDb.removeOp(opId);
    pending = (await OfflineDb.pendingOps()).length;
    notifyListeners();
  }

  /// البحث عن منتج: من السيرفر أولاً، ثم من النسخة المحلية عند انقطاع الاتصال.
  Future<(Map<String, dynamic>?, bool)> lookup(String code) async {
    try {
      final p = await session.api!.get<Map<String, dynamic>>('/products/lookup', query: {
        'q': code, if (session.currency != null) 'currency': session.currency,
      });
      session.setOnline(true);
      return (p, false);
    } on ApiException catch (e) {
      if (e.status == 404) return (null, false);
      if (!e.offline) rethrow;
      session.setOnline(false);
      final cached = await OfflineDb.findByCode(code);
      return (cached, true);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

final syncProvider = ChangeNotifierProvider<SyncService>((ref) => SyncService(ref.read(sessionProvider)));
