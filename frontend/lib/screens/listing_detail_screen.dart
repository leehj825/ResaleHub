import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart'; // [필수] 브라우저 열기용 패키지
import 'package:frontend/models/listing.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/listing_service.dart' as ls;
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
  final _listingService = ls.ListingService();

  late Listing _listing;
  bool _deleting = false;

  // 여러 이미지용 상태
  List<String> _imageUrls = [];
  bool _loadingImages = true;
  String? _imageError;

  // 상태 변경 중 여부
  bool _updatingStatus = false;
  bool _publishing = false; // [추가] 발행 중 로딩 표시

  final List<String> _statusOptions = const ['draft', 'listed', 'sold'];

  @override
  void initState() {
    super.initState();
    _listing = widget.listing;
    _loadImages();
    // 기존 _loadMarketplaces()는 더 이상 필요 없음 (Listing 모델 안에 정보가 있음)
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

  /// [중요] 발행 후 URL 등 최신 정보를 받아오기 위해 리스팅을 다시 불러옴
  Future<void> _reloadListing() async {
    try {
      final updated = await _listingService.getListing(_listing.id);
      if (!mounted) return;
      setState(() {
        _listing = updated;
      });
    } catch (e) {
      // 리로드 실패 시 조용히 넘어가거나 로그 출력
      debugPrint('Failed to reload listing: $e');
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
      Navigator.of(context).pop();
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

  Future<void> _changeStatus(String newStatus) async {
    if (newStatus == _listing.status || _updatingStatus) return;

    setState(() {
      _updatingStatus = true;
    });

    try {
      final updated = await _listingService.updateListing(
        _listing.id,
        status: newStatus,
      );
      if (!mounted) return;
      setState(() {
        _listing = updated;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Status updated to "$newStatus"')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to update status: $e')),
      );
    } finally {
      if (!mounted) return;
      setState(() {
        _updatingStatus = false;
      });
    }
  }

  // --- [eBay 연동] ---
  Future<void> _publishToEbay() async {
    setState(() => _publishing = true);
    try {
      await _listingService.publishToEbay(_listing.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Published to eBay successfully!')),
      );
      // URL 등을 확인하기 위해 리스팅 정보 갱신
      await _reloadListing();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to publish to eBay: $e')),
      );
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _publishToPoshmark() async {
    setState(() => _publishing = true);
    try {
      await _listingService.publishToPoshmark(_listing.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Published to Poshmark (dummy).')),
      );
      await _reloadListing();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to publish to Poshmark: $e')),
      );
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  /// [UI] 마켓플레이스 섹션 빌더
  Widget _buildMarketplaceSection() {
    // 1. eBay 정보 찾기
    final ebayInfo = _listing.marketplaces.firstWhere(
      (m) => m.marketplace == 'ebay',
      orElse: () => MarketplaceInfo(marketplace: '', status: ''),
    );
    // URL이 있으면 "이미 발행됨"으로 간주
    bool isEbayPublished = ebayInfo.listingUrl != null && ebayInfo.listingUrl!.isNotEmpty;

    // 2. Poshmark 정보 찾기 (예시)
    final poshInfo = _listing.marketplaces.firstWhere(
      (m) => m.marketplace == 'poshmark',
      orElse: () => MarketplaceInfo(marketplace: '', status: ''),
    );
    bool isPoshPublished = poshInfo.status == 'published';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "Marketplaces",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 10),

        if (_publishing)
          const Padding(
            padding: EdgeInsets.all(8.0),
            child: Center(child: CircularProgressIndicator()),
          ),

        Row(
          children: [
            // --- eBay Button ---
            Expanded(
              child: isEbayPublished
                  ? ElevatedButton.icon(
                      onPressed: () async {
                        final uri = Uri.parse(ebayInfo.listingUrl!);
                        if (await canLaunchUrl(uri)) {
                          await launchUrl(uri, mode: LaunchMode.externalApplication);
                        } else {
                          if (!mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text('Could not open: ${ebayInfo.listingUrl}')),
                          );
                        }
                      },
                      icon: const Icon(Icons.open_in_new, color: Colors.white),
                      label: const Text("View eBay"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.green,
                        foregroundColor: Colors.white,
                      ),
                    )
                  : OutlinedButton.icon(
                      onPressed: _publishing ? null : _publishToEbay,
                      icon: const Icon(Icons.shopping_bag_outlined),
                      label: const Text("List on eBay"),
                    ),
            ),
            const SizedBox(width: 8),

            // --- Poshmark Button ---
            Expanded(
              child: isPoshPublished
                  ? ElevatedButton.icon(
                      onPressed: () {
                        // Poshmark URL이 있다면 여기서 launchUrl
                      },
                      icon: const Icon(Icons.check),
                      label: const Text("Poshmark"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.grey, // 비활성 느낌
                        foregroundColor: Colors.white,
                      ),
                    )
                  : OutlinedButton.icon(
                      onPressed: _publishing ? null : _publishToPoshmark,
                      icon: const Icon(Icons.style_outlined),
                      label: const Text("List Posh"),
                    ),
            ),
          ],
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final baseUrl = _authService.baseUrl;

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
            // 메인 이미지
            Center(
              child: mainImageUrl != null
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: AspectRatio(
                        aspectRatio: 1,
                        child: Image.network(
                          mainImageUrl,
                          fit: BoxFit.cover,
                          errorBuilder: (c, e, s) => Container(
                            color: Colors.grey.shade200,
                            child: const Icon(Icons.broken_image, size: 50, color: Colors.grey),
                          ),
                        ),
                      ),
                    )
                  : Container(
                      width: double.infinity,
                      height: 300,
                      decoration: BoxDecoration(
                        color: Colors.grey.shade100,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.grey.shade300),
                      ),
                      alignment: Alignment.center,
                      child: const Icon(
                        Icons.image_not_supported,
                        size: 64,
                        color: Colors.grey,
                      ),
                    ),
            ),
            const SizedBox(height: 16),

            // 서브 이미지 리스트
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
                                child: const Icon(Icons.close,
                                    size: 16, color: Colors.white),
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),
            
            const SizedBox(height: 24),

            Text(
              _listing.title,
              style: theme.textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              '${_listing.price.toStringAsFixed(2)} ${_listing.currency}',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.green,
              ),
            ),

            const SizedBox(height: 16),

            // 상태 변경 섹션
            Text('Status', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: _statusOptions.map((status) {
                final isSelected = _listing.status == status;
                return ChoiceChip(
                  label: Text(status),
                  selected: isSelected,
                  onSelected: _updatingStatus
                      ? null
                      : (selected) {
                          if (selected) _changeStatus(status);
                        },
                );
              }).toList(),
            ),
            if (_updatingStatus)
              const Padding(
                padding: EdgeInsets.only(top: 8.0),
                child: LinearProgressIndicator(),
              ),

            const SizedBox(height: 24),

            // 설명
            Text('Description', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              _listing.description?.isNotEmpty == true
                  ? _listing.description!
                  : 'No description',
              style: theme.textTheme.bodyMedium,
            ),

            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),

            // [수정된 부분] 마켓플레이스 섹션 (View 버튼 포함)
            _buildMarketplaceSection(),
            
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}
