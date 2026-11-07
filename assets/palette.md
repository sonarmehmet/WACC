# WACC görsel kimliği

Özgün tasarım (WACC projesi için çizildi; başka bir markanın logosu ya da ikonu değildir). Fikir: ortadaki **Hub** ve ona bağlı dört **ajan** düğümü (claude1, claude2, claude3 + bir yardımcı). Sağ üstteki içi boş düğüm "bekleyen/onay" anlamındadır.

## Dosyalar
| Dosya | Kullanım |
|---|---|
| `icon.svg` | Ana ikon (1024 görünüm kutusu, yuvarlatılmış köşe). Her boyutun kaynağı. |
| `logo.svg` | İkon + "WACC" yazısı (açık zemin için, yatay). |
| `icon-1024.png`, `icon-512.png`, `icon-192.png`, `favicon-32.png` | `python assets/render.py` ile `icon.svg`'den üretilir (Chromium/Playwright gerekir). Elle düzenleme, SVG'yi değiştirip yeniden üret. |

## Renkler (web paneliyle aynı değişkenler: `web/public/style.css`)
Panel tek, koyu "kontrol odası" temasıdır (açık tema yok).
| Rol | Renk |
|---|---|
| Zemin `--bg` | `#05070a` |
| Panel `--panel` (cam paneller bunun üstüne yarı saydam biner) | `#0b1317` |
| Metin `--text` | `#dcece7` |
| Soluk metin `--muted` | `#6f8b85` |
| Vurgu `--accent` (neon yeşil) | `#37e6b3` |
| Vurgu üstü metin `--accent-text` | `#04140f` |
| Başarılı `--ok` | `#37e6b3` |
| Uyarı `--warn` | `#ffb04a` |
| Hata `--bad` | `#ff5a6a` |

Marka rengi: **`#2557d6`** (ikon zemini). İkon her iki zeminde aynı kalır; koyu zeminde logo yazısı `#dcece7` olmalı.
Radar durum renkleri: beklemede yeşil `#37e6b3`, onay bekliyor turuncu `#ff9f3a`, acil durdurma kırmızı `#ff4d4d`, token gerekli mavi `#3aa0ff`, bağlantı yok gri `#56666a`.

## Kontrast (WCAG, hesaplandı)
Metin çiftleri için hedef 4,5:1, vurgu rengi yüzeyde 3:1. Hepsi geçiyor.
| Çift | Oran |
|---|---|
| Metin / panel | 15,36 |
| Soluk metin / panel | 5,10 |
| Vurgu üstü metin / vurgu | 11,81 |
| Başarılı / panel | 11,73 |
| Uyarı / panel | 10,32 |
| Hata / panel | 6,18 |
| Vurgu / panel | 11,73 |

## Entegrasyon (claude3, issue #5)
- Web: `<link rel="icon" type="image/png" href="favicon-32.png">` ve başlıkta logo; dosyaları `web/public/` altına kopyala (serve.py yalnızca orayı sunar).
- Flutter: `icon-1024.png` ile `flutter_launcher_icons` ya da elle `mipmap-*` boyutları; uygulama adı "WACC".
- Masaüstü: pencere ikonu bağlandı (`desktop/wacc_desktop/ui.py`, `assets/icon-192.png`).
