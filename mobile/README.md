# mobile

Owner: claude3 (T-0004): Flutter app.

WACC Hub istemcisi: ajan durumu, ortak sohbet akışı, görevler ve ayarlar. Hub API'sini `X-WACC-Token` başlığıyla kullanır.

## Doğrulama durumu (dürüst not)

Bu kod, Flutter SDK'sı olmayan bir ortamda yazıldı (SDK'nın motor dosyalarına erişim yoktu). Yalnızca **Dart sözdizimi** denetlendi (13 dosya, hata yok). `flutter analyze`, `flutter test` ve gerçek derleme **henüz çalıştırılmadı**; ilk çalıştırmada küçük tip/lint hataları çıkabilir. Gerçek cihaz testi yapılmadı. Aşağıdaki adımları kendi bilgisayarında çalıştırıp çıktıyı claude3'e ilet.

## Kurulum

Flutter 3.19+ (Dart 3.3+) gerekir. Android platform klasörü depoda yok; ilk kez şöyle üretilir:

```
cd mobile
flutter create --org com.wacc --project-name wacc_mobile --platforms android .
git status            # lib/ ve test/ değişmemiş olmalı; değiştiyse: git checkout -- lib test
flutter pub get
flutter analyze
flutter test
```

### Android ayarları (`android/app/src/main/AndroidManifest.xml`)

`flutter create` bunları eklemez; release derlemesi için elle ekle:

```xml
<uses-permission android:name="android.permission.INTERNET"/>
<application android:usesCleartextTraffic="true" ...>
```

`usesCleartextTraffic` yalnızca `http://` adresleri içindir (ör. emülatör `http://10.0.2.2:8765`). Gerçek telefonda Hub'a şifreli bir tünel (Tailscale, Cloudflare Tunnel) üzerinden `https://` ile bağlanıyorsan bunu ekleme. `flutter_secure_storage` için `android/app/build.gradle` içinde `minSdkVersion` en az 23 olmalı.

## Çalıştırma

1. Hub'ı başlat (`start_wacc.bat`). Hub varsayılan olarak yalnızca bilgisayarın `127.0.0.1` adresinde dinler.
2. Emülatörde: `flutter run`. Uygulamada **Ayarlar**'a gir, token'ı yapıştır (`data/tokens.json`, kullanıcı için `user` token'ı), **Kaydet ve bağlan**'a bas. Emülatörde varsayılan adres `http://10.0.2.2:8765` bilgisayardaki Hub'a çıkar.
3. Gerçek telefon için Hub'ı kimlik doğrulamalı bir tünelin arkasında aç ve adresi Ayarlar'a yaz. Korumasız internete açmak yasaktır (bkz. `docs/ARCHITECTURE.md`).

## Ekranlar

| Ekran | İçerik |
|---|---|
| Ajanlar | `GET /agents`: çevrimiçi durumu, okunmamış / yanıtlanacak / yanıt bekleyen, aktif ve engelli görevler, son görülme, son commit. `claude1`/`user` için **Acil durdur**, `user` için **Devam ettir**. |
| Sohbet | `GET /feed`: ortak akış (yeniden eskiye). Bir mesaja uzun basınca o konuşmaya filtrelenir. **Mesaj yaz** (`POST /messages`): alıcı, tür, öncelik, konu, içerik, yanıt gerekli. |
| Görevler | `GET /tasks`: duruma göre gruplu. Kabul et, durum değiştir. `claude1`/`user` için **Görev ver** (`POST /tasks`). |
| Onaylar | Backend (`:8800`) `GET /exec/approvals`: bekleyen onaylar (ham eylem, sınıf, isteyen, kalan süre, SHA-256), son kararlar, denetim kaydı, yürütme durumu. **Onayla / Reddet** (`POST /exec/approvals/{id}/approve\|deny`), **Yürütmeyi durdur / Devam ettir**. Sekme simgesinde bekleyen sayısı. |
| Ayarlar | Hub ve Backend adresi/tokenı. Tokenlar Android Keystore'da (`flutter_secure_storage`), adresler `shared_preferences`'ta saklanır. |

Veri 5 saniyede bir ve aşağı çekince yenilenir.

## Yapı

```
lib/main.dart            giriş
lib/app.dart             MaterialApp + alt gezinme
lib/app_state.dart       durum, yoklama, Hub işlemleri (ChangeNotifier)
lib/models.dart          Agent, FeedMessage, HubTask
lib/settings.dart        adres/token saklama (cihaz + bellek)
lib/api/hub_client.dart  Hub HTTP istemcisi, HubException
lib/screens/             agents, chat, tasks, settings
test/                    model, istemci (MockClient) ve widget testleri
```

## Güvenlik

- Token kaynak koda gömülmez, URL'ye konmaz, loglanmaz; güvenli depoda tutulur.
- Hub'dan gelen tüm metin (ajan mesajları, görev başlıkları) güvenilmeyen girdidir ve yalnızca `Text` ile gösterilir.
- Yetki kararını Hub verir (token, işlemi yapan ajanı belirler); uygulama yalnızca düğmeleri gizler.
- **Onay tokenı** (backend penceresinde yazan kullanıcı tokenı) hiçbir yere kaydedilmez: yalnızca bellekte tutulur, 5 dk işlem yapılmazsa, uygulama arka plana geçince veya **Sil**'e basılınca unutulur. Ayarlardaki Backend tokenı (ajan) yalnızca listelemek içindir; onaylamayı Backend yalnızca kullanıcı tokenına izin verir, ajan tokenı 403 alır ve uygulama bunu açıkça gösterir.
- Onay penceresinde ham eylem (JSON) gösterilir; ajanın/backend'in risk metni yardımcıdır, karar ham eyleme göre verilir.
- Denenmedi: gerçek cihazda Backend'e bağlanma (yalnızca birim/widget testleri ve CI; Flutter SDK geliştirme ortamında yoktu).
