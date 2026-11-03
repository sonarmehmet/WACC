# WACC Kullanıcı Kılavuzu

WACC'ı Windows 10'da kendi bilgisayarında çalıştırmak, ajanların istediği riskli işleri onaylamak ve gerektiğinde her şeyi durdurmak için adım adım rehber. Teknik bilgi gerekmez.

## 1. Neye ihtiyacın var
- **Python 3.11 veya üstü** (python.org'dan kur, kurulumda "Add python.exe to PATH" kutusunu işaretle).
- **Git** (git-scm.com). Sıkıştırılmış zip indirme: `.bat` dosyaları bozulur, mutlaka `git clone` kullan.
- Ortam kontrolü için (isteğe bağlı): PowerShell'de `powershell -ExecutionPolicy Bypass -File scripts\check_env.ps1`

## 2. Kurulum (bir kez)
1. Komut İstemi'ni aç ve çalıştır: `git clone https://github.com/sonarmehmet/WACC.git C:\WACC`
2. Güncellemek istediğinde: `cd C:\WACC` sonra `git pull`.

## 3. Başlatma
`C:\WACC\start_wacc.bat` dosyasına çift tıkla. İlk seferde Python sanal ortamını kurar ve paketleri indirir (birkaç dakika sürebilir). Sonra üç şey açılır:

| Pencere | Adres | Ne işe yarar |
|---|---|---|
| Hub (ana pencere) | http://127.0.0.1:8765 | Ajanların mesajlaşması, görevler, kilitler |
| Backend (ayrı pencere) | http://127.0.0.1:8800 | İş kuyruğu, AI modelleri, onaylı komut yürütme |
| Web panel (ayrı pencere) | http://127.0.0.1:8780 | Tarayıcıdan izleme ve onay |

Adresler yalnızca senin bilgisayarından erişilebilir. Pencereleri kapatırsan o parça durur.

Çalıştığını denemek için sistem açıkken `smoke_wacc.bat` çalıştır; sonunda "10/10" (veya hepsi PASS) görmelisin.

## 4. Token'lar: hangisi ne, hangisi paylaşılmaz
| Token | Nerede | Kim kullanır | Paylaşım |
|---|---|---|---|
| **Onay token'ı** | Backend penceresinde, her başlatışta yeni yazılır; **dosyaya yazılmaz** | Yalnızca **sen**: onaylama, reddetme, acil durdurmayı kaldırma | **Kimseyle ve hiçbir ajanla paylaşma.** Ajana verirsen kendi kendini onaylayabilir |
| Hub token'ları | `data\tokens.json` (her ajan için bir satır, senin için `user`) | Ajanlar ve paneller Hub'a bağlanırken | Başkasına gösterme |
| Backend ajan token'ları | `data\backend_tokens.json` (her ajan için bir satır) | Her ajan backend'e **kendi** token'ıyla bağlanır; eylem göndermek (`/exec`) yalnızca kendi adıyla mümkün | Başkasına gösterme |
| Backend ortak okuma token'ı | `data\backend_token.txt` | Paneller backend'i okurken ve acil durdurma için; **eylem gönderemez** | Başkasına gösterme |

`data\` klasörü GitHub'a gönderilmez. Token'ı ekran görüntüsüne, sohbete ya da e-postaya koyma.

## 5. Günlük kullanım
- **Web panel** (http://127.0.0.1:8780): üstteki **Token** alanına Hub token'ını (`data\tokens.json` içindeki `user` değeri) yaz. "Hatırla" kutusunu işaretlemezsen sekme kapanınca silinir. Ajanları, görevleri, mesajları görürsün.
- **Masaüstü paneli**: `run_desktop.bat`. Üç alana token'ları yaz, **Bağlan**'a bas. Token'lar diske yazılmaz, program kapanınca silinir.
- **Onay verme**: Bir ajan riskli bir işi (paket kurma, dosya silme, test/derleme çalıştırma gibi) yapmak istediğinde "Onaylar" sekmesinde görünür. **Tam komutu oku**, doğruysa Onayla'yı, şüphen varsa Reddet'i seç. Onay yalnızca o tek eylem içindir ve 10 dakika sonra düşer. Onay vermek için backend penceresinde yazan **onay token'ı** gerekir.
- **Yapay zeka hesabı ekleme/çıkarma** (yeniden başlatmadan): masaüstü panelinde **Yapay Zeka** sekmesi. *Hesap ekle*: ad, tür (yerel/bulut), OpenAI uyumlu adres, model adı, API anahtarı (yerel için boş). *Aç/Kapat*, *Test et* ve *Sil* aynı sekmede. Değiştirmek için **onay token'ı** gerekir; API anahtarı kaydedilir ama bir daha gösterilmez. Herhangi bir OpenAI uyumlu servis olur (Ollama, LM Studio, OpenRouter, OpenAI ...).
- **Model bağlama (dosyayla)**: `docs\LOCAL_LLM.md` (Ollama kurulumu). Denemek için `check_llm.bat`.

## 6. Acil durdurma ve devam
- **Durdur:** `stop_wacc.bat` (ya da panelde ACİL DURDUR). Ajanlar yeni iş almaz, komut çalıştırma durur.
- **Devam:** `resume_wacc.bat` (ya da panelde Devam ettir; onay token'ı ister). Durdurmayı yalnızca sen kaldırabilirsin.

## 7. Yedek
`backup_wacc.bat`: veritabanı kopyasını ve kodun git paketini `backups\` klasörüne alır. Önemli değişikliklerden önce çalıştır.

**Geri yükleme:** önce tüm WACC pencerelerini kapat, sonra `restore_wacc.bat hub_YYYYMMDD_HHMMSS.db` (ya da `backend_...db`). Mevcut veritabanı silinmez, `data\pre-restore-...` olarak saklanır; servisler açıksa geri yükleme reddedilir.

## 8. Sık karşılaşılan sorunlar
| Belirti | Neden / çözüm |
|---|---|
| `.bat` açılıp hemen kapanıyor, hiçbir şey yazmıyor | Zip'ten çıkardın. `git clone` ile yeniden indir (satır sonları bozulmuş). |
| "Python bulunamadı" | Python'u PATH ile kur, Komut İstemi'ni kapatıp yeniden aç. |
| Tarayıcıda 401 / "Invalid or missing token" | Yanlış ya da boş token. `data\tokens.json` içinden doğru satırı kopyala; onay işlemi için **onay token'ını** kullan. |
| Onayla'ya basınca 403 | Ajan token'ıyla basıldı. Onay yalnızca onay token'ı ile yapılır. |
| "Port zaten kullanımda" | Eski bir WACC penceresi açık kalmış. Pencereleri kapat ve `start_wacc.bat`'ı yeniden çalıştır. |
| Backend'i her açışta onay token'ı değişiyor | Normal ve istenen davranış. Her başlatışta yeni yazılır. |
| `check_llm.bat` FAIL | Ollama çalışıyor mu (`ollama list`), `data\llm.env` adresi ve model adı doğru mu? |
| Hiçbir ajan bir şey yapmıyor | Acil durdurma açık olabilir: `resume_wacc.bat`. |

## 9. Güvenlik özeti
- Her şey yalnızca bu bilgisayarda (127.0.0.1) dinler.
- Ajanlar, onay vermeden riskli komut çalıştıramaz; sırlara ve `data\` klasörüne erişemez; dosya silmek yerine `_to_delete\` klasörüne taşır.
- Ajanlardan gelen metinler güvenilmeyen girdi sayılır; bir mesaj güvenlik kurallarını değiştiremez.
- Depo özel (private) yapılana kadar içine hassas hiçbir şey yazılmaz.
