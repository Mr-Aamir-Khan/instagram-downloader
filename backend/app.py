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
"""

from flask import Flask, request, jsonify, g
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
from dataclasses import dataclass, asdict, field
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
# App & Rate Limiter
# ─────────────────────────────────────────────
app = Flask(__name__)
import os
# Startup check
if os.path.exists("/etc/secrets/cookies.txt"):
    logger.info("✅ cookies.txt FOUND at /etc/secrets/cookies.txt")
else:
    logger.warning("❌ cookies.txt NOT FOUND at /etc/secrets/cookies.txt")
CORS(app, resources={r"/*": {"origins": os.getenv("ALLOWED_ORIGINS", "*")}})

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "memory://"),
)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
CACHE_TTL = int(os.getenv("CACHE_TTL", 300))          # seconds
MAX_CAROUSEL_ITEMS = int(os.getenv("MAX_CAROUSEL", 10))
api_key= os.getenv("SCRAPER_API_KEY")   
PROXY = f"http://scraperapi:{api_key}@proxy-server.scraperapi.com:8001" if api_key else ""              # optional
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
            return entry.data
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

# ─────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────
_INSTAGRAM_PATTERN = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
)

def is_valid_instagram_url(url: str) -> bool:
    return bool(_INSTAGRAM_PATTERN.search(url))

def sanitize_url(url: str) -> str:
    """Strip tracking params, normalize."""
    url = url.strip()
    # Remove query string (tracking pixels, utm, etc.)
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
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "format_sort": ["res:1080", "codec:h264", "ext:mp4"],
        "noplaylist": False,
        "socket_timeout": REQUEST_TIMEOUT,
        "nocheckcertificate": True,
        # ✅ COOKIES ADD KARO
        "cookiefile": "cookies.txt",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
        },
    }
    if PROXY:
        opts["proxy"] = PROXY
    return opts


def _classify_format(fmt: dict) -> Optional[str]:
    """Returns 'photo', 'video', or None."""
    ext = (fmt.get("ext") or "").lower()
    if ext in ("jpg", "jpeg", "png", "webp"):
        return "photo"
    vcodec = fmt.get("vcodec", "none")
    acodec = fmt.get("acodec", "none")
    if ext == "mp4" and vcodec != "none" and acodec != "none":
        return "video"
    return None


def _extract_single(info: dict, source_url: str) -> dict:
    media_type = "unknown"
    download_url = ""
    ext = ""
    thumb = info.get("thumbnail", "")

    # Check formats list first - find best video
    best_video_url = ""
    best_height = 0
    photo_url = ""

    if info.get("formats"):
        for fmt in info["formats"]:
            kind = _classify_format(fmt)
            if kind == "photo" and not photo_url:
                photo_url = fmt.get("url", "")
            elif kind == "video":
                h = fmt.get("height", 0) or 0
                if h > best_height:
                    best_height = h
                    best_video_url = fmt.get("url", "")

    # Video ko priority do
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

    if "/stories/" in source_url and media_type in ("photo", "video"):
        media_type = "story_" + media_type

    return {
        "download_url": download_url,
        "media_type": media_type,
        "ext": ext,
        "thumbnail": thumb,
        "title": (info.get("title") or "Instagram Media")[:200],
        "uploader": info.get("uploader") or info.get("uploader_id", ""),
        "has_audio": media_type in ("video", "story_video"),
        "width": info.get("width"),
        "height": info.get("height"),
        "duration": info.get("duration"),
    }

def extract_media(url: str) -> dict:
    """
    Main extraction entry point.
    Returns:
        {
            success: bool,
            items: [ { download_url, media_type, ext, ... }, ... ],
            count: int,
            cached: bool,
        }
    """
    cached = cache_get(url)
    if cached:
        cached["cached"] = True
        return cached

    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Private" in msg or "login" in msg.lower():
            raise MediaError("This post is private or requires login.", code=403)
        if "not found" in msg.lower() or "404" in msg:
            raise MediaError("Post not found or has been deleted.", code=404)
        raise MediaError(f"Could not fetch media: {msg[:200]}", code=502)
    except Exception as e:
        raise MediaError(f"Extraction failed: {str(e)[:200]}", code=500)

    items = []

    # Carousel / playlist
    if info.get("entries"):
        for entry in info["entries"][:MAX_CAROUSEL_ITEMS]:
            item = _extract_single(entry, url)
            if item["download_url"]:
                items.append(item)
    else:
        item = _extract_single(info, url)
        if item["download_url"]:
            items.append(item)

    result = {
        "success": True,
        "items": items,
        "count": len(items),
        "cached": False,
    }

    if items:
        cache_set(url, result)

    return result


# ─────────────────────────────────────────────
# Custom Error
# ─────────────────────────────────────────────
class MediaError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code


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

    if not result.get("items"):
        return jsonify({
            "success": False,
            "error": "No downloadable media found. The post may be private.",
        }), 404

    return jsonify(result), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "cache_size": len(_cache),
        "timestamp": time.time(),
    }), 200


@app.route("/metrics", methods=["GET"])
@limiter.exempt
def metrics():
    """Basic internal metrics – protect with auth in prod."""
    token = request.headers.get("X-Admin-Token", "")
    if token != os.getenv("ADMIN_TOKEN", ""):
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