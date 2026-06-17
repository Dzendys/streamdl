import asyncio
import json
import os
import re
import sys
import time
import logging
import uuid
import shutil
from typing import AsyncGenerator
from fastapi import FastAPI, Request, HTTPException, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import yt_dlp
import uvicorn

# Configure professional logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("streamdl")

# Load Configuration from Environment Variables
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")
YTDLP_COOLDOWN = int(os.getenv("YTDLP_COOLDOWN", "600"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")

app = FastAPI(title="StreamDL API")

# Ensure required directories exist and mount static files
os.makedirs("templates", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Startup cleanup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def cleanup_on_startup():
    """Clean up any leftover files in temp_downloads folder on system startup."""
    temp_dir = "temp_downloads"
    if os.path.exists(temp_dir):
        logger.info("Cleaning up leftover temporary downloads on startup...")
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to cleanup temp_downloads on startup: {e}")

def cleanup_temp_dir(directory_path: str):
    """Delete a temporary download directory and all its contents."""
    try:
        if os.path.exists(directory_path):
            shutil.rmtree(directory_path)
            logger.info(f"Cleaned up temp directory: {directory_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup temp directory {directory_path}: {e}")

# ---------------------------------------------------------------------------
# yt-dlp auto-update
# ---------------------------------------------------------------------------

last_update_time = 0.0
update_lock = asyncio.Lock()

async def run_update(bypass_cooldown: bool = False) -> tuple[bool, str]:
    """Run an in-memory upgrade of yt-dlp via pip install and module reload."""
    global last_update_time
    async with update_lock:
        now = time.time()
        if not bypass_cooldown and (now - last_update_time < YTDLP_COOLDOWN):
            return False, "cooldown"

        logger.info("Executing pip upgrade for yt-dlp...")
        try:
            process = await asyncio.create_subprocess_exec(
                "pip", "install", "--upgrade", "yt-dlp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                to_del = [m for m in sys.modules if m.startswith('yt_dlp')]
                for m in to_del:
                    del sys.modules[m]
                import yt_dlp
                last_update_time = time.time()
                new_ver = yt_dlp.version.__version__
                logger.info(f"yt-dlp updated to {new_ver}")
                return True, f"Success: updated to {new_ver}"
            else:
                err_msg = stderr.decode().strip() or stdout.decode().strip()
                logger.error(f"pip update failed: {err_msg}")
                return False, f"pip update failed: {err_msg}"
        except Exception as e:
            logger.exception("Exception during pip update")
            return False, f"Exception: {str(e)}"

async def trigger_auto_update_on_failure() -> None:
    """Trigger background auto-update on yt-dlp failures if cooldown allows."""
    now = time.time()
    if now - last_update_time >= YTDLP_COOLDOWN:
        logger.warning("Auto-updating yt-dlp due to failure...")
        success, msg = await run_update()
        logger.info(f"Auto-update: success={success}, msg={msg}")

# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def format_duration(duration: float | None) -> str:
    """Format duration in seconds to H:MM:SS or M:SS."""
    if not duration:
        return "Neznámá"
    try:
        d = int(duration)
        h, m, s = d // 3600, (d % 3600) // 60, d % 60
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
    except (ValueError, TypeError):
        return "Neznámá"

def estimate_sizes(formats: list[dict], duration: float | None) -> dict[str, int]:
    """Estimate total sizes for each quality level from available formats."""
    sizes = {}
    audio_size = 0
    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            audio_size = max(audio_size, f.get("filesize") or f.get("filesize_approx") or 0)

    if not audio_size and duration:
        audio_size = int((128000 / 8) * duration)

    for q in ["360", "480", "720", "1080", "max"]:
        video_size = 0
        height_limit = 99999 if q == "max" else int(q)
        for f in formats:
            if f.get("acodec") == "none" and f.get("vcodec") != "none":
                height = f.get("height") or 0
                if height <= height_limit:
                    video_size = max(video_size, f.get("filesize") or f.get("filesize_approx") or 0)

        if not video_size and duration:
            bitrates = {"360": 500000, "480": 800000, "720": 1500000, "1080": 3000000, "max": 6000000}
            video_size = int((bitrates[q] / 8) * duration)

        sizes[q] = video_size + audio_size

    sizes["audio"] = audio_size
    return sizes

def _has_real_video(f: dict) -> bool:
    """Return True if the format has a real video codec (not audio-only)."""
    vc = f.get("vcodec")
    return bool(vc) and vc != "none"

# Simple in-memory cache for metadata (valid for 5 minutes)
metadata_cache: dict[str, tuple[float, dict]] = {}

async def extract_metadata(url: str) -> dict:
    """Fetch video info using yt-dlp with in-memory caching."""
    now = time.time()
    if url in metadata_cache:
        cached_time, data = metadata_cache[url]
        if now - cached_time < 300:
            logger.info(f"Serving metadata from cache: {url}")
            return data

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'check_formats': False,
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
    }
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    loop = asyncio.get_event_loop()

    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        metadata_cache[url] = (time.time(), data)
        return data
    except Exception as e:
        logger.exception(f"yt-dlp metadata extraction failed for: {url}")
        asyncio.create_task(trigger_auto_update_on_failure())
        raise HTTPException(status_code=400, detail=f"Chyba yt-dlp: {str(e)}")

# ---------------------------------------------------------------------------
# Download job state (for SSE progress streaming)
# ---------------------------------------------------------------------------

download_jobs: dict[str, dict] = {}

# Regex to parse yt-dlp progress lines like:
#   [download]  45.3% of   23.45MiB at   3.21MiB/s ETA 00:06
PROGRESS_RE = re.compile(
    r'\[download\]\s+(\d+\.?\d*)%\s+of\s+~?\s*([\d.]+\s*\S+)\s+at\s+(~?[\d.]+\s*\S+)\s+ETA\s+([\d:]+)'
)

def _build_ydlp_cmd(
    output_template: str,
    download_mode: str,
    video_quality: str,
    audio_bitrate: str,
    threads: int,
) -> list[str]:
    """Build the yt-dlp CLI command list based on download options."""
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--newline",                           # one progress line per update
        "--concurrent-fragments", str(threads),
        "-o", output_template,
    ]

    if os.path.exists(COOKIES_FILE):
        cmd.extend(["--cookiefile", COOKIES_FILE])

    if download_mode == "audio":
        cmd.extend([
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", f"{audio_bitrate}k",
        ])
    elif download_mode == "mute":
        h = 99999 if video_quality == "max" else int(video_quality)
        fs = "bestvideo/best" if h == 99999 else f"bestvideo[height<={h}]/best[height<={h}]/best"
        cmd.extend(["-f", fs])
    else:  # auto — video + audio merge with fallback for audio-only sources
        h = 99999 if video_quality == "max" else int(video_quality)
        if h == 99999:
            fs = "bestvideo+bestaudio/bestaudio/best"
        else:
            fs = f"bestvideo[height<={h}]+bestaudio/bestvideo+bestaudio/bestaudio/best[height<={h}]/best"
        cmd.extend(["-f", fs, "--merge-output-format", "mp4"])

    return cmd


async def stream_download(download_id: str, cmd: list[str], url: str, temp_dir: str) -> None:
    """
    Run yt-dlp as a subprocess and push parsed progress events to the job's queue.
    Reads stderr line-by-line for real-time progress without blocking.
    """
    job = download_jobs[download_id]
    queue: asyncio.Queue = job["queue"]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        async for raw_line in process.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            m = PROGRESS_RE.search(line)
            if m:
                percent, total, speed, eta = m.groups()
                downloaded_bytes = float(percent) / 100.0
                await queue.put({
                    "type": "progress",
                    "percent": float(percent),
                    "total": total,
                    "speed": speed,
                    "eta": eta,
                })
            elif "[Merger]" in line:
                await queue.put({"type": "status", "phase": "merging"})
            elif "[ExtractAudio]" in line:
                await queue.put({"type": "status", "phase": "converting"})

        await process.wait()

        if process.returncode != 0:
            job["status"] = "error"
            await queue.put({"type": "error", "message": "yt-dlp selhal při stahování"})
        else:
            # Find the output file (ignore .part files)
            files = [f for f in os.listdir(temp_dir) if not f.endswith(".part")]
            if files:
                filename = files[0]
                job["filepath"] = os.path.join(temp_dir, filename)
                job["filename"] = filename
                job["status"] = "done"
                await queue.put({"type": "done", "filename": filename})
            else:
                job["status"] = "error"
                await queue.put({"type": "error", "message": "Soubor po stažení nenalezen"})

    except Exception as e:
        logger.exception(f"stream_download error for job {download_id}")
        job["status"] = "error"
        await queue.put({"type": "error", "message": str(e)})
    finally:
        await queue.put(None)  # Sentinel — signals end of stream


async def sse_event_generator(download_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events from the download job's queue."""
    if download_id not in download_jobs:
        yield f'data: {json.dumps({"type": "error", "message": "Job nenalezen"})}\n\n'
        return

    queue: asyncio.Queue = download_jobs[download_id]["queue"]

    try:
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=300)
            if item is None:
                yield f'data: {json.dumps({"type": "end"})}\n\n'
                break
            yield f'data: {json.dumps(item)}\n\n'
    except asyncio.TimeoutError:
        yield f'data: {json.dumps({"type": "error", "message": "Timeout"})}\n\n'

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Render the homepage UI."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/yt-dlp/version")
async def get_yt_dlp_version():
    """Retrieve currently active version of yt-dlp."""
    import yt_dlp
    return {"version": yt_dlp.version.__version__}


@app.post("/api/yt-dlp/update")
async def update_yt_dlp_endpoint():
    """Manually trigger yt-dlp update."""
    success, msg = await run_update(bypass_cooldown=True)
    import yt_dlp
    return {"success": success, "message": msg, "version": yt_dlp.version.__version__}


@app.post("/api/info")
async def get_video_info(url: str = Form(...)):
    """Fetch structured metadata and file size estimates for quality cards."""
    if not url:
        raise HTTPException(status_code=400, detail="URL je vyžadována")

    info = await extract_metadata(url)

    title = info.get("title", "Neznámé video")
    thumbnail = info.get("thumbnail", "")
    duration = info.get("duration", 0)
    uploader = info.get("uploader", "Neznámý autor")
    formats = info.get("formats", [])

    sizes = estimate_sizes(formats, duration)
    has_video = any(_has_real_video(f) for f in formats)
    max_height = 0
    if has_video:
        max_height = max((f.get("height") or 0) for f in formats if _has_real_video(f))

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration": format_duration(duration),
        "uploader": uploader,
        "sizes": sizes,
        "has_video": has_video,
        "max_height": max_height,
    }


