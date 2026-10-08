import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// استيراد المنتجات من ملف Excel موجود على الموبايل: اختيار الملف، ربط الأعمدة بحقول المنتج، ثم الحفظ.
class ImportScreen extends ConsumerStatefulWidget {
  const ImportScreen({super.key});

  @override
  ConsumerState<ImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends ConsumerState<ImportScreen> {
  bool _busy = false;
  String? _fileName;
  String? _fileId;
  List<String> _headers = [];
  List<List<String>> _rows = [];
  int _total = 0;
  Map<int, String> _mapping = {};
  List<Map<String, dynamic>> _targets = [];
  bool _updateExisting = true;
  Map<String, dynamic>? _result;

  Future<void> _pick() async {
    final picked = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['xlsx', 'xlsm']);
    final file = picked?.files.single;
    if (file == null || file.path == null) return;
    setState(() {
      _busy = true;
      _result = null;
    });
    try {
      final bytes = await File(file.path!).readAsBytes();
      final res = await ref.read(sessionProvider).api!.post<Map<String, dynamic>>('/products/import/preview', {
        'file_base64': base64Encode(bytes),
        'filename': file.name,
      });
      if (!mounted) return;
      setState(() {
        _fileName = file.name;
        _fileId = '${res['file_id']}';
        _headers = (res['headers'] as List).map((e) => '$e').toList();
        _rows = (res['rows'] as List).map((r) => (r as List).map((e) => '$e').toList()).toList();
        _total = (res['total'] as num?)?.toInt() ?? 0;
        _mapping = {for (final e in (res['mapping'] as Map).entries) int.parse('${e.key}'): '${e.value}'};
        _targets = (res['targets'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
      });
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _import() async {
    if (_fileId == null) return;
    if (!_mapping.values.any((v) => v == 'name' || v == 'code')) {
      showMsg(context, 'اربط عمود اسم المنتج أو الكود على الأقل', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final res = await ref.read(sessionProvider).api!.post<Map<String, dynamic>>('/products/import', {
        'file_id': _fileId,
        'mapping': {for (final e in _mapping.entries) '${e.key}': e.value},
        'update_existing': _updateExisting,
      });
      if (!mounted) return;
      setState(() {
        _result = res;
        _fileId = null;
      });
      showMsg(context, 'تم الاستيراد: ${res['created']} جديد، ${res['updated']} محدّث');
    } on ApiException catch (e) {
      if (mounted) showMsg(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _sample(int col) {
    for (final r in _rows) {
      if (col < r.length && r[col].isNotEmpty && r[col] != 'null') return r[col];
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final result = _result;
    return Scaffold(
      appBar: AppBar(title: const Text('استيراد منتجات من Excel')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 30),
        children: [
          SectionCard(
            title: 'ملف Excel',
            icon: Icons.table_view_rounded,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  _fileName == null
                      ? 'اختر ملف Excel (xlsx) من الموبايل. الصف الأول يحوي عناوين الأعمدة مثل: الاسم، الكود، سعر التكلفة، الكمية...'
                      : '$_fileName — $_total صف',
                  style: TextStyle(color: scheme.outline),
                ),
                const SizedBox(height: 10),
                FilledButton.tonalIcon(
                  onPressed: _busy ? null : _pick,
                  icon: const Icon(Icons.folder_open_rounded),
                  label: Text(_fileName == null ? 'اختيار ملف' : 'اختيار ملف آخر'),
                ),
              ],
            ),
          ),
          if (_fileId != null) ...[
            const SizedBox(height: 12),
            SectionCard(
              title: 'ربط الأعمدة بحقول المنتج',
              icon: Icons.link_rounded,
              child: Column(
                children: [
                  for (var i = 0; i < _headers.length; i++)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: DropdownButtonFormField<String>(
                        key: ValueKey('map-$i-${_mapping[i]}'),
                        initialValue: _mapping[i],
                        isExpanded: true,
                        decoration: InputDecoration(
                          labelText: _headers[i],
                          helperText: _sample(i).isEmpty ? null : 'مثال: ${_sample(i)}',
                        ),
                        items: [
                          const DropdownMenuItem<String>(value: null, child: Text('— تجاهل هذا العمود —')),
                          for (final t in _targets)
                            DropdownMenuItem<String>(value: '${t['key']}', child: Text('${t['label']}')),
                        ],
                        onChanged: (v) => setState(() {
                          if (v == null) {
                            _mapping.remove(i);
                          } else {
                            _mapping.removeWhere((k, val) => val == v && k != i);
                            _mapping[i] = v;
                          }
                        }),
                      ),
                    ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _updateExisting,
                    onChanged: (v) => setState(() => _updateExisting = v),
                    title: const Text('تحديث المنتجات الموجودة بنفس الكود'),
                    subtitle: const Text('عند الإيقاف تُتجاهل المنتجات الموجودة مسبقاً'),
                  ),
                  const SizedBox(height: 8),
                  FilledButton.icon(
                    onPressed: _busy ? null : _import,
                    icon: _busy
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.upload_rounded),
                    label: Text('استيراد $_total منتج'),
                  ),
                ],
              ),
            ),
          ],
          if (result != null) ...[
            const SizedBox(height: 12),
            SectionCard(
              title: 'نتيجة الاستيراد',
              icon: Icons.check_circle_outline_rounded,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('منتجات جديدة: ${result['created']}'),
                  Text('منتجات محدّثة: ${result['updated']}'),
                  if ((result['skipped'] ?? 0) != 0) Text('متجاهلة: ${result['skipped']}'),
                  if ((result['error_count'] ?? 0) != 0) ...[
                    const SizedBox(height: 6),
                    Text('أخطاء: ${result['error_count']}', style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w700)),
                    for (final e in (result['errors'] as List? ?? const []))
                      Text('صف ${(e as Map)['row']}: ${e['error']}', style: const TextStyle(fontSize: 12)),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
