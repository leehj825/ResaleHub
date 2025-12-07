class Listing {
  final int id;
  final String title;
  final String? description;
  final double price;
  final String currency;
  final String status;

  Listing({
    required this.id,
    required this.title,
    this.description,
    required this.price,
    required this.currency,
    required this.status,
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    return Listing(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String?,
      price: double.parse(json['price'].toString()),
      currency: json['currency'] as String,
      status: json['status'] as String,
    );
  }
}
