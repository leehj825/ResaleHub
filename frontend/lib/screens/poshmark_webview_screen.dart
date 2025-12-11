import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart'; // [중요] 패키지 변경됨
import 'package:frontend/services/marketplace_service.dart';

class PoshmarkWebViewScreen extends StatefulWidget {
  const PoshmarkWebViewScreen({super.key});

  @override
  State<PoshmarkWebViewScreen> createState() => _PoshmarkWebViewScreenState();
}

class _PoshmarkWebViewScreenState extends State<PoshmarkWebViewScreen> {
  // [중요] InAppWebView의 쿠키 매니저 사용
  final CookieManager cookieManager = CookieManager.instance();
  InAppWebViewController? webViewController;
  bool _isProcessing = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Log in to Poshmark"),
        actions: [
          // 수동 저장 버튼 (자동 감지가 안 될 경우 대비)
          TextButton(
            onPressed: _isProcessing ? null : () => _extractAndSendCookies(manual: true),
            child: const Text(
              "Save Login",
              style: TextStyle(color: Colors.blue, fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          InAppWebView(
            initialUrlRequest: URLRequest(url: WebUri("https://poshmark.com/login")),
            initialSettings: InAppWebViewSettings(
              // 모바일 환경처럼 보이게 설정 (봇 탐지 회피)
              userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
              javaScriptEnabled: true,
              useShouldOverrideUrlLoading: true,
              mediaPlaybackRequiresUserGesture: false,
              // 쿠키 허용 설정
              thirdPartyCookiesEnabled: true,
            ),
            onWebViewCreated: (controller) {
              webViewController = controller;
            },
            onLoadStop: (controller, url) async {
              if (url == null) return;
              final urlStr = url.toString();
              print(">>> Page Loaded: $urlStr");

              // 로그인 후 페이지 감지 로직
              // 1. 로그인 페이지가 아님 (/login 미포함)
              // 2. 포쉬마크 도메인임
              // 3. 메인 피드, 옷장 등으로 이동했음
              if (!_isProcessing && 
                  !urlStr.contains("/login") && 
                  urlStr.contains("poshmark.com") &&
                  (urlStr == "https://poshmark.com/" || 
                   urlStr.contains("/feed") || 
                   urlStr.contains("/closet/"))) {
                
                print(">>> Auto-detecting login success...");
                // 페이지 로딩이 완전히 끝날 때까지 잠시 대기
                await Future.delayed(const Duration(milliseconds: 1500));
                await _extractAndSendCookies();
              }
            },
          ),
          
          // 로딩 인디케이터
          if (_isProcessing)
            Container(
              color: Colors.black54,
              child: const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Colors.white),
                    SizedBox(height: 16),
                    Text("Saving connection...", style: TextStyle(color: Colors.white)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _extractAndSendCookies({bool manual = false}) async {
    if (_isProcessing) return;
    setState(() => _isProcessing = true);

    try {
      // 1. 쿠키 가져오기 (Poshmark 도메인)
      final List<Cookie> cookies = await cookieManager.getCookies(url: WebUri("https://poshmark.com"));
      
      print(">>> Extracted ${cookies.length} cookies");

      // 쿠키가 너무 적으면(로그인 안됨) 중단
      if (cookies.isEmpty || cookies.length < 3) {
        if (manual && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('No login cookies found. Please log in first.')),
          );
        } else {
          print(">>> Not enough cookies found yet. Skipping auto-save.");
        }
        setState(() => _isProcessing = false);
        return;
      }

      // 2. 백엔드 전송용 데이터 변환
      // Cookie 객체(inappwebview)를 Map으로 변환
      final cookieList = cookies.map((c) => {
        'name': c.name,
        'value': c.value,
        'domain': c.domain,
        'path': c.path,
      }).toList();

      print(">>> Sending cookies to backend: $cookieList");

      // 3. 백엔드 전송
      final marketplaceService = MarketplaceService();
      await marketplaceService.connectPoshmarkViaCookies(cookieList);
      
      if (!mounted) return;
      
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Poshmark connected successfully!'),
          backgroundColor: Colors.green,
        ),
      );
      
      // 성공 시 true 반환하며 화면 닫기 (SettingsScreen에서 새로고침 트리거)
      Navigator.of(context).pop(true); 

    } catch (e) {
      print(">>> Connection Error: $e");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connection failed: $e')),
        );
      }
      setState(() => _isProcessing = false);
    }
  }
}