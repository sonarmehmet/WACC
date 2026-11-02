# WACC Backend

Owner: claude2 (T-0001..T-0003). T-0001 core was started by claude1 on branch `task/backend-core`.

## Run (Windows)

```
set PYTHONPATH=backend
.venv\Scripts\python -m wacc_backend
```
Listens on `127.0.0.1:8800`. Token: env `WACC_BACKEND_TOKEN`, or generated into `data/backend_token.txt` (git-ignored).

## Settings (env)
`WACC_BACKEND_HOST` (default 127.0.0.1), `WACC_BACKEND_PORT` (8800), `WACC_DATA_DIR`, `WACC_BACKEND_DB`, `WACC_BACKEND_TOKEN`.

## API
- `GET /health` (public)
- `GET/POST /projects`, `GET/PATCH /projects/{id}`, `POST /projects/{id}/archive` (header `X-WACC-Token`)

Projects are archived, never hard-deleted.

- Task Engine: `POST /jobs`, `GET /jobs`, `GET /jobs/summary`, `POST /jobs/claim`, `POST /jobs/{id}/complete|fail|cancel`, `POST /engine/pause|resume`
- Agent Manager: `GET/POST /agents`, `POST /agents/{name}/heartbeat`, `POST /agents/{name}/enabled`

Job akışı: QUEUED → RUNNING → SUCCEEDED / FAILED (başarısızlıkta üstel bekleme ile yeniden deneme, `max_attempts` sonrası FAILED) / CANCELLED. Engine yalnızca iş kuyruğudur; gerçek komut çalıştırma Execution Backend'in (T-0009) işidir.

- AI Orchestrator: `POST /ai/complete` (`prefer`: local/cloud/auto), `GET /ai/providers`, `GET /ai/usage`, `POST /ai/budget`
- Memory: `POST/GET /memory`, `GET /memory/search?q=`, `GET /memory/{id}`, `POST /memory/{id}/archive`

## AI sağlayıcıları (env, yalnızca açıkça ayarlanırsa etkin)
| Değişken | Anlamı |
|---|---|
| `WACC_ENABLE_MOCK=1` | Deneme için sahte sağlayıcı |
| `WACC_LOCAL_LLM_URL`, `WACC_LOCAL_LLM_MODEL` | Yerel model (Ollama/LM Studio, örn. `http://127.0.0.1:11434/v1`). Yalnızca localhost kabul edilir |
| `WACC_CLOUD_LLM_URL`, `WACC_CLOUD_LLM_KEY`, `WACC_CLOUD_LLM_MODEL`, `WACC_CLOUD_PRICE_IN_PER_1K`, `WACC_CLOUD_PRICE_OUT_PER_1K` | OpenAI uyumlu bulut uç noktası. Yalnızca https. Anahtar sadece env'den okunur, depoya/loga/veritabanına yazılmaz |

Yönlendirme: önce yerel (ücretsiz), başarısız olursa bulut. Bulut çağrıları günlük bütçeye (varsayılan 1.00 USD) takılır. Kullanım defteri yalnızca token ve maliyet tutar, istem/yanıt metni tutmaz.

Memory: gizli anahtar benzeri içerik reddedilir; kayıtlar silinmez, arşivlenir.

## Yürütme backend'i (T-0009) — `docs/EXECUTION_SECURITY.md`
Her makine eylemi tek kapıdan geçer: `POST /exec` → acil durdurma kontrolü → sınıflandırma → reddet / onay iste / çalıştır → denetim kaydı.

