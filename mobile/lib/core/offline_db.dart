import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

/// نسخة محلية من المنتجات + طابور العمليات المؤجلة (وضع بدون اتصال).
class OfflineDb {
  static Database? _db;

  static Future<Database> get db async {
    if (_db != null) return _db!;
    final path = p.join(await getDatabasesPath(), 'ft_offline.db');
    _db = await openDatabase(path, version: 1, onCreate: (d, _) async {
      await d.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, code TEXT, barcode TEXT, name TEXT, data TEXT)');
      await d.execute('CREATE INDEX ix_code ON products(code)');
      await d.execute('CREATE INDEX ix_barcode ON products(barcode)');
      await d.execute('CREATE TABLE ops (op_id TEXT PRIMARY KEY, type TEXT, payload TEXT, title TEXT, created_at TEXT, error TEXT)');
      await d.execute('CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)');
    });
    return _db!;
  }

  static Future<void> upsertProducts(List<Map<String, dynamic>> items, {bool replaceAll = false}) async {
    final d = await db;
    await d.transaction((tx) async {
      if (replaceAll) await tx.delete('products');
      final batch = tx.batch();
      for (final it in items) {
        batch.insert('products', {
          'id': it['id'],
          'code': '${it['code'] ?? ''}'.toUpperCase(),
          'barcode': '${it['barcode'] ?? ''}',
          'name': '${it['name'] ?? ''}',
          'data': jsonEncode(it),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      await batch.commit(noResult: true);
    });
  }

  static Future<void> removeProducts(List<int> ids) async {
    if (ids.isEmpty) return;
    final d = await db;
    await d.delete('products', where: 'id IN (${List.filled(ids.length, '?').join(',')})', whereArgs: ids);
  }

  static Future<Map<String, dynamic>?> findByCode(String code) async {
    final d = await db;
    final rows = await d.query('products', where: 'code = ? OR barcode = ?', whereArgs: [code.trim().toUpperCase(), code.trim()], limit: 1);
    return rows.isEmpty ? null : jsonDecode(rows.first['data'] as String) as Map<String, dynamic>;
  }

  static Future<List<Map<String, dynamic>>> search(String q, {int limit = 50}) async {
    final d = await db;
    final like = '%${q.trim()}%';
    final rows = await d.query('products', where: 'name LIKE ? OR code LIKE ? OR barcode LIKE ?', whereArgs: [like, like.toUpperCase(), like], limit: limit, orderBy: 'name');
    return rows.map((r) => jsonDecode(r['data'] as String) as Map<String, dynamic>).toList();
  }

  static Future<int> productCount() async {
    final d = await db;
    return Sqflite.firstIntValue(await d.rawQuery('SELECT COUNT(*) FROM products')) ?? 0;
  }

  static Future<String?> meta(String k) async {
    final d = await db;
    final rows = await d.query('meta', where: 'k = ?', whereArgs: [k]);
    return rows.isEmpty ? null : rows.first['v'] as String?;
  }

  static Future<void> setMeta(String k, String? v) async {
    final d = await db;
    if (v == null) {
      await d.delete('meta', where: 'k = ?', whereArgs: [k]);
    } else {
      await d.insert('meta', {'k': k, 'v': v}, conflictAlgorithm: ConflictAlgorithm.replace);
    }
  }

  // ---------------- طابور العمليات ----------------
  static Future<void> enqueue(String opId, String type, Map<String, dynamic> payload, String title) async {
    final d = await db;
    await d.insert('ops', {
      'op_id': opId, 'type': type, 'payload': jsonEncode(payload), 'title': title,
      'created_at': DateTime.now().toIso8601String(), 'error': null,
    });
  }

  static Future<List<Map<String, dynamic>>> pendingOps() async {
    final d = await db;
    final rows = await d.query('ops', orderBy: 'created_at');
    return rows.map((r) => {...r, 'payload': jsonDecode(r['payload'] as String)}).toList();
  }

  static Future<void> removeOp(String opId) async {
    final d = await db;
    await d.delete('ops', where: 'op_id = ?', whereArgs: [opId]);
  }

  static Future<void> markOpError(String opId, String error) async {
    final d = await db;
    await d.update('ops', {'error': error}, where: 'op_id = ?', whereArgs: [opId]);
  }

  static Future<void> clearAll() async {
    final d = await db;
    await d.delete('products');
    await d.delete('meta');
  }
}
