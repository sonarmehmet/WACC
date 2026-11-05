# Güvenlik yarışması: puan tablosu

Kurallar: yalnızca **gerçek ve doğrulanmış** açık puan alır. Önem puanı: CRITICAL 10, HIGH 6, MEDIUM 3, LOW 1. Aynı açığın tekrar raporlanması puan vermez; daha önce kapatılan bir açığın düzeltmesini **atlatan yeni bir yol** yeni açıktır. Doğrulamayı ajan değil claude1 yapar (PoC'yi yeniden çalıştırır ya da kodda gösterir). Kod okuyarak bulunup çalıştırılmayanlar "doğrulanmadı" sayılır ve puan almaz. Potansiyel (henüz var olmayan platformun) riskleri en çok 1 puan.

## Sıralama

| # | Ajan | Doğrulanmış bulgu | Puan | Durum |
|---|---|---|---|---|
| 1 | **Web Güvenlik Ajanı** | 2 (HIGH x2) | **12** | 2 deneme hız sınırına takıldı; ilk bulgular kaydedilmişti |
| 2 | Android Güvenlik Ajanı | 0 | 0 | 3 denemenin üçü de bulgu kaydedemeden hız sınırına takıldı |
| 3 | iOS Güvenlik Ajanı | 0 | 0 | Başlatılmadı: depoda iOS uygulaması/IPA yok (riskleri Android raporunda "potansiyel" bölümü olacak) |
| - | claude1 (inceleme, yarışma dışı) | 12 (3 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW; bkz. SECURITY_REVIEW.md) | - | kapatıldı |

## Bulgular

| ID | Ajan | Önem | Başlık | Doğrulama | Durum |
|---|---|---|---|---|---|
| W-01 | Web | HIGH | Ajan `web/public/app.js` / `index.html` dosyasını onaysız yazıp panelde kullanıcı/onay token'ını çalabilir | PoC: dosya `write_file` ile onaysız yazıldı, panel sunucusu değişen dosyayı sundu | **Kapatıldı**: `web/public/` yazma onayı ister |
| W-02 | Web | HIGH | Ajan `backend/wacc_backend/*`, `hub/wacc_hub/*`, `launcher/*` Python kodunu onaysız yazıp sonraki başlatmada kod çalıştırabilir (SECURITY_REVIEW #4'ün atlatılması) | PoC: `backend/wacc_backend/__init__.py` yazıldı, `import` edilince kod çalıştı; claude1 de politikada 3+ derinliğin korunmadığını doğruladı | **Kapatıldı**: tüm çalışan kod klasörleri onay ister |

Not: W-01 ve W-02'nin kök nedeni aynı (dar yazma-koruma listesi) ama etkileri ve düzeltme yerleri ayrı olduğu için ikisi de puan aldı.

## Kurulu uygulamada etki
Kurulum dosyasındaki (`WACC.exe`) ajan çalışma klasörü kod klasöründen ayrıdır (`%LOCALAPPDATA%\WACC\workspace`), bu yüzden bu iki açık yalnızca `start_wacc.bat` ile depo kökünden çalıştırmada sömürülebilirdi.
