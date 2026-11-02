# Yerel model (Ollama) ve bulut modeli bağlama

Backend'in AI Orchestrator'ı OpenAI uyumlu uç noktalarla çalışır. Yerel model önce denenir, bulut yalnızca günlük bütçe içinde kullanılır.

## 1. Ollama kur (Windows)
1. https://ollama.com adresinden kur, sonra bir model indir: `ollama pull qwen2.5-coder:7b` (GPU/RAM'ine göre küçük/büyük seç; `scripts\check_env.ps1` GPU ve RAM'i gösterir).
2. Ollama `http://127.0.0.1:11434` üzerinde dinler; OpenAI uyumlu adres `http://127.0.0.1:11434/v1`.

## 2. WACC'a tanıt
`data\llm.env` dosyası oluştur (git'e girmez, ajanlar `data\` klasörünü okuyamaz):

```
WACC_LOCAL_LLM_URL=http://127.0.0.1:11434/v1
WACC_LOCAL_LLM_MODEL=qwen2.5-coder:7b
# İsteğe bağlı bulut (yalnızca https; anahtar sadece bu dosyada/ortamda kalır):
# WACC_CLOUD_LLM_URL=https://...
# WACC_CLOUD_LLM_KEY=...
# WACC_CLOUD_LLM_MODEL=...
```
Dosya yalnızca `WACC_` ile başlayan anahtarları okur; onay token'ı (`WACC_BACKEND_USER_TOKEN`) ve ajan token'ı bu dosyadan **okunmaz**. Ortamda zaten tanımlı olan değer dosyadakini ezer.

## 3. Dene
`check_llm.bat` (ya da `python scripts\check_llm.py`): her model için tek küçük istek atar, `PASS/FAIL`, süre ve cevabın ilk kelimelerini yazar; anahtarı yazmaz. Sonra `start_wacc.bat` ile backend'i başlat; `GET /ai/providers` sağlayıcıları, `GET /ai/usage` kullanımı gösterir.

Not: bu yol sahte HTTP sunucusuyla test edilmiştir; gerçek model ile ilk deneme kullanıcıdadır.
