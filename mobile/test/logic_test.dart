import 'package:flutter_test/flutter_test.dart';
import 'package:ft_mobile/core/format.dart';
import 'package:ft_mobile/core/storage.dart';
import 'package:ft_mobile/state/cart.dart';

void main() {
  group('ServerInfo.parse', () {
    test('QR payload from the desktop app', () {
      final s = ServerInfo.parse('{"t":"ft","id":"abc","n":"FT","h":["192.168.1.5","10.0.0.2"],"p":8765}');
      expect(s, isNotNull);
      expect(s!.hosts, ['192.168.1.5', '10.0.0.2']);
      expect(s.port, 8765);
      expect(s.baseUrl, 'http://192.168.1.5:8765/api/v1');
    });

    test('manual address with and without port', () {
      expect(ServerInfo.parse('192.168.1.9:9000')!.port, 9000);
      expect(ServerInfo.parse('192.168.1.9')!.port, 8765);
      expect(ServerInfo.parse('http://pc.local:8765')!.primaryHost, 'pc.local');
    });

    test('rejects foreign QR codes', () {
      expect(ServerInfo.parse('{"t":"other"}'), isNull);
    });

    test('withPrimary moves host first', () {
      final s = ServerInfo(hosts: ['a', 'b'], port: 1).withPrimary('b');
      expect(s.hosts, ['b', 'a']);
    });
  });

  group('Cart', () {
    test('merges same product and computes totals', () {
      final cart = Cart();
      cart.add({'id': 1, 'name': 'A', 'code': 'A1', 'sale_price': 10});
      cart.add({'id': 1, 'name': 'A', 'code': 'A1', 'sale_price': 10});
      cart.add({'id': 2, 'name': 'B', 'code': 'B1', 'sale_price': 2.5}, qty: 4);
      cart.discount = 5;
      expect(cart.lines.length, 2);
      expect(cart.subtotal, 30);
      expect(cart.total, 25);
    });

    test('payload omits paid for cash and includes customer', () {
      final cart = Cart()..add({'id': 3, 'name': 'C', 'code': 'C', 'sale_price': 1});
      cart.customer = {'id': 9};
      final cash = cart.toPayload('USD');
      expect(cash.containsKey('paid'), isFalse);
      expect(cash['customer_id'], 9);
      cart.paymentMethod = 'partial';
      cart.paid = 0.5;
      final partial = cart.toPayload('USD', priceOverride: true);
      expect(partial['paid'], 0.5);
      expect((partial['lines'] as List).first['unit_price'], 1);
    });

    test('setQty to zero removes line', () {
      final cart = Cart()..add({'id': 1, 'name': 'A', 'code': 'A', 'sale_price': 1});
      cart.setQty(cart.lines.first, 0);
      expect(cart.isEmpty, isTrue);
    });
  });

  test('formatting', () {
    expect(fmtMoney(1234.5, r'$'), r'1,234.50 $');
    expect(fmtMoney(13000, 'ل.س', 0), '13,000 ل.س');
    expect(fmtQty(3), '3');
    expect(fmtQty(2.5), '2.5');
  });
}
