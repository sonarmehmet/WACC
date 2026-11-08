import 'dart:io' show Platform;
import 'dart:math' as math;

import 'package:flutter/material.dart';

/// WACC control-room look shared with the desktop panel (same colours as web/public/style.css).
const Color jarvisBg = Color(0xFF05070A);
const Color jarvisPanel = Color(0xFF0B1317);
const Color jarvisAccent = Color(0xFF37E6B3);
const Color jarvisWarn = Color(0xFFFFB04A);
const Color jarvisBad = Color(0xFFFF5A6A);

ThemeData jarvisTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: jarvisAccent,
    brightness: Brightness.dark,
  ).copyWith(
    primary: jarvisAccent,
    onPrimary: const Color(0xFF031510),
    surface: jarvisPanel,
    error: jarvisBad,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: jarvisBg,
    appBarTheme: const AppBarTheme(backgroundColor: jarvisBg, elevation: 0, centerTitle: true),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: jarvisBg,
      indicatorColor: jarvisAccent.withAlpha(46),
    ),
  );
}

/// The animated radar orb. [color] follows the state: green idle, amber waiting for approval, red emergency stop.
class RadarOrb extends StatefulWidget {
  const RadarOrb({super.key, required this.color, this.size = 150});

  final Color color;
  final double size;

  @override
  State<RadarOrb> createState() => _RadarOrbState();
}

class _RadarOrbState extends State<RadarOrb> with SingleTickerProviderStateMixin {
  // An endless animation never "settles": widget tests (pumpAndSettle) get a still orb, the app a moving one.
  static bool get _underTest {
    try {
      return Platform.environment.containsKey('FLUTTER_TEST');
    } catch (_) {
      return false;
    }
  }

  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 6))
    ..value = 0.15;

  @override
  void initState() {
    super.initState();
    if (!_underTest) _c.repeat();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => CustomPaint(painter: _OrbPainter(_c.value, widget.color)),
      ),
    );
  }
}

class _OrbPainter extends CustomPainter {
  _OrbPainter(this.t, this.color);

  final double t;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.shortestSide / 2 - 6;
    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = jarvisAccent.withAlpha(31);
    canvas.drawCircle(c, r, ring);
    canvas.drawCircle(c, r * 0.72, ring);
    canvas.drawCircle(c, r * 0.32, ring);
    final arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 3
      ..color = color
      ..maskFilter = const MaskFilter.blur(BlurStyle.solid, 3);
    final a = t * 2 * math.pi;
    canvas.drawArc(Rect.fromCircle(center: c, radius: r), a, 0.95, false, arc);
    arc.color = const Color(0xFF1F6E5A);
    canvas.drawArc(Rect.fromCircle(center: c, radius: r * 0.72), -a * 0.7 + math.pi, 0.7, false, arc);
    final pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 3);
    final core = 7 + pulse * 5;
    canvas.drawCircle(c, core * 2.2, Paint()..color = color.withAlpha(46));
    canvas.drawCircle(c, core, Paint()..color = color);
  }

  @override
  bool shouldRepaint(_OrbPainter old) => old.t != t || old.color != color;
}
