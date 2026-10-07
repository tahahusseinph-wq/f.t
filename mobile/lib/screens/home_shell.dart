import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';

import '../core/alerts.dart';
import '../core/theme.dart';
import '../state/cart.dart';
import '../state/session.dart';
import '../state/sync.dart';
import '../widgets/common.dart';
import 'company_screen.dart';
import 'count_screen.dart';
import 'customers_screen.dart';
import 'dashboard_screen.dart';
import 'invoices_screen.dart';
import 'notifications_screen.dart';
import 'pos_screen.dart';
import 'search_screen.dart';
import 'settings_screen.dart';
import 'users_screen.dart';

/// صفحة من صفحات البرنامج ضمن قسم (نفس تقسيم نسخة الكمبيوتر).
class ShellPage {
  const ShellPage(this.key, this.title, this.icon, this.section, this.builder);

  final String key;
  final String title;
  final IconData icon;
  final String section;
  final Widget Function() builder;
}

const sectionIcons = {
  'الرئيسية': Icons.home_rounded,
  'المبيعات': Icons.shopping_cart_rounded,
  'المخزون': Icons.inventory_2_rounded,
  'النظام': Icons.settings_rounded,
};

/// الصفحة المفتوحة حالياً — أي شاشة تستطيع الانتقال بتغييرها (مثل «بيع لهذا الزبون»).
final shellPageProvider = StateProvider<String?>((ref) => null);

List<ShellPage> visiblePages(Session s) => [
  if (s.can('dashboard.view')) ShellPage('dashboard', 'لوحة التحكم', Icons.dashboard_rounded, 'الرئيسية', () => const DashboardScreen()),
  if (s.can('dashboard.view') || s.can('inventory.view'))
    ShellPage('notifications', 'الإشعارات', Icons.notifications_rounded, 'الرئيسية', () => const NotificationsScreen(embedded: true)),
  if (s.can('sales.create')) ShellPage('pos', 'نقطة البيع', Icons.point_of_sale_rounded, 'المبيعات', () => const PosScreen()),
  if (s.can('sales.create'))
    ShellPage('invoices', 'الفواتير', Icons.receipt_long_rounded, 'المبيعات', () => const InvoicesScreen(embedded: true)),
  if (s.can('customers.manage')) ShellPage('customers', 'الزبائن', Icons.people_alt_rounded, 'المبيعات', () => const CustomersScreen()),
  ShellPage('search', 'المنتجات', Icons.search_rounded, 'المخزون', () => const SearchScreen()),
  if (s.can('inventory.adjust')) ShellPage('count', 'الجرد', Icons.fact_check_rounded, 'المخزون', () => const CountScreen()),
  if (s.can('users.manage'))
    ShellPage('users', 'المستخدمون', Icons.manage_accounts_rounded, 'النظام', () => const UsersScreen(embedded: true)),
  if (s.can('settings.manage')) ShellPage('company', 'بيانات الفاتورة', Icons.storefront_rounded, 'النظام', () => const CompanyScreen()),
  ShellPage('settings', 'الإعدادات', Icons.tune_rounded, 'النظام', () => const MoreScreen()),
];

