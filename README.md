# StreamDL

A professional streaming proxy and media downloader powered by FastAPI, yt-dlp, and FFmpeg.

## Description

StreamDL is a lightweight web application and API service designed to download and transcode multimedia content (video and audio) from hundreds of supported platforms (e.g., YouTube, SoundCloud, TikTok, Vimeo). The entire solution operates as a pass-through proxy: all media data is piped directly through memory to the user's browser in real-time, without writing any temporary files to the server's disk storage.

## Key Features & Advantages

- **Zero Disk Usage:** Media streams are buffered and piped on the fly from the source to the client. This prevents server disk space exhaustion and enhances user privacy.
- **On-the-Fly Audio Transcoding:** Audio streams are transcoded in real-time to MP3 format with configurable bitrates (up to 320 kbps) using FFmpeg.
- **On-the-Fly Video/Audio Merging:** For platforms supplying separate video and audio streams (e.g., YouTube 1080p or 4K), FFmpeg merges the inputs on the fly into an MP4 container and streams the output directly to the client.
- **Self-Healing Update Mechanism:** The system monitors extraction failures and automatically schedules background updates for the `yt-dlp` library. To prevent infinite update loops, a 10-minute cooldown window is enforced. Updates can also be triggered manually from the UI.
- **Premium User Interface:** A fully responsive, glassmorphic dark-theme UI featuring real-time size estimation, dynamic content type detection (disabling video modes for audio-only URLs), and client-side cancellation support (via `AbortController`).

## Installation & Setup

### System Requirements
- Python 3.11 or newer (for local installations)
- FFmpeg installed and available in the system's `PATH`
- Docker and Docker Compose (recommended for production deployment)

### Local Setup (Without Docker)

1. Clone the repository:
   ```bash
   git clone <REPOSITORY_URL>
   cd yt
   ```

2. Install python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Start the application:
   ```bash
   python app.py
   ```
   The application will run on `http://localhost:8080` by default.

### Deployment Using Docker Compose (Recommended)

1. Build the Docker image and start the container in detached mode:
   ```bash
   docker compose up --build -d
   ```
   The application will map to host port `8082` (customizable via the `ports` property in `docker-compose.yml`).

2. Stop the services:
   ```bash
   docker compose down
   ```

## Configuration (Environment Variables)

The application can be configured by defining the following environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PORT` | `8080` | Port the web server listens to inside the container. |
| `HOST` | `0.0.0.0` | Bind IP address for the web server. |
| `YTDLP_COOLDOWN` | `600` | Cooldown period (in seconds) between yt-dlp update checks. |
| `COOKIES_FILE` | `cookies.txt` | Path to a cookies file for extraction from restricted sites. |
| `MAX_STREAM_TIMEOUT` | `60.0` | Connection timeout (in seconds) for HTTP remote streaming clients. |

Set these variables in the `environment` section of `docker-compose.yml`.

## API Documentation

### 1. Fetch Media Metadata

Extracts media information and calculates file size estimates.

- **Endpoint:** `/api/info`
- **Method:** `POST`
- **Request Format (Form Data):**
  - `url` (string, required): URL of the target video/audio.

- **Response Example (JSON):**
  ```json
  {
    "title": "Video Title",
    "thumbnail": "https://domain.com/image.jpg",
    "duration": "2:15:32",
    "uploader": "Channel Name / Author",
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

### 2. Stream & Download Media

Triggers the transcoding/merging pipeline and streams the binary content back.

- **Endpoint:** `/api/download`
- **Method:** `POST`
- **Request Format (Form Data):**
  - `url` (string, required): URL of the media.
  - `downloadMode` (string, optional, default `auto`): Download mode. Options:
    - `auto`: Download video and audio, merge them into MP4.
    - `audio`: Download audio only and transcode to MP3.
    - `mute`: Download video only (without audio).
  - `videoQuality` (string, optional, default `max`): Video resolution threshold limit. Options: `max`, `1080`, `720`, `480`.
  - `audioBitrate` (string, optional, default `320`): Target datate rate for MP3 conversion in kbps. Options: `320`, `256`, `192`, `128`.

### 3. Get yt-dlp Version

- **Endpoint:** `/api/yt-dlp/version`
- **Method:** `GET`
- **Response Example (JSON):**
  ```json
  {
    "version": "2026.06.17"
  }
  ```

### 4. Upgrade yt-dlp

- **Endpoint:** `/api/yt-dlp/update`
- **Method:** `POST`
- **Response Example (JSON):**
  ```json
  {
    "success": true,
    "message": "Success: updated to 2026.06.17",
    "version": "2026.06.17"
  }
  ```
