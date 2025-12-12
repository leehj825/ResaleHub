import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

/// Builds an Image.file widget from PlatformFile (non-web only)
Widget buildImageFromPlatformFile(
  PlatformFile file, {
  double? width,
  double? height,
  BoxFit fit = BoxFit.cover,
}) {
  if (file.path != null) {
    return Image.file(
      File(file.path!),
      width: width,
      height: height,
      fit: fit,
    );
  } else {
    return Container(
      width: width,
      height: height,
      color: Colors.grey[300],
      child: const Icon(Icons.image, color: Colors.grey),
    );
  }
}

