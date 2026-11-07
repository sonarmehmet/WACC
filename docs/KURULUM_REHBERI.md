# WACC Kurulum Rehberi (sıfırdan, tuş tuş)

Bu rehber Windows 10'da hiçbir şey kurulu değilken başlar ve WACC'ı çalıştırıp bir ajanı onaylatmaya kadar götürür. Her adımda **hangi tuşa ya da düğmeye basacağın** yazıyor. Kısaltılmış kullanım için `KULLANICI_KILAVUZU.md`, model bağlama için `LOCAL_LLM.md` dosyalarına bak.

> Dürüst not: Bu adımlar GitHub'daki otomatik testlerde (Windows dahil) doğrulandı. Senin bilgisayarında, gerçek bir modelle ve telefonla **henüz denenmedi**. Takıldığın yerde ekrandaki yazıyı olduğu gibi kopyalayıp bize ilet (en sonda "Bize ne yazacaksın" bölümü var).

İçindekiler: Kolay yol (WACC-Setup.exe) · 1 Ön hazırlık · 2 İndirme · 3 İlk başlatma · 4 Token'ları bulma · 5 Web panel · 6 Masaüstü uygulaması · 7 Onay verme · 8 Ajan ekleme · 9 Yapay zekâ hesabı / Ollama · 10 Durdurma, yedek, güncelleme · 11 Telefon · 12 Sorunlar · 13 Bize ne yazacaksın

---

## KOLAY YOL: tek dosya, çift tık (önerilen)

Python, Git, token, ayar: hiçbiri gerekmez.

