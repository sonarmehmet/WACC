# WACC Mimari

## Katmanlar

1. **Communication Hub** (`hub/wacc_hub`): ajanlar arası mesaj, görev, kilit, karar, checkpoint. SQLite (WAL, busy_timeout, `BEGIN IMMEDIATE`) + FastAPI + CLI.
2. **Backend** (`backend/`): FastAPI çekirdek, AI Orchestrator, Agent Manager, Task Engine, Memory, Windows Execution Backend.
3. **İstemciler**: Flutter (Android, ileride iOS), Web panel, Windows Desktop. Hepsi Hub/Backend API'sini token ile kullanır.
4. **Gemini**: yalnızca görsel işler ve yetkilendirilmiş bilgisayar operatörlüğü.

Git, kod ve sürüm yönetimi içindir. Mesaj ve görev koordinasyonu yalnızca Hub'dadır.

## Hub veri modeli

`agents`, `tasks`, `messages`, `locks`, `decisions`, `checkpoints`, `escalations`, `system_flags`, `audit_log`.

### Mesaj yaşam döngüsü
`QUEUED → DELIVERED → READ → ANSWERED` (`FAILED`: 5 teslim denemesinden sonra).
- `idempotency_key` aynı mesajın iki kez işlenmesini engeller.
- Inbox, Outbox, Sent, Unread, Pending Responses, Assigned Tasks sorguları vardır.
- `response_required` olan mesajlar yanıtlanana kadar "pending" görünür.

### Görev yaşam döngüsü
`BACKLOG → ASSIGNED → ACCEPTED → IN_PROGRESS → REVIEW → COMPLETED` (+ `BLOCKED`, `CANCELLED`).
- Görevi yalnızca claude1 veya kullanıcı oluşturur/atar.
- `COMPLETED` için commit hash zorunlu; açık bağımlılık varsa tamamlanamaz.
- `BLOCKED` için açıklama zorunlu.

### Kilitler
- Yol bazlı; üst/alt klasör çakışması da engellenir (`backend/api` ↔ `backend/api/routes.py`).
- TTL 30–3600 sn, `heartbeat` ile uzar. Süresi dolan kilit **otomatik silinmez**.
- Başka ajan devralmak için önce Git durumu ve son checkpoint'i incelemeli, sonra `takeover` ile alır (kayıt altına alınır, eski sahibe uyarı gider).
- Oturum bitince (`session-end`) tüm kilitler bırakılır.

### Tartışma sınırı
Bir konuşmada 8 yardım/inceleme/hata mesajına karar kaydı olmadan ulaşılırsa Hub, claude1 ve kullanıcıya `SYSTEM_ALERT` gönderir; claude1 karar önerisi hazırlar.

### Acil durdurma
`emergency_stop` bayrağı açıkken kullanıcı dışındaki tüm yazma işlemleri reddedilir (`EMERGENCY_STOP`). Yalnızca kullanıcı `resume` yapabilir.

## Bağlantı gerçeği

Hub verisi kullanıcının bilgisayarındaki `data/hub.db` dosyasındadır. Bir Claude oturumunun Hub'ı kullanabilmesi için ya aynı bilgisayarda çalışması (CLI) ya da Hub API'sine ağ üzerinden erişebilmesi gerekir. Buluttaki bir oturum, kullanıcının `127.0.0.1` adresine ulaşamaz. Bu durumda iki yol vardır: oturumları bilgisayarda çalıştırmak (Claude Code / masaüstü) veya Hub'ı kimlik doğrulamalı bir tünel (ör. Cloudflare Tunnel/Tailscale) arkasında açmak. Korumasız internete açmak yasaktır.
