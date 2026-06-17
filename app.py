import asyncio
import os
import urllib.parse
import sys
import time
import logging
import uuid
import shutil
from fastapi import FastAPI, Request, HTTPException, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
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

# Helper functions for disk cleanup

def cleanup_temp_dir(directory_path: str):
    """Delete a temporary download directory and all its contents."""
    try:
        if os.path.exists(directory_path):
            shutil.rmtree(directory_path)
            logger.info(f"Successfully cleaned up temp directory: {directory_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup temp directory {directory_path}: {e}")

@app.on_event("startup")
def cleanup_on_startup():
    """Clean up any leftover files in temp_downloads folder on system startup."""
    temp_dir = "temp_downloads"
    if os.path.exists(temp_dir):
        logger.info("Cleaning up leftover temporary downloads on startup...")
        try:
            shutil.rmtree(temp_dir)
            logger.info("Temporary downloads folder cleaned successfully.")
        except Exception as e:
            logger.error(f"Failed to cleanup temp_downloads on startup: {e}")

# Auto-update state tracking for yt-dlp
last_update_time = 0.0
update_lock = asyncio.Lock()

async def run_update(bypass_cooldown: bool = False) -> tuple[bool, str]:
    """
    Run an in-memory upgrade of yt-dlp via pip install and module reload.
    Uses a lock to prevent concurrent update triggers.
    """
    global last_update_time
    async with update_lock:
        now = time.time()
        if not bypass_cooldown and (now - last_update_time < YTDLP_COOLDOWN):
            logger.info("yt-dlp update requested but cooldown is active.")
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
                # Force-reload of yt_dlp submodules to load updated library without restarting container
                to_del = [m for m in sys.modules if m.startswith('yt_dlp')]
                for m in to_del:
                    del sys.modules[m]
                import yt_dlp
                last_update_time = time.time()
                new_ver = yt_dlp.version.__version__
                logger.info(f"yt-dlp successfully updated to version {new_ver}")
                return True, f"Success: updated to {new_ver}"
            else:
                err_msg = stderr.decode().strip() or stdout.decode().strip()
                logger.error(f"pip update failed: {err_msg}")
                return False, f"pip update failed: {err_msg}"
        except Exception as e:
            logger.exception("Exception occurred during pip update")
            return False, f"Exception during update: {str(e)}"

async def trigger_auto_update_on_failure() -> None:
    """Trigger background automatic updates on yt-dlp failures if cooldown is not active."""
    now = time.time()
    if now - last_update_time >= YTDLP_COOLDOWN:
        logger.warning("Auto-updating yt-dlp in background due to request failure...")
        success, msg = await run_update()
        logger.info(f"Background auto-update completed: success={success}, msg={msg}")

def format_duration(duration: float | None) -> str:
    """Format float/int duration in seconds to H:MM:SS or M:SS string format."""
    if not duration:
        return "Neznámá"
    try:
        duration_int = int(duration)
        hours = duration_int // 3600
        minutes = (duration_int % 3600) // 60
        seconds = duration_int % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    except (ValueError, TypeError):
        return "Neznámá"

def estimate_sizes(formats: list[dict], duration: float | None) -> dict[str, int]:
    """Estimate total sizes of audio/video qualities from available formats."""
    sizes = {}
    audio_size = 0
    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            audio_size = max(audio_size, f.get("filesize") or f.get("filesize_approx") or 0)
            
    if not audio_size and duration:
        # Fallback to standard 128 kbps audio stream size estimation
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
            # Bitrate-based fallback estimation in bits per second
            bitrates = {"360": 500000, "480": 800000, "720": 1500000, "1080": 3000000, "max": 6000000}
            video_size = int((bitrates[q] / 8) * duration)

        sizes[q] = video_size + audio_size

    # Set SD resolution size and default audio-only size
    sizes["480"] = sizes["480"]
    sizes["audio"] = audio_size
    return sizes

# Simple in-memory cache for metadata to avoid duplicate requests
metadata_cache = {}

async def extract_metadata(url: str) -> dict:
    """Fetch video info and format mappings using yt-dlp with in-memory caching."""
    # Check cache first (valid for 5 minutes / 300 seconds)
    now = time.time()
    if url in metadata_cache:
        cached_time, data = metadata_cache[url]
        if now - cached_time < 300:
            logger.info(f"Serving metadata from cache for URL: {url}")
            return data

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'check_formats': False,  # Disable HEAD requests to verify format URLs (massive speedup)
        'youtube_include_dash_manifest': False,  # Skip slow DASH manifest queries
        'youtube_include_hls_manifest': False,   # Skip slow HLS manifest queries
        'remote_components': {'ejs:github'},    # Allow challenge solver script downloading to prevent YouTube throttling
    }
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    loop = asyncio.get_event_loop()
    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        data = await loop.run_in_executor(None, extract)
        # Store metadata in cache
        metadata_cache[url] = (time.time(), data)
        return data
    except Exception as e:
        logger.exception(f"yt-dlp failed to extract metadata for url: {url}")
        asyncio.create_task(trigger_auto_update_on_failure())
        raise HTTPException(status_code=400, detail=f"Chyba yt-dlp: {str(e)}")


