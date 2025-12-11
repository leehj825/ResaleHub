// lib/services/marketplace_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;

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

  /// 🔍 eBay Sandbox Inventory 전체 조회 (디버그용)
  ///
  /// 백엔드의 GET /marketplaces/ebay/inventory 를 호출해서
  /// eBay Sell Inventory API 결과(JSON)를 그대로 반환한다.
  ///
  /// 반환 예:
  /// {
  ///   "inventoryItems": [ ... ],
  ///   "total": 1,
  ///   "href": "...",
  ///   ...
  /// }
  Future<Map<String, dynamic>> getEbayInventory() async {
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

    return jsonDecode(res.body) as Map<String, dynamic>;
  }
}
