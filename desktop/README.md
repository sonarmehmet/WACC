# desktop

Windows masaüstü paneli (Tkinter, ek paket gerekmez). Ajanlar, görevler, **onay bekleyen eylemler**, denetim kaydı ve acil durdurma.

Çalıştırma: `run_desktop.bat` ya da `python -m wacc_desktop` (klasör: `desktop/`).

- Token'lar: Hub (`data/tokens.json` içinden), backend (`data/backend_token.txt`) ve **onay token'ı** (backend penceresinde yazar). Hepsi yalnızca bellekte tutulur, diske yazılmaz.
- Onay ve "devam ettir" yalnızca onay token'ıyla çalışır; her onay tek eylem içindir.
- Hub'dan gelen metinler güvenilmeyen girdidir, sadece etiket olarak gösterilir.
