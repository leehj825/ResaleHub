// frontend/lib/screens/poshmark_webview_screen.dart
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_cookie_manager/webview_cookie_manager.dart';
import 'package:frontend/services/marketplace_service.dart'; // You'll update this

class PoshmarkWebViewScreen extends StatefulWidget {
  const PoshmarkWebViewScreen({super.key});

  @override
  State<PoshmarkWebViewScreen> createState() => _PoshmarkWebViewScreenState();
}

class _PoshmarkWebViewScreenState extends State<PoshmarkWebViewScreen> {
  late final WebViewController _controller;
  final cookieManager = WebviewCookieManager();
  bool _isLoggedIn = false;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1") // Look like a real iPhone
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (String url) async {
            // Check if we are logged in (redirected to feed or closet)
            if (!_isLoggedIn && 
                (url == "https://poshmark.com/" || 
                 url == "https://poshmark.com/feed" ||
                 url.contains("/closet/"))) {
              
              _isLoggedIn = true;
              await _extractAndSendCookies();
            }
          },
        ),
      )
      ..loadRequest(Uri.parse('https://poshmark.com/login'));
  }

  Future<void> _extractAndSendCookies() async {
    // 1. Get cookies from the WebView
    final cookies = await cookieManager.getCookies('https://poshmark.com');
    
    // 2. Convert to list of maps for backend
    final cookieList = cookies.map((c) => {
      'name': c.name,
      'value': c.value,
      'domain': c.domain,
      'path': c.path,
    }).toList();

    try {
      // 3. Send to your Backend
      final marketplaceService = MarketplaceService(); // Ensure this service exists
      await marketplaceService.connectPoshmarkViaCookies(cookieList);
      
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Poshmark connected successfully!')),
      );
      Navigator.of(context).pop(true); // Return success
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to save connection: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Log in to Poshmark")),
      body: WebViewWidget(controller: _controller),
    );
  }
}