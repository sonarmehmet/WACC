# Güvenlik saldırı incelemesi (claude1, 2026-11-04)

Yöntem: uygulamaya "saldırgan ajan" gözüyle bakıldı. Bulgular yalnızca kodu okuyarak değil, **çalışan kodla gerçekten denenerek** doğrulandı (sahte kök dizin, gerçek `git`, sahte HTTP sunucuları). FastAPI yerel ortamda kurulamadığı için API katmanı kod okuyarak incelendi ve CI'daki testlerle doğrulandı. Her açık için regresyon testi var: `backend/tests/test_policy_attacks.py`.

## Düzeltilen bulgular

| # | Önem | Bulgu | Nasıl sömürülüyordu | Düzeltme |
|---|---|---|---|---|
| 1 | **Kritik** | İzinli `git` komutlarıyla sır okuma | `git add -f data` + `git diff --cached` ile `data/tokens.json` ve API anahtarları ajana okunuyordu (doğrudan okuma engelliydi, bu yol atlıyordu) | Zorlama bayrakları (`-f`, `-fA`, `--forc`...) onay ister; `REV:PATH`, `:0:PATH`, `:(top)PATH` biçimleri de yol denetiminden geçer |
| 2 | **Kritik** | Kök dışına dosya yazma | `git log --format=%B --output=C:\...\Startup\x.bat` ile ajanın seçtiği içerik herhangi bir yere yazılıyordu | `--output`, `--textconv`, `--ext-diff`, `-O` ve kısaltmaları reddedilir; `--seçenek=YOL` değerleri de yol denetiminden geçer |
| 3 | **Kritik** | Onaysız kod çalıştırma | `python -m compileall` otomatik izinliydi; `-m` ile çalışma klasörü arama yoluna girer, ajanın yazdığı `compileall.py` çalışıyordu | `compileall`, `flutter analyze`, `dart analyze` artık "proje kodu çalıştırır" sınıfında (onay ister) |
| 4 | Yüksek | Başlatma zincirine yazma | `start_wacc.bat`, `requirements.txt`, kökte `json.py`/`fastapi.py` gibi dosyalar onaysız yazılabiliyordu; sonraki başlatmada kod çalışırdı | Bu dosya türleri ve `scripts/`, `.github/`, güvenlik modülleri yazma onayı ister |
| 5 | Yüksek | Sağlayıcı API anahtarı sızıntısı | AI uç noktası 302 ile yönlendirirse `urllib` `Authorization` başlığını hedefe de gönderiyordu | Yönlendirmeler izlenmez |
| 6 | Orta | `POST /engine/resume` herkese açık | Herhangi bir ajan, kullanıcının durdurduğu iş kuyruğunu yeniden başlatabiliyordu | Yalnızca kullanıcı tokenı |
| 7 | Orta | `POST /agents` ile başkasının kaydını ezme | Ajan, başka ajanın rol/yeteneklerini değiştirebiliyordu | Ajan yalnızca kendini kaydedebilir |
| 8 | Orta | Onay kuyruğunu boğma | Bir ajan sınırsız farklı onay isteği açıp gerçek istekleri gömebilirdi | Ajan başına en fazla 20 bekleyen istek |
| 9 | Orta | "Daha önce onaylandı" kısayolu | `pip install .` / `-r dosya` bir kez onaylanınca, içerik değişse bile aynı komut onaysız çalışıyordu | Yalnızca düz paket adları (sürümlü) kısayoldan yararlanır |
| 10 | Düşük | Negatif `Content-Length` | Web proxy işleyici iş parçacığı çöküyordu | 400 döner |
| 11 | Orta | Gövde boyutu sınırı yok | Bir ajan tokeniyle tek istekte devasa karar/not/içerik yollayıp disk ve belleği doldurmak mümkündü (Hub ve Backend) | Hub 1 MB, Backend 4 MB üstü istek 413; parçalı (chunked) gövde kabul edilmez |
| 12 | Düşük | Sınırsız kilit | Bir ajan tüm klasörleri uzun süreli kilitleyip diğerlerini durdurabilirdi | Ajan başına en fazla 40 kilit |

## Denendi, açık bulunmadı
Geri yükleme (`restore`): `..`, mutlak yol, ters eğik çizgi, NUL, sürücü harfi, yeni satır ile yedek adı kaçırma. Web paneli: statik dosya yol geçişi (`..`, `%2e%2e`, ters eğik çizgi), DNS rebinding (`Host`), çapraz kaynak yazma (`Origin`), proxy yol enjeksiyonu (`@`, CRLF, sonda satır sonu, uzun kimlik), izin listesi dışı backend yolları, başlık enjeksiyonu.

## Bilinen kalan riskler (kabul edilen veya kullanıcı kararı)
- Token dosyaları `data\` içinde düz; aynı makinede ajanın kendi kabuğu varsa okuyabilir. Ajanlar yalnızca `/exec` üzerinden çalışmalı.
- `git add -A` gibi komutlar hâlâ otomatik; `data/` `.gitignore`'da olduğu sürece sızdırmaz. `.gitignore` yazmak onay ister.
- Glob içeren git yol belirteçleri (`d*/t*.json`) yalnızca zaten izlenen dosyaları gösterir; sırlar izlenmediği için pratikte etkisiz.
- Cloud AI adresi özel bir IP'ye (https) çevrilebilir (SSRF): yalnızca kullanıcı hesap ekleyebildiği için kabul edildi.
- Sahtecilik/yanıltma: onay ekranı komutu gösterir; Unicode benzeri karakterler gösterimi yanıltabilir (düşük).
- Gerçek makinede, gerçek ajanlarla ve gerçek modelle denenmedi.
