# web

Owner: claude3 (T-0005): web panel.

Hafif, derleme gerektirmeyen yerel panel. Düz HTML/CSS/JS ve yalnızca standart kütüphaneli bir Python sunucusu kullanır; `npm` veya ek paket gerekmez.

## Çalıştırma

1. Hub çalışıyor olmalı (`start_wacc.bat` veya `python -m wacc_hub serve`, varsayılan `http://127.0.0.1:8765`).
2. Paneli başlat:

   ```
   python web/serve.py
   ```

   Panel `http://127.0.0.1:8780` adresinde açılır. Seçenekler: `--port 8790`, `--hub http://127.0.0.1:8765`, `--backend http://127.0.0.1:8800` (ya da `WACC_WEB_PORT`, `WACC_HUB_URL`, `WACC_BACKEND_URL` ortam değişkenleri).
3. Sağ üstteki alana kendi tokenını yapıştır ve **Bağlan**'a bas. Token `data/tokens.json` içindedir; panel için `user` tokenını kullan. **Hatırla** kutusu varsayılan olarak kapalıdır: token yalnızca bu sekmenin `sessionStorage` alanında durur ve sekme kapanınca silinir. Kutuyu işaretlersen token bu tarayıcının `localStorage` alanında kalıcı saklanır (`user` tokenı onay verebilen tek token olduğu için yalnızca kendi bilgisayarında işaretle). **Unut** her iki yerden de siler.

## Ne gösterir / ne yapar

| Sekme | İçerik |
|---|---|
| Ajanlar | Her ajanın durumu, çevrimiçi bilgisi, okunmamış / yanıtlanacak / yanıt bekleyen sayıları, aktif ve engelli görevler, son commit ve son mesaj. `user` için **Acil durdur** ve **Devam ettir** düğmeleri. |
| Akış | Ortak mesaj akışı (yeniden eskiye). Mesaj gönderme formu (alıcı, tür, öncelik, konu, içerik, yanıt gerekli). Bir mesajdaki `#konuşma` etiketine tıklayınca akış o konuşmaya filtrelenir ve yeni mesaj aynı konuşmaya eklenir. |
| Görevler | Duruma göre gruplanmış görevler. Görev oluşturma formu (yalnızca `claude1`/`user`). Her görevde kabul etme, durum/commit/not güncelleme ve atama işlemleri. |
| Kilitler | Aktif yol kilitleri, sahibi, bitiş zamanı ve süresi dolmuş olanlar. |

Veri 5 saniyede bir yenilenir (sekme görünürken). Hub durursa üstteki rozet "Hub'a ulaşılamıyor" der.

| Backend | Salt okunur: iş kuyruğu (özet + son işler), ajan kaydı, projeler, AI sağlayıcıları ve günlük maliyet. Backend'in kendi tokenı gerekir (`data/backend_token.txt`); Hub tokenından farklıdır. |
| Onaylar | Ajanların istediği riskli eylemleri (silme, kurulum, push…) görüntüler ve onaylar/reddeder; yürütmeyi durdurur/devam ettirir; son kararlar ve denetim kaydı. Ayrıntılar aşağıda. |

| Yapay Zeka | Sağlayıcı hesapları: liste (açık/kapalı, kaynak, fiyat), günlük harcama/bütçe; yerel (loopback) veya bulut (https + anahtar) hesap ekle, aç/kapat, gerçek küçük istekle **Test**, sil. Yazma işlemleri kullanıcı tokenı ister (yalnızca bellekte, 5 dk boşta düşer). API anahtarı gönderilmeden önce formdan silinir, hiçbir yerde saklanmaz ve yanıtta geri gelmez. Ortam sağlayıcıları (`local-llm`, `cloud-llm`, `mock`) silinemez, yalnızca açılıp kapatılır. |

### Onaylar sekmesi

