import 'package:flutter/material.dart';
import 'screens/login_screen.dart';

void main() {
  runApp(const ResaleHubApp());
}

class ResaleHubApp extends StatelessWidget {
  const ResaleHubApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ResaleHub AI',
      theme: ThemeData(
        primarySwatch: Colors.blue,
      ),
      home: const LoginScreen(),
    );
  }
}
