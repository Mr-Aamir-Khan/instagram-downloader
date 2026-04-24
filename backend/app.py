"""
Instagram Downloader - Production Grade
Features:
- Rate limiting (per IP + global)
- Multi-post / carousel support
- Structured error handling
- Input validation & sanitization
- Request logging
- Cache with TTL
- Health + metrics endpoint
- Proxy media endpoint (CORS fix)
"""

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import yt_dlp
import re
import os
import time
import uuid
import logging
import threading
import requests as req
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Custom Error — PEHLE define karo, baad mein use hoga
# ─────────────────────────────────────────────
class MediaError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code

# ─────────────────────────────────────────────
# App & CORS
# ─────────────────────────────────────────────
app = Flask(__name__)

# Startup check
COOKIE_PATH = os.getenv("COOKIE_FILE", "cookies.txt")
if os.path.exists(COOKIE_PATH):
    logger.info("✅ cookies.txt FOUND at %s", COOKIE_PATH)
else:
    logger.warning("❌ cookies.txt NOT FOUND at %s", COOKIE_PATH)

CORS(app, origins="*", supports_credentials=False)

# ─────────────────────────────────────────────
# Rate Limiter
# ─────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "memory://"),
)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
CACHE_TTL = int(os.getenv("CACHE_TTL", 300))
MAX_CAROUSEL_ITEMS = int(os.getenv("MAX_CAROUSEL", 10))
api_key = os.getenv("SCRAPER_API_KEY")
PROXY = f"http://scraperapi:{api_key}@proxy-server.scraperapi.com:8001" if api_key else ""
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))

# ─────────────────────────────────────────────
# Cache (thread-safe, TTL-based)
# ─────────────────────────────────────────────
@dataclass
class CacheEntry:
    data: dict
    expires_at: float

_cache: dict[str, CacheEntry] = {}
_cache_lock = threading.Lock()

def cache_get(key: str) -> Optional[dict]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry.expires_at:
            # BUG FIX: shallow copy karo taaki original dict mutate na ho
            return dict(entry.data)
        _cache.pop(key, None)
        return None

def cache_set(key: str, data: dict) -> None:
    with _cache_lock:
        _cache[key] = CacheEntry(data=data, expires_at=time.time() + CACHE_TTL)

def cache_purge_expired() -> int:
    now = time.time()
    with _cache_lock:
        expired = [k for k, v in _cache.items() if now >= v.expires_at]
        for k in expired:
            del _cache[k]
        return len(expired)

# Background thread — har 60 second mein expired cache purge karo
def _purge_loop():
    while True:
        time.sleep(60)
        try:
            purged = cache_purge_expired()
            if purged:
                logger.info("Cache purge: %d expired entries removed", purged)
        except Exception:
            pass

threading.Thread(target=_purge_loop, daemon=True).start()

# ─────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────
_INSTAGRAM_PATTERN = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
)

def is_valid_instagram_url(url: str) -> bool:
    return bool(_INSTAGRAM_PATTERN.search(url))

def sanitize_url(url: str) -> str:
    url = url.strip()
    url = url.split("?")[0].rstrip("/")
    return url

# ─────────────────────────────────────────────
# Media Extraction
# ─────────────────────────────────────────────
def _ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        # Format 2 = combined video+audio, ya best video + best audio merge
        "format": "2/bestvideo+bestaudio/best",
        "noplaylist": False,
        "socket_timeout": REQUEST_TIMEOUT,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
        },
    }
    if os.path.exists(COOKIE_PATH):
        opts["cookiefile"] = COOKIE_PATH
    if PROXY:
        opts["proxy"] = PROXY
    return opts


def _classify_format(fmt: dict) -> Optional[str]:
    """
    BUG FIX: Pehle video check karo — ext ke saath-saath vcodec bhi dekho.
    Instagram ke kuch formats mein ext nahi hoti ya m4v/webm hoti hai.
    """
    ext = (fmt.get("ext") or "").lower()
    vcodec = fmt.get("vcodec") or "none"
    acodec = fmt.get("acodec") or "none"

    # Photo formats
    if ext in ("jpg", "jpeg", "png", "webp"):
        return "photo"

    # BUG FIX: video ke liye sirf mp4 mat check karo — vcodec pe rely karo
    # acodec "none" bhi ho sakta hai (video-only stream) — woh bhi video hai
    if vcodec != "none":
        return "video"

    # Extension se fallback check
    if ext in ("mp4", "m4v", "webm", "mov"):
        return "video"

    return None

