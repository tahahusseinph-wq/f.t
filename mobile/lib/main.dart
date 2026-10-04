import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/storage.dart';
import 'core/theme.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'screens/pairing_screen.dart';
import 'state/session.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppStorage.init();
  runApp(const ProviderScope(child: FtApp()));
}

class FtApp extends ConsumerStatefulWidget {
  const FtApp({super.key});

  @override
  ConsumerState<FtApp> createState() => _FtAppState();
}

class _FtAppState extends ConsumerState<FtApp> {
  @override
  void initState() {
    super.initState();
    ref.read(sessionProvider).restore();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final Widget home;
    if (!session.ready) {
      home = const _Splash();
    } else if (!session.paired) {
      home = const PairingScreen();
    } else if (!session.loggedIn) {
      home = const LoginScreen();
    } else {
      home = const HomeShell();
    }
    return MaterialApp(
      title: 'مجموعة فاروق الطعمة',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: session.darkMode ? ThemeMode.dark : ThemeMode.light,
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: AnimatedSwitcher(duration: const Duration(milliseconds: 250), child: KeyedSubtree(key: ValueKey(home.runtimeType), child: home)),
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Brand.black,
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Image.asset('assets/images/logo.png', width: 140),
            const SizedBox(height: 24),
            const CircularProgressIndicator(color: Brand.accent),
          ]),
        ),
      );
}