- Eylem türleri: `read_file`, `list_dir`, `write_file`, `delete_path` (silmez, `_to_delete/` altına taşır), `run` (`argv` listesi, shell yok), `http_get`.
- Sonuç durumları: `OK`, `ERROR`, `KILLED`, `DENIED`, `APPROVAL_REQUIRED` (+ `approval_id`).
- Onay: `GET /exec/approvals`, `POST /exec/approvals/{id}/approve|deny` **yalnızca kullanıcı token'ıyla**. Onay eylemin SHA-256'sına bağlıdır, tek kullanımlıktır, 10 dakikada dolar. Ajan onaydan sonra aynı eylemi `approval_id` ile tekrar gönderir.
- Kullanıcı token'ı **diske yazılmaz**: backend her açılışta yeni üretir ve yalnızca konsol penceresinde gösterir (ajanlar aynı bilgisayarda çalıştığı için dosyadan okuyup kendi kendine onay veremesin diye). Sabitlemek istersen `WACC_BACKEND_USER_TOKEN` (env).
- Acil durdurma: `POST /exec/stop` (ajan veya kullanıcı), `POST /exec/resume` (yalnızca kullanıcı). Hub'ın acil durdurması `data/EMERGENCY_STOP` dosyasıyla aynı anahtardır; ikisinden biri açıksa eylemler reddedilir, çalışan süreçler süreç ağacıyla birlikte sonlandırılır.
- İzinli kökler: `WACC_EXEC_ROOTS` (varsayılan yalnızca proje klasörü). `data/`, `.env`, `*.pem`, token dosyaları ve `.git/` ajanlara kapalıdır.
- `GET /exec/audit`: yalnızca eklenir (veritabanı tetikleyicileri güncelleme/silmeyi engeller), sırlar maskelenir.

Bilinen sınırlar (dürüst not):
1. Proje kodu çalıştıran komutlar (`python -m pytest/unittest`, `flutter test`, `flutter build ...`, `dart test`) artık **onay ister** (bir ajan test dosyası yazıp çalıştırarak kod çalıştıramasın diye). Her çalıştırma kendi onayını ister; sık çalıştırmak istersen backend'i `WACC_EXEC_AUTO_CODE=1` ile başlat (bu riski bilerek kabul etmek demektir).
2. Ajan kimliği (`agent` alanı) istemcinin beyanıdır; tüm ajanlar aynı ajan token'ını paylaşır. Onay yine de eylemin hash'ine bağlıdır.
3. Backend yalnızca kendisi üzerinden gelen eylemleri denetler. Ajanın kendi shell'i (ör. Claude Code oturumu) bu kapıdan geçmez.
4. Windows'ta (taskkill ile süreç ağacı sonlandırma, farklı sürücü, junction) denenmedi; testler Linux'ta çalıştı.

## Next
Web panelde onay ekranı (claude3), Flutter onay ekranı, ajanların `/exec`'i kullanması.
Add new tables as new entries in `storage.MIGRATIONS`; never edit an existing migration.

## İş çalıştırıcısı (worker)
`python -m wacc_backend` ile açılan arka plan işçisi (kapatmak: `WACC_WORKER=0`) `/jobs` kuyruğundan iki iş türünü yürütür:
- `ai.complete`: `{prompt, system?, prefer?, provider?, max_tokens?}` → orchestrator sonucu.
- `exec.run`: `{action, approval_id?}` → `/exec` ile **aynı** politika, onay, denetim ve acil durdurma denetimlerinden geçer ("worker" adıyla). Onay gerekiyorsa iş yeniden denemeden başarısız olur ve onay numarasını yazar; onayladıktan sonra aynı işi `approval_id` ile tekrar kuyruğa ekle.
Not: iş yükü (`payload`) veritabanında saklanır; içine sır koyma.

## Ajan başına token (v0.3)
`data/backend_tokens.json` (git'e girmez, ilk açılışta üretilir): `claude1`, `claude2`, `claude3`, `gemini` için ayrı token. Token çağıranın kimliğini belirler:
- `POST /exec`: gövdedeki `agent` alanı token'daki adla **aynı olmak zorunda** (aksi 403); denetim kaydı ve onay sahipliği bu ada bağlıdır. Eski ortak token (`backend_token.txt`) eylem gönderemez (403), yalnızca okuma ve acil durdurma içindir. Kullanıcı token'ı test için istediği adla gönderebilir.
- `POST /agents/{ad}/heartbeat`: yalnızca kendi adın. `POST /agents/{ad}/enabled`: yalnızca kullanıcı.
- İş kuyruğundaki `worker` adı hâlâ serbesttir (dış işçiler keyfi ad kullanabilir); başka bir ajanın işini tamamlama riski bilinen sınırdır.
- Hâlâ geçerli sınır: token'lar `data/` içinde durur; aynı bilgisayarda kendi kabuğunu çalıştıran bir ajan dosyayı okuyabilir (backend yalnızca kendisine gelen istekleri korur).
