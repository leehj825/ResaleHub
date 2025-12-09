// lib/models/listing.dart

class MarketplaceInfo {
  final String marketplace;
  final String? listingUrl;
  final String status;
  final String? externalItemId;
  
  // [추가됨] 상세 정보를 위한 필드
  final String? sku;
  final String? offerId;

  MarketplaceInfo({
    required this.marketplace,
    this.listingUrl,
    required this.status,
    this.externalItemId,
    this.sku,
    this.offerId,
  });

  factory MarketplaceInfo.fromJson(Map<String, dynamic> json) {
    return MarketplaceInfo(
      marketplace: json['marketplace'] ?? '',
      listingUrl: json['external_url'], // 백엔드 스키마 필드명(external_url) 매핑
      status: json['status'] ?? '',
      externalItemId: json['external_item_id'],
      sku: json['sku'],          // [추가됨] 백엔드 필드 매핑
      offerId: json['offer_id'], // [추가됨] 백엔드 필드 매핑
    );
  }
}

class Listing {
  final int id;
  final String title;
  final String? description;
  final double price;

  // [필수 필드 유지] 앱 전반에서 사용됨
  final String currency;
  final String status;
  final String? thumbnailUrl;

  // [상세 화면용]
  final List<String> imageUrls;
  
  // [마켓플레이스 연동 정보]
  final List<MarketplaceInfo> marketplaces;

  Listing({
    required this.id,
    required this.title,
    this.description,
    required this.price,
    this.currency = 'USD',
    this.status = 'draft',
    this.thumbnailUrl,
    this.imageUrls = const [],
    this.marketplaces = const [],
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    // 마켓플레이스 정보 파싱
    var mkList = json['marketplace_links'] as List? ?? [];
    List<MarketplaceInfo> marketplacesData = 
        mkList.map((i) => MarketplaceInfo.fromJson(i)).toList();

    return Listing(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String?,
      
      price: double.tryParse(json['price'].toString()) ?? 0.0,
      
      currency: json['currency'] as String? ?? 'USD',
      status: json['status'] as String? ?? 'draft',
      thumbnailUrl: json['thumbnail_url'] as String?,
      
      imageUrls: json['image_urls'] != null 
          ? List<String>.from(json['image_urls']) 
          : [],
      
      marketplaces: marketplacesData,
    );
  }

  // 썸네일 전체 URL 헬퍼 메서드
  String? fullThumbnailUrl(String baseUrl) {
    if (thumbnailUrl == null) return null;
    return '$baseUrl$thumbnailUrl';
  }
}