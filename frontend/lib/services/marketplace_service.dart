// lib/services/marketplace_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;

import 'auth_service.dart';

class MarketplaceService {
  final _auth = AuthService();

  MarketplaceService._internal();
  static final MarketplaceService _instance = MarketplaceService._internal();
  factory MarketplaceService() => _instance;

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


}