@app.post("/api/download/start")
async def start_download(
    url: str = Form(...),
    downloadMode: str = Form("auto"),
    videoQuality: str = Form("max"),
    audioBitrate: str = Form("320"),
    concurrency: int = Form(5),
):
    """
    Validate request, build yt-dlp command, create a download job, and return
    a download_id that the client uses to subscribe to SSE progress events.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL je vyžadována")

    threads = max(1, min(16, concurrency))
    info = await extract_metadata(url)
    title = info.get("title", "video")
    formats = info.get("formats", [])

    clean_title = "".join(c for c in title if c.isalnum() or c in "._- ").strip()

    has_video = any(_has_real_video(f) for f in formats)
    download_mode = downloadMode

    if not has_video:
        if download_mode == "mute":
            raise HTTPException(
                status_code=400,
                detail="Tento odkaz obsahuje pouze zvuk (žádná video stopa)."
            )
        elif download_mode == "auto":
            download_mode = "audio"

    download_id = str(uuid.uuid4())
    temp_dir = os.path.join("temp_downloads", download_id)
    os.makedirs(temp_dir, exist_ok=True)

    output_template = os.path.join(temp_dir, f"{clean_title}.%(ext)s")
    cmd = _build_ydlp_cmd(output_template, download_mode, videoQuality, audioBitrate, threads)

    download_jobs[download_id] = {
        "status": "running",
        "queue": asyncio.Queue(),
        "temp_dir": temp_dir,
        "filepath": None,
        "filename": None,
        "error": None,
        "created_at": time.time(),
    }

    logger.info(f"Starting download job {download_id}: {' '.join(cmd)} {url}")
    asyncio.create_task(stream_download(download_id, cmd, url, temp_dir))

    return {"download_id": download_id, "title": clean_title}


@app.get("/api/download/{download_id}/events")
async def download_events(download_id: str):
    """SSE endpoint: streams real-time download progress for the given job."""
    return StreamingResponse(
        sse_event_generator(download_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Prevent nginx from buffering SSE
        },
    )


@app.get("/api/download/{download_id}/file")
async def get_download_file(download_id: str, background_tasks: BackgroundTasks):
    """Serve the downloaded file once complete and schedule temp directory cleanup."""
    if download_id not in download_jobs:
        raise HTTPException(status_code=404, detail="Job nenalezen nebo vypršel")

    job = download_jobs[download_id]
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Soubor ještě není připraven")

    filepath = job["filepath"]
    filename = job["filename"]

    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Soubor nenalezen na disku")

    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4a": "audio/mp4",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    temp_dir = job["temp_dir"]
    background_tasks.add_task(cleanup_temp_dir, temp_dir)
    del download_jobs[download_id]

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type=media_type,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
