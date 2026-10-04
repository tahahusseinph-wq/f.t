import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// شاشة مسح الباركود/QR. في الوضع المتواصل (continuous) تستدعي onCode لكل رمز جديد دون الإغلاق.
class ScannerScreen extends StatefulWidget {
  const ScannerScreen({super.key, this.title = 'امسح الباركود', this.continuous = false, this.onCode});

  final String title;
  final bool continuous;
  final Future<String?> Function(String code)? onCode;

  /// يفتح الماسح ويعيد أول رمز.
  static Future<String?> scan(BuildContext context, {String title = 'امسح الباركود'}) =>
      Navigator.push<String>(context, MaterialPageRoute(builder: (_) => ScannerScreen(title: title)));

  @override
  State<ScannerScreen> createState() => _ScannerScreenState();
}

class _ScannerScreenState extends State<ScannerScreen> {
  final controller = MobileScannerController(detectionSpeed: DetectionSpeed.noDuplicates);
  String? _last;
  DateTime _lastAt = DateTime(2000);
  String? _feedback;
  bool _busy = false;

  Future<void> _onDetect(BarcodeCapture capture) async {
    final code = capture.barcodes.firstOrNull?.rawValue;
    if (code == null || _busy) return;
    if (!widget.continuous) {
      Navigator.pop(context, code);
      return;
    }
    // نفس الرمز خلال ثانيتين يُعتبر قراءة مكررة
    if (code == _last && DateTime.now().difference(_lastAt).inMilliseconds < 2000) return;
    _last = code;
    _lastAt = DateTime.now();
    _busy = true;
    final msg = await widget.onCode?.call(code);
    if (mounted) setState(() => _feedback = msg);
    _busy = false;
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title), actions: [
          IconButton(icon: const Icon(Icons.flash_on), onPressed: controller.toggleTorch),
          IconButton(icon: const Icon(Icons.cameraswitch), onPressed: controller.switchCamera),
        ]),
        body: Stack(children: [
          MobileScanner(controller: controller, onDetect: _onDetect),
          Center(
            child: Container(
              width: 260,
              height: 170,
              decoration: BoxDecoration(border: Border.all(color: Colors.white, width: 3), borderRadius: BorderRadius.circular(16)),
            ),
          ),
          if (_feedback != null)
            Positioned(
              left: 16,
              right: 16,
              bottom: 32,
              child: Card(
                child: Padding(padding: const EdgeInsets.all(14), child: Text(_feedback!, textAlign: TextAlign.center)),
              ),
            ),
        ]),
      );
}
