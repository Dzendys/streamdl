import asyncio
import os
import urllib.parse
import sys
import time
import logging
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import httpx
import yt_dlp
import uvicorn

# Configure professional logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("streamydl")

# Load Configuration from Environment Variables
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")
YTDLP_COOLDOWN = int(os.getenv("YTDLP_COOLDOWN", "600"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
MAX_STREAM_TIMEOUT = float(os.getenv("MAX_STREAM_TIMEOUT", "60.0"))

app = FastAPI(title="StreamyDL API")

# Ensure required directories exist and mount static files
os.makedirs("templates", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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

async def extract_metadata(url: str) -> dict:
    """Fetch video info and format mappings using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    loop = asyncio.get_event_loop()
    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        return await loop.run_in_executor(None, extract)
    except Exception as e:
        logger.exception(f"yt-dlp failed to extract metadata for url: {url}")
        asyncio.create_task(trigger_auto_update_on_failure())
        raise HTTPException(status_code=400, detail=f"Chyba yt-dlp: {str(e)}")

# Realtime Streaming Generators

async def ffmpeg_audio_generator(process: asyncio.subprocess.Process):
    """Yield transcoded audio chunks from ffmpeg stdout and ensure process cleanup."""
    try:
        while True:
            chunk = await process.stdout.read(65536)
            if not chunk:
                break
            yield chunk
    except asyncio.CancelledError:
        logger.info("ffmpeg audio stream cancelled by client.")
        raise
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except Exception:
                pass
            await process.wait()

async def ffmpeg_merge_generator(process: asyncio.subprocess.Process):
    """Yield merged mp4 chunks from ffmpeg stdout and ensure process cleanup."""
    try:
        while True:
            chunk = await process.stdout.read(65536)
            if not chunk:
                break
            yield chunk
    except asyncio.CancelledError:
        logger.info("ffmpeg video+audio merge stream cancelled by client.")
        raise
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except Exception:
                pass
            await process.wait()

async def httpx_stream_generator(stream_url: str):
    """Yield raw stream bytes directly from remote stream URL using HTTPX client."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient(timeout=MAX_STREAM_TIMEOUT) as client:
            async with client.stream("GET", stream_url, headers=headers) as r:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    yield chunk
    except asyncio.CancelledError:
        logger.info("Direct HTTP stream cancelled by client.")
        raise


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
    url: str = Form(...),
    downloadMode: str = Form("auto"),
    videoQuality: str = Form("1080"),
    audioBitrate: str = Form("320")
):
    """Stream media file directly through memory proxy, transcoding or merging on the fly."""
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

    audio_url = None
    video_url = None
    filesize = None
    selected_ext = "mp4"

    if download_mode == "audio":
        audio_only_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none" and f.get("vcodec") == "none"]
        if not audio_only_formats:
            audio_only_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none"]
        
        if audio_only_formats:
            audio_only_formats.sort(key=lambda x: x.get("abr") or x.get("filesize") or x.get("filesize_approx") or 0, reverse=True)
            best_audio = audio_only_formats[0]
            audio_url = best_audio.get("url")
            filesize = best_audio.get("filesize") or best_audio.get("filesize_approx")
        else:
            audio_url = info.get("url")
            filesize = info.get("filesize") or info.get("filesize_approx")

    elif download_mode == "mute":
        height_limit = 99999 if videoQuality == "max" else int(videoQuality)
        video_only_formats = [f for f in formats if f.get("vcodec") and f.get("vcodec") != "none" and (f.get("height") or 0) <= height_limit]
        if video_only_formats:
            video_only_formats.sort(key=lambda x: (x.get("height") or 0, x.get("filesize") or x.get("filesize_approx") or 0), reverse=True)
            best_video = video_only_formats[0]
            video_url = best_video.get("url")
            filesize = best_video.get("filesize") or best_video.get("filesize_approx")
            selected_ext = best_video.get("ext", "mp4")
        else:
            video_url = info.get("url")
            filesize = info.get("filesize") or info.get("filesize_approx")
            selected_ext = info.get("ext", "mp4")

    else: # auto mode (video + audio merging)
        height_limit = 99999 if videoQuality == "max" else int(videoQuality)
        video_formats = [f for f in formats if f.get("vcodec") and f.get("vcodec") != "none" and (f.get("height") or 0) <= height_limit]
        
        if video_formats:
            video_formats.sort(key=lambda x: (x.get("height") or 0, x.get("filesize") or x.get("filesize_approx") or 0), reverse=True)
            best_video = video_formats[0]
            
            # Single stream with audio: bypass merging pipeline
            if best_video.get("acodec") and best_video.get("acodec") != "none":
                video_url = best_video.get("url")
                filesize = best_video.get("filesize") or best_video.get("filesize_approx")
                selected_ext = best_video.get("ext", "mp4")
            else:
                video_url = best_video.get("url")
                selected_ext = "mp4"
                
                audio_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none" and f.get("vcodec") == "none"]
                if not audio_formats:
                    audio_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none"]
                
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get("abr") or x.get("filesize") or x.get("filesize_approx") or 0, reverse=True)
                    audio_url = audio_formats[0].get("url")
                    
                v_size = best_video.get("filesize") or best_video.get("filesize_approx") or 0
                a_size = 0
                if audio_formats:
                    a_size = audio_formats[0].get("filesize") or audio_formats[0].get("filesize_approx") or 0
                if v_size or a_size:
                    filesize = v_size + a_size
        else:
            video_url = info.get("url")
            filesize = info.get("filesize") or info.get("filesize_approx")
            selected_ext = info.get("ext", "mp4")

    # Generate streams based on resolved parameters
    if download_mode == "audio":
        if not audio_url:
            raise HTTPException(status_code=400, detail="Nelze získat URL audio streamu.")

        filename = f"{clean_title}.mp3"
        cmd = [
            'ffmpeg', '-y', '-i', audio_url, '-vn',
            '-c:a', 'libmp3lame', '-b:a', f'{audioBitrate}k',
            '-f', 'mp3', 'pipe:1'
        ]

        logger.info(f"Streaming audio: {filename} at {audioBitrate} kbps")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        return StreamingResponse(ffmpeg_audio_generator(process), media_type="audio/mpeg", headers=headers)

    elif video_url and audio_url:
        filename = f"{clean_title}.mp4"
        cmd = [
            'ffmpeg', '-y', '-i', video_url, '-i', audio_url,
            '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy',
            '-movflags', 'faststart+frag_keyframe+empty_moov',
            '-f', 'mp4', 'pipe:1'
        ]

        logger.info(f"Streaming merged video and audio: {filename}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        return StreamingResponse(ffmpeg_merge_generator(process), media_type="video/mp4", headers=headers)

    else:
        # Single file download directly piped from source HTTP stream
        stream_url = video_url or audio_url
        if not stream_url:
            raise HTTPException(status_code=400, detail="Nelze získat URL streamu.")

        ext = selected_ext
        filename = f"{clean_title}.{ext}"
        media_type = f"video/{ext}" if download_mode != "audio" else f"audio/{ext}"

        logger.info(f"Streaming direct single format target: {filename}")
        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        if filesize:
            headers["Content-Length"] = str(filesize)

        return StreamingResponse(httpx_stream_generator(stream_url), media_type=media_type, headers=headers)

if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
