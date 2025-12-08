class MarketplaceInfo {
  final String marketplace;
  final String? listingUrl;
  final String status;
  final String? externalItemId;

  MarketplaceInfo({
    required this.marketplace,
    this.listingUrl,
    required this.status,
    this.externalItemId,
  });

  factory MarketplaceInfo.fromJson(Map<String, dynamic> json) {
    return MarketplaceInfo(
      marketplace: json['marketplace'] ?? '',
      listingUrl: json['external_url'], // 백엔드 스키마 필드명(external_url) 매핑
      status: json['status'] ?? '',
      externalItemId: json['external_item_id'],
    );
  }
}

class Listing {
  final int id;
  final String title;
  final String? description; // nullable로 복구
  final double price;

  // [Old Version에서 복구] 앱의 다른 화면들이 이 필드들을 사용합니다.
  final String currency;
  final String status;
  final String? thumbnailUrl;

  // [상세 화면을 위해 필요]
  final List<String> imageUrls;
  
  // [New Version 기능] 마켓플레이스 연동 정보
  final List<MarketplaceInfo> marketplaces;

  Listing({
    required this.id,
    required this.title,
    this.description,
    required this.price,
    this.currency = 'USD',    // 기본값 설정
    this.status = 'draft',    // 기본값 설정
    this.thumbnailUrl,
    this.imageUrls = const [],
    this.marketplaces = const [],
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    // 1. 마켓플레이스 정보 파싱
    var mkList = json['marketplace_links'] as List? ?? [];
    List<MarketplaceInfo> marketplacesData = 
        mkList.map((i) => MarketplaceInfo.fromJson(i)).toList();

    return Listing(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String?,
      
      // 가격을 안전하게 double로 변환
      price: double.tryParse(json['price'].toString()) ?? 0.0,
      
      // [복구된 필드 매핑]
      currency: json['currency'] as String? ?? 'USD',
      status: json['status'] as String? ?? 'draft',
      thumbnailUrl: json['thumbnail_url'] as String?, // snake_case 주의
      
      // 이미지 URL 리스트
      imageUrls: json['image_urls'] != null 
          ? List<String>.from(json['image_urls']) 
          : [],
      
      marketplaces: marketplacesData,
    );
  }

  // (선택 사항) 썸네일 전체 URL 헬퍼 메서드도 필요하다면 유지
  String? fullThumbnailUrl(String baseUrl) {
    if (thumbnailUrl == null) return null;
    return '$baseUrl$thumbnailUrl';
  }
}