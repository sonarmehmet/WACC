# WACC görsel kimliği

Özgün tasarım (WACC projesi için çizildi; başka bir markanın logosu ya da ikonu değildir). Fikir: ortadaki **Hub** ve ona bağlı dört **ajan** düğümü (claude1, claude2, claude3 + bir yardımcı). Sağ üstteki içi boş düğüm "bekleyen/onay" anlamındadır.

## Dosyalar
| Dosya | Kullanım |
|---|---|
| `icon.svg` | Ana ikon (1024 görünüm kutusu, yuvarlatılmış köşe). Her boyutun kaynağı. |
| `logo.svg` | İkon + "WACC" yazısı (açık zemin için, yatay). |
| `icon-1024.png`, `icon-512.png`, `icon-192.png`, `favicon-32.png` | `python assets/render.py` ile `icon.svg`'den üretilir (Chromium/Playwright gerekir). Elle düzenleme, SVG'yi değiştirip yeniden üret. |

## Renkler (web paneliyle aynı değişkenler: `web/public/style.css`)
| Rol | Açık tema | Koyu tema |
|---|---|---|
| Zemin `--bg` | `#f5f6f8` | `#12151b` |
| Panel `--panel` | `#ffffff` | `#1b2029` |
| Metin `--text` | `#1c2330` | `#e6e9ef` |
| Soluk metin `--muted` | `#667085` | `#98a2b3` |
| Çizgi `--line` | `#dde1e8` | `#2b323f` |
| Vurgu `--accent` | `#2557d6` | `#6c93ff` |
| Vurgu üstü metin `--accent-text` | `#ffffff` | `#0b1020` |
| Başarılı `--ok` | `#1a7f4b` | `#4cc38a` |
| Uyarı `--warn` | `#b25e09` | `#f0a24a` |
| Hata `--bad` | `#c0362c` | `#ff7a70` |

Marka rengi: **`#2557d6`** (ikon zemini). Koyu zeminde logo yazısı `#e6e9ef` olmalı; ikon her iki temada aynı kalır.

## Kontrast (WCAG, hesaplandı)
Metin çiftleri için hedef 4,5:1, vurgu rengi yüzeyde 3:1. Hepsi geçiyor.
| Tema | Çift | Oran |
|---|---|---|
| Açık | metin / panel | 15,76 |
| Açık | soluk metin / panel | 4,97 |
| Açık | beyaz / vurgu (ikon, düğme) | 6,15 |
| Açık | başarılı / panel | 5,02 |
| Açık | uyarı / panel | 4,67 |
| Açık | hata / panel | 5,52 |
| Koyu | metin / panel | 13,43 |
| Koyu | soluk metin / panel | 6,34 |
| Koyu | vurgu üstü metin / vurgu | 6,54 |
| Koyu | başarılı / panel | 7,38 |
| Koyu | uyarı / panel | 7,76 |
| Koyu | hata / panel | 6,43 |
| Koyu | vurgu / panel | 5,65 |

## Entegrasyon (claude3, issue #5)
- Web: `<link rel="icon" type="image/png" href="favicon-32.png">` ve başlıkta logo; dosyaları `web/public/` altına kopyala (serve.py yalnızca orayı sunar).
- Flutter: `icon-1024.png` ile `flutter_launcher_icons` ya da elle `mipmap-*` boyutları; uygulama adı "WACC".
- Masaüstü: pencere ikonu bağlandı (`desktop/wacc_desktop/ui.py`, `assets/icon-192.png`).