# API Endpoints

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

    duration_str = format_duration(duration)
    
    formats = info.get("formats", [])
    sizes = estimate_sizes(formats, duration)

    has_video = any(f.get("vcodec") and f.get("vcodec") != "none" for f in formats)
    
    max_height = 0
    if has_video:
        max_height = max((f.get("height") or 0) for f in formats if f.get("vcodec") and f.get("vcodec") != "none")

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration_str,
        "uploader": uploader,
        "sizes": sizes,
        "has_video": has_video,
        "max_height": max_height
    }

@app.post("/api/download")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    downloadMode: str = Form("auto"),
    videoQuality: str = Form("1080"),
    audioBitrate: str = Form("320")
):
    """Download media using yt-dlp to a temporary folder, then stream it via FileResponse and clean up."""
    if not url:
        raise HTTPException(status_code=400, detail="URL je vyžadována")

    info = await extract_metadata(url)
    title = info.get("title", "video")
    formats = info.get("formats", [])

    # Filter carriage returns and quotes from headers
    clean_title = "".join(c for c in title if c.isalnum() or c in "._- ").strip()

    # Verify video capability to adjust fallback mode
    has_video = any(f.get("vcodec") and f.get("vcodec") != "none" for f in formats)

    download_mode = downloadMode
    if not has_video:
        if download_mode == "mute":
            raise HTTPException(
                status_code=400, 
                detail="Tento odkaz obsahuje pouze zvuk (neobsahuje žádnou video stopu)."
            )
        elif download_mode == "auto":
            download_mode = "audio"

    # Create a unique temporary directory
    download_id = str(uuid.uuid4())
    temp_dir = os.path.join("temp_downloads", download_id)
    os.makedirs(temp_dir, exist_ok=True)

    # Use %(ext)s so yt-dlp and ffmpeg can resolve final extension automatically
    output_template = os.path.join(temp_dir, f"{clean_title}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--concurrent-fragments", "5",
        "-o", output_template
    ]

    if os.path.exists(COOKIES_FILE):
        cmd.extend(["--cookiefile", COOKIES_FILE])

    # Configure modes
    if download_mode == "audio":
        cmd.extend([
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", f"{audioBitrate}k"
        ])
    elif download_mode == "mute":
        height_limit = 99999 if videoQuality == "max" else int(videoQuality)
        if height_limit == 99999:
            format_spec = "bestvideo/best"
        else:
            format_spec = f"bestvideo[height<={height_limit}]/best[height<={height_limit}]"
        cmd.extend(["-f", format_spec])
    else: # auto mode (video + audio merging)
        height_limit = 99999 if videoQuality == "max" else int(videoQuality)
        if height_limit == 99999:
            format_spec = "bestvideo+bestaudio/best"
        else:
            format_spec = f"bestvideo[height<={height_limit}]+bestaudio/best[height<={height_limit}]"
        cmd.extend([
            "-f", format_spec,
            "--merge-output-format", "mp4"
        ])

    logger.info(f"Initiating yt-dlp download: {' '.join(cmd)}")
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            err_msg = stderr.decode().strip() or stdout.decode().strip()
            logger.error(f"yt-dlp download failed: {err_msg}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Stahování selhalo: {err_msg}")
            
    except asyncio.CancelledError:
        logger.warning(f"Download request cancelled by client during server download. Cleaning up...")
        if process and process.returncode is None:
            try:
                process.kill()
                logger.info("Killed yt-dlp download subprocess due to cancellation.")
            except Exception:
                pass
            await process.wait()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    # Locate downloaded file
    files = os.listdir(temp_dir)
    if not files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Stažený soubor nebyl nalezen.")

    downloaded_filename = files[0]
    downloaded_filepath = os.path.join(temp_dir, downloaded_filename)

    # Register immediate cleanup task
    background_tasks.add_task(cleanup_temp_dir, temp_dir)

    # Resolve media type based on extension
    ext = os.path.splitext(downloaded_filename)[1].lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4a": "audio/mp4"
    }
    media_type = media_types.get(ext, "application/octet-stream")

    headers = {
        "Access-Control-Expose-Headers": "Content-Disposition"
    }

    return FileResponse(
        path=downloaded_filepath,
        filename=downloaded_filename,
        media_type=media_type,
        headers=headers
    )

if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
