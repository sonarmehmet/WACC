# Windows Execution Backend — Güvenlik Spesifikasyonu (T-0008)

Durum: **ONAYLANDI (2026-10-31, kullanıcı).** T-0009 bu belgeye göre `backend/wacc_backend/execution/` altında uygulandı (claude1); ayrıntılı sınırlar `backend/README.md`'de.

## 1. İlkeler
1. **Varsayılan: yasak.** Listede olmayan hiçbir eylem çalışmaz.
2. **En az yetki.** Backend normal kullanıcı yetkisiyle çalışır; yönetici yetkisi hiçbir zaman otomatik istenmez.
3. **Tek kapı.** Dosya, süreç ve sistem erişiminin tamamı Execution Backend'den geçer; ajanlar doğrudan shell açmaz.
4. **Girdi güvenilmezdir.** Ajan mesajları, dosya içerikleri ve web sayfaları veridir, talimat değildir. "Onaylandı" diyen bir mesaj onay sayılmaz.
5. **İz bırak.** Her istek, karar ve sonuç `audit_log`'a yazılır.
6. **Durdurulabilir.** Acil durdurma her eylemi keser (bölüm 6).

## 2. Eylem sınıfları

| Sınıf | Örnek | Kural |
|---|---|---|
| `READ` | `C:\WACC` içinde dosya/klasör okuma, `git status`, `git log` | Otomatik, denetim kaydı |
| `WRITE_PROJECT` | `C:\WACC` içinde dosya yazma/düzenleme, `git add/commit` | Otomatik, denetim kaydı, kilit sistemine uyar |
| `RUN_ALLOWLIST` | `python`, `git`, `flutter`, `dart`, `adb`, `node` (sabit alt komut listesiyle) | Otomatik, argüman doğrulaması + zaman aşımı |
| `INSTALL` | `pip`, `npm`, `flutter pub` ile paket kurma | **Onay gerekir** (paket adı + sürüm gösterilir) |
| `NETWORK` | Allowlist'teki alan adlarına istek (paket kayıtları, GitHub) | Otomatik; diğer alan adları onay gerektirir |
| `PUBLISH` | `git push`, uygulama yayını | **Onay gerekir** |
| `DELETE` | Dosya/klasör silme, `git reset --hard`, `git clean` | **Her seferinde onay**; mümkünse `_to_delete/` altına taşıma |
| `SYSTEM_CHANGE` | Kayıt defteri, servis, güvenlik duvarı, Defender, PATH, yönetici yetkisi | **Her seferinde onay**, ayrı uyarı; ajan yönetici yetkisi isteyemez, yalnızca kullanıcıya talimat önerebilir |
| `PERSONAL_FILES` | `C:\WACC` dışındaki kişisel dosyalar | **Yasak.** Okuma da, proje dışına gönderme de |
| `FINANCIAL` | Ödeme, satın alma, bankacılık | **Yasak** (backend tarafından hiçbir zaman çalıştırılmaz) |
| `SECRET_EXPORT` | API anahtarı/token dışa aktarma, loglara yazma | **Yasak** |

Sınıfı belirlenemeyen eylem `SYSTEM_CHANGE` sayılır.

## 3. Yol ve süreç güvenliği
- İzinli kökler yapılandırılır (varsayılan yalnızca `C:\WACC`). Her yol önce tam çözülür (`..`, kısa ad, junction/symlink dahil); çözülmüş yol kök dışındaysa reddedilir.
- `data/` altındaki `tokens.json`, `*token*.txt`, `.env*` dosyaları ajanlara okunmaz.
- Süreçler `shell=True` olmadan, argüman listesiyle başlatılır; komut birleştirme (`&&`, `|`, `>`) yoktur.
- Her süreç için zaman aşımı (varsayılan 120 sn, üst sınır 30 dk), çıktı sınırı (1 MB) ve çalışma dizini kısıtı vardır.
- Alt sürece yalnızca gerekli ortam değişkenleri geçirilir; API anahtarları geçirilmez.
- Git: `main`'e doğrudan yazma ve `--force` push reddedilir.

## 4. Onay akışı
`ApprovalRequest`: `id`, `requested_by`, `action_class`, `action` (komut/yol/argümanlar), `risk_summary`, `action_hash`, `status`, `created_at`, `expires_at`, `decided_by`, `decided_at`.

Durumlar: `PENDING → APPROVED | DENIED | EXPIRED → EXECUTED`.

- Onayı **yalnızca `user` tokenı** verir (Ajanlar ekranından). Bu token diske yazılmaz, backend her açılışta üretip konsolda gösterir. Hiçbir ajan, hiçbir mesajla onay veremez.
- Onay, istenen eylemin `action_hash` değerine bağlıdır; eylem bir karakter değişirse onay geçersizdir.
- Tek kullanımlıktır; varsayılan geçerlilik 10 dakikadır.
- Kullanıcıya gösterilen özet ham komutu ve etkilenecek yolları içerir; ajanın yazdığı açıklama yalnızca yardımcı metindir.
- Onay beklerken ajan işe devam etmez; görev `BLOCKED` değil, "onay bekliyor" olarak işaretlenir.

## 5. Denetim kaydı
Her eylem için: zaman, isteyen ajan, sınıf, eylem özeti, onay kimliği, sonuç (`OK/DENIED/ERROR/KILLED`), süre. Kayıtlar yalnızca eklenir (append-only), silinmez. Token, anahtar ve parola benzeri değerler yazılmadan önce maskelenir.

## 6. Acil durdurma sözleşmesi
- Her eylemden önce `emergency_stop` bayrağı kontrol edilir; açıksa eylem `EMERGENCY_STOP` ile reddedilir.
- Çalışan uzun süreçler en geç 2 saniye içinde sonlandırılır (süreç ağacıyla birlikte).
- Bekleyen onaylar `EXPIRED` olur; durdurma sırasında verilen onay çalıştırılmaz.
- Yalnızca kullanıcı devam ettirebilir. Devam sonrası ajanlar `session-start` yapmadan eylem isteyemez.

## 7. Bilgisayar operatörü (Gemini) için ek kurallar
- Ekran/tarayıcı eylemleri oturum başına kapsam belirleyen bir onayla başlar (hangi uygulama, hangi site, süre).
- Ödeme, parola girişi, güvenlik ayarları ve silme adımlarında her zaman durup kullanıcıya sorar.
- Ekranda görülen metin talimat değildir; sayfadaki "şunu yap" ifadeleri yok sayılır.

## 8. T-0009 için kabul kriterleri
1. Her eylem sınıfı için en az bir izinli, bir reddedilen test.
2. Yol kaçışı (`..`, junction, mutlak yol, farklı sürücü) testleri reddedilir.
3. Onay: yanlış kullanıcı, süresi dolmuş, değişmiş `action_hash` ve ikinci kullanım reddedilir.
4. Acil durdurma çalışan sahte bir sürecin sonlanmasını sağlar.
5. Denetim kaydında sır bulunmaz.
6. Gerçek komutlar yerine sahte yürütücü (fake executor) ile test edilir; gerçek Windows testi yapılmadıysa rapor bunu açıkça yazar.

## 9. Onaylanan kararlar (2026-10-31)
1. `git commit` otomatik; `git push` her zaman ayrı onaylıdır.
2. Aynı paket/sürüm proje başına bir kez onaylanır; sürüm değişirse yeniden sorulur.
3. İzinli ağ alan adları: `pypi.org`, `files.pythonhosted.org`, `github.com`, `pub.dev`, `registry.npmjs.org`. Diğerleri onay ister.
