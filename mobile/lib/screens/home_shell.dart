import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/alerts.dart';
import '../state/cart.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'count_screen.dart';
import 'dashboard_screen.dart';
import 'notifications_screen.dart';
import 'pos_screen.dart';
import 'search_screen.dart';
import 'settings_screen.dart';

class _Tab {
  const _Tab(this.label, this.icon, this.title, this.body);

  final String label;
  final IconData icon;
  final String title;
  final Widget body;
}

/// الهيكل الرئيسي: تبويبات حسب صلاحيات المستخدم.
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int index = 0;
  int unread = 0;
  late final AlertsWatcher alerts;

  @override
  void initState() {
    super.initState();
    final session = ref.read(sessionProvider);
    alerts = AlertsWatcher(session)..onUnread = (n) => mounted ? setState(() => unread = n) : null;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(syncProvider).start();
      alerts.start();
    });
  }

  @override
  void dispose() {
    alerts.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final sync = ref.watch(syncProvider);
    final cartCount = ref.watch(cartProvider).lines.length;
    final tabs = <_Tab>[
      if (session.can('dashboard.view')) const _Tab('الرئيسية', Icons.dashboard_outlined, 'لوحة التحكم', DashboardScreen()),
      const _Tab('بحث', Icons.search, 'البحث عن منتج', SearchScreen()),
      if (session.can('sales.create')) const _Tab('بيع', Icons.point_of_sale, 'نقطة البيع', PosScreen()),
      if (session.can('inventory.adjust')) const _Tab('جرد', Icons.fact_check_outlined, 'الجرد', CountScreen()),
      const _Tab('المزيد', Icons.menu, 'المزيد', MoreScreen()),
    ];
    if (index >= tabs.length) index = 0;
    final tab = tabs[index];
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          Image.asset('assets/images/logo.png', width: 32),
          const SizedBox(width: 10),
          Text(tab.title),
        ]),
        actions: [
          if (session.can('dashboard.view') || session.can('inventory.view'))
            IconButton(
              icon: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.notifications_outlined)),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NotificationsScreen())).then((_) => alerts.poll()),
            ),
        ],
      ),
      body: Column(children: [
        if (!session.online) OfflineBanner(pending: sync.pending, onRetry: sync.syncAll),
        Expanded(child: tab.body),
      ]),
      bottomNavigationBar: tabs.length < 2
          ? null
          : NavigationBar(
              selectedIndex: index,
              onDestinationSelected: (i) => setState(() => index = i),
              destinations: [
                for (final t in tabs)
                  NavigationDestination(
                    icon: t.label == 'بيع' && cartCount > 0 ? Badge(label: Text('$cartCount'), child: Icon(t.icon)) : Icon(t.icon),
                    label: t.label,
                  ),
              ],
            ),
    );
  }
}
