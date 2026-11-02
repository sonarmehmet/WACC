# Kalan işler — herkes alabilir

Tek doğruluk kaynağı: GitHub Issues → https://github.com/sonarmehmet/WACC/issues (etiket `open-to-any`).
Kullanıcıya düşen işler `user` etiketlidir.

## Nasıl çalışılır (3 Claude + Gemini aynı anda)
1. `docs/HANDOFF.md` oku. Issue listesine bak; `in-progress` etiketi olmayan, kendi klasörüne uyan bir iş seç.
2. Issue'ya `Üstleniyorum: <ajan adı>` yorumu yaz, `in-progress` ekle. **Aynı anda iki ajan aynı işi almaz**; ilk yorum kazanır.
3. Kendi dalında çalış: `task/<kısa-ad>`. Başkasının klasörüne yazma (klasör sahipliği `docs/HANDOFF.md`'de); gerekiyorsa issue'ya yorumla sahibinden iste.
4. Önce kodu yaz, **testleri en sona** yaz ve çalıştır. CI (Linux + Windows) yeşil olmadan "bitti" deme.
5. Bitince issue'ya ne yaptığını, neyin **denenmediğini** yaz; dalı claude1'e bildir (`main`'e yalnızca claude1 birleştirir). Sonra issue'yu kapat.

## Liste (2026-11-02 itibarıyla)
| # | İş | Öneri | Etiket |
|---|---|---|---|
| 2 | Flutter onay ekranı | claude3 | mobile |
| 3 | Flutter Android derleme + cihaz denemesi | claude3 | mobile |
| 4 | Gemini logo/ikon/palet (T-0007) | gemini | assets |
| 5 | Web/masaüstü: görsel entegrasyon + onay bildirimi | claude3 | web-desktop |
| 6 | Backend ajan başına token | claude2 | backend, security |
| 7 | Hub `watch` komutu | claude1/claude2 | hub-docs |
| 8 | Türkçe kullanıcı kılavuzu | herkes | hub-docs |
| 9 | Gemini operatör protokolü | claude1 + gemini | hub-docs, security |
| 10 | `restore_wacc.bat` | claude1/claude2 | hub-docs |
| 11 | Güvenlik taraması (public depo) | claude1 dışında biri | security |
| 12-14 | Kullanıcı işleri (ilk çalıştırma, Ollama, private yapma) | kullanıcı | user |

## Henüz hiç denenmemiş (dürüst durum)
Gerçek yerel/bulut model, gerçek telefon/emülatör, kullanıcının kendi Windows makinesinde elle kullanım. Diğer her şey Linux + Windows CI'da otomatik test edilir (Windows'ta `start_wacc.bat` uçtan uca dahil).
