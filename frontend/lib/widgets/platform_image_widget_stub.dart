import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

/// Stub for web platform (should not be called)
Widget buildImageFromPlatformFile(
  PlatformFile file, {
  double? width,
  double? height,
  BoxFit fit = BoxFit.cover,
}) {
  // This should never be called on web as kIsWeb check happens first
  return Container(
    width: width,
    height: height,
    color: Colors.grey[300],
    child: const Icon(Icons.image, color: Colors.grey),
  );
}

