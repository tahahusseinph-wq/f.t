import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/format.dart';
import '../core/theme.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'notifications_screen.dart';
import 'package:flutter_riverpod/legacy.dart';

const _periods = {'today': 'اليوم', 'week': '7 أيام', 'month': 'الشهر', 'year': 'السنة'};

final _periodProvider = StateProvider<String>((ref) => 'today');

final dashboardProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final session = ref.watch(sessionProvider);
  final period = ref.watch(_periodProvider);
  return session.api!.get<Map<String, dynamic>>('/dashboard', query: {'period': period});
});

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(dashboardProvider);
    final period = ref.watch(_periodProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(dashboardProvider),
      child: ListView(padding: const EdgeInsets.all(16), children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final e in _periods.entries)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 8),
                child: ChoiceChip(
                  label: Text(e.value),
                  selected: period == e.key,
                  onSelected: (_) => ref.read(_periodProvider.notifier).state = e.key,
                ),
              ),
          ]),
        ),
        const SizedBox(height: 12),
        data.when(
          loading: () => const Padding(padding: EdgeInsets.all(60), child: Center(child: CircularProgressIndicator())),
          error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(dashboardProvider)),
          data: (d) => _Body(d: d),
        ),
      ]),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.d});

  final Map<String, dynamic> d;

  @override
  Widget build(BuildContext context) {
    final k = d['kpis'] as Map<String, dynamic>;
    final sym = '${d['currency_symbol']}';
    String m(String key) => fmtMoney(asNum(k[key]), sym);
    final tiles = <Widget>[
      KpiTile(label: 'صافي المبيعات', value: m('sales'), icon: Icons.payments_outlined, color: Brand.primary),
      KpiTile(label: 'الفواتير', value: '${k['invoices']}', icon: Icons.receipt_long, color: const Color(0xFF7E57C2)),
      if (k.containsKey('net_profit')) KpiTile(label: 'صافي الربح', value: m('net_profit'), icon: Icons.trending_up, color: Brand.success),
      KpiTile(label: 'متوسط الفاتورة', value: m('avg_invoice'), icon: Icons.sell_outlined, color: Brand.warning),
      if (k.containsKey('stock_cost')) KpiTile(label: 'قيمة المخزون', value: m('stock_cost'), icon: Icons.warehouse_outlined, color: const Color(0xFF00897B)),
      KpiTile(label: 'مبيعات آجلة', value: m('credit'), icon: Icons.account_balance_wallet_outlined, color: Brand.danger),
    ];
    final series = (d['series'] as List).cast<Map<String, dynamic>>();
    final top = (d['top_products'] as List).cast<Map<String, dynamic>>();
    final alerts = (d['alerts'] as List).cast<Map<String, dynamic>>();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      GridView.count(
        crossAxisCount: 2,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        mainAxisSpacing: 10,
        crossAxisSpacing: 10,
        childAspectRatio: 1.9,
        children: tiles,
      ),
      const SizedBox(height: 12),
      SectionCard(
        title: 'المبيعات',
        icon: Icons.show_chart,
        child: SizedBox(height: 200, child: _SalesChart(series: series)),
      ),
      const SizedBox(height: 12),
      SectionCard(
        title: 'التنبيهات الهامة',
        icon: Icons.warning_amber_rounded,
        trailing: TextButton(
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NotificationsScreen())),
          child: const Text('الكل'),
        ),
        child: alerts.isEmpty
            ? const Padding(padding: EdgeInsets.all(8), child: Text('لا توجد تنبيهات 👌'))
            : Column(children: [for (final a in alerts.take(8)) AlertTile(alert: a)]),
      ),
      const SizedBox(height: 12),
      SectionCard(
        title: 'الأكثر مبيعاً',
        icon: Icons.star_outline,
        child: top.isEmpty
            ? const Text('لا توجد مبيعات في هذه الفترة')
            : Column(children: [
                for (final t in top)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Expanded(child: Text('${t['name']}', maxLines: 1, overflow: TextOverflow.ellipsis)),
                        Text(fmtMoney(asNum(t['revenue']), sym), style: const TextStyle(fontWeight: FontWeight.w700)),
                      ]),
                      const SizedBox(height: 4),
                      LinearProgressIndicator(value: (asNum(t['share']) / 100).toDouble().clamp(0, 1), minHeight: 6, borderRadius: BorderRadius.circular(4)),
                    ]),
                  ),
              ]),
      ),
    ]);
  }
}

class _SalesChart extends StatelessWidget {
  const _SalesChart({required this.series});

  final List<Map<String, dynamic>> series;

  @override
  Widget build(BuildContext context) {
    if (series.isEmpty) return const Center(child: Text('لا توجد بيانات'));
    final color = Theme.of(context).colorScheme.primary;
    LineChartBarData line(String key, Color c, {bool area = false}) => LineChartBarData(
          spots: [for (var i = 0; i < series.length; i++) FlSpot(i.toDouble(), asNum(series[i][key]).toDouble())],
          isCurved: true,
          preventCurveOverShooting: true,
          color: c,
          barWidth: area ? 3 : 2,
          dotData: const FlDotData(show: false),
          dashArray: area ? null : [6, 4],
          belowBarData: BarAreaData(show: area, color: c.withValues(alpha: 0.15)),
        );
    final step = (series.length / 5).ceil().clamp(1, 1000);
    return Directionality(
      textDirection: TextDirection.ltr,
      child: LineChart(LineChartData(
        gridData: const FlGridData(drawVerticalLine: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(),
          rightTitles: const AxisTitles(),
          leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 42)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: step.toDouble(),
              getTitlesWidget: (v, meta) {
                final i = v.toInt();
                if (i < 0 || i >= series.length) return const SizedBox();
                return Text('${series[i]['label']}', style: const TextStyle(fontSize: 10));
              },
            ),
          ),
        ),
        lineBarsData: [
          line('sales', color, area: true),
          if (series.first.containsKey('profit')) line('profit', Brand.success),
        ],
      )),
    );
  }
}
