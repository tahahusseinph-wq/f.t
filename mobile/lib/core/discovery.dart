import 'package:multicast_dns/multicast_dns.dart';

import 'storage.dart';

/// البحث التلقائي عن سيرفر الأدمن على الشبكة المحلية (mDNS).
Future<List<ServerInfo>> discoverServers({Duration timeout = const Duration(seconds: 4)}) async {
  const type = '_fttrading._tcp.local';
  final client = MDnsClient();
  final found = <String, ServerInfo>{};
  try {
    await client.start();
    await for (final ptr in client.lookup<PtrResourceRecord>(ResourceRecordQuery.serverPointer(type), timeout: timeout)) {
      await for (final srv in client.lookup<SrvResourceRecord>(ResourceRecordQuery.service(ptr.domainName), timeout: timeout)) {
        final hosts = <String>[];
        await for (final ip in client.lookup<IPAddressResourceRecord>(ResourceRecordQuery.addressIPv4(srv.target), timeout: timeout)) {
          hosts.add(ip.address.address);
        }
        if (hosts.isNotEmpty) {
          final id = ptr.domainName.split('.').first.replaceFirst('FT-', '');
          found[id] = ServerInfo(hosts: hosts, port: srv.port, id: id, name: '');
        }
      }
    }
  } catch (_) {
    // بعض الشبكات تمنع mDNS؛ يبقى المسح بـ QR أو الإدخال اليدوي متاحاً
  } finally {
    client.stop();
  }
  return found.values.toList();
}
