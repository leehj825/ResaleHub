import 'package:flutter/material.dart';

import 'package:frontend/models/listing.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/screens/new_listing_screen.dart';
import 'package:frontend/screens/listing_detail_screen.dart';

class ListingsScreen extends StatefulWidget {
  const ListingsScreen({super.key});

  @override
  State<ListingsScreen> createState() => _ListingsScreenState();
}

class _ListingsScreenState extends State<ListingsScreen> {
  final _listingService = ListingService();
  final _authService = AuthService();

  bool _loading = true;
  String? _error;

  List<Listing> _allListings = [];
  List<Listing> _filteredListings = [];

  String _searchQuery = '';
  String _statusFilter = 'all'; // all / draft / listed / sold
  String _sortOption = 'newest';

  @override
  void initState() {
    super.initState();
    _loadListings();
  }

  Future<void> _loadListings() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _listingService.getMyListings();
      if (!mounted) return;
      setState(() {
        _allListings = items;
      });
      _applyFilters();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      _loading = false;
    }
  }

  Future<void> _openNewListing() async {
    final created = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(builder: (_) => const NewListingScreen()),
    );

    if (created != null) {
      await _loadListings();
    }
  }

  // --------------------------------
  // 👉 Detail 화면으로 이동
  // --------------------------------
  Future<void> _openListingDetail(Listing listing) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ListingDetailScreen(listing: listing),
      ),
    );
    await _loadListings();
  }

  Future<void> _deleteListing(Listing listing) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Listing'),
        content: Text('Are you sure you want to delete "${listing.title}"?'),
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

    try {
      await _listingService.deleteListing(listing.id);
      if (!mounted) return;
      setState(() {
        _allListings.removeWhere((l) => l.id == listing.id);
      });
      _applyFilters();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete: $e')),
      );
    }
  }

  // --------------------------------
  // 필터 + 정렬 적용
  // --------------------------------
  void _applyFilters() {
    List<Listing> items = List<Listing>.from(_allListings);

    // 검색어 적용
    final q = _searchQuery.trim().toLowerCase();
    if (q.isNotEmpty) {
      items = items.where((l) {
        final title = l.title.toLowerCase();
        final desc = (l.description ?? '').toLowerCase();
        return title.contains(q) || desc.contains(q);
      }).toList();
    }

    // 상태 필터
    if (_statusFilter != 'all') {
      items = items.where((l) => l.status == _statusFilter).toList();
    }

    // 정렬
    switch (_sortOption) {
      case 'price_asc':
        items.sort((a, b) => a.price.compareTo(b.price));
        break;
      case 'price_desc':
        items.sort((a, b) => b.price.compareTo(a.price));
        break;
      case 'newest':
      default:
        break;
    }

    setState(() {
      _filteredListings = items;
    });
  }

  void _onSearchChanged(String value) {
    _searchQuery = value;
    _applyFilters();
  }

  void _onStatusFilterChanged(String? value) {
    if (value == null) return;
    _statusFilter = value;
    _applyFilters();
  }

  void _onSortOptionChanged(String? value) {
    if (value == null) return;
    _sortOption = value;
    _applyFilters();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final baseUrl = _authService.baseUrl;

    return Scaffold(
      appBar: AppBar(
        title: const Text('My Listings'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text('Error: $_error'))
              : Column(
                  children: [
                    // Search
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                      child: TextField(
                        decoration: const InputDecoration(
                          prefixIcon: Icon(Icons.search),
                          labelText: 'Search by title or description',
                          border: OutlineInputBorder(),
                        ),
                        onChanged: _onSearchChanged,
                      ),
                    ),

                    // Filters row
                    Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 4),
                      child: Row(
                        children: [
                          // Status filter
                          Expanded(
                            child: DropdownButtonFormField<String>(
                              value: _statusFilter,
                              decoration: const InputDecoration(
                                labelText: 'Status',
                                border: OutlineInputBorder(),
                                isDense: true,
                              ),
                              items: const [
                                DropdownMenuItem(value: 'all', child: Text('All')),
                                DropdownMenuItem(
                                    value: 'draft', child: Text('Draft')),
                                DropdownMenuItem(
                                    value: 'listed', child: Text('Listed')),
                                DropdownMenuItem(
                                    value: 'sold', child: Text('Sold')),
                              ],
                              onChanged: _onStatusFilterChanged,
                            ),
                          ),
                          const SizedBox(width: 8),

                          // Sort filter
                          Expanded(
                            child: DropdownButtonFormField<String>(
                              value: _sortOption,
                              decoration: const InputDecoration(
                                labelText: 'Sort by',
                                border: OutlineInputBorder(),
                                isDense: true,
                              ),
                              items: const [
                                DropdownMenuItem(
                                    value: 'newest', child: Text('Newest')),
                                DropdownMenuItem(
                                    value: 'price_asc', child: Text('Price ↑')),
                                DropdownMenuItem(
                                    value: 'price_desc', child: Text('Price ↓')),
                              ],
                              onChanged: _onSortOptionChanged,
                            ),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 4),

                    // List items
                    Expanded(
                      child: _filteredListings.isEmpty
                          ? const Center(
                              child: Text('No listings match filters.'),
                            )
                          : ListView.builder(
                              itemCount: _filteredListings.length,
                              itemBuilder: (context, index) {
                                final item = _filteredListings[index];

                                String? thumbUrl;
                                if (item.thumbnailUrl != null) {
                                  thumbUrl = '$baseUrl${item.thumbnailUrl}';
                                }

                                return Card(
                                  margin: const EdgeInsets.symmetric(
                                    horizontal: 12,
                                    vertical: 8,
                                  ),
                                  child: ListTile(
                                    onTap: () => _openListingDetail(item), // 👈 수정됨
                                    leading: thumbUrl != null
                                        ? ClipRRect(
                                            borderRadius:
                                                BorderRadius.circular(8),
                                            child: Image.network(
                                              thumbUrl,
                                              width: 56,
                                              height: 56,
                                              fit: BoxFit.cover,
                                            ),
                                          )
                                        : const Icon(
                                            Icons.image_not_supported,
                                            size: 40,
                                          ),
                                    title: Text(item.title),
                                    subtitle: Text(
                                      '${item.price.toStringAsFixed(2)} ${item.currency} • ${item.status}',
                                      style: theme.textTheme.bodySmall,
                                    ),
                                    trailing: IconButton(
                                      icon: const Icon(
                                        Icons.delete_outline,
                                        color: Colors.redAccent,
                                      ),
                                      onPressed: () => _deleteListing(item),
                                    ),
                                  ),
                                );
                              },
                            ),
                    ),
                  ],
                ),
      floatingActionButton: FloatingActionButton(
        onPressed: _openNewListing,
        child: const Icon(Icons.add),
      ),
    );
  }
}
