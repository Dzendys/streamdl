import asyncio
import os
import urllib.parse
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx
import yt_dlp
import uvicorn
import sys
import time

app = FastAPI()

# Make templates directory if not exists
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# Auto-update state for yt-dlp
last_update_time = 0.0
update_lock = asyncio.Lock()

async def run_update(bypass_cooldown: bool = False):
    global last_update_time
    async with update_lock:
        now = time.time()
        if not bypass_cooldown and (now - last_update_time < 600):
            return False, "cooldown"
        
        try:
            process = await asyncio.create_subprocess_exec(
                "pip", "install", "--upgrade", "yt-dlp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                # Force reload of yt_dlp submodules
                to_del = [m for m in sys.modules if m.startswith('yt_dlp')]
                for m in to_del:
                    del sys.modules[m]
                import yt_dlp
                last_update_time = time.time()
                new_ver = yt_dlp.version.__version__
                return True, f"Success: updated to {new_ver}"
            else:
                err_msg = stderr.decode().strip() or stdout.decode().strip()
                return False, f"pip update failed: {err_msg}"
        except Exception as e:
            return False, f"Exception during update: {str(e)}"

async def trigger_auto_update_on_failure():
    now = time.time()
    if now - last_update_time >= 600:
        print("yt-dlp failed. Triggering background auto-update...")
        success, msg = await run_update()
        print(f"Background auto-update result: success={success}, msg={msg}")

@app.get("/api/yt-dlp/version")
async def get_yt_dlp_version():
    import yt_dlp
    return {"version": yt_dlp.version.__version__}

@app.post("/api/yt-dlp/update")
async def update_yt_dlp_endpoint():
    success, msg = await run_update(bypass_cooldown=True)
    import yt_dlp
    version = yt_dlp.version.__version__
    return {"success": success, "message": msg, "version": version}

@app.post("/api/info")
async def get_video_info(url: str = Form(...)):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    loop = asyncio.get_event_loop()
    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, extract)
    except Exception as e:
        import traceback
        traceback.print_exc()
        asyncio.create_task(trigger_auto_update_on_failure())
        raise HTTPException(status_code=400, detail=f"yt-dlp error: {str(e)}")

    title = info.get("title", "Neznámé video")
    thumbnail = info.get("thumbnail", "")
    duration = info.get("duration", 0)
    uploader = info.get("uploader", "Neznámý autor")

    if duration:
        duration_int = int(duration)
        hours = duration_int // 3600
        minutes = (duration_int % 3600) // 60
        seconds = duration_int % 60
        if hours > 0:
            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration_str = f"{minutes}:{seconds:02d}"
    else:
        duration_str = "Neznámá"

    formats = info.get("formats", [])
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

    # Also map "360p" description size to "480" since we combine 480/360 in one card
    sizes["480"] = sizes["480"]
    sizes["audio"] = audio_size

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
    download_mode = downloadMode
    video_quality = videoQuality
    audio_bitrate = audioBitrate

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Extract all formats/metadata first without format filters to avoid yt-dlp crashing
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    loop = asyncio.get_event_loop()
    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, extract)
    except Exception as e:
        asyncio.create_task(trigger_auto_update_on_failure())
        raise HTTPException(status_code=400, detail=f"yt-dlp error: {str(e)}")

    title = info.get("title", "video")
    formats = info.get("formats", [])

    # Clean filename of carriage returns or quotes
    clean_title = "".join(c for c in title if c.isalnum() or c in "._- ").strip()

    # Check if this content actually has any video streams
    has_video = any(f.get("vcodec") and f.get("vcodec") != "none" for f in formats)

    if not has_video:
        if download_mode == "mute":
            raise HTTPException(status_code=400, detail="Tento odkaz obsahuje pouze zvuk (neobsahuje žádnou video stopu).")
        elif download_mode == "auto":
            # Gracefully fallback to audio-only download mode
            download_mode = "audio"

    # Resolve format URLs and metadata in Python
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
        height_limit = 99999 if video_quality == "max" else int(video_quality)
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

    else: # auto (video + audio)
        height_limit = 99999 if video_quality == "max" else int(video_quality)
        video_formats = [f for f in formats if f.get("vcodec") and f.get("vcodec") != "none" and (f.get("height") or 0) <= height_limit]
        
        if video_formats:
            video_formats.sort(key=lambda x: (x.get("height") or 0, x.get("filesize") or x.get("filesize_approx") or 0), reverse=True)
            best_video = video_formats[0]
            
            # Check if this video format already has audio (e.g. single format format like 18 or 22 on YouTube)
            if best_video.get("acodec") and best_video.get("acodec") != "none":
                # Single format with audio: no merging needed!
                video_url = best_video.get("url")
                filesize = best_video.get("filesize") or best_video.get("filesize_approx")
                selected_ext = best_video.get("ext", "mp4")
            else:
                # Video only, we need separate audio to merge
                video_url = best_video.get("url")
                selected_ext = "mp4" # merging output is always mp4
                
                audio_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none" and f.get("vcodec") == "none"]
                if not audio_formats:
                    audio_formats = [f for f in formats if f.get("acodec") and f.get("acodec") != "none"]
                
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get("abr") or x.get("filesize") or x.get("filesize_approx") or 0, reverse=True)
                    audio_url = audio_formats[0].get("url")
                    
                # estimated total size is sum of video and audio size
                v_size = best_video.get("filesize") or best_video.get("filesize_approx") or 0
                a_size = 0
                if audio_formats:
                    a_size = audio_formats[0].get("filesize") or audio_formats[0].get("filesize_approx") or 0
                if v_size or a_size:
                    filesize = v_size + a_size
        else:
            # Fallback to default url
            video_url = info.get("url")
            filesize = info.get("filesize") or info.get("filesize_approx")
            selected_ext = info.get("ext", "mp4")

    # Stream dispatch logic
    if download_mode == "audio":
        if not audio_url:
            raise HTTPException(status_code=400, detail="Nelze získat URL audio streamu.")

        filename = f"{clean_title}.mp3"
        cmd = [
            'ffmpeg',
            '-y',
            '-i', audio_url,
            '-vn',
            '-c:a', 'libmp3lame',
            '-b:a', f'{audio_bitrate}k',
            '-f', 'mp3',
            'pipe:1'
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        async def generator():
            try:
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except:
                        pass
                    await process.wait()

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        return StreamingResponse(generator(), media_type="audio/mpeg", headers=headers)

    elif video_url and audio_url:
        # Separate video and audio streams: merge them using ffmpeg on the fly
        filename = f"{clean_title}.mp4"
        cmd = [
            'ffmpeg',
            '-y',
            '-i', video_url,
            '-i', audio_url,
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-movflags', 'faststart+frag_keyframe+empty_moov',
            '-f', 'mp4',
            'pipe:1'
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        async def generator():
            try:
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except:
                        pass
                    await process.wait()

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        return StreamingResponse(generator(), media_type="video/mp4", headers=headers)

    else:
        # Single format (e.g. video only, or fallback single-file download)
        stream_url = video_url or audio_url
        if not stream_url:
            raise HTTPException(status_code=400, detail="Nelze získat URL streamu.")

        ext = selected_ext
        filename = f"{clean_title}.{ext}"
        media_type = f"video/{ext}" if download_mode != "audio" else f"audio/{ext}"

        async def generator():
            async with httpx.AsyncClient(timeout=60.0) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                async with client.stream("GET", stream_url, headers=headers) as r:
                    async for chunk in r.aiter_bytes(chunk_size=65536):
                        yield chunk

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(filename)}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        if filesize:
            headers["Content-Length"] = str(filesize)

        return StreamingResponse(generator(), media_type=media_type, headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
