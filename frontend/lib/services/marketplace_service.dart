// lib/services/marketplace_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;

import 'package:frontend/models/ebay_item.dart';
import 'package:frontend/models/poshmark_item.dart';
import 'auth_service.dart';

class MarketplaceService {
  final _auth = AuthService();

  MarketplaceService._internal();
  static final MarketplaceService _instance = MarketplaceService._internal();
  factory MarketplaceService() => _instance;

  /// eBay 연결 여부 확인
  Future<bool> isEbayConnected() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/ebay/status');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to get eBay status: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return data['connected'] == true;
  }

  /// eBay OAuth 로그인 URL 가져오기
  Future<String> getEbayConnectUrl() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/ebay/connect');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to get eBay connect URL: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return data['auth_url'] as String;
  }

  /// eBay 연결 해제
  Future<void> disconnectEbay() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/ebay/disconnect');

    final response = await http.delete(
      url,
      headers: {
        "Authorization": "Bearer $token",
      },
    );

    if (response.statusCode >= 400) {
      throw Exception('Failed to disconnect eBay: ${response.body}');
    }
  }

  /// 🔍 eBay Sandbox Inventory 전체 조회
  Future<List<EbayItem>> getEbayInventory() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/ebay/inventory');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
        'Accept': 'application/json',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load eBay inventory: ${res.body}');
    }

    final data = jsonDecode(res.body);
    
    final List<dynamic> itemsJson = data['inventoryItems'] ?? [];

    return itemsJson.map((json) => EbayItem.fromJson(json)).toList();
  }

  /// eBay Inventory item 삭제
  Future<void> deleteEbayInventoryItem(String sku) async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/ebay/inventory/$sku');
    final res = await http.delete(
      url,
      headers: {
        'Authorization': 'Bearer $token',
        'Accept': 'application/json',
      },
    );

    if (res.statusCode >= 300) {
      throw Exception('Failed to delete item: ${res.body}');
    }
  }

  /// Sync eBay inventory with local listings
  Future<Map<String, dynamic>> syncEbayInventory() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/ebay/sync-inventory');
    final res = await http.post(
      url,
      headers: {
        'Authorization': 'Bearer $token',
        'Accept': 'application/json',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to sync inventory: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return data;
  }

  // ============================================
  // Poshmark Inventory Methods
  // ============================================

  /// Poshmark 인벤토리 조회
  Future<List<PoshmarkItem>> getPoshmarkInventory() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/inventory');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
        'Accept': 'application/json',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load Poshmark inventory: ${res.body}');
    }

    final data = jsonDecode(res.body);
    
    final List<dynamic> itemsJson = data['items'] ?? [];

    return itemsJson.map((json) => PoshmarkItem.fromJson(json)).toList();
  }

  // ============================================
  // Poshmark Connection Methods
  // ============================================

  /// Poshmark 연결 여부 확인
  Future<bool> isPoshmarkConnected() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/status');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to get Poshmark status: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return data['connected'] == true;
  }

  /// Poshmark 연결 URL 가져오기 (eBay 스타일)
  Future<String> getPoshmarkConnectUrl() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/connect');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to get Poshmark connect URL: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return data['connect_url'] as String;
  }

  /// [NEW] Poshmark 쿠키 기반 연결 (WebView에서 추출한 쿠키 전송)
  /// 이 함수가 추가되었습니다.
  Future<void> connectPoshmarkViaCookies(List<Map<String, dynamic>> cookies) async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/connect/cookies');

    final response = await http.post(
      url,
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
      body: jsonEncode(cookies),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to connect Poshmark via cookies: ${response.body}');
    }
  }

  /// Poshmark 연결 해제
  Future<void> disconnectPoshmark() async {
    final baseUrl = _auth.baseUrl;
    final token = await _auth.getToken();
    if (token == null) throw Exception('Not logged in');

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/disconnect');

    final response = await http.delete(
      url,
      headers: {
        "Authorization": "Bearer $token",
      },
    );

    if (response.statusCode >= 400) {
      throw Exception('Failed to disconnect Poshmark: ${response.body}');
    }
  }
}