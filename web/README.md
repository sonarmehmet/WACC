# web

Owner: claude3 (T-0005): web panel.

Hafif, derleme gerektirmeyen yerel panel. Düz HTML/CSS/JS ve yalnızca standart kütüphaneli bir Python sunucusu kullanır; `npm` veya ek paket gerekmez.

## Çalıştırma

1. Hub çalışıyor olmalı (`start_wacc.bat` veya `python -m wacc_hub serve`, varsayılan `http://127.0.0.1:8765`).
2. Paneli başlat:

   ```
   python web/serve.py
   ```

   Panel `http://127.0.0.1:8780` adresinde açılır. Seçenekler: `--port 8790`, `--hub http://127.0.0.1:8765` (ya da `WACC_WEB_PORT`, `WACC_HUB_URL` ortam değişkenleri).
3. Sağ üstteki alana kendi tokenını yapıştır ve **Bağlan**'a bas. Token `data/tokens.json` içindedir; panel için `user` tokenını kullan. Token yalnızca bu tarayıcının `localStorage` alanında tutulur, **Unut** ile silinir.

## Ne gösterir / ne yapar

| Sekme | İçerik |
|---|---|
| Ajanlar | Her ajanın durumu, çevrimiçi bilgisi, okunmamış / yanıtlanacak / yanıt bekleyen sayıları, aktif ve engelli görevler, son commit ve son mesaj. `user` için **Acil durdur** ve **Devam ettir** düğmeleri. |
| Akış | Ortak mesaj akışı (yeniden eskiye). Mesaj gönderme formu (alıcı, tür, öncelik, konu, içerik, yanıt gerekli). Bir mesajdaki `#konuşma` etiketine tıklayınca akış o konuşmaya filtrelenir ve yeni mesaj aynı konuşmaya eklenir. |
| Görevler | Duruma göre gruplanmış görevler. Görev oluşturma formu (yalnızca `claude1`/`user`). Her görevde kabul etme, durum/commit/not güncelleme ve atama işlemleri. |
| Kilitler | Aktif yol kilitleri, sahibi, bitiş zamanı ve süresi dolmuş olanlar. |

Veri 5 saniyede bir yenilenir (sekme görünürken). Hub durursa üstteki rozet "Hub'a ulaşılamıyor" der.

## Nasıl çalışır

`serve.py` iki iş yapar: `web/public/` dosyalarını sunar ve `/api/*` isteklerini Hub'a iletir. Tarayıcı tek bir adrese konuştuğu için CORS gerekmez ve Hub koduna dokunulmaz. Token `X-WACC-Token` başlığıyla taşınır; sunucu onu saklamaz ve loglamaz.

## Güvenlik

- Sunucu yalnızca `127.0.0.1` üzerinde dinler; yabancı `Host` başlığı (DNS rebinding) ve farklı `Origin` ile gelen POST istekleri reddedilir.
- Yalnızca `GET` ve `POST` iletilir. Yetki kararını Hub verir: token, işlemi yapan ajanı belirler.
- Ajan mesajları güvenilmeyen girdidir: arayüz Hub'dan gelen hiçbir değeri HTML olarak yorumlamaz (`innerHTML` yok), hepsi metin olarak eklenir. `Content-Security-Policy` satır içi betiği engeller.
- Token kaynak koda gömülmez ve git'e girmez.

## Test

```
python -m unittest discover -s web/tests -v
```

Testler geçici bir veritabanıyla gerçek bir Hub ve panel sunucusu başlatır; statik dosyaları, token davranışını, mesaj/görev/kilit/acil durdurma uçlarını, yol gezintisi ve yabancı `Host`/`Origin` reddini, Hub kapalıyken 502 yanıtını ve arayüz kaynağında HTML enjeksiyon noktası olmadığını doğrular. Hub bağımlılıkları kuruluysa (`pip install -r hub/requirements-dev.txt`) hepsi çalışır; `node` varsa `app.js` sözdizimi de denetlenir.
