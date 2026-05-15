import asyncio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import yt_dlp

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Universal Media Extraction API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_CONCURRENT_TASKS = 5
extraction_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

async def run_extraction(opts, url):
    def extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    return await asyncio.to_thread(extract)

@app.get("/api/extract")
@limiter.limit("30/minute") 
async def extract_media(
    request: Request,
    url: str = Query(..., description="The media URL (YouTube, TikTok, Twitter, FB, Reddit, etc.)"),
    format_profile: str = Query("best", description="Quality format"),
    flatten_playlists: bool = Query(True, description="Fast playlist extraction")
):
    ydl_opts = {
        'format': format_profile,
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'extract_flat': flatten_playlists, 
        'clean_infojson': True
    }

    try:
        async with extraction_semaphore:
            info = await run_extraction(ydl_opts, url)
            source_site = info.get("extractor_key", "Unknown")
            
            if 'entries' in info:
                entries = []
                for entry in info.get('entries', []):
                    if entry: 
                        entries.append({
                            "id": entry.get("id"),
                            "title": entry.get("title", "Unknown Title"),
                            "url": entry.get("url"), 
                            "duration": entry.get("duration"),
                            "uploader": entry.get("uploader", "Unknown")
                        })
                return {
                    "status": "success",
                    "type": "playlist",
                    "source": source_site,
                    "id": info.get("id"),
                    "title": info.get("title", "Unknown Playlist"),
                    "item_count": len(entries),
                    "data": entries
                }
            else:
                thumbnails = info.get("thumbnails", [])
                best_thumbnail = thumbnails[-1]["url"] if thumbnails else info.get("thumbnail")
                direct_url = info.get("url")

                return {
                    "status": "success",
                    "type": "video",
                    "source": source_site,
                    "id": info.get("id"),
                    "title": info.get("title", "Unknown Title"),
                    "uploader": info.get("uploader", "Unknown"),
                    "thumbnail": best_thumbnail,
                    "duration": info.get("duration"),
                    "direct_url": direct_url,
                    "ext": info.get("ext", "mp4")
                }
                
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Extraction Error: Unsupported URL or Private Content. Details: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error: Service self-healing.")
