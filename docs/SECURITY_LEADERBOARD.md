# Güvenlik yarışması: puan tablosu

Kurallar: yalnızca **gerçek ve doğrulanmış** açık puan alır. Önem puanı: CRITICAL 10, HIGH 6, MEDIUM 3, LOW 1. Aynı açığın tekrar raporlanması puan vermez; daha önce kapatılan bir açığın düzeltmesini **atlatan yeni bir yol** yeni açıktır. Doğrulamayı ajan değil claude1 yapar (PoC'yi yeniden çalıştırır ya da kodda gösterir). Kod okuyarak bulunup çalıştırılmayanlar "doğrulanmadı" sayılır ve puan almaz. Potansiyel (henüz var olmayan platformun) riskleri en çok 1 puan.

## Sıralama

| # | Ajan | Doğrulanmış bulgu | Puan | Durum |
|---|---|---|---|---|
| 1 | **Android Güvenlik Ajanı** | 5 (1 HIGH, 2 MEDIUM, 2 LOW) | **14** | tek başına çalıştırınca bitirdi; A-06..A-08 doğrulanamadığı için puansız |
| 2 | **Web Güvenlik Ajanı** | 2 (2 HIGH) | **12** | hız sınırında kesildi; kesilmeden önce kaydettiği 2 bulgu sayıldı |
| 3 | iOS Güvenlik Ajanı | 0 | 0 | Başlatılmadı (iOS uygulaması yok); riskleri Android raporunda "potansiyel" yazıldı |
| - | claude1 (inceleme, yarışma dışı) | 12 (3 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW; bkz. SECURITY_REVIEW.md) | - | kapatıldı |

## Bulgular

| ID | Ajan | Önem | Başlık | Doğrulama | Durum |
|---|---|---|---|---|---|
| W-01 | Web | HIGH | Ajan `web/public/app.js` / `index.html` dosyasını onaysız yazıp panelde kullanıcı/onay token'ını çalabilir | PoC: dosya `write_file` ile onaysız yazıldı, panel sunucusu değişen dosyayı sundu | **Kapatıldı**: `web/public/` yazma onayı ister |
| W-02 | Web | HIGH | Ajan `backend/wacc_backend/*`, `hub/wacc_hub/*`, `launcher/*` Python kodunu onaysız yazıp sonraki başlatmada kod çalıştırabilir (SECURITY_REVIEW #4'ün atlatılması) | PoC: `backend/wacc_backend/__init__.py` yazıldı, `import` edilince kod çalıştı; claude1 de politikada 3+ derinliğin korunmadığını doğruladı | **Kapatıldı**: tüm çalışan kod klasörleri onay ister |

| A-01 | Android | HIGH | Onay ekranı ham eylemi 4000 karakterde uyarısız kırpıyor; ajan komutun tehlikeli kuyruğunu gizleyebilir | Çalıştırıldı: eylem 4132 karakter, ilk 4001'de payload yok; claude1 backend'in uzun eylemi APPROVAL'a aldığını doğruladı | **Kapatıldı**: backend 3500 karakterden uzun eylemi reddeder, uygulama kırpmaz |
| A-02 | Android | MEDIUM | Görünmez/yön değiştiren (U+202E, U+200B) ve Kiril benzeri karakterler onay ekranında olduğu gibi görünüyor | claude1 yeniden çalıştırdı: üçü de APPROVAL ile geçti | **Kapatıldı**: backend reddeder; uygulama bu karakterleri `\u{kod}` gösterir |
| A-03 | Android | MEDIUM | `write_file` onayında içerik görünmüyor (yalnız yol/hash) | claude1 yeniden çalıştırdı | **Kapatıldı**: onay özetinde içeriğin ilk 300 karakteri |
| A-04 | Android | LOW (ajan MEDIUM dedi; token Keystore'da kaldığından düşürüldü) | `allowBackup` kapatılmamış | Sahte android/ yapısında çalıştırıldı | **Kapatıldı**: `prepare_android.py` `allowBackup=false` ekler |
| A-05 | Android | LOW | `pubspec.lock` yok, CI sürümleri her seferinde yeniden çözüyor; action'lar SHA'ya sabit değil | Dosya yok | Açık: `pubspec.lock` Flutter SDK gerektirir, yerelde üretilemedi |
| A-06..08 | Android | LOW | http adres uyarısı yok; token türü kontrolü yok; imzalama/obfuscation | Statik, doğrulanmadı | Puan yok (doğrulanmadı) |

Not: W-01 ve W-02'nin kök nedeni aynı (dar yazma-koruma listesi) ama etkileri ve düzeltme yerleri ayrı olduğu için ikisi de puan aldı.

## Kurulu uygulamada etki
Kurulum dosyasındaki (`WACC.exe`) ajan çalışma klasörü kod klasöründen ayrıdır (`%LOCALAPPDATA%\WACC\workspace`), bu yüzden bu iki açık yalnızca `start_wacc.bat` ile depo kökünden çalıştırmada sömürülebilirdi.
