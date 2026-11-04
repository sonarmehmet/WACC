# Güvenlik saldırı testi günlüğü

Yöntem: gerçek Hub + Backend (RealExecutor, geçici proje köküyle) + web paneli ayağa kalkıp bir **ajan tokenıyla** saldırı denendi (HTTP üzerinden), ayrıca kaynak kodu incelendi. Tehdit modeli: ele geçirilmiş / yanlış yönlendirilmiş bir LLM ajanı kendi tokenıyla API'yi sürüyor.

## Bulunan ve düzeltilen açıklar (tümü kanıtlandı, regresyon testi var)
| # | Önem | Açık | Düzeltme |
|---|---|---|---|
| 1 | Kritik | `git diff/log/show --output=<yol>` onaysız ALLOW: proje kökü **dışına** dosya yazar/keser | `--opt=<yol>` değerleri de kök kontrolünden geçer; `--output` vb. tehlikeli seçenekler reddedilir |
| 2 | Kritik | `git fetch --upload-p=<komut> .` (git uzun seçeneklerin **kısaltmasını** kabul eder; deny-list yalnızca tam yazımı yakalıyordu) onaysız **komut çalıştırır** | Seçenek adı, tehlikeli seçeneklerin herhangi bir önekiyse (`--upload-p`, `--e`…) reddedilir |
| 3 | Yüksek | `.github/workflows`, `backend/wacc_backend/*`, `hub/wacc_hub/*`, `web/serve.py`, `*.bat/*.sh`, `conftest.py`, `sitecustomize.py`, `requirements*.txt`, `package.json`, `pubspec.yaml`… onaysız yazılabiliyordu (sonraki başlatma/test/kurulumda kod çalışır, kimlik doğrulama zayıflatılabilir) | Korumalı önek + dosya adı listesi genişletildi (büyük/küçük harf duyarsız); bu yazmalar kullanıcı onayı ister |
| 4 | Yüksek | Paket kurulum onayı yalnızca komutun metnine bağlıydı: onaylanmış `pip install -r requirements.txt` sonradan içeriği değiştirilip **onaysız** tekrar çalıştırılabiliyordu | Onay özeti `-r` dosyalarının, manifestlerin ve yerel paket ağacının SHA-256'sını kapsar; içerik değişirse yeni onay gerekir |
| 5 | Orta | `git -m <x>`: sonraki argüman yol kontrolünden muaftı (her alt komutta) | Yalnızca `commit`/`tag` iletisi için |
| 6 | Orta | `git fetch file:///…` / `ext::` / `host:yol` onaysız | URL/uzak konum içeren `fetch` onay ister |
| 7 | Düşük | `http_get` yönlendirmeleri (başka host, http, özel adres) takip ediyordu (SSRF) | Her yönlendirme kontrol edilir, farklı host/güvensiz adres reddedilir |
| 8 | Düşük | AI sağlayıcı isteği yönlendirmeyi takip ediyordu; `Authorization: Bearer <anahtar>` başlığı yönlendirilen adrese gidebilirdi | Yönlendirme takip edilmez |
| 9 | Düşük | `limit=-1` SQLite'ta "sınırsız" demek: Hub `/inbox /sent /feed /audit` ve Backend listeleri tüm tabloyu döküyordu | En az 1'e sıkıştırılır |
| 10 | Düşük | Web proxy: negatif `Content-Length` işleyici istisnası (bağlantı sessizce kopar) | Temiz 400 |

## Denenen ve dayanan saldırılar
Tokensız her rota (Hub + Backend OpenAPI'deki tümü) 401; ajan tokeni kullanıcı-yalnız rotalarda 403 (onay/ret/devam/AI hesabı/bütçe); ortak token onaylayamaz; `/exec` gövdesindeki `agent` alanıyla kimlik taklidi işe yaramıyor; onay başka eyleme, başka ajana, ikinci kez kullanılamıyor (HASH_MISMATCH/FORBIDDEN/NOT_APPROVED); `../`, mutlak yol, sembolik bağ, `.git`, `data/`, `.env`, NUL, 2 MB+ içerik reddi; Hub'a SQL enjeksiyon dizeleri; ajan Hub'da ajan ekleyemez/kapatamaz/silemez, acil durdurmayı kaldıramaz; web panel: yabancı `Host`, `Origin: null`, çapraz kaynak POST, `..`/`%2e%2e`/çift kodlama/ters eğik çizgi, `/backend/../`, kodlanmış `/`, CRLF enjeksiyonu, `//` yetki bölümü, TE/CL kaçakçılığı, devasa `Content-Length`, TRACE/OPTIONS (CORS başlığı yok).

## Açık kalanlar / not
- Hub `/feed` her kimliği doğrulanmış ajana tüm konuşmaları gösterir (tasarım gereği; gizlilik istenirse kısıtlanmalı).
- Ajanlar `web/public/` altına onaysız yazabilir (claude3'ün işi); panel kullanıcı tokenını bellekte tuttuğundan kötü niyetli bir `app.js` onu sızdırabilir. Birleştirmeden önce insan incelemesi (PR) bu riski karşılar; istenirse `web/public/` da korumalı listeye alınır.
- Windows'a özgü (burada denenemedi): NTFS alternatif veri akışı (`dosya::$DATA`), 8.3 kısa adlar, sondaki nokta/boşluk. Yol çözümü `resolve()` ile normalize eder ama bu varyantlar gerçek Windows'ta ayrıca denenmeli.
- Paket kurulumunda sürüm sabitlenmemişse (`pip install paket`) onaydan sonra sürüm değişebilir.