def _extract_single(info: dict, source_url: str) -> dict:
    thumb = info.get("thumbnail", "")
    best_video_url = ""
    best_height = 0
    photo_url = ""
    has_audio = False

    if info.get("formats"):
        # Step 1: Pehle format_id "2" dhundho — combined video+audio hota hai
        for fmt in info["formats"]:
            if fmt.get("format_id") == "2" and fmt.get("url"):
                best_video_url = fmt["url"]
                best_height = fmt.get("height", 0) or 0
                has_audio = True
                break

        # Step 2: Agar "2" nahi mila toh video+audio dono wala format dhundho
        if not best_video_url:
            for fmt in info["formats"]:
                ext = (fmt.get("ext") or "").lower()
                vcodec = fmt.get("vcodec") or "none"
                acodec = fmt.get("acodec") or "none"
                fmt_url = fmt.get("url", "")

                # Photo check
                if ext in ("jpg", "jpeg", "png", "webp"):
                    if not photo_url:
                        photo_url = fmt_url
                    continue

                # Video+Audio combined stream
                if vcodec != "none" and acodec != "none" and fmt_url:
                    h = fmt.get("height", 0) or 0
                    if h > best_height:
                        best_height = h
                        best_video_url = fmt_url
                        has_audio = True

        # Step 3: Sirf video only bhi nahi mila toh video-only le lo
        if not best_video_url:
            for fmt in info["formats"]:
                vcodec = fmt.get("vcodec") or "none"
                fmt_url = fmt.get("url", "")
                if vcodec != "none" and fmt_url:
                    h = fmt.get("height", 0) or 0
                    if h > best_height:
                        best_height = h
                        best_video_url = fmt_url
                        has_audio = False  # audio nahi hai

    # Priority decide karo
    if best_video_url:
        download_url = best_video_url
        media_type = "video"
        ext = "mp4"
    elif photo_url:
        download_url = photo_url
        media_type = "photo"
        ext = "jpg"
    elif info.get("display_url"):
        download_url = info["display_url"]
        media_type = "photo"
        ext = "jpg"
    elif thumb:
        download_url = thumb
        media_type = "photo"
        ext = "jpg"
    else:
        download_url = ""
        media_type = "unknown"
        ext = ""

    if "/stories/" in source_url and media_type in ("photo", "video"):
        media_type = "story_" + media_type

    return {
        "download_url": download_url,
        "media_type": media_type,
        "ext": ext,
        "thumbnail": thumb,
        "title": (info.get("title") or "Instagram Media")[:200],
        "uploader": info.get("uploader") or info.get("uploader_id", ""),
        "has_audio": has_audio,
        "width": info.get("width"),
        "height": info.get("height"),
        "duration": info.get("duration"),
    }


def extract_media(url: str) -> dict:
    cached = cache_get(url)
    if cached:
        cached["cached"] = True
        return cached

    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise MediaError("No data extracted.", code=500)

    except MediaError:
        raise  # apna error re-raise karo
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        msg_lower = msg.lower()
        if any(x in msg_lower for x in ["private", "login", "forbidden", "403"]):
            raise MediaError("This post is private or requires login.", code=403)
        if any(x in msg_lower for x in ["not found", "404"]):
            raise MediaError("Post not found or deleted.", code=404)
        raise MediaError(f"Could not fetch media: {msg[:200]}", code=502)
    except Exception as e:
        raise MediaError(f"Extraction failed: {str(e)[:200]}", code=500)

    items = []

    entries = info.get("entries")
    if entries:
        entries = list(entries)[:MAX_CAROUSEL_ITEMS]
    else:
        entries = [info]

    # BUG FIX: item append loop ke ANDAR hona chahiye — indentation fix
    for entry in entries:
        item = _extract_single(entry, url)
        if item and item.get("download_url"):   # ← ye loop ke ANDAR hai
            items.append(item)

    if not items:
        raise MediaError("No downloadable media found.", code=404)

    result = {
        "success": True,
        "items": items,
        "count": len(items),
        "cached": False,
    }

    cache_set(url, result)
    return result


