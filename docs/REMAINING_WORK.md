# Kalan işler — herkes alabilir

Tek doğruluk kaynağı: GitHub Issues → https://github.com/sonarmehmet/WACC/issues (etiket `open-to-any`).
Kullanıcıya düşen işler `user` etiketlidir.

## Nasıl çalışılır (3 Claude + Gemini aynı anda)
1. `docs/HANDOFF.md` oku. Issue listesine bak; `in-progress` etiketi olmayan, kendi klasörüne uyan bir iş seç.
2. Issue'ya `Üstleniyorum: <ajan adı>` yorumu yaz, `in-progress` ekle. **Aynı anda iki ajan aynı işi almaz**; ilk yorum kazanır.
3. Kendi dalında çalış: `task/<kısa-ad>`. Başkasının klasörüne yazma (klasör sahipliği `docs/HANDOFF.md`'de); gerekiyorsa issue'ya yorumla sahibinden iste.
4. Önce kodu yaz, **testleri en sona** yaz ve çalıştır. CI (Linux + Windows) yeşil olmadan "bitti" deme.
5. Bitince issue'ya ne yaptığını, neyin **denenmediğini** yaz; dalı claude1'e bildir (`main`'e yalnızca claude1 birleştirir). Sonra issue'yu kapat.

## Dağıtım (kullanıcı onaylı; ayrıntı: issue #15)
| Ajan | İşler |
|---|---|
| claude1 | #7 Hub `watch`, #8 kullanıcı kılavuzu, #9 Gemini operatör protokolü, #4 branding, #18 yapay zeka hesapları (hepsi bitti) |
| claude2 | #11 güvenlik taraması (#6 ve #10'u claude1 yaptı, claude2 bağlanmadığı için) |
| claude3 | #2 Flutter onay ekranı, #3 Flutter Android derleme, #5 web/masaüstü entegrasyonu, #19 web+Flutter yapay zeka hesapları ekranı |
| gemini | devre dışı (kullanıcı kararı); #4 logo/ikon/palet claude1 tarafından yapıldı, #9 isteğe bağlı |
| kullanıcı | #12 ilk çalıştırma, #13 Ollama, #14 private yapma |

Ajan bağlanmamışsa işini claude1 devralır ve issue'ya yazar.

## Henüz hiç denenmemiş (dürüst durum)
Gerçek yerel/bulut model, gerçek telefon/emülatör, kullanıcının kendi Windows makinesinde elle kullanım. Diğer her şey Linux + Windows CI'da otomatik test edilir (Windows'ta `start_wacc.bat` uçtan uca dahil).
