import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/theme.dart';

void showMsg(BuildContext context, String text, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(text, style: const TextStyle(fontFamily: 'Cairo')),
      backgroundColor: error ? Brand.danger : null,
      behavior: SnackBarBehavior.floating,
    ));
}

Future<bool> confirmDialog(BuildContext context, String text, {String yes = 'نعم', bool danger = false}) async {
  final res = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      content: Text(text),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
        FilledButton(
          style: danger ? FilledButton.styleFrom(backgroundColor: Brand.danger) : null,
          onPressed: () => Navigator.pop(c, true),
          child: Text(yes),
        ),
      ],
    ),
  );
  return res ?? false;
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.text, this.action});

  final IconData icon;
  final String text;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 64, color: Theme.of(context).colorScheme.outlineVariant),
            const SizedBox(height: 12),
            Text(text, textAlign: TextAlign.center, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
            if (action != null) ...[const SizedBox(height: 16), action!],
          ]),
        ),
      );
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => EmptyState(
        icon: error is ApiException && (error as ApiException).offline ? Icons.wifi_off_rounded : Icons.error_outline,
        text: '$error',
        action: onRetry == null ? null : OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('إعادة المحاولة')),
      );
}

/// بطاقة صلصال بارزة: تدرج ناعم، حافة مضيئة، وظل ممتد.
class ClayCard extends StatelessWidget {
  const ClayCard({super.key, required this.child, this.padding = const EdgeInsets.all(14), this.radius = 24, this.onTap, this.gradient, this.depth = 1});

  final Widget child;
  final EdgeInsets padding;
  final double radius;
  final VoidCallback? onTap;
  final Gradient? gradient;
  final double depth;

  @override
  Widget build(BuildContext context) {
    final clay = Clay.of(context);
    return DecoratedBox(
      decoration: clay.raised(radius: radius, gradient: gradient, depth: depth),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(radius),
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

/// زر تنقل بشكل كبسولة صلصال (الأقسام والصفحات في الشريط العلوي).
class ClayPill extends StatelessWidget {
  const ClayPill({super.key, required this.label, required this.icon, required this.selected, required this.onTap, this.strong = false, this.badge = 0});

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  /// strong = قسم رئيسي (يتلون بالأزرق عند التحديد)، وإلا صفحة فرعية (غائرة عند التحديد).
  final bool strong;
  final int badge;

  @override
  Widget build(BuildContext context) {
    final clay = Clay.of(context);
    final BoxDecoration deco;
    final Color fg;
    if (selected && strong) {
      deco = clay.raised(radius: 18, gradient: clay.primaryGradient, depth: 0.6);
      fg = Colors.white;
    } else if (selected) {
      deco = clay.sunken(radius: 18, color: clay.primarySoft);
      fg = clay.primary;
    } else if (strong) {
      deco = BoxDecoration(borderRadius: BorderRadius.circular(18));
      fg = clay.muted;
    } else {
      deco = clay.raised(radius: 18, depth: 0.45);
      fg = clay.text;
    }
    Widget ic = Icon(icon, size: 18, color: selected ? fg : (strong ? clay.muted : clay.icon));
    if (badge > 0) ic = Badge(label: Text('$badge'), child: ic);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      decoration: deco,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: onTap,
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: strong ? 14 : 13, vertical: 8),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              ic,
              const SizedBox(width: 6),
              Text(label, style: TextStyle(color: fg, fontWeight: selected || strong ? FontWeight.w700 : FontWeight.w500, fontSize: 13.5)),
            ]),
          ),
        ),
      ),
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, this.title, this.icon, required this.child, this.trailing, this.padding = const EdgeInsets.all(14)});

  final String? title;
  final IconData? icon;
  final Widget child;
  final Widget? trailing;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => ClayCard(
        padding: padding,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(children: [
                  if (icon != null) ...[Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary), const SizedBox(width: 8)],
                  Expanded(child: Text(title!, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15))),
                  ?trailing,
                ]),
              ),
            child,
          ]),
      );
}

class KpiTile extends StatelessWidget {
  const KpiTile({super.key, required this.label, required this.value, required this.icon, required this.color, this.sub});

  final String label;
  final String value;
  final IconData icon;
  final Color color;
  final String? sub;

  @override
  Widget build(BuildContext context) => ClayCard(
        padding: const EdgeInsets.all(12),
        radius: 22,
        child: Row(children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter,
                    colors: [color.withValues(alpha: 0.10), color.withValues(alpha: 0.22)]),
                borderRadius: BorderRadius.circular(15),
              ),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.outline)),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                ),
                if (sub != null) Text(sub!, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.outline)),
              ]),
            ),
          ]),
      );
}

class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.status});

  final String? status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      'out' => ('نافد', Brand.danger),
      'low' => ('منخفض', Brand.warning),
      _ => ('متوفر', Brand.success),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12)),
    );
  }
}

class ProductImage extends StatelessWidget {
  const ProductImage({super.key, required this.api, this.name, this.size = 56});

  final ApiClient? api;
  final String? name;
  final double size;

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Icon(Icons.inventory_2_outlined, color: Theme.of(context).colorScheme.primary, size: size * 0.45),
    );
    if (api == null || name == null || name!.isEmpty) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: CachedNetworkImage(
        imageUrl: api!.imageUrl(name!),
        httpHeaders: api!.authHeaders,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorWidget: (_, _, _) => placeholder,
        placeholder: (_, _) => placeholder,
      ),
    );
  }
}

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.pending, required this.onRetry});

  final int pending;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Material(
        color: Brand.warning,
        child: InkWell(
          onTap: onRetry,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            child: Row(children: [
              const Icon(Icons.wifi_off_rounded, color: Colors.white, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'بدون اتصال بالسيرفر — تعمل على النسخة المحلية${pending > 0 ? ' • $pending عملية بانتظار المزامنة' : ''}',
                  style: const TextStyle(color: Colors.white, fontSize: 12),
                ),
              ),
              const Text('إعادة', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
            ]),
          ),
        ),
      );
}
