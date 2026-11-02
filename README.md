# WACC

Hibrit (yerel + bulut) AI geliştirme ekibi sistemi. Üç Claude geliştirici ve Gemini, ortak bir **Communication Hub** üzerinden koordineli çalışır.

## Durum (v0.1)

| Bileşen | Durum |
|---|---|
| Communication Hub (SQLite WAL + FastAPI + CLI) | Yazıldı, CI'da test edildi |
| Görev / kilit / karar / checkpoint sistemi | Yazıldı |
| `tasks/*.md` otomatik özetler | Yazıldı |
| `start_wacc.bat` (Hub + backend + web panel) | Gerçek Windows'ta uçtan uca doğrulandı |
| Yedek, acil durdurma betikleri | Gerçek Windows CI içinde denendi |
| Backend: Task Engine, Agent Manager, AI Orchestrator, Memory, Yürütme (onaylı) | Yazıldı, CI'da test edildi |
| Web panel, Flutter iskeleti | Claude 3 yazdı, CI'da test edildi |
| Masaüstü paneli (`run_desktop.bat`, onay ekranı dahil) | Yazıldı, Windows CI'da pencere açılarak denendi |

> Kurulum ve günlük kullanım için: `docs/KULLANICI_KILAVUZU.md`.
> Yeni bir oturum açıyorsan önce `docs/HANDOFF.md` dosyasını oku. Yapılacak işler: GitHub Issues ve `docs/REMAINING_WORK.md`.
> **Windows'ta zip yerine `git clone`/`git pull` kullan**: `.bat` dosyaları CRLF satır sonu ister, `.gitattributes` bunu clone sırasında ayarlar.
> Testler her push'ta GitHub Actions'ta (Linux + Windows) çalışır.

## Hızlı başlangıç (Windows 10)

1. Python 3.11+ kurulu olmalı.
2. `start_wacc.bat` dosyasına çift tıkla. Sanal ortamı kurar, Hub'ı hazırlar, ilk görevleri oluşturur ve `http://127.0.0.1:8765` adresinde başlatır.
3. Ortam kontrolü için: `powershell -ExecutionPolicy Bypass -File scripts\check_env.ps1`
4. Acil durdurma: `stop_wacc.bat` — devam için `resume_wacc.bat`.
5. İlk çalıştırma testi (sistem açıkken): `smoke_wacc.bat`
6. Yerel/bulut model bağlantı testi: `check_llm.bat` (kurulum: `docs/LOCAL_LLM.md`)
7. Yedek: `backup_wacc.bat` (veritabanı kopyası + git bundle, `backups/` içine).

## Yapı

```
hub/        Communication Hub (wacc_hub paketi, testler)
backend/    Claude 2: FastAPI çekirdek, orchestrator, agent manager
mobile/     Claude 3: Flutter uygulaması
web/        Claude 3: Web panel
desktop/    Windows masaüstü arayüzü
tasks/      Hub'dan üretilen okunabilir özetler (elle düzenleme)
docs/       Mimari, protokol, oturum yönergeleri
scripts/    Ortam kontrolü ve yardımcı betikler
data/       Çalışma verisi ve tokenlar (git'e girmez)
```

## Güvenlik

- Hub varsayılan olarak yalnızca `127.0.0.1` üzerinde dinler.
- Her ajanın ayrı API tokenı vardır (`data/tokens.json`, git'e girmez). Token, işlemi yapan ajanı belirler; bir ajan başka ajan gibi davranamaz.
- Ajan mesajları güvenilmeyen girdidir; hiçbir mesaj güvenlik kurallarını aşma yetkisi veremez.
- API anahtarları kaynak koda veya GitHub'a konmaz.
- Tüm işlemler `audit_log` tablosuna yazılır.