# ─────────────────────────────────────────────
# Request Lifecycle
# ─────────────────────────────────────────────
@app.before_request
def attach_request_id():
    g.request_id = str(uuid.uuid4())[:8]
    g.start_time = time.time()

@app.after_request
def log_request(response):
    duration = round((time.time() - getattr(g, 'start_time', time.time())) * 1000, 1)
    logger.info(
        "[%s] %s %s → %d (%sms)",
        getattr(g, 'request_id', 'unknown'), request.method, request.path,
        response.status_code, duration,
    )
    response.headers["X-Request-ID"] = getattr(g, 'request_id', 'unknown')
    return response


# ─────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────
@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({
        "success": False,
        "error": "Rate limit exceeded. Please slow down.",
        "retry_after": e.description,
    }), 429

@app.errorhandler(404)
def not_found(_):
    return jsonify({"success": False, "error": "Endpoint not found."}), 404

@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify({"success": False, "error": "Method not allowed."}), 405

@app.errorhandler(500)
def internal_error(e):
    logger.error("Unhandled exception: %s", e, exc_info=True)
    return jsonify({"success": False, "error": "Internal server error."}), 500


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route("/download", methods=["POST"])
@limiter.limit("10 per minute")
def download():
    data = request.get_json(silent=True)
    if not data or "url" not in data:
        return jsonify({"success": False, "error": "Request body must include 'url'."}), 400

    raw_url = str(data["url"]).strip()
    if not raw_url:
        return jsonify({"success": False, "error": "URL cannot be empty."}), 400
    if len(raw_url) > 500:
        return jsonify({"success": False, "error": "URL too long."}), 400

    url = sanitize_url(raw_url)

    if not is_valid_instagram_url(url):
        return jsonify({
            "success": False,
            "error": "Invalid Instagram URL. Supported: /p/, /reel/, /tv/, /stories/",
        }), 422

    logger.info("[%s] Downloading: %s", g.request_id, url)

    try:
        result = extract_media(url)
    except MediaError as e:
        return jsonify({"success": False, "error": str(e)}), e.code
    except Exception as e:
        logger.exception("[%s] Unexpected error", g.request_id)
        return jsonify({"success": False, "error": "Unexpected server error."}), 500

    return jsonify(result), 200


@app.route("/proxy-media", methods=["GET"])
@limiter.exempt
def proxy_media():
    """Instagram CDN images/videos proxy — CORS fix"""
    from urllib.parse import urlparse

    media_url = request.args.get("url", "").strip()
    if not media_url:
        return jsonify({"error": "URL required"}), 400

    # BUG FIX: proper domain check — substring match bypass hota tha
    try:
        parsed = urlparse(media_url)
        netloc = parsed.netloc.lower()
        allowed = ("instagram.com", "cdninstagram.com", "fbcdn.net")
        if not any(netloc == d or netloc.endswith("." + d) for d in allowed):
            return jsonify({"error": "Invalid URL"}), 400
    except Exception:
        return jsonify({"error": "Malformed URL"}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.instagram.com/",
        }
        # BUG FIX: context manager use karo — connection leak fix
        with req.get(media_url, headers=headers, stream=True, timeout=15) as r:
            content_type = r.headers.get("Content-Type", "image/jpeg")
            # Content chunked yield karo
            def generate():
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            return Response(generate(), content_type=content_type)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/health", methods=["GET"])
@limiter.exempt
def health():
    return jsonify({
        "status": "ok",
        "cache_size": len(_cache),
        "timestamp": time.time(),
    }), 200


@app.route("/metrics", methods=["GET"])
@limiter.exempt
def metrics():
    token = request.headers.get("X-Admin-Token", "")
    admin_token = os.getenv("ADMIN_TOKEN")
    # BUG FIX: empty string match nahi hona chahiye
    if not token or not admin_token or token != admin_token:
        return jsonify({"error": "Unauthorized"}), 401
    purged = cache_purge_expired()
    return jsonify({
        "cache_active": len(_cache),
        "cache_purged_this_call": purged,
        "max_carousel": MAX_CAROUSEL_ITEMS,
        "cache_ttl_seconds": CACHE_TTL,
    }), 200


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    logger.info("Starting Instagram Downloader on port %d (debug=%s)", port, debug)
    app.run(debug=debug, host="0.0.0.0", port=port)