- Bekleyen onay sayısı sekmede ve sayfa başlığında görünür (`Onaylar (2)`); Backend tokenı (veya onay tokenı) varsa her 5 saniyede güncellenir.
- Her kartta **ham eylem** (backend'in doğruladığı biçim), eylem sınıfı, isteyen ajan, kalan süre ve eylem özeti (SHA-256) gösterilir. Backend'in risk özeti ve ajanın açıklaması yalnızca yardımcıdır; karar ham eyleme bakılarak verilir. Onay yalnızca o eyleme bağlıdır, tek kullanımlıktır, 10 dakikada dolar (`docs/EXECUTION_SECURITY.md`).
- **Onaylamak için kullanıcı tokenı gerekir**: backend penceresinde her açılışta yazılır, diske kaydedilmez. Panel onu **hiçbir depoya yazmaz** (ne `localStorage` ne `sessionStorage`): yalnızca bellekte tutar, girilince alandan siler, 5 dakika işlem yapılmazsa, **Sil**'e ya da **Unut**'a basılınca ve sayfa yenilenince unutur. Token olmadan sekme salt okunurdur (düğmeler kapalı).
- **Onayla** her seferinde ham eylemi gösteren bir onay penceresi açar. Ajan tokenı onaylayamaz, yalnızca kullanıcı tokenı onaylar/reddeder/devam ettirir; bunu panel değil Backend zorlar.
- **Yürütmeyi durdur**: Backend'in acil durdurması (Hub'ın paylaşılan `data/EMERGENCY_STOP` bayrağıyla aynı anahtar). **Devam ettir** yalnızca kullanıcı tokenıyla çalışır.

## Nasıl çalışır

`serve.py` `web/public/` dosyalarını sunar, `/api/*` isteklerini Hub'a ve `/backend/*` isteklerini Backend'e iletir. Tarayıcı tek bir adrese konuştuğu için CORS gerekmez ve Hub/Backend koduna dokunulmaz. Tokenlar `X-WACC-Token` başlığıyla taşınır; sunucu onları saklamaz ve loglamaz.

`/backend/*` bilerek dardır (izin listesi, kesin eşleşme):

| Yön | Yollar |
|---|---|
| GET | `/health`, `/projects`, `/jobs`, `/jobs/summary`, `/agents`, `/ai/providers`, `/ai/usage`, `/exec/approvals`, `/exec/status`, `/exec/audit` |
| POST | `/exec/approvals/{id}/approve`, `/exec/approvals/{id}/deny`, `/exec/stop`, `/exec/resume`, `/ai/accounts`, `/ai/providers/{ad}/enabled`, `/ai/providers/{ad}/test` |
| DELETE | `/ai/accounts/{ad}` |

Bunların dışındaki her şey (hafıza, AI çağrısı, bütçe, iş/proje yazma, `POST /exec` ile eylem gönderme…) panelden geçmez: GET için `404 NOT_EXPOSED`, POST için `405`.

### Bildirim ve görsel kimlik

- Onaylar sekmesindeki **Yeni onayda bildirim göster** düğmesi tarayıcı iznini yalnızca tıklayınca ister. İzin verilirse, sekme arka plandayken yeni bir onay isteği geldiğinde sabit metinli bir bildirim gösterilir (ajanların yazdığı hiçbir metin bildirime konmaz); arka plandayken yalnızca bekleyen onay sayısı yoklanır.
- `favicon-32.png` ve `icon-192.png` `assets/` içindeki dosyaların kopyalarıdır (serve.py yalnızca `web/public/` sunar); renkler `assets/palette.md` ile aynı CSS değişkenleridir.

## Güvenlik

- Sunucu yalnızca `127.0.0.1` üzerinde dinler; yabancı `Host` başlığı (DNS rebinding) ve farklı `Origin` ile gelen POST istekleri (CSRF) reddedilir; onay kararı da buna dahildir.
- Yalnızca `GET` ve `POST` iletilir. Yetki kararını Hub ve Backend verir: token, işlemi yapan ajanı/rolü belirler; panel yalnızca düğmeleri gizler.
- Ajan mesajları güvenilmeyen girdidir: arayüz Hub'dan gelen hiçbir değeri HTML olarak yorumlamaz (`innerHTML` yok), hepsi metin olarak eklenir. `Content-Security-Policy` satır içi betiği engeller.
- Token kaynak koda gömülmez ve git'e girmez. Kullanıcı (onay) tokenı hiçbir depoya yazılmaz.

## Test

```
python -m unittest discover -s web/tests -v
```

Testler geçici veritabanlarıyla gerçek bir Hub, gerçek bir Backend (sahte yürütücüyle) ve panel sunucusu başlatır; statik dosyaları, token davranışını, mesaj/görev/kilit/acil durdurma uçlarını, yol gezintisi ve yabancı `Host`/`Origin` reddini, Hub/Backend kapalıyken 502 yanıtını, `/backend/*` izin listesini, bekleyen onayın listelenmesini, ajan tokenının onaylayamamasını, kullanıcı onayından sonra ajanın eylemi bir kez çalıştırabilmesini, durdur/devam ettirme ve arayüz kaynağında HTML enjeksiyon noktası ile token saklama olmadığını doğrular. Hub bağımlılıkları kuruluysa (`pip install -r hub/requirements-dev.txt`) hepsi çalışır; `node` varsa `app.js` sözdizimi de denetlenir.
