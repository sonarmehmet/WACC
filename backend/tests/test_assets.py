import re
import struct
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class BrandingAssets(unittest.TestCase):
    def test_svgs_are_valid_xml_without_scripts_or_external_references(self):
        for name in ("icon.svg", "logo.svg"):
            text = (ASSETS / name).read_text(encoding="utf-8")
            root = ElementTree.fromstring(text)
            self.assertTrue(root.tag.endswith("svg"), name)
            self.assertNotRegex(text, r"(?i)<script|onload=|href=\"http|xlink:href|<image|<foreignObject", name)

    def test_png_sizes_match_their_names(self):
        for name, size in (("icon-1024.png", 1024), ("icon-512.png", 512), ("icon-192.png", 192), ("favicon-32.png", 32)):
            self.assertEqual(png_size(ASSETS / name), (size, size), name)

    def test_palette_in_doc_matches_the_web_panel_css_and_passes_contrast(self):
        css = (ROOT / "web" / "public" / "style.css").read_text(encoding="utf-8")
        doc = (ASSETS / "palette.md").read_text(encoding="utf-8")
        light = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", css.split("@media")[0]))
        for token in ("bg", "panel", "text", "muted", "line", "accent", "ok", "warn", "bad"):
            self.assertIn(light[token].lower(), doc.lower(), token)
        self.assertGreaterEqual(contrast(light["text"], light["panel"]), 4.5)
        self.assertGreaterEqual(contrast(light["muted"], light["panel"]), 4.5)
        self.assertGreaterEqual(contrast(light["accent-text"], light["accent"]), 4.5)
        self.assertGreaterEqual(contrast("#ffffff", "#2557d6"), 4.5)  # icon glyphs on the brand color


if __name__ == "__main__":
    unittest.main()
