import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/listing.dart';
import '../services/listing_service.dart';

class EditListingScreen extends StatefulWidget {
  final Listing listing;

  const EditListingScreen({
    super.key,
    required this.listing,
  });

  @override
  State<EditListingScreen> createState() => _EditListingScreenState();
}

class _EditListingScreenState extends State<EditListingScreen> {
  late TextEditingController _titleController;
  late TextEditingController _descriptionController;
  late TextEditingController _priceController;

  bool _saving = false;
  String? _error;

  final _listingService = ListingService();
  List<PlatformFile> _newImages = [];

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.listing.title);
    _descriptionController =
        TextEditingController(text: widget.listing.description ?? '');
    _priceController =
        TextEditingController(text: widget.listing.price.toString());
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    super.dispose();
  }

  Future<void> _pickMoreImages() async {
    setState(() {
      _error = null;
    });

    final result = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      type: FileType.image,
    );

    if (result != null && result.files.isNotEmpty) {
      setState(() {
        _newImages = result.files;
      });
    }
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final price = double.tryParse(_priceController.text.trim()) ?? 0.0;

      // 1) listing 정보 수정
      final updated = await _listingService.updateListing(
        widget.listing.id,
        title: _titleController.text.trim(),
        description: _descriptionController.text.trim().isEmpty
            ? null
            : _descriptionController.text.trim(),
        price: price,
      );

      // 2) 새로 선택한 이미지 있으면 업로드
      if (_newImages.isNotEmpty) {
        await _listingService.uploadImages(widget.listing.id, _newImages);
      }

      if (!mounted) return;
      Navigator.of(context).pop<Listing>(updated);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _saving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Edit Listing'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _descriptionController,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Description'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _priceController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Price (USD)'),
            ),
            const SizedBox(height: 16),

            // 사진 추가 버튼
            Row(
              children: [
                ElevatedButton(
                  onPressed: _saving ? null : _pickMoreImages,
                  child: const Text('Add Photos'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    _newImages.isEmpty
                        ? 'No new photos'
                        : '${_newImages.length} new photo(s) selected',
                    style: theme.textTheme.bodyMedium,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            if (_error != null)
              Text(
                _error!,
                style: theme.textTheme.bodyMedium?.copyWith(color: Colors.red),
              ),

            const SizedBox(height: 8),

            _saving
                ? const CircularProgressIndicator()
                : SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: _save,
                      child: const Text('Save Changes'),
                    ),
                  ),
          ],
        ),
      ),
    );
  }
}
