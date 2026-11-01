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

## Next (T-0009)
Windows Execution Backend (`docs/EXECUTION_SECURITY.md`'ye göre). Add new tables as new entries in `storage.MIGRATIONS`; never edit an existing migration.
