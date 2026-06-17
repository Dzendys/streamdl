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
TEMP_DIR = "temp_downloads"

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
    """Clean up any leftover files inside temp downloads folder on system startup."""
    if os.path.exists(TEMP_DIR):
        logger.info(f"Cleaning up leftover temporary downloads inside {TEMP_DIR} on startup...")
        for item in os.listdir(TEMP_DIR):
            item_path = os.path.join(TEMP_DIR, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            except Exception as e:
                logger.error(f"Failed to delete {item_path} on startup: {e}")

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

async def get_installed_ytdlp_version() -> str:
    """Get the currently installed version of yt-dlp on disk by running a subprocess."""
    try:
        process = await asyncio.create_subprocess_exec(
            "python", "-c", "import yt_dlp; print(yt_dlp.version.__version__)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        return stdout.decode().strip()
    except Exception:
        return ""

async def restart_server_soon():
    """Schedule process exit after a brief delay, allowing HTTP response to be sent."""
    await asyncio.sleep(1.0)
    logger.info("Restarting application container to cleanly load the updated yt-dlp version...")
    os._exit(0)

last_update_time = 0.0
update_lock = asyncio.Lock()

async def run_update(bypass_cooldown: bool = False) -> tuple[bool, str]:
    """Run an upgrade of yt-dlp via pip install and trigger a clean restart if a new version is detected."""
    global last_update_time
    async with update_lock:
        now = time.time()
        if not bypass_cooldown and (now - last_update_time < YTDLP_COOLDOWN):
            return False, "cooldown"

        logger.info("Checking current yt-dlp version on disk...")
        old_ver = await get_installed_ytdlp_version()

        logger.info("Executing pip upgrade for yt-dlp...")
        try:
            process = await asyncio.create_subprocess_exec(
                "pip", "install", "--upgrade", "yt-dlp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                last_update_time = time.time()
                new_ver = await get_installed_ytdlp_version()
                in_memory_ver = yt_dlp.version.__version__
                
                if new_ver != in_memory_ver:
                    logger.info(f"yt-dlp upgraded from {in_memory_ver} to {new_ver}. Scheduling server restart...")
                    asyncio.create_task(restart_server_soon())
                    return True, f"Success: updated to {new_ver} (restarting server to apply)"
                else:
                    logger.info(f"yt-dlp is already at the latest version: {new_ver}")
                    return True, f"Already up-to-date: {new_ver}"
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

LANG_MAP = {
    'cs': 'Čeština',
    'en': 'Angličtina',
    'sk': 'Slovenština',
    'de': 'Němčina',
    'fr': 'Francouzština',
    'es': 'Španělština',
    'it': 'Italština',
    'pl': 'Polština',
    'ru': 'Ruština',
    'ja': 'Japonština',
    'zh': 'Čínština',
    'ko': 'Korejština',
    'uk': 'Ukrajinština',
}

def format_srt(transcript: list[dict]) -> str:
    """Format transcript segments into standard SRT subtitle format."""
    srt = []
    for i, entry in enumerate(transcript, 1):
        start = entry['start']
        end = start + entry['duration']
        
        def format_time(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            
        srt.append(f"{i}\n{format_time(start)} --> {format_time(end)}\n{entry['text']}")
    return "\n\n".join(srt) + "\n"

def format_vtt(transcript: list[dict]) -> str:
    """Format transcript segments into standard WEBVTT subtitle format."""
    vtt = ["WEBVTT\n"]
    for i, entry in enumerate(transcript, 1):
        start = entry['start']
        end = start + entry['duration']
        
        def format_time(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
            
        vtt.append(f"{i}\n{format_time(start)} --> {format_time(end)}\n{entry['text']}")
    return "\n\n".join(vtt) + "\n"

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

# Dictionary to store active download jobs
download_jobs: dict = {}

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

def _fmt_bytes(n: float | int | None) -> str:
    """Format a byte count to a human-readable string (e.g. '23.4 MiB')."""
    if not n or n <= 0:
        return '?'
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TiB'


def _build_ydl_opts(
    output_template: str,
    download_mode: str,
    video_quality: str,
    audio_bitrate: str,
    threads: int,
) -> dict:
    """Build a yt-dlp YoutubeDL options dict based on the requested download mode."""
    opts: dict = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'outtmpl': output_template,
        'concurrent_fragment_downloads': threads,
        'noprogress': False,
    }

    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    if download_mode == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['writethumbnail'] = True
        opts['postprocessors'] = [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': audio_bitrate,
            },
            {
                'key': 'EmbedThumbnail',
            }
        ]
    elif download_mode == 'mute':
        h = 99999 if video_quality == 'max' else int(video_quality)
        opts['format'] = 'bestvideo/best' if h == 99999 else f'bestvideo[height<={h}]/best[height<={h}]/best'
    else:  # auto — video + audio, fallback for audio-only sources
        h = 99999 if video_quality == 'max' else int(video_quality)
        opts['format'] = (
            'bestvideo+bestaudio/bestaudio/best' if h == 99999
            else f'bestvideo[height<={h}]+bestaudio/bestvideo+bestaudio/bestaudio/best[height<={h}]/best'
        )
        opts['merge_output_format'] = 'mp4'

    return opts


async def stream_download(download_id: str, ydl_opts: dict, url: str, temp_dir: str) -> None:
    """
    Run yt-dlp via its Python API in a thread executor and push structured
    progress events to the job's asyncio queue in real-time.

    Using the Python API with progress_hooks avoids all pipe-buffering issues
    that arise when reading subprocess stdout/stderr.
    """
    job = download_jobs[download_id]
    queue: asyncio.Queue = job['queue']
    loop = asyncio.get_event_loop()

    def _push(event: dict) -> None:
        """Thread-safe push to the asyncio queue."""
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def progress_hook(d: dict) -> None:
        """Called by yt-dlp on every progress update (runs in the executor thread)."""
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes') or 0
            total      = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            speed      = d.get('speed') or 0
            eta_s      = d.get('eta')

            percent  = round(downloaded / total * 100, 1) if total > 0 else 0
            eta_str  = f"{int(eta_s // 60)}:{int(eta_s % 60):02d}" if eta_s else ''

            _push({
                'type':    'progress',
                'percent': percent,
                'downloaded': _fmt_bytes(downloaded),
                'total':   _fmt_bytes(total),
                'speed':   (_fmt_bytes(speed) + '/s') if speed else '',
                'eta':     eta_str,
            })

        elif d['status'] == 'finished':
            # Fragment/single-file download done — postprocessing may follow
            _push({'type': 'status', 'phase': 'processing'})

    def postprocessor_hook(d: dict) -> None:
        """Called when a postprocessor (FFmpeg merge / audio extract) starts or finishes."""
        if d['status'] == 'started':
            pp = d.get('postprocessor', '')
            if 'Merger' in pp:
                _push({'type': 'status', 'phase': 'merging'})
            elif 'Audio' in pp or 'Extract' in pp:
                _push({'type': 'status', 'phase': 'converting'})

    def run() -> None:
        """Blocking download — runs in a thread pool executor."""
        import yt_dlp as _yt  # import inside thread to pick up any runtime reloads
        opts = {
            **ydl_opts,
            'progress_hooks':      [progress_hook],
            'postprocessor_hooks': [postprocessor_hook],
        }
        with _yt.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        await loop.run_in_executor(None, run)

        files = [
            f for f in os.listdir(temp_dir)
            if f.endswith(('.mp3', '.mp4', '.mkv', '.webm', '.m4a'))
        ]
        if files:
            filename = files[0]
            job['filepath'] = os.path.join(temp_dir, filename)
            job['filename'] = filename
            job['status']   = 'done'
            await queue.put({'type': 'done', 'filename': filename})
        else:
            job['status'] = 'error'
            await queue.put({'type': 'error', 'message': 'Soubor po stažení nenalezen'})

    except Exception as e:
        logger.exception(f"stream_download error for job {download_id}")
        job['status'] = 'error'
        await queue.put({'type': 'error', 'message': str(e)})
    finally:
        await queue.put(None)  # Sentinel — signals end of SSE stream



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

    # Extract subtitles information using youtube-transcript-api
    subtitles = []
    auto_subtitles = []
    
    match = re.search(r'(?:v=|\/)([\w-]{11})(?:\?|&|$|/)', url)
    if match:
        video_id = match.group(1)
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            
            for t in transcript_list:
                if not t.is_generated:
                    subtitles.append({
                        "code": t.language_code,
                        "name": LANG_MAP.get(t.language_code, t.language),
                        "type": "native"
                    })
                else:
                    if t.language_code in LANG_MAP:
                        auto_subtitles.append({
                            "code": t.language_code,
                            "name": LANG_MAP[t.language_code],
                            "type": "auto"
                        })
            
            # Offer auto-translation to cs/en if they aren't already present
            has_cs = any(s['code'] == 'cs' for s in subtitles) or any(s['code'] == 'cs' for s in auto_subtitles)
            has_en = any(s['code'] == 'en' for s in subtitles) or any(s['code'] == 'en' for s in auto_subtitles)
            
            if not has_cs:
                auto_subtitles.append({
                    "code": "cs",
                    "name": "Čeština (automatický překlad)",
                    "type": "translate"
                })
            if not has_en:
                auto_subtitles.append({
                    "code": "en",
                    "name": "Angličtina (automatický překlad)",
                    "type": "translate"
                })
        except Exception as e:
            logger.info(f"Could not load transcripts for {video_id}: {e}")

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration": format_duration(duration),
        "uploader": uploader,
        "sizes": sizes,
        "has_video": has_video,
        "max_height": max_height,
        "subtitles": subtitles,
        "auto_subtitles": auto_subtitles,
    }


@app.get("/api/subtitles")
async def download_subtitles(url: str, lang: str, type: str, format: str):
    """Download and format subtitles for a YouTube video on the fly."""
    if not url or not lang:
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    if format not in ["srt", "vtt"]:
        raise HTTPException(status_code=400, detail="Invalid format. Supported: srt, vtt")
        
    match = re.search(r'(?:v=|\/)([\w-]{11})(?:\?|&|$|/)', url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    video_id = match.group(1)
    
    video_title = "titulky"
    try:
        info = await extract_metadata(url)
        video_title = info.get("title", "titulky")
        video_title = re.sub(r'[\\/*?:"<>|]', "", video_title)
        video_title = video_title.replace(" ", "_")
    except Exception:
        pass
        
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        
        transcript_obj = None
        
        if type in ["native", "auto"]:
            try:
                transcript_obj = transcript_list.find_transcript([lang])
            except Exception:
                pass
                
        if not transcript_obj:
            try:
                first_t = next(iter(transcript_list))
                transcript_obj = first_t.translate(lang)
            except Exception as te:
                raise HTTPException(status_code=404, detail=f"Nelze přeložit titulky do jazyka {lang}: {str(te)}")
                
        transcript_data = transcript_obj.fetch()
        
        import html
        cleaned_data = []
        for entry in transcript_data:
            text = html.unescape(entry.text)
            text = re.sub(r'<[^>]+>', '', text)
            cleaned_data.append({
                'text': text,
                'start': entry.start,
                'duration': entry.duration
            })
            
        if format == "srt":
            content = format_srt(cleaned_data)
            media_type = "application/x-subrip"
            filename = f"{video_title}.{lang}.srt"
        else:
            content = format_vtt(cleaned_data)
            media_type = "text/vtt"
            filename = f"{video_title}.{lang}.vtt"
            
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\""
            }
        )
    except Exception as e:
        logger.exception("Failed to download subtitles")
        raise HTTPException(status_code=500, detail=f"Chyba při stahování titulků: {str(e)}")


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
    temp_dir = os.path.join(TEMP_DIR, download_id)
    os.makedirs(temp_dir, exist_ok=True)

    output_template = os.path.join(temp_dir, f"{clean_title}.%(ext)s")
    ydl_opts = _build_ydl_opts(output_template, download_mode, videoQuality, audioBitrate, threads)

    download_jobs[download_id] = {
        "status": "running",
        "queue": asyncio.Queue(),
        "temp_dir": temp_dir,
        "filepath": None,
        "filename": None,
        "error": None,
        "created_at": time.time(),
    }

    logger.info(f"Starting download job {download_id} | mode={download_mode} quality={videoQuality} url={url}")
    asyncio.create_task(stream_download(download_id, ydl_opts, url, temp_dir))

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
