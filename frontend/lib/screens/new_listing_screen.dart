import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/listing.dart';
import '../services/listing_service.dart';
import '../widgets/platform_image_widget.dart';

class NewListingScreen extends StatefulWidget {
  const NewListingScreen({super.key});

  @override
  State<NewListingScreen> createState() => _NewListingScreenState();
}

class _NewListingScreenState extends State<NewListingScreen> {
  final _formKey = GlobalKey<FormState>();
  final _titleController = TextEditingController();
  final _descriptionController = TextEditingController();
  final _priceController = TextEditingController();
  final _skuController = TextEditingController(); // [추가] SKU 입력용
  
  // Poshmark-specific field controllers
  final _brandController = TextEditingController();
  final _sizeController = TextEditingController();
  final _originalPriceController = TextEditingController();
  final _categoryController = TextEditingController();
  final _subCategoryController = TextEditingController();
  final _colorsController = TextEditingController();
  final _materialController = TextEditingController();

  // [추가] 상태(Condition) 선택용 기본값
  String _selectedCondition = 'New with Tags'; 
  
  // Condition 옵션들 (사용자 친화적인 이름)
  final List<String> _conditionOptions = [
    'New with Tags',
    'New without Tags',
    'Pre-owned',
    'For Parts or Not Working'
  ];

  bool _saving = false;
  String? _error;

  final _listingService = ListingService();

  // 선택된 이미지들
  List<PlatformFile> _selectedImages = [];

  Future<void> _pickImages() async {
    setState(() {
      _error = null;
    });

    try {
      // 파일 선택기 실행 (다중 선택 가능)
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: true,
        type: FileType.image,
      );

      if (result != null && result.files.isNotEmpty) {
        setState(() {
          _selectedImages = result.files;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to pick images: $e';
      });
    }
  }

