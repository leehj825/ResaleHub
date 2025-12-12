import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart'; // [필수] import

import 'screens/login_screen.dart';
import 'utils/platform_helper.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // [macOS/Windows/Linux] 데스크톱 앱 창 크기 설정 (Galaxy S25 비율 근사치)
  // Skip window manager on web platform
  if (isDesktop) {
    await windowManager.ensureInitialized();

    WindowOptions windowOptions = const WindowOptions(
      size: Size(400, 850),        // 시작 크기 (가로 400, 세로 850)
      minimumSize: Size(400, 850), // 최소 크기 고정
      maximumSize: Size(400, 850), // 최대 크기 고정 (폰 크기 유지)
      center: true,                // 화면 정중앙 실행
      backgroundColor: Colors.transparent,
      skipTaskbar: false,
      titleBarStyle: TitleBarStyle.normal,
    );

    windowManager.waitUntilReadyToShow(windowOptions, () async {
      await windowManager.show();
      await windowManager.focus();
    });
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'ResaleHub',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        useMaterial3: true,
      ),
      home: const LoginScreen(), // 로그인 화면부터 시작
    );
  }
}