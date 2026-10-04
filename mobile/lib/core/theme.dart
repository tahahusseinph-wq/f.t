import 'package:flutter/material.dart';

/// ألوان الهوية مأخوذة من شعار المجموعة.
class Brand {
  static const primary = Color(0xFF1565C0);
  static const accent = Color(0xFF6BB8E6);
  static const black = Color(0xFF0B0F14);
  static const success = Color(0xFF2E7D32);
  static const warning = Color(0xFFF57C00);
  static const danger = Color(0xFFE53935);
}

ThemeData buildTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: Brand.primary,
    brightness: brightness,
    primary: dark ? const Color(0xFF4A9BE8) : Brand.primary,
    secondary: Brand.accent,
    error: Brand.danger,
    surface: dark ? const Color(0xFF161D25) : Colors.white,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: 'Cairo', brightness: brightness);
  return base.copyWith(
    scaffoldBackgroundColor: dark ? const Color(0xFF0E1319) : const Color(0xFFF3F6FA),
    appBarTheme: AppBarTheme(
      backgroundColor: dark ? const Color(0xFF080B0F) : Brand.black,
      foregroundColor: Colors.white,
      centerTitle: false,
      elevation: 0,
      titleTextStyle: const TextStyle(fontFamily: 'Cairo', fontSize: 18, fontWeight: FontWeight.w700, color: Colors.white),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: scheme.surface,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: dark ? const Color(0xFF293443) : const Color(0xFFDCE4EE)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF111820) : Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: dark ? const Color(0xFF293443) : const Color(0xFFDCE4EE)),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontFamily: 'Cairo', fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 46),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      indicatorColor: scheme.primary.withValues(alpha: 0.15),
      labelTextStyle: WidgetStateProperty.all(const TextStyle(fontFamily: 'Cairo', fontSize: 12)),
    ),
  );
}