  Future<void> _save() async {
    // Validate form
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final price = double.tryParse(_priceController.text.trim()) ?? 0.0;
      final originalPrice = _originalPriceController.text.trim().isEmpty
          ? null
          : double.tryParse(_originalPriceController.text.trim());
      
      // Validate price
      if (price <= 0) {
        setState(() {
          _error = 'Price must be greater than 0';
          _saving = false;
        });
        return;
      }

      // 1) Listing 생성 요청 (SKU, Condition, Poshmark fields 포함)
      final listing = await _listingService.createListing(
        title: _titleController.text.trim(),
        description: _descriptionController.text.trim().isEmpty
            ? null
            : _descriptionController.text.trim(),
        price: price,
        // 입력된 SKU가 없으면 null을 보내 백엔드에서 자동 생성하게 함
        sku: _skuController.text.trim().isEmpty ? null : _skuController.text.trim(),
        condition: _selectedCondition,
        brand: _brandController.text.trim().isEmpty ? null : _brandController.text.trim(),
        size: _sizeController.text.trim().isEmpty ? null : _sizeController.text.trim(),
        originalPrice: originalPrice,
        category: _categoryController.text.trim().isEmpty ? null : _categoryController.text.trim(),
        subCategory: _subCategoryController.text.trim().isEmpty ? null : _subCategoryController.text.trim(),
        colors: _colorsController.text.trim().isEmpty ? null : _colorsController.text.trim(),
        material: _materialController.text.trim().isEmpty ? null : _materialController.text.trim(),
      );

      // 2) 이미지가 선택되어 있다면 업로드
      if (_selectedImages.isNotEmpty) {
        await _listingService.uploadImages(listing.id, _selectedImages);
      }

      if (!mounted) return;
      // 목록 화면으로 돌아가면서 생성된 객체 전달 (목록 새로고침용)
      Navigator.of(context).pop<Listing>(listing);
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
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    _skuController.dispose();
    _brandController.dispose();
    _sizeController.dispose();
    _originalPriceController.dispose();
    _categoryController.dispose();
    _subCategoryController.dispose();
    _colorsController.dispose();
    _materialController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('New Listing'),
      ),
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Title (Required)
                TextFormField(
                  controller: _titleController,
                  decoration: const InputDecoration(
                    labelText: 'Title *',
                    hintText: 'e.g., Samsung Galaxy S25',
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Title is required';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),
                
                // Description
                TextField(
                  controller: _descriptionController,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Description',
                    hintText: 'Describe the item condition, features, etc.',
                  ),
                ),
                const SizedBox(height: 12),
                
                // Price & SKU Row
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _priceController,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: const InputDecoration(
                          labelText: 'Price (USD)',
                          hintText: '0.00',
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: TextField(
                        controller: _skuController,
                        decoration: const InputDecoration(
                          labelText: 'SKU (Optional)',
                          hintText: 'Auto-generated if empty',
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // Condition Dropdown
                DropdownButtonFormField<String>(
                  value: _selectedCondition,
                  decoration: const InputDecoration(labelText: 'Condition'),
                  items: _conditionOptions.map((String condition) {
                    return DropdownMenuItem<String>(
                      value: condition,
                      child: Text(condition),
                    );
                  }).toList(),
                  onChanged: (String? newValue) {
                    if (newValue != null) {
                      setState(() {
                        _selectedCondition = newValue;
                      });
                    }
                  },
                ),
                const SizedBox(height: 12),

                // Brand (Required)
                TextFormField(
                  controller: _brandController,
                  decoration: const InputDecoration(
                    labelText: 'Brand *',
                    hintText: 'e.g., Nike',
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Brand is required';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),

                // Size (Required)
                TextFormField(
                  controller: _sizeController,
                  decoration: const InputDecoration(
                    labelText: 'Size *',
                    hintText: 'e.g., M, 10, 32x30',
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Size is required';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),

                // Original Price
                TextFormField(
                  controller: _originalPriceController,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                    labelText: 'Original Price (USD)',
                    hintText: '0.00',
                    helperText: 'Required for NWT items',
                  ),
                ),
                const SizedBox(height: 12),

                // Category & Sub-Category Row
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _categoryController,
                        decoration: const InputDecoration(
                          labelText: 'Category',
                          hintText: 'e.g., Men, Women',
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: TextField(
                        controller: _subCategoryController,
                        decoration: const InputDecoration(
                          labelText: 'Sub-Category',
                          hintText: 'e.g., Shoes, Tops',
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // Colors
                TextField(
                  controller: _colorsController,
                  decoration: const InputDecoration(
                    labelText: 'Colors',
                    hintText: 'e.g., Black, Red',
                    helperText: 'Primary color (comma-separated for multiple)',
                  ),
                ),
                const SizedBox(height: 12),

                // Material (Optional)
                TextField(
                  controller: _materialController,
                  decoration: const InputDecoration(
                    labelText: 'Material (Optional)',
                    hintText: 'e.g., Cotton',
                  ),
                ),

                const SizedBox(height: 24),

                // Image Picker
                Row(
                  children: [
                    ElevatedButton.icon(
                      onPressed: _saving ? null : _pickImages,
                      icon: const Icon(Icons.photo_library),
                      label: const Text('Select Photos'),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _selectedImages.isEmpty
                            ? 'No photos selected'
                            : '${_selectedImages.length} photo(s) selected',
                        style: theme.textTheme.bodyMedium,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),

                // Image Preview (Horizontal Scroll)
                if (_selectedImages.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  SizedBox(
                    height: 80,
                    child: ListView.builder(
                      scrollDirection: Axis.horizontal,
                      itemCount: _selectedImages.length,
                      itemBuilder: (context, index) {
                        return Padding(
                          padding: const EdgeInsets.only(right: 8.0),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: PlatformImageWidget(
                              file: _selectedImages[index],
                              width: 80,
                              height: 80,
                              fit: BoxFit.cover,
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ],

                const SizedBox(height: 24),

                // Error Message
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      _error!,
                      style: theme.textTheme.bodyMedium?.copyWith(color: Colors.red),
                    ),
                  ),

                // Save Button
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _saving ? null : _save,
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: theme.primaryColor,
                      foregroundColor: Colors.white,
                      disabledBackgroundColor: Colors.grey[400],
                      disabledForegroundColor: Colors.white,
                    ),
                    child: _saving
                        ? Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                                ),
                              ),
                              const SizedBox(width: 12),
                              const Text('Saving...', style: TextStyle(fontSize: 16)),
                            ],
                          )
                        : const Text('Save', style: TextStyle(fontSize: 16)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}