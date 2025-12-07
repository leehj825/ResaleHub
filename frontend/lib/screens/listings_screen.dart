import 'package:flutter/material.dart';

import 'package:frontend/models/listing.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/screens/new_listing_screen.dart';
import 'package:frontend/screens/edit_listing_screen.dart';

class ListingsScreen extends StatefulWidget {
  const ListingsScreen({super.key});

  @override
  State<ListingsScreen> createState() => _ListingsScreenState();
}

class _ListingsScreenState extends State<ListingsScreen> {
  final _listingService = ListingService();
  final _authService = AuthService(); // baseUrl 여기서 가져옴

  bool _loading = true;
  String? _error;
  List<Listing> _listings = [];

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
        _listings = items;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loading = false;
      });
    }
  }

  Future<void> _openNewListing() async {
    final created = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(builder: (_) => const NewListingScreen()),
    );

    if (created != null) {
      _loadListings();
    }
  }

  Future<void> _openEditListing(Listing listing) async {
    final updated = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(
        builder: (_) => EditListingScreen(listing: listing),
      ),
    );

    if (updated != null) {
      _loadListings();
    }
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
        _listings.removeWhere((l) => l.id == listing.id);
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final baseUrl = _authService.baseUrl; // 여기서 baseUrl 확보

    return Scaffold(
      appBar: AppBar(
        title: const Text('My Listings'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text('Error: $_error'))
              : _listings.isEmpty
                  ? const Center(child: Text('No listings yet.'))
                  : ListView.builder(
                      itemCount: _listings.length,
                      itemBuilder: (context, index) {
                        final item = _listings[index];

                        // thumbnail_url → full URL
                        String? thumbnailFullUrl;
                        if (item.thumbnailUrl != null) {
                          thumbnailFullUrl = '$baseUrl${item.thumbnailUrl}';
                        }

                        return Card(
                          margin: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 8,
                          ),
                          child: ListTile(
                            onTap: () => _openEditListing(item), // 탭 → 수정 화면
                            leading: thumbnailFullUrl != null
                                ? ClipRRect(
                                    borderRadius: BorderRadius.circular(8),
                                    child: Image.network(
                                      thumbnailFullUrl,
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
      floatingActionButton: FloatingActionButton(
        onPressed: _openNewListing,
        child: const Icon(Icons.add),
      ),
    );
  }
}