1. Tarayıcıda şu adrese git: **https://github.com/sonarmehmet/WACC/releases/tag/latest**
2. **Assets** altındaki **WACC-Setup.exe** dosyasına tıkla, iner (yaklaşık 17 MB).
3. İnen **WACC-Setup.exe** dosyasına çift tıkla.
4. Windows mavi bir uyarı gösterebilir: **"Windows bilgisayarınızı korudu"**. Bunun sebebi kurulum dosyasının ücretli bir yazılım sertifikasıyla **imzalanmamış** olması; dosya bizim derlememiz. **Ek bilgi**'ye bas, sonra **Yine de çalıştır**'a bas.
5. Kurulum yönetici izni istemez. Sihirbazda **İleri**/**Kur**'a bas, en sonda **WACC'ı şimdi başlat** kutusu işaretli gelir, **Bitir**'e bas.
6. WACC penceresi açılır. **Token yazman gerekmez**, pencere kendiliğinden bağlanır. Masaüstünde ve Başlat menüsünde **WACC** simgesi oluşur; sonraki seferlerde ona çift tıkla.
7. Tarayıcıdaki panel için pencerenin üstündeki **Web panel** düğmesine bas (adres http://127.0.0.1:8780).

Bilmen gerekenler:
- Hub, Backend ve web paneli WACC.exe'nin içinde çalışır. Pencereyi kapatınca hepsi durur.
- Verilerin (veritabanı, token'lar, ajan çalışma klasörü) `%LOCALAPPDATA%\WACC` içinde durur. Kaldırırken silinmez. Dosya gezgininin adres çubuğuna `%LOCALAPPDATA%\WACC` yazıp Enter'a basarak açabilirsin.
- Yapay zekâ modeli bağlamak için pencerede **Yapay Zeka** sekmesi (bkz. bölüm 9). Onay token'ı pencerede hazır, yazman gerekmez. Pencere artık koyu "kontrol odası" görünümünde açılır (ortada radar, solda saat ve göstergeler, sağda sekmeler); bunun için bilgisayarında Microsoft Edge ya da Chrome olması yeter (Windows 10'da Edge hazır gelir). Kapatmak için pencereyi kapat ya da **UYGULAMAYI KAPAT** düğmesine bas. Tarayıcı bulunamazsa eski sade pencere açılır.
- Kaldırmak: Windows **Ayarlar → Uygulamalar → WACC → Kaldır**.
- "Port kullanımda" hatası görürsen WACC zaten açıktır (görev çubuğuna bak) ya da eski bir `start_wacc.bat` penceresi açıktır, kapat.
- Depo private yapılınca bu indirme adresi için GitHub'a giriş yapman gerekir.
- Bu kurulum GitHub'ın Windows sunucusunda derlenip kuruldu ve açılışı otomatik denendi; **senin makinende, gerçek bir ajan ve modelle henüz denenmedi**. Hata olursa ekrandaki yazıyı ve `%LOCALAPPDATA%\WACC\data\wacc.log` dosyasının son satırlarını bize yaz.

Aşağıdaki adımlar (1-12) kaynak koddan elle kurulum içindir; kurulum dosyasını kullanıyorsan gerekmez.

---

## 1. Ön hazırlık (bir kez)

### 1.1 Python kur
1. Tarayıcıdan **python.org/downloads** adresine git.
2. Sarı **Download Python 3.x.x** düğmesine bas (sürüm **3.11 veya üstü** olmalı).
3. İnen dosyaya çift tıkla.
4. Açılan ilk pencerenin **en altındaki** **Add python.exe to PATH** kutusunu **işaretle**. (Bunu unutursan WACC çalışmaz.)
5. **Install Now**'a bas. Windows "izin ver" diye sorarsa **Evet**.
6. "Setup was successful" yazınca **Close**.

Kontrol: **Windows tuşu**na bas, `cmd` yaz, **Enter**. Siyah pencerede şunu yaz ve **Enter**'a bas:

```
python --version
```
`Python 3.11...` ya da daha yüksek bir sürüm görmelisin. "bulunamadı" yazıyorsa Python'u PATH kutusunu işaretleyerek yeniden kur, cmd'yi kapatıp yeniden aç.

### 1.2 Git kur
1. **git-scm.com** adresine git, **Download for Windows**'a bas.
2. İnen dosyayı aç, **Evet** de, sonra tüm pencerelerde **Next**'e basarak ilerle (varsayılanlar doğru), en sonda **Install**, sonra **Finish**.

Kontrol: yeni bir cmd penceresi aç, `git --version` yaz, **Enter**. Bir sürüm numarası görmelisin.

> Zip olarak indirme! GitHub'ın "Download ZIP" düğmesi `.bat` dosyalarının satır sonlarını bozar, WACC açılıp hemen kapanır. Mutlaka `git clone` kullan.

### 1.3 (İsteğe bağlı) Ortam kontrolü
cmd'ye (klonladıktan sonra, bkz. 2) şunu yaz:
```
powershell -ExecutionPolicy Bypass -File C:\WACC\scripts\check_env.ps1
```
Python, Git, RAM ve ekran kartı bilgisini gösterir (model seçerken işine yarar).

---

## 2. WACC'ı indir

1. **Windows tuşu**, `cmd`, **Enter**.
2. Şunu yaz, **Enter**:
   ```
   git clone https://github.com/sonarmehmet/WACC.git C:\WACC
   ```
3. Bitince `C:\WACC` klasörü oluşur. (Depo private yapıldıktan sonra GitHub giriş penceresi çıkarsa hesabınla giriş yap.)

Daha sonra güncellemek için: cmd'de `cd C:\WACC` **Enter**, `git pull` **Enter**.

---

## 3. İlk başlatma

1. Dosya Gezgini'ni aç (**Windows tuşu + E**), adres çubuğuna `C:\WACC` yaz, **Enter**.
2. **start_wacc.bat** dosyasına **çift tıkla**.
3. Siyah bir pencere açılır. **İlk seferde birkaç dakika sürer**: sanal ortam kurar ve paketleri indirir. Pencereyi **kapatma**, bekle. İnternet bağlı olmalı.
4. Windows Güvenlik Duvarı "izin ver" diye sorarsa **İptal** (Cancel) de. WACC yalnızca bu bilgisayarda çalışır, dışarıya açılması gerekmez.
5. Bittiğinde **üç ayrı pencere** olur:

   | Pencere başlığı | Ne yapar | Adres |
   |---|---|---|
   | WACC Launcher (ana) | Hub: ajan mesajları, görevler, kilitler | http://127.0.0.1:8765 |
   | WACC Backend | İş kuyruğu, AI modelleri, onaylı komut yürütme | http://127.0.0.1:8800 |
   | WACC Panel | Tarayıcıdan izleme ve onay | http://127.0.0.1:8780 |

6. **Backend penceresine bak.** Orada uzun rastgele bir yazı (**ONAY TOKEN'I**) görünür. Bu senin onay şifrendir.
   - Kimseyle ve hiçbir ajanla paylaşma, ekran görüntüsüne alma.
   - Backend her açıldığında **yeni** bir tane yazar. Dosyaya kaydedilmez. İhtiyacın olunca bu pencereden kopyalarsın (pencerede metni seçip **Enter** ile kopyalanır; ya da sağ tık). Pencere kapandıysa `start_wacc.bat`'ı yeniden çalıştır, yeni token yazılır.
7. **Üç pencereyi de açık bırak.** Kapatırsan o parça durur.

### Çalıştığını doğrula
Sistem açıkken `C:\WACC\smoke_wacc.bat` dosyasına çift tıkla. Sonda "10/10" ya da hepsi PASS görmelisin. FAIL varsa ekranı bize ilet.

---

## 4. Token'larını bul

WACC'ta birkaç ayrı şifre var. Karıştırma:

| İsim | Nerede | Ne için |
|---|---|---|
| **Hub kullanıcı token'ı** | `C:\WACC\data\tokens.json` içinde `"user"` satırı | Web panele/uygulamaya giriş, Hub işleri |
| **Onay token'ı** | Backend penceresi | Onaylama, reddetme, acil durdurmayı kaldırma, AI hesabı ekleme |
| Backend ortak okuma token'ı | `C:\WACC\data\backend_token.txt` | Panellerin backend'i okuması; **eylem gönderemez** |
| Ajan token'ları | `data\tokens.json` ve `data\backend_tokens.json` | Ajanlar kendi adlarıyla bağlanır |

`tokens.json`'u açmak için: Dosya Gezgini'nde `C:\WACC\data` klasörüne git, `tokens.json`'a **sağ tık → Birlikte aç → Not Defteri**. `"user":` yanındaki tırnak içindeki yazıyı (tırnaklar hariç) seç, **Ctrl+C** ile kopyala.

`data` klasörü GitHub'a gönderilmez. Token'ları sohbete, e-postaya ya da ekran görüntüsüne koyma.

---

## 5. Web panel

1. Tarayıcıda **http://127.0.0.1:8780** adresine git.
2. Üstteki **X-WACC-Token** alanına **Hub kullanıcı token'ını** (`tokens.json` içindeki `user`) yapıştır (**Ctrl+V**), **Bağlan**'a bas. Ajanlar, Akış, Görevler ve Kilitler dolar.
3. **Hatırla** kutusunu işaretlemezsen sekme kapanınca token silinir (daha güvenli). **Unut** düğmesi panelin tuttuğu tüm token'ları siler.
4. **Backend** sekmesi: **Backend token** alanına `data\backend_token.txt` dosyasının içindeki yazıyı yapıştır, **Bağlan**'a bas (yalnızca görüntüleme).
5. **Onaylar** sekmesi: **Onay token'ı (kullanıcı)** alanına Backend penceresindeki token'ı yapıştır, **Kullan**'a bas. Token yalnızca bellekte tutulur, alandan hemen silinir; 5 dakika işlem yapmazsan ya da sayfayı yenilersen unutulur. **Sil** düğmesi hemen unutturur. Bu token olmadan onayları yalnızca görürsün.
6. **Yapay Zeka** sekmesi aynı onay token'ını kullanır (alanına yapıştırıp **Kullan**).
7. Yeni onay isteğinde bildirim istersen **Yeni onayda bildirim göster** düğmesine bas ve tarayıcının izin sorusuna **İzin ver** de.

---

## 6. Masaüstü uygulaması

1. `C:\WACC\run_desktop.bat` dosyasına çift tıkla.
2. Üstteki üç alana sırayla yaz: **Hub token** (`tokens.json` içindeki `user`), **Backend token** (`backend_token.txt`) ve **Onay token'ı** (Backend penceresindeki). **Bağlan**'a bas. Ajan ekleme/silme ve AI hesabı değiştirme için Hub token'ı olarak **kullanıcı** token'ını girmiş olmalısın.
3. Token'lar diske yazılmaz, program kapanınca silinir.
4. Sekmeler: **Ajanlar**, **Akış**, **Görevler**, **Onaylar**, **Yapay Zeka** vb.

---

## 7. Bir ajan riskli iş isterse: onay verme

Paket kurma, dosya silme, test/derleme çalıştırma gibi işler otomatik çalışmaz.

1. Web panelde ya da masaüstünde **Onaylar** sekmesini aç.
2. Bekleyen bir istek görürsün: **ham komut**, sınıf, isteyen ajan, kalan süre, SHA-256.
3. **Komutun tamamını dikkatle oku.** Anlamadığın ya da beklemediğin bir şey varsa **Reddet**.
4. Doğruysa **Onayla**'ya bas. (Onay token'ı alanı doluysa çalışır; yoksa 403 alırsın.)
5. Onay **yalnızca o tek eylem** içindir ve **10 dakika** sonra düşer.

---

## 8. Ajan ekleme / çıkarma

**Masaüstü:** **Ajanlar** sekmesi → **Ajan ekle** → ad (küçük harf, rakam, `-` veya `_`, harfle başlar, 2-20 karakter), tür (Claude/Gemini/ChatGPT/Diğer), isteğe bağlı rol, isteğe bağlı bağlı AI hesabı → **Ekle**.
**Web panel:** Ajanlar sekmesinde **Ajan ekle** formu (Hub kullanıcı token'ı ile girmişsen görünür).
**Telefon:** Ajanlar ekranında **Ajan ekle** (kullanıcı token'ı ile).

- Açılan pencerede yeni ajanın **token'ı bir kez** gösterilir. **Hemen kopyala ve sakla**; bir daha gösterilmez.
- **Kapat/Aç:** ajan reddedilir/geri alınır. **Sil:** token iptal olur, görevleri BACKLOG'a döner, geçmiş kalır. claude1-3 ve gemini silinmez, yalnızca kapatılır.

**Önemli sınır:** ChatGPT veya Gemini'nin **web sohbetleri** senin bilgisayarındaki 127.0.0.1 adresine ulaşamaz, token verilse bile bağlanamazlar. Çalışan yol: bir **API hesabı** (bkz. 9) ekleyip ajana bağlamak. Token'ı bulut ajana vermeden önce iki kez düşün.

---

## 9. Yapay zekâ hesabı ve yerel model (Ollama)

### 9.1 Ollama ile yerel model
1. **ollama.com** → **Download** → Windows. Kur (hep **Next/Install**).
2. cmd aç, bir model indir (bilgisayarına göre küçük/büyük):
   ```
   ollama pull qwen2.5-coder:7b
   ```
   Bitince `ollama list` ile model adını gör.
3. Not Defteri'ni aç, şunu yapıştır, **Dosya → Farklı Kaydet** → Dosya adı: `C:\WACC\data\llm.env`, **Kayıt türü: Tüm dosyalar** (yoksa `.txt` eklenir):
   ```
   WACC_LOCAL_LLM_URL=http://127.0.0.1:11434/v1
   WACC_LOCAL_LLM_MODEL=qwen2.5-coder:7b
   ```
4. `C:\WACC\check_llm.bat` dosyasına çift tıkla. `PASS` görmelisin (FAIL ise Ollama çalışıyor mu, model adı doğru mu kontrol et).
5. WACC'ı kapatıp `start_wacc.bat` ile yeniden başlat.

### 9.2 Pencereden hesap ekleme (yeniden başlatmadan)
**En kolay yol (Grok, ChatGPT, Claude, OpenRouter, Ollama):** pencerenin sağındaki **Ajanlar** sekmesinin en üstünde **"Yapay zekâ ekle (tek adım)"** kutusu var.
1. **Sağlayıcı** listesinden seç (örn. *Grok (xAI)*). Ajan adı ve model kendiliğinden dolar.
2. **API anahtarı** kutusuna anahtarı yapıştır. Anahtarı sağlayıcının sitesinden alırsın: Grok → console.x.ai, ChatGPT → platform.openai.com, Claude → console.anthropic.com. Ollama (bu bilgisayarda çalışan model) için anahtar gerekmez.
3. **Ekle**'ye bas. WACC hesabı açar, ajanı ekler ve bir deneme çağrısı yapar; kutunun altında "Çalışıyor" ya da nedenini yazar. Model adı eskimişse kutudaki **Model** alanını sağlayıcının güncel adıyla değiştirip tekrar dene.

Anahtar yalnızca bu bilgisayarda saklanır, bir daha gösterilmez. Elle ayrıntılı ayar istersen **Yapay Zeka** sekmesi (masaüstü, web ya da telefon) → **Hesap ekle**: ad, tür (yerel/bulut), OpenAI uyumlu adres, model, API anahtarı (yerel için boş) → **Ekle** → **Test et**.

**Sesli ve yazılı komut:** ortadaki radarın altında bir komut kutusu ve iki düğme var. **SESLİ KOMUT** tek seferlik dinler, **SÜREKLİ DİNLE** açıkken "WACC" diye başlayan komutlara cevap verir. İlk basışta pencere mikrofon izni ister, **İzin ver** de. Ses tanıma Edge/Chrome'un kendi servisini kullanır, internet gerekir; internet yoksa kutuya yazarak aynı komutları verirsin. Örnekler: *durum*, *onaylar*, *görevler*, *görev ekle kurulum rehberini düzelt*, *claude1'e söyle testleri çalıştır*, *grok ekle*, *acil durdur*, *yardım*. Güvenlik için ses yalnızca gezinir, durumu okur, formları doldurur ve **acil durdurur**; **onay, ret ve devam ettirme her zaman senin tıklaman** ister (ortamdaki bir ses yanlış komut vermesin diye).
- Bulut adresleri yalnızca **https** olabilir, yerel adresler yalnızca bu bilgisayar (127.0.0.1) olabilir.
- API anahtarı kaydedilir ama **bir daha gösterilmez**. Test bulut hesabında gerçek bir istek atar ve günlük bütçeye sayılır.
- OpenAI uyumlu her servis olur (Ollama, LM Studio, OpenRouter, OpenAI...).

---

## 10. Durdurma, devam, yedek, güncelleme

| İş | Ne yapacaksın |
|---|---|
| **Acil durdur** | `C:\WACC\stop_wacc.bat`'a çift tıkla (ya da panelde **ACİL DURDUR**). Ajanlar yeni iş almaz, komut çalıştırma durur. |
| **Devam ettir** | `resume_wacc.bat` ya da panelde **Devam ettir** (onay token'ı ister). Durdurmayı yalnızca sen kaldırabilirsin. |
| **Yedek al** | `backup_wacc.bat` → veritabanları ve kod paketi `backups\` klasörüne. Önemli değişiklikten önce çalıştır. |
| **Geri yükle** | Önce **tüm WACC pencerelerini kapat**. cmd'de `cd C:\WACC` sonra `restore_wacc.bat hub_YYYYMMDD_HHMMSS.db` (ya da `backend_...db`; dosya adı `backups\` içinde). Eski veritabanı `data\pre-restore-...` olarak saklanır. Servisler açıksa reddeder. |
| **Güncelle** | Pencereleri kapat, cmd: `cd C:\WACC` → `git pull` → `start_wacc.bat`. |
| **Tamamen kapat** | Üç pencereyi de kapat. |

---

## 11. Telefon (isteğe bağlı, denenmedi)

Hub ve Backend yalnızca bu bilgisayarın içinde dinler, telefon doğrudan bağlanamaz. Telefon için güvenli köprü (Tailscale ya da kimlik doğrulamalı Cloudflare Tunnel) gerekir; ayrıntı ve APK derleme adımları `mobile/README.md` içinde. Korumasız internete açmak **yasaktır**. Emin değilsen telefon adımını atla; masaüstü ve web panel yeterlidir.

---

## 12. Sık karşılaşılan sorunlar

| Belirti | Çözüm |
|---|---|
| `.bat` açılıp hemen kapanıyor | Zip'ten çıkardın. `C:\WACC`'ı sil, `git clone` ile yeniden indir. |
| "Python bulunamadı" | Python'u **Add python.exe to PATH** işaretleyerek kur, cmd'yi yeniden aç. |
| Paket indirme hatası | İnternet bağlantısını kontrol et, `start_wacc.bat`'ı yeniden çalıştır. |
| Tarayıcıda 401 / "Invalid or missing token" | Yanlış token. `data\tokens.json`'dan `user` değerini kopyala. |
| Onayla'da 403 | Ajan token'ı kullanılmış. Onay yalnızca **onay token'ı** ile olur. |
| "Port zaten kullanımda" | Eski WACC penceresi açık. Hepsini kapat, yeniden başlat. |
| Backend token'ı her açılışta değişiyor | Normal ve istenen. |
| Hiçbir ajan iş yapmıyor | Acil durdurma açık olabilir: `resume_wacc.bat`. |
| `check_llm.bat` FAIL | Ollama açık mı (`ollama list`), `data\llm.env` adresi ve model adı doğru mu, dosya `.txt` olarak mı kaydedilmiş? |
| Web panel boş / "Backend'e ulaşılamıyor" | Backend penceresi kapanmış ya da hata vermiş. Pencereyi kontrol et, `start_wacc.bat`'ı yeniden çalıştır. |

---

## 13. Bize ne yazacaksın (ilk çalıştırma geri bildirimi, GitHub #12)

Bir şey ters giderse şunları yaz:
1. Hangi adımda (numarasıyla) takıldın?
2. Ekrandaki **hata yazısını olduğu gibi** kopyala (token'ları **silerek**!).
3. `python --version` ve `git --version` çıktısı.
4. Son pencere görüntüsü (token görünüyorsa kapat/sansürle).

Her şey yolunda gittiyse de "smoke_wacc.bat 10/10 geçti" diye haber ver: bu, gerçek makinede ilk doğrulama olur.

## Son: repoyu private yap (GitHub #14, en sonda)

Her şey çalışınca GitHub'da depoya git → **Settings** → en altta **Danger Zone** → **Change repository visibility** → **Make private**. Bundan sonra `git clone`/`git pull` için GitHub hesabınla giriş yapman gerekir.
