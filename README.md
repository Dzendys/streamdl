# StreamyDL

Profesionální streamovací proxy a downloader médií využívající FastAPI, yt-dlp a FFmpeg.

## Popis projektu

StreamyDL je webová aplikace a API služba určená ke stahování a konverzi multimediálního obsahu (videa a zvuku) ze stovek podporovaných platforem (např. YouTube, SoundCloud, TikTok, Vimeo). Celé řešení funguje jako průchozí proxy – veškerá data jsou v reálném čase přenášena přes operační paměť přímo do prohlížeče uživatele bez ukládání jakýchkoliv dočasných souborů na disk serveru.

## Hlavní výhody a vlastnosti

- **Nulové nároky na diskové úložiště (Zero Disk Usage):** Data se neukládají na server, což chrání diskovou kapacitu serveru před zaplněním a zvyšuje soukromí uživatelů.
- **Konverze zvuku za běhu:** Zvukové stopy jsou v reálném čase převáděny do formátu MP3 s volitelným datovým tokem (až 320 kbps) pomocí FFmpeg.
- **Slučování stop on-the-fly:** V případě oddělených video a audio stop (např. YouTube Full HD/4K) FFmpeg za běhu slučuje oba streamy do jednoho MP4 kontejneru a výstup rovnou odesílá uživateli.
- **Robustní mechanismus aktualizací:** Aplikace monitoruje selhání extrakce dat a při chybě automaticky spouští aktualizaci knihovny `yt-dlp` na pozadí. Pro zamezení nekonečných smyček je implementován časový limit (cooldown) 10 minut. Aktualizaci lze vyvolat i manuálně z uživatelského rozhraní.
- **Prémiové uživatelské rozhraní:** Responzivní design s moderními glassmorfními prvky, tmavým režimem, dynamickou detekcí typu obsahu, automatickým blokováním nedostupných rozlišení a možností zrušit probíhající stahování (pomocí `AbortController`).

## Instalace a spuštění

### Požadavky na systém
- Python 3.11 nebo novější (v případě lokálního běhu mimo Docker)
- FFmpeg nainstalovaný v systému a dostupný v systémové cestě (`PATH`)
- Docker a Docker Compose (doporučeno pro produkční nasazení)

### Lokální instalace (bez Dockeru)

1. Naklonujte repozitář:
   ```bash
   git clone <URL_REPA>
   cd yt
   ```

2. Nainstalujte potřebné závislosti:
   ```bash
   pip install -r requirements.txt
   ```

3. Spusťte aplikaci:
   ```bash
   python app.py
   ```
   Aplikace bude ve výchozím nastavení dostupná na adrese `http://localhost:8080`.

### Nasazení na server pomocí Docker Compose (doporučeno)

1. Sestavte Docker obraz a spusťte kontejner na pozadí:
   ```bash
   docker compose up --build -d
   ```
   Aplikace bude mapována na port `8082` hostitelského serveru (lze změnit v konfiguraci `ports` v souboru `docker-compose.yml`).

2. Pro vypnutí služeb spusťte:
   ```bash
   docker compose down
   ```

## Konfigurace (Environment Variables)

Aplikaci lze plně přizpůsobit pomocí následujících proměnných prostředí:

| Proměnná | Výchozí hodnota | Popis |
| :--- | :--- | :--- |
| `PORT` | `8080` | Port, na kterém naslouchá webový server uvnitř kontejneru. |
| `HOST` | `0.0.0.0` | IP adresa, na kterou se server váže. |
| `YTDLP_COOLDOWN` | `600` | Ochranná lhůta (v sekundách) mezi pokusy o aktualizaci yt-dlp. |
| `COOKIES_FILE` | `cookies.txt` | Název souboru s exportovanými cookies pro stahování chráněného obsahu. |
| `MAX_STREAM_TIMEOUT` | `60.0` | Časový limit (v sekundách) pro navázání spojení se zdrojem streamu. |

Proměnné se nastavují v sekci `environment` v souboru `docker-compose.yml`.

## Dokumentace API

### 1. Získání metadat média

Vrátí podrobné informace o médiu včetně odhadů velikosti souborů pro různé kvality.

- **Endpoint:** `/api/info`
- **Metoda:** `POST`
- **Formát požadavku (Form Data):**
  - `url` (string, povinné): Odkaz na video či audio soubor.

- **Příklad odpovědi (JSON):**
  ```json
  {
    "title": "Název videa",
    "thumbnail": "https://domain.com/image.jpg",
    "duration": "2:15:32",
    "uploader": "Název kanálu / Autor",
    "sizes": {
      "360": 1234567,
      "480": 2345678,
      "720": 4567890,
      "1080": 9876543,
      "max": 12345678,
      "audio": 543210
    },
    "has_video": true,
    "max_height": 1080
  }
  ```

### 2. Streamování a stahování média

Spustí proces zpracování a streamování dat. Odpovědí je binární proud dat.

- **Endpoint:** `/api/download`
- **Metoda:** `POST`
- **Formát požadavku (Form Data):**
  - `url` (string, povinné): Odkaz na médium.
  - `downloadMode` (string, volitelné, výchozí `auto`): Režim stahování. Možnosti:
    - `auto`: Stáhne video i audio a sloučí je dohromady (výstup MP4).
    - `audio`: Stáhne pouze audio stopu a převede ji na MP3.
    - `mute`: Stáhne pouze obrazovou stopu (bez zvuku).
  - `videoQuality` (string, volitelné, výchozí `max`): Limit rozlišení videa. Možnosti: `max`, `1080`, `720`, `480`.
  - `audioBitrate` (string, volitelné, výchozí `320`): Datový tok pro MP3 konverzi v kbps. Možnosti: `320`, `256`, `192`, `128`.

### 3. Získání verze yt-dlp

- **Endpoint:** `/api/yt-dlp/version`
- **Metoda:** `GET`
- **Příklad odpovědi (JSON):**
  ```json
  {
    "version": "2026.06.17"
  }
  ```

### 4. Spuštění aktualizace yt-dlp

- **Endpoint:** `/api/yt-dlp/update`
- **Metoda:** `POST`
- **Příklad odpovědi (JSON):**
  ```json
  {
    "success": true,
    "message": "Success: updated to 2026.06.17",
    "version": "2026.06.17"
  }
  ```