/// الهيكل الرئيسي: شريط علوي بالأقسام، ثم صفحات القسم الحالي — مثل نسخة الكمبيوتر.
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int unread = 0;
  final Map<String, String> _lastInSection = {};
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

  void _go(String key) {
    ref.read(shellPageProvider.notifier).state = key;
    if (key == 'notifications') alerts.poll();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final sync = ref.watch(syncProvider);
    final cartCount = ref.watch(cartProvider).lines.length;
    final clay = Clay.of(context);
    final pages = visiblePages(session);
    final requested = ref.watch(shellPageProvider);
    final page = pages.firstWhere(
      (p) => p.key == requested,
      orElse: () => pages.firstWhere((p) => p.key == 'dashboard' || p.key == 'pos', orElse: () => pages.first),
    );
    _lastInSection[page.section] = page.key;
    final sections = <String>{for (final p in pages) p.section}.toList();
    final siblings = pages.where((p) => p.section == page.section).toList();

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            // ===== الشريط العلوي (بطاقة صلصال) =====
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: ClayCard(
                radius: 26,
                padding: const EdgeInsets.fromLTRB(8, 6, 12, 6),
                child: Row(
                  children: [
                    Image.asset('assets/images/logo.png', width: 38),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            'مجموعة الطعمة التجارية',
                            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15, color: clay.text, height: 1.2),
                          ),
                          Text(page.title, style: TextStyle(fontSize: 12, color: clay.primary, height: 1.2)),
                        ],
                      ),
                    ),
                    if (session.can('dashboard.view') || session.can('inventory.view'))
                      IconButton(
                        tooltip: 'الإشعارات',
                        icon: Badge(
                          isLabelVisible: unread > 0,
                          label: Text('$unread'),
                          child: const Icon(Icons.notifications_none_rounded),
                        ),
                        onPressed: () => _go('notifications'),
                      ),
                    IconButton(
                      tooltip: 'الوضع الليلي',
                      icon: Icon(session.darkMode ? Icons.light_mode_rounded : Icons.dark_mode_rounded),
                      onPressed: session.toggleDark,
                    ),
                    _UserChip(session: session),
                  ],
                ),
              ),
            ),
            // ===== الأقسام =====
            SizedBox(
              height: 58,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
                children: [
                  for (final sec in sections)
                    Padding(
                      padding: const EdgeInsetsDirectional.only(end: 6),
                      child: ClayPill(
                        label: sec,
                        icon: sectionIcons[sec] ?? Icons.circle,
                        strong: true,
                        selected: sec == page.section,
                        badge: sec == 'المبيعات' && sec != page.section ? cartCount : 0,
                        onTap: () => _go(_lastInSection[sec] ?? pages.firstWhere((p) => p.section == sec).key),
                      ),
                    ),
                ],
              ),
            ),
            // ===== صفحات القسم الحالي =====
            if (siblings.length > 1)
              SizedBox(
                height: 54,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
                  children: [
                    for (final p in siblings)
                      Padding(
                        padding: const EdgeInsetsDirectional.only(end: 8),
                        child: ClayPill(
                          label: p.title,
                          icon: p.icon,
                          selected: p.key == page.key,
                          badge: p.key == 'pos' ? cartCount : 0,
                          onTap: () => _go(p.key),
                        ),
                      ),
                  ],
                ),
              ),
            if (!session.online) OfflineBanner(pending: sync.pending, onRetry: sync.syncAll),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 200),
                child: KeyedSubtree(key: ValueKey(page.key), child: page.builder()),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// صورة المستخدم: قائمة بالاسم والدور وتسجيل الخروج.
class _UserChip extends StatelessWidget {
  const _UserChip({required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    final clay = Clay.of(context);
    return PopupMenuButton<String>(
      tooltip: session.displayName,
      onSelected: (v) async {
        if (v == 'logout' && await confirmDialog(context, 'تسجيل الخروج؟')) await session.logout();
      },
      itemBuilder: (_) => [
        PopupMenuItem(
          enabled: false,
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(
              session.displayName,
              style: TextStyle(fontWeight: FontWeight.w700, color: clay.text),
            ),
            subtitle: Text(session.roleLabel),
          ),
        ),
        const PopupMenuDivider(),
        const PopupMenuItem(
          value: 'logout',
          child: Row(
            children: [
              Icon(Icons.logout_rounded, color: Brand.danger),
              SizedBox(width: 10),
              Text('تسجيل الخروج'),
            ],
          ),
        ),
      ],
      child: Container(
        width: 36,
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          gradient: clay.primaryGradient,
          shape: BoxShape.circle,
          boxShadow: [BoxShadow(color: clay.primary.withValues(alpha: 0.45), blurRadius: 10, offset: const Offset(0, 4))],
        ),
        child: Text(
          session.displayName.characters.firstOrNull ?? '؟',
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
        ),
      ),
    );
  }
}
