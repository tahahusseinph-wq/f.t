import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';

class CartLine {
  CartLine({required this.productId, required this.name, required this.code, required this.price, this.quantity = 1, this.unit = ''});

  final int productId;
  final String name;
  final String code;
  final String unit;
  double price; // بعملة العرض
  double quantity;
  double discount = 0;

  double get total => price * quantity - discount;
}

/// طرق الدفع (نفس نسخة الكمبيوتر). النقدي وشام كاش يُسدَّدان كاملاً لحظة البيع.
const paymentMethods = {'cash': 'نقدي', 'shamcash': 'شام كاش', 'credit': 'آجل', 'partial': 'جزئي'};
const paidInFull = {'cash', 'shamcash'};

class Cart extends ChangeNotifier {
  final List<CartLine> lines = [];
  Map<String, dynamic>? customer;
  double discount = 0;
  String paymentMethod = 'cash';
  double paid = 0;
  String notes = '';
  String shamRef = ''; // رقم عملية شام كاش

  bool get isEmpty => lines.isEmpty;
  double get subtotal => lines.fold(0, (s, l) => s + l.total);
  double get total => subtotal - discount;

  void add(Map<String, dynamic> product, {double qty = 1}) {
    final id = product['id'] as int;
    final existing = lines.where((l) => l.productId == id).toList();
    if (existing.isNotEmpty) {
      existing.first.quantity += qty;
    } else {
      lines.add(CartLine(
        productId: id,
        name: '${product['name']}',
        code: '${product['code']}',
        unit: '${product['unit'] ?? ''}',
        price: (product['sale_price'] as num?)?.toDouble() ?? 0,
        quantity: qty,
      ));
    }
    notifyListeners();
  }

  void setQty(CartLine l, double q) {
    if (q <= 0) {
      lines.remove(l);
    } else {
      l.quantity = q;
    }
    notifyListeners();
  }

  void remove(CartLine l) {
    lines.remove(l);
    notifyListeners();
  }

  void update() => notifyListeners();

  /// البيع الآجل أو الجزئي يحتاج زبوناً مسجلاً.
  bool get needsCustomer => !paidInFull.contains(paymentMethod);

  /// عند تغيير العملة أو سعر الصرف: كل المبالغ (بعملة العرض) تُضرب بنسبة التحويل.
  void rescale(double factor) {
    if (factor <= 0 || factor == 1) return;
    for (final l in lines) {
      l.price *= factor;
      l.discount *= factor;
    }
    discount *= factor;
    paid *= factor;
    notifyListeners();
  }

  String get fullNotes {
    final ref = shamRef.trim();
    if (paymentMethod != 'shamcash' || ref.isEmpty) return notes;
    return '$notes\nرقم عملية شام كاش: $ref'.trim();
  }

  void clear() {
    lines.clear();
    customer = null;
    discount = 0;
    paid = 0;
    paymentMethod = 'cash';
    notes = '';
    shamRef = '';
    notifyListeners();
  }

  /// الأسعار تُرسل بعملة العرض ويحولها السيرفر للعملة الأساسية.
  Map<String, dynamic> toPayload(String? currency, {bool priceOverride = false}) => {
        'lines': [
          for (final l in lines)
            {'product_id': l.productId, 'quantity': l.quantity, if (priceOverride) 'unit_price': l.price, 'discount': l.discount},
        ],
        if (customer != null) 'customer_id': customer!['id'],
        'discount': discount,
        'payment_method': paymentMethod,
        if (!paidInFull.contains(paymentMethod)) 'paid': paid,
        'currency_code': ?currency,
        'notes': fullNotes,
      };
}

final cartProvider = ChangeNotifierProvider<Cart>((ref) => Cart());
