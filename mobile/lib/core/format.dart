import 'package:intl/intl.dart';

final _num = NumberFormat('#,##0.##', 'en');
final _money = NumberFormat('#,##0.00', 'en');
final _int = NumberFormat('#,##0', 'en');

String fmtQty(num? v) => _num.format(v ?? 0);

String fmtMoney(num? v, [String symbol = '', int decimals = 2]) {
  final text = decimals == 0 ? _int.format(v ?? 0) : _money.format(v ?? 0);
  return symbol.isEmpty ? text : '$text $symbol';
}

String fmtDate(String? iso, {bool time = true}) {
  if (iso == null) return '';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  return DateFormat(time ? 'yyyy-MM-dd HH:mm' : 'yyyy-MM-dd').format(d);
}

num asNum(dynamic v) => v is num ? v : num.tryParse('$v') ?? 0;
