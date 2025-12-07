import 'package:flutter/material.dart';
import 'package:frontend/models/listing.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:frontend/screens/edit_listing_screen.dart';

class ListingDetailScreen extends StatefulWidget {
  final Listing listing;

  const ListingDetailScreen({
    super.key,
    required this.listing,
  });

  @override
  State<ListingDetailScreen> createState() => _ListingDetailScreenState();
}

class _ListingDetailScreenState extends State<ListingDetailScreen> {
  final _authService = AuthService();
  final _listingService = ListingService();

  late Listing _listing;
  bool _deleting = false;

  // 여러 이미지용 상태
  List<String> _imageUrls = [];     // "/media/..." 형태
  bool _loadingImages = true;
  String? _imageError;

  @override
  void initState() {
    super.initState();
    _listing = widget.listing;
    _loadImages();
  }

  Future<void> _loadImages() async {
    setState(() {
      _loadingImages = true;
      _imageError = null;
    });

    try {
      final urls = await _listingService.getListingImages(_listing.id);
      if (!mounted) return;
      setState(() {
        _imageUrls = urls;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _imageError = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loadingImages = false;
      });
    }
  }

  Future<void> _editListing() async {
    final updated = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(
        builder: (_) => EditListingScreen(listing: _listing),
      ),
    );

    if (updated != null && mounted) {
      setState(() {
        _listing = updated;
      });
      // 수정 후 썸네일/이미지가 바뀌었을 수 있으니 다시 로드
      _loadImages();
    }
  }

  Future<void> _deleteListing() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Listing'),
        content: Text('Are you sure you want to delete "${_listing.title}"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text(
              'Delete',
              style: TextStyle(color: Colors.red),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    setState(() {
      _deleting = true;
    });

    try {
      await _listingService.deleteListing(_listing.id);
      if (!mounted) return;
      Navigator.of(context).pop(); // 목록으로 돌아가기
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _deleting = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete: $e')),
      );
    }
  }

  Future<void> _deleteImage(String imageUrl) async {
    try {
      await _listingService.deleteListingImage(_listing.id, imageUrl);
      if (!mounted) return;
      setState(() {
        _imageUrls.remove(imageUrl);
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete image: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final baseUrl = _authService.baseUrl;

    // 메인 이미지: 여러 장 있으면 첫 번째, 없으면 thumbnailUrl, 그것도 없으면 null
    String? mainImageUrl;
    if (_imageUrls.isNotEmpty) {
      mainImageUrl = '$baseUrl${_imageUrls.first}';
    } else if (_listing.thumbnailUrl != null) {
      mainImageUrl = '$baseUrl${_listing.thumbnailUrl}';
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Listing Detail'),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit),
            onPressed: _editListing,
            tooltip: 'Edit',
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: _deleting ? null : _deleteListing,
            tooltip: 'Delete',
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 메인 큰 이미지
            Center(
              child: mainImageUrl != null
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: AspectRatio(
                        aspectRatio: 1,
                        child: Image.network(
                          mainImageUrl,
                          fit: BoxFit.cover,
                        ),
                      ),
                    )
                  : Container(
                      width: 200,
                      height: 200,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.grey.shade300),
                      ),
                      child: const Icon(
                        Icons.image_not_supported,
                        size: 64,
                        color: Colors.grey,
                      ),
                    ),
            ),
            const SizedBox(height: 16),

            // 썸네일 리스트 (여러 이미지 + 삭제 버튼)
            if (_loadingImages)
              const Center(child: CircularProgressIndicator())
            else if (_imageError != null)
              Text(
                _imageError!,
                style: theme.textTheme.bodyMedium?.copyWith(color: Colors.red),
              )
            else if (_imageUrls.isNotEmpty)
              SizedBox(
                height: 100,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  itemCount: _imageUrls.length,
                  itemBuilder: (context, index) {
                    final url = _imageUrls[index];
                    final fullUrl = '$baseUrl$url';

                    return Padding(
                      padding: const EdgeInsets.only(right: 8.0),
                      child: Stack(
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: Image.network(
                              fullUrl,
                              width: 100,
                              height: 100,
                              fit: BoxFit.cover,
                            ),
                          ),
                          Positioned(
                            right: 2,
                            top: 2,
                            child: InkWell(
                              onTap: () => _deleteImage(url),
                              child: Container(
                                decoration: BoxDecoration(
                                  color: Colors.black54,
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                padding: const EdgeInsets.all(2),
                                child: const Icon(
                                  Icons.close,
                                  size: 16,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              )
            else
              Text(
                'No additional images',
                style: theme.textTheme.bodySmall,
              ),

            const SizedBox(height: 24),

            // 제목 + 가격 + 상태
            Text(
              _listing.title,
              style: theme.textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              '${_listing.price.toStringAsFixed(2)} ${_listing.currency}',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Status: ${_listing.status}',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: Colors.grey.shade700,
              ),
            ),

            const SizedBox(height: 24),

            // 설명
            Text(
              'Description',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              _listing.description?.isNotEmpty == true
                  ? _listing.description!
                  : 'No description',
              style: theme.textTheme.bodyMedium,
            ),

            const SizedBox(height: 24),

            if (_deleting)
              const Center(
                child: CircularProgressIndicator(),
              ),
          ],
        ),
      ),
    );
  }
}
