import 'package:flutter/material.dart';

/// ألوان الهوية — نفس ألوان نسخة الكمبيوتر (نمط Claymorphism).
class Brand {
  static const primary = Color(0xFF5B7CFA);
  static const accent = Color(0xFF8FB4FF);
  static const black = Color(0xFF1E2742);
  static const success = Color(0xFF2FA673);
  static const warning = Color(0xFFE8892F);
  static const danger = Color(0xFFEF5B70);
}

/// لوحة ألوان الصلصال للوضعين الفاتح والداكن (مطابقة لـ theme.py في نسخة الكمبيوتر).
class Clay {
  const Clay({
    required this.bg, required this.surface, required this.surfaceHi, required this.surface2, required this.border,
    required this.hi, required this.lo, required this.text, required this.muted, required this.icon,
    required this.primary, required this.primaryHi, required this.primaryLo, required this.primarySoft,
    required this.input, required this.shadow, required this.selection, required this.dark,
  });

  final Color bg, surface, surfaceHi, surface2, border, hi, lo, text, muted, icon;
  final Color primary, primaryHi, primaryLo, primarySoft, input, shadow, selection;
  final bool dark;

  static const light = Clay(
    bg: Color(0xFFE8ECF6), surface: Color(0xFFF6F7FC), surfaceHi: Color(0xFFFFFFFF), surface2: Color(0xFFE6EAF5),
    border: Color(0xFFD5DCEC), hi: Color(0xFFFFFFFF), lo: Color(0xFFC9D2E7), text: Color(0xFF1E2742),
    muted: Color(0xFF6A7491), icon: Color(0xFF56607E), primary: Color(0xFF5B7CFA), primaryHi: Color(0xFF7E99FF),
    primaryLo: Color(0xFF4462DA), primarySoft: Color(0xFFE2E8FF), input: Color(0xFFEDF0F8),
    shadow: Color(0xFF8E9CC6), selection: Color(0xFFDCE3FF), dark: false,
  );

  static const darkPalette = Clay(
    bg: Color(0xFF191E2E), surface: Color(0xFF242A3F), surfaceHi: Color(0xFF2C3350), surface2: Color(0xFF20253A),
    border: Color(0xFF323A57), hi: Color(0xFF3A4366), lo: Color(0xFF131725), text: Color(0xFFE7EBF7),
    muted: Color(0xFF99A2C0), icon: Color(0xFFB9C1DC), primary: Color(0xFF7B94FF), primaryHi: Color(0xFF97ACFF),
    primaryLo: Color(0xFF5C76E6), primarySoft: Color(0xFF2C3562), input: Color(0xFF1C2135),
    shadow: Color(0xFF03050A), selection: Color(0xFF323D6E), dark: true,
  );

  static Clay of(BuildContext context) => Theme.of(context).brightness == Brightness.dark ? darkPalette : light;

  /// ظل الصلصال: ظل ناعم ممتد للأسفل + إضاءة خفيفة أعلى العنصر.
  List<BoxShadow> shadows({double depth = 1}) => [
        BoxShadow(color: shadow.withValues(alpha: dark ? 0.55 : 0.28), offset: Offset(0, 9 * depth), blurRadius: 24 * depth),
        BoxShadow(color: hi.withValues(alpha: dark ? 0.35 : 0.9), offset: Offset(0, -3 * depth), blurRadius: 8 * depth),
      ];

  /// خلفية عنصر بارز (بطاقة/زر).
  BoxDecoration raised({double radius = 24, Gradient? gradient, double depth = 1}) => BoxDecoration(
        gradient: gradient ?? LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [surfaceHi, surface]),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: hi.withValues(alpha: dark ? 0.6 : 1), width: 1.5),
        boxShadow: shadows(depth: depth),
      );

  /// خلفية عنصر غائر (حقل، عنصر محدد).
  BoxDecoration sunken({double radius = 18, Color? color}) => BoxDecoration(
        color: color ?? input,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: lo.withValues(alpha: dark ? 0.9 : 0.7), width: 1.5),
      );

  LinearGradient get primaryGradient =>
      LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [primaryHi, primary]);
}

ThemeData buildTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final c = dark ? Clay.darkPalette : Clay.light;
  final scheme = ColorScheme.fromSeed(
    seedColor: c.primary,
    brightness: brightness,
    primary: c.primary,
    secondary: Brand.accent,
    error: Brand.danger,
    surface: c.surface,
    onSurface: c.text,
    outline: c.muted,
    outlineVariant: c.lo,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: 'Cairo', brightness: brightness);
  final rounded = RoundedRectangleBorder(borderRadius: BorderRadius.circular(18));
  final edge = BorderSide(color: c.hi.withValues(alpha: dark ? 0.6 : 1), width: 1.5);
  final softShadow = c.shadow.withValues(alpha: dark ? 0.8 : 0.35);
  return base.copyWith(
    scaffoldBackgroundColor: c.bg,
    canvasColor: c.bg,
    dividerColor: c.border,
    appBarTheme: AppBarTheme(
      backgroundColor: c.bg,
      foregroundColor: c.text,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(fontFamily: 'Cairo', fontSize: 18, fontWeight: FontWeight.w700, color: c.text),
    ),
    cardTheme: CardThemeData(
      elevation: 6,
      color: c.surfaceHi,
      shadowColor: softShadow,
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22), side: edge),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.input,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(18), borderSide: BorderSide(color: c.lo)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: c.lo.withValues(alpha: dark ? 0.9 : 0.7), width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(18), borderSide: BorderSide(color: c.primary, width: 2)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 50),
        elevation: 6,
        shadowColor: c.primary.withValues(alpha: 0.55),
        shape: rounded,
        textStyle: const TextStyle(fontFamily: 'Cairo', fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 48),
        backgroundColor: c.surfaceHi,
        foregroundColor: c.text,
        elevation: 3,
        shadowColor: softShadow,
        side: edge,
        shape: rounded,
      ),
    ),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(shape: rounded)),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: c.icon)),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: c.primary,
      foregroundColor: Colors.white,
      elevation: 8,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        backgroundColor: c.input,
        selectedBackgroundColor: c.primary,
        selectedForegroundColor: Colors.white,
        foregroundColor: c.text,
        side: BorderSide(color: c.lo.withValues(alpha: 0.7), width: 1.5),
        shape: rounded,
        textStyle: const TextStyle(fontFamily: 'Cairo', fontWeight: FontWeight.w700),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: c.surfaceHi,
      selectedColor: c.primary,
      secondarySelectedColor: c.primary,
      checkmarkColor: Colors.white,
      labelStyle: TextStyle(fontFamily: 'Cairo', color: c.text),
      secondaryLabelStyle: const TextStyle(fontFamily: 'Cairo', color: Colors.white, fontWeight: FontWeight.w700),
      side: edge,
      shape: rounded,
      elevation: 3,
      shadowColor: softShadow,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.surfaceHi,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: c.surfaceHi,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    snackBarTheme: SnackBarThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.primary, linearTrackColor: c.input),
  );
}
