import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../models/listing.dart';
import 'auth_service.dart';

class ListingService {
  ListingService._internal();
  static final ListingService _instance = ListingService._internal();
  factory ListingService() => _instance;

  final _authService = AuthService();

  Future<List<Listing>> getMyListings() async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load listings: ${res.body}');
    }

    final data = jsonDecode(res.body) as List<dynamic>;
    return data
        .map((e) => Listing.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // [수정됨] thumbnailUrl 파라미터 추가
  Future<Listing> createListing({
    required String title,
    String? description,
    required double price,
    String currency = 'USD',
    String? sku,
    String? condition,
    String? importFrom,
    String? importExternalId,
    String? importUrl,
    String? thumbnailUrl, // 추가
  }) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/');
    
    final body = {
      'title': title,
      'description': description,
      'price': price,
      'currency': currency,
      'sku': sku,
      'condition': condition,
      'import_from_marketplace': importFrom,
      'import_external_id': importExternalId,
      'import_url': importUrl,
      'thumbnail_url': thumbnailUrl, // 백엔드로 전송
    };

    final res = await http.post(
      url,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode(body),
    );

    if (res.statusCode != 201) {
      throw Exception('Failed to create listing: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return Listing.fromJson(data);
  }

  // ... (나머지 updateListing, deleteListing, uploadImages, getListingImages 등은 기존과 동일) ...
  // [파일 길이상 생략된 부분은 기존 코드를 그대로 유지하세요]
  Future<Listing> updateListing(
    int listingId, {
    String? title,
    String? description,
    double? price,
    String? currency,
    String? status,
    String? sku,
    String? condition,
  }) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not authenticated');
    }

    final url = Uri.parse('$baseUrl/listings/$listingId');

    final body = <String, dynamic>{};
    if (title != null) body['title'] = title;
    if (description != null) body['description'] = description;
    if (price != null) body['price'] = price;
    if (currency != null) body['currency'] = currency;
    if (status != null) body['status'] = status;
    if (sku != null) body['sku'] = sku;
    if (condition != null) body['condition'] = condition;

    final res = await http.put(
      url,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode(body),
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to update listing: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return Listing.fromJson(data);
  }

  Future<void> deleteListing(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not authenticated');
    }

    final url = Uri.parse('$baseUrl/listings/$listingId');

    final res = await http.delete(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 204) {
      throw Exception('Failed to delete listing: ${res.body}');
    }
  }

  Future<void> uploadImages(int listingId, List<File> files) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not authenticated');
    }

    final uri = Uri.parse('$baseUrl/listings/$listingId/images');

    final request = http.MultipartRequest('POST', uri);
    request.headers['Authorization'] = 'Bearer $token';

    for (final file in files) {
      final fileName = file.path.split('/').last;
      request.files.add(
        await http.MultipartFile.fromPath(
          'files',
          file.path,
          filename: fileName,
        ),
      );
    }

    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode != 201) {
      throw Exception('Failed to upload images: ${response.body}');
    }
  }

  Future<List<String>> getListingImages(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/$listingId/images');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load images: ${res.body}');
    }

    final data = jsonDecode(res.body) as List<dynamic>;
    return data.map((e) => e as String).toList();
  }

  Future<void> deleteListingImage(int listingId, String imageUrl) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final parts = imageUrl.split('/');
    final filename = parts.isNotEmpty ? parts.last : imageUrl;

    final url = Uri.parse('$baseUrl/listings/$listingId/images/$filename');
    final res = await http.delete(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 204) {
      throw Exception('Failed to delete image: ${res.body}');
    }
  }

  Future<void> publishToEbay(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/ebay/$listingId/publish');
    final res = await http.post(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to publish to eBay: ${res.body}');
    }
  }

  Future<void> publishToPoshmark(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/poshmark/$listingId/publish');
    final res = await http.post(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to publish to Poshmark: ${res.body}');
    }
  }

  Future<List<String>> getListingMarketplaces(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/marketplaces/listings/$listingId');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load marketplaces: ${res.body}');
    }

    final data = jsonDecode(res.body) as List<dynamic>;
    return data.map((e) => e.toString()).toList();
  }

  Future<Listing> getListing(int id) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/$id');
    
    final response = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return Listing.fromJson(data);
    } else {
      throw Exception('Failed to load listing: ${response.body}');
    }
  }
}