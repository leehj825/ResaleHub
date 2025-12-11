class EbayItem {
  final String sku;
  final String title;
  final String description; // 추가됨
  final int quantity;
  final String? imageUrl;
  final String? condition;
  final String? groupId;    // 추가됨 (변형 상품 그룹 ID)

  EbayItem({
    required this.sku,
    required this.title,
    required this.description,
    required this.quantity,
    this.imageUrl,
    this.condition,
    this.groupId,
  });

  factory EbayItem.fromJson(Map<String, dynamic> json) {
    final product = json['product'] as Map<String, dynamic>? ?? {};
    
    // 제목
    final String title = product['title']?.toString() ?? 'No Title';
    
    // 설명 (없으면 빈 문자열)
    final String description = product['description']?.toString() ?? '';

    // 이미지
    String? img;
    if (product['imageUrls'] is List) {
      final list = product['imageUrls'] as List;
      if (list.isNotEmpty) {
        img = list[0].toString();
      }
    }

    // 재고 수량
    final availability = json['availability'] as Map<String, dynamic>? ?? {};
    final shipTo = availability['shipToLocationAvailability'] as Map<String, dynamic>? ?? {};
    
    int qty = 0;
    if (shipTo['quantity'] != null) {
      qty = int.tryParse(shipTo['quantity'].toString()) ?? 0;
    }

    return EbayItem(
      sku: json['sku']?.toString() ?? '',
      title: title,
      description: description,
      quantity: qty,
      imageUrl: img,
      condition: json['condition']?.toString(),
      groupId: json['groupId']?.toString(),
    );
  }
}