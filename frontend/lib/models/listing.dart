class Listing {
  final int id;
  final String title;
  final String? description;
  final double price;
  final String currency;
  final String status;
  final String? thumbnailUrl;

  Listing({
    required this.id,
    required this.title,
    this.description,
    required this.price,
    required this.currency,
    required this.status,
    this.thumbnailUrl,
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    return Listing(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String?,
      price: double.parse(json['price'].toString()),
      currency: json['currency'] as String,
      status: json['status'] as String,
      thumbnailUrl: json['thumbnail_url'] as String?,
    );
  }
  
  String? fullThumbnailUrl(String baseUrl) {
    if (thumbnailUrl == null) return null;
    // thumbnail_url 이 "/media/..." 형태니까 앞에 baseUrl 붙여줌
    return '$baseUrl$thumbnailUrl';
  }
}
