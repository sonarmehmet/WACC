"""Render assets/icon.svg to PNG sizes with the preinstalled Chromium (Playwright). Run: python assets/render.py"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SIZES = {"icon-1024.png": 1024, "icon-512.png": 512, "icon-192.png": 192, "favicon-32.png": 32}

svg = (HERE / "icon.svg").read_text(encoding="utf-8")
with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, size in SIZES.items():
        page = browser.new_page(viewport={"width": size, "height": size})
        page.set_content(f'<html><body style="margin:0;background:transparent">'
                         f'<img src="data:image/svg+xml;utf8,{__import__("urllib.parse").parse.quote(svg)}" width="{size}" height="{size}"></body></html>')
        page.wait_for_timeout(200)
        page.screenshot(path=str(HERE / name), omit_background=True)
        page.close()
    browser.close()
print("rendered", ", ".join(SIZES))
