# StreamDL

A lightweight media downloader and transcoder API powered by FastAPI, yt-dlp, and FFmpeg.

## Description

StreamDL is a web service that downloads, transcodes (MP3), and merges (MP4) video/audio from YouTube and other platforms to a temporary folder, streaming the finished file to the client's browser, followed by automatic cleanup.

## Key Features

- **Temporary Storage & Auto-Cleanup:** Downloads, merges, and transcodes media to a customizable temporary folder on the server, serving the completed file and immediately deleting it afterward.
- **Auto-Updates:** Automatically upgrades `yt-dlp` in the background upon extraction errors (with a 10-min cooldown) or manually via UI.
- **Modern UI:** Responsive glassmorphic dark-theme frontend with progress bars, ETA, and download cancel buttons.
- **Configurable:** Fully customizable via environment variables.

## Installation & Setup

### Requirements
- Python 3.11+ (local) & FFmpeg
- Or Docker & Docker Compose

### Local Setup
```bash
git clone <REPOSITORY_URL> && cd yt
pip install -r requirements.txt
python app.py
```
App runs at `http://localhost:8080`.

### Docker Deployment (Recommended)

1. **Prepare Environment Variables**
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   Customize variables in `.env` if needed (e.g. change ports, directories, or limits).

2. **Start the Service**
   Start the container in detached mode:
   ```bash
   docker compose up --build -d
   ```
   By default, the app is mapped to host port `8082`. Stop the container using `docker compose down`.

For the configuration details, refer to the [docker-compose.yml](docker-compose.yml) file.


## Configuration (Environment Variables)

Variables are loaded from the `.env` file when running via Docker Compose:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `YTDLP_COOLDOWN` | `600` | Cooldown (seconds) between yt-dlp update checks. |
| `COOKIES_FILE` | `cookies.txt` | Path to cookies file inside the container. |
| `MAX_STREAM_TIMEOUT` | `60.0` | Connection timeout (seconds) for streaming clients. |

## API Documentation

### 1. Fetch Metadata
Extracts media info and calculates estimated file sizes.
- **POST** `/api/info`
- **Form Data:** `url` (string, required)
- **Response:** JSON containing title, duration, uploader, size estimates, and media format support.

### 2. Start Download Job
Triggers the download/transcode pipeline.
- **POST** `/api/download/start`
- **Form Data:**
  - `url` (string, required)
  - `downloadMode` (`auto`, `audio`, `mute`)
  - `videoQuality` (`max`, `1080`, `720`, `480`)
  - `audioBitrate` (`320`, `256`, `192`, `128`)
  - `concurrency` (int, default 5)
- **Response:** `{"download_id": "...", "title": "..."}`

### 3. Progress Event Stream (SSE)
Streams download status and progress from the server.
- **GET** `/api/download/{download_id}/events`
- **Response:** SSE events (`progress`, `status`, `done`, `error`).

### 4. Fetch File
Downloads the completed media file and cleans up the temporary directory.
- **GET** `/api/download/{download_id}/file`
- **Response:** Streams the completed file.

### 5. yt-dlp Info & Update
- **GET** `/api/yt-dlp/version` — Get current yt-dlp version.
- **POST** `/api/yt-dlp/update` — Manually trigger yt-dlp update.
