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

### 1. Pre-built Docker Image via GHCR (Recommended)

You can run the service directly using the pre-built image hosted on GitHub Container Registry:

**Option A: Using Docker Compose (Recommended)**
Create a `docker-compose.yml` file:
```yaml
services:
  streamdl:
    image: ghcr.io/dzendys/streamdl:latest
    container_name: streamdl
    ports:
      - "8082:8080"
    env_file:
      - .env
    volumes:
      - ./temp_downloads:/app/temp_downloads
    restart: unless-stopped
```
Prepare your `.env` file from the example (`cp .env.example .env`) and start the service:
```bash
docker compose up -d
```

**Option B: Using Docker Run**
Prepare your `.env` file from the example (`cp .env.example .env`) and run the container:
```bash
docker run -d \
  --name streamdl \
  -p 8082:8080 \
  --env-file .env \
  -v ./temp_downloads:/app/temp_downloads \
  --restart unless-stopped \
  ghcr.io/dzendys/streamdl:latest
```

The service will be accessible at `http://localhost:8082`.

### 2. Docker Build from Source

If you want to build the Docker image locally from source:

1. Clone the repository: `git clone <REPOSITORY_URL> && cd streamdl`
2. Prepare your `.env` file: `cp .env.example .env`
3. Build and run using the default [docker-compose.yml](docker-compose.yml):
   ```bash
   docker compose up --build -d
   ```

### 3. Local Setup (Python & FFmpeg)

To run the application directly on your host machine:

1. Ensure you have **Python 3.11+** and **FFmpeg** installed on your system.
2. Clone the repository and install dependencies:
   ```bash
   git clone <REPOSITORY_URL> && cd streamdl
   pip install -r requirements.txt
   ```
3. Prepare your environment variables (optional):
   ```bash
   cp .env.example .env
   ```
4. Start the application:
   ```bash
   python app.py
   ```
   The app will run at `http://localhost:8080`.


## Configuration (Environment Variables)

Variables are loaded from the `.env` file when running via Docker Compose or when passed to the container.

Example `.env` file ([.env.example](.env.example)):
```env
# Cooldown time in seconds between yt-dlp executions
YTDLP_COOLDOWN=600

# File name for YouTube cookies (placed in the container workspace /app)
COOKIES_FILE=cookies.txt

# Maximum time in seconds to wait for a stream to start
MAX_STREAM_TIMEOUT=60.0
```

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
