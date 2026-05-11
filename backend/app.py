"""
Instagram Downloader - Production Grade (Fixed: Carousel + Photo/Video Detection)
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
import json
import http.cookiejar as cookielib
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


class MediaError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code


app = Flask(__name__)

COOKIE_PATH = os.getenv("COOKIE_FILE", "cookies.txt")
if os.path.exists(COOKIE_PATH):
    logger.info("✅ cookies.txt FOUND at %s", COOKIE_PATH)
else:
    logger.warning("❌ cookies.txt NOT FOUND at %s", COOKIE_PATH)

CORS(
    app,
    origins="*",
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Disposition", "Content-Length"],
    supports_credentials=False,
    automatic_options=True,
)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "memory://"),
)

CACHE_TTL = int(os.getenv("CACHE_TTL", 300))
MAX_CAROUSEL_ITEMS = int(os.getenv("MAX_CAROUSEL", 10))
api_key = os.getenv("SCRAPER_API_KEY")
PROXY = f"http://scraperapi:{api_key}@proxy-server.scraperapi.com:8001" if api_key else ""
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))


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

_INSTAGRAM_PATTERN = re.compile(r"^https?://(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+")


def is_valid_instagram_url(url: str) -> bool:
    return bool(_INSTAGRAM_PATTERN.search(url))


def sanitize_url(url: str) -> str:
    url = url.strip()
    url = url.rstrip("/")
    return url


def _ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "best",
        "noplaylist": False,
        "socket_timeout": REQUEST_TIMEOUT,
        "nocheckcertificate": True,
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


def _extract_single(info: dict, source_url: str) -> dict:
    thumb = info.get("thumbnail", "")
    download_url = ""
    media_type = "unknown"
    ext = ""
    has_audio = False

    url = info.get("url", "")
    ext = (info.get("ext") or "").lower()

    if url and ext in ("mp4", "m4v", "webm", "mov"):
        download_url = url
        media_type = "video"
        has_audio = True
    elif url and ext in ("jpg", "jpeg", "png", "webp"):
        download_url = url
        media_type = "photo"
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
        "has_audio": has_audio,
        "width": info.get("width"),
        "height": info.get("height"),
        "duration": info.get("duration"),
    }


def extract_photo_post(url: str) -> dict:
    """Fallback for single photo when yt-dlp fails (only for /p/ URLs)."""
    match = re.search(r'/p/([^/]+)', url)
    if not match:
        raise MediaError("Invalid post URL", code=422)

    shortcode = match.group(1)
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
    }

    resp = req.get(embed_url, headers=headers, timeout=15, verify=False)
    if resp.status_code != 200:
        raise MediaError("Could not fetch post", code=502)

    html = resp.text

    img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+dst-jpg_e15_fr[^"]+)"', html)
    if not img_match:
        img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+p1080x1080[^"]+)"', html)
    if not img_match:
        img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+\.jpg[^"]+)"', html)

    if not img_match:
        raise MediaError("No image found in post", code=404)

    img_url = img_match.group(1).replace("&amp;", "&").replace("\\/", "/")

    return {
        "download_url": img_url,
        "media_type": "photo",
        "ext": "jpg",
        "thumbnail": img_url,
        "title": "Instagram Photo",
        "uploader": "",
        "has_audio": False,
        "width": None,
        "height": None,
        "duration": None,
    }


# ------------------------- GRAPHQL EXTRACTION (Fixes carousel) -------------------------
def _extract_graphql_node(node: dict) -> Optional[dict]:
    """Convert a GraphQL media node into our standard item format."""
    typename = node.get("__typename", "")
    if typename == "GraphVideo":
        video_url = node.get("video_url", "")
        if video_url:
            return {
                "download_url": video_url,
                "media_type": "video",
                "ext": "mp4",
                "thumbnail": node.get("display_url", ""),
                "title": "Instagram Video",
                "uploader": node.get("owner", {}).get("username", ""),
                "has_audio": True,
                "width": node.get("dimensions", {}).get("width"),
                "height": node.get("dimensions", {}).get("height"),
                "duration": node.get("video_duration"),
            }
    elif typename in ("GraphImage", "GraphStoryImage"):
        img_url = node.get("display_url", "")
        if img_url:
            return {
                "download_url": img_url,
                "media_type": "photo",
                "ext": "jpg",
                "thumbnail": img_url,
                "title": "Instagram Photo",
                "uploader": node.get("owner", {}).get("username", ""),
                "has_audio": False,
                "width": node.get("dimensions", {}).get("width"),
                "height": node.get("dimensions", {}).get("height"),
                "duration": None,
            }
    return None


def extract_with_graphql(url: str) -> dict:
    """Extract all media items from an Instagram post using GraphQL endpoint."""
    match = re.search(r'(instagram\.com/(p|reel|tv|stories)/([\w\-]+))', url)
    if not match:
        raise MediaError("Invalid Instagram URL for GraphQL extraction", 400)

    shortcode = match.group(3)
    api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=1"

    session = req.Session()
    retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    if PROXY:
        session.proxies = {"http": PROXY, "https": PROXY}
    session.verify = False

    # Load cookies if available
    if os.path.exists(COOKIE_PATH):
        cj = cookielib.MozillaCookieJar(COOKIE_PATH)
        cj.load(ignore_expires=True)
        session.cookies.update(cj)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://www.instagram.com/",
    }

    try:
        resp = session.get(api_url, headers=headers, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        raise MediaError(f"GraphQL request failed: {str(e)[:100]}", 502)

    if resp.status_code != 200:
        raise MediaError(f"GraphQL endpoint returned {resp.status_code}", 502)

    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise MediaError("Invalid JSON from Instagram GraphQL", 502)

    graphql = data.get("graphql", {})
    media = graphql.get("shortcode_media", {})
    if not media:
        raise MediaError("No media data found in GraphQL response", 404)

    items = []
    # Carousel (sidecar) handling
    if media.get("__typename") == "GraphSidecar":
        edges = media.get("edge_sidecar_to_children", {}).get("edges", [])
        for edge in edges[:MAX_CAROUSEL_ITEMS]:
            node = edge.get("node", {})
            item = _extract_graphql_node(node)
            if item and item.get("download_url"):
                items.append(item)
    else:
        # Single photo/video
        item = _extract_graphql_node(media)
        if item and item.get("download_url"):
            items.append(item)

    if not items:
        raise MediaError("No downloadable media found in GraphQL data", 404)

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "cached": False,
    }


# ------------------------- MAIN EXTRACTION WITH FALLBACK -------------------------
def extract_media(url: str) -> dict:
    cached = cache_get(url)
    if cached:
        cached["cached"] = True
        return cached

    # First attempt: yt-dlp (fast, handles reels and videos well)
    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise MediaError("No data extracted.", code=500)

        items = []
        entries = info.get("entries")
        if entries:
            entries = list(entries)[:MAX_CAROUSEL_ITEMS]
        else:
            entries = [info]

        for entry in entries:
            item = _extract_single(entry, url)
            if item and item.get("download_url"):
                items.append(item)

        if items:
            result = {"success": True, "items": items, "count": len(items), "cached": False}
            cache_set(url, result)
            return result

        # If yt-dlp returned no items, fall through to GraphQL
        raise MediaError("yt-dlp returned no items, falling back to GraphQL", code=500)

    except MediaError as e:
        # Only re-raise if it's a critical permission error; otherwise try GraphQL
        if e.code in (403, 404) and "private" in str(e).lower():
            raise
        logger.warning("[%s] yt-dlp failed (%s), trying GraphQL fallback", g.request_id, str(e))
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if "private" in msg or "login" in msg or "forbidden" in msg:
            raise MediaError("This post is private or requires login.", code=403)
        if "not found" in msg or "404" in msg:
            logger.warning("[%s] yt-dlp said not found, will try GraphQL", g.request_id)
        else:
            logger.warning("[%s] yt-dlp download error: %s", g.request_id, msg)
    except Exception as e:
        logger.warning("[%s] yt-dlp unexpected error: %s", g.request_id, str(e))

    # Fallback: GraphQL extraction
    try:
        result = extract_with_graphql(url)
        cache_set(url, result)
        return result
    except MediaError as e:
        raise e
    except Exception as e:
        logger.exception("[%s] GraphQL fallback failed", g.request_id)
        raise MediaError(f"All extraction methods failed: {str(e)[:200]}", code=500)


# ----------------------------------------------------------------------
# Middleware & Routes (unchanged except /dl minor improvement)
# ----------------------------------------------------------------------

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response


@app.before_request
def attach_request_id():
    g.request_id = str(uuid.uuid4())[:8]
    g.start_time = time.time()


@app.after_request
def log_request(response):
    duration = round((time.time() - getattr(g, "start_time", time.time())) * 1000, 1)
    logger.info(
        "[%s] %s %s → %d (%sms)",
        getattr(g, "request_id", "unknown"),
        request.method,
        request.path,
        response.status_code,
        duration,
    )
    response.headers["X-Request-ID"] = getattr(g, "request_id", "unknown")
    return response


@app.errorhandler(429)
def too_many_requests(e):
    return (
        jsonify(
            {
                "success": False,
                "error": "Rate limit exceeded. Please slow down.",
                "retry_after": e.description,
            }
        ),
        429,
    )


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
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Invalid Instagram URL. Supported: /p/, /reel/, /tv/, /stories/",
                }
            ),
            422,
        )

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
    from urllib.parse import urlparse

    media_url = request.args.get("url", "").strip()
    if not media_url:
        return jsonify({"error": "URL required"}), 400

    force_download = request.args.get("dl", "0") == "1"
    filename = request.args.get("filename", "instaget_media").strip()

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
        proxies = {"http": PROXY, "https": PROXY} if PROXY else None

        with req.get(
            media_url, headers=headers, stream=True, timeout=60, proxies=proxies, verify=False
        ) as r:
            content_type = r.headers.get("Content-Type", "application/octet-stream")
            content_length = r.headers.get("Content-Length")

            def generate():
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk

            response = Response(generate(), content_type=content_type)

            if force_download:
                response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
                response.headers["Content-Type"] = "application/octet-stream"

            if content_length:
                response.headers["Content-Length"] = content_length

            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Expose-Headers"] = (
                "Content-Disposition, Content-Length"
            )

            return response

    except Exception as e:
        logger.exception("[%s] Proxy error", g.request_id)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/dl", methods=["GET"])
@limiter.exempt
def dl():
    import tempfile, shutil

    url = request.args.get("url", "").strip()
    index = int(request.args.get("index", 0))

    if not url or not is_valid_instagram_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    try:
        tmpdir = tempfile.mkdtemp()
        opts = _ydl_opts()
        opts["skip_download"] = False
        opts["outtmpl"] = f"{tmpdir}/%(autonumber)s.%(ext)s"
        opts["format"] = "best"
        opts["noplaylist"] = False

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as e:
            if "no video in this post" in str(e).lower():
                shutil.rmtree(tmpdir, ignore_errors=True)
                try:
                    photo = extract_photo_post(sanitize_url(url))
                    photo_url = photo["download_url"]
                    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
                    r = req.get(
                        photo_url,
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Referer": "https://www.instagram.com/",
                        },
                        timeout=30,
                        proxies=proxies,
                        verify=False,
                    )
                    response = Response(r.content, content_type="image/jpeg")
                    response.headers[
                        "Content-Disposition"
                    ] = f'attachment; filename="instaget_photo_{index+1}.jpg"'
                    response.headers["Access-Control-Allow-Origin"] = "*"
                    return response
                except Exception as pe:
                    return jsonify({"error": f"Photo download failed: {str(pe)}"}), 500
            raise

        files = sorted(os.listdir(tmpdir))
        if not files:
            return jsonify({"error": "Download failed"}), 500

        index = min(index, len(files) - 1)
        filepath = os.path.join(tmpdir, files[index])
        ext = filepath.split(".")[-1]

        def generate():
            try:
                with open(filepath, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        if ext in ("jpg", "jpeg", "png", "webp"):
            content_type = f"image/{ext}"
        else:
            content_type = "video/mp4"

        response = Response(generate(), content_type=content_type)
        response.headers[
            "Content-Disposition"
        ] = f'attachment; filename="instaget_media_{index+1}.{ext}"'
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    except Exception as e:
        logger.exception("DL error")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
@limiter.exempt
def health():
    return (
        jsonify(
            {
                "status": "ok",
                "cache_size": len(_cache),
                "timestamp": time.time(),
            }
        ),
        200,
    )


@app.route("/metrics", methods=["GET"])
@limiter.exempt
def metrics():
    token = request.headers.get("X-Admin-Token", "")
    admin_token = os.getenv("ADMIN_TOKEN")
    if not token or not admin_token or token != admin_token:
        return jsonify({"error": "Unauthorized"}), 401
    purged = cache_purge_expired()
    return (
        jsonify(
            {
                "cache_active": len(_cache),
                "cache_purged_this_call": purged,
                "max_carousel": MAX_CAROUSEL_ITEMS,
                "cache_ttl_seconds": CACHE_TTL,
            }
        ),
        200,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    logger.info("Starting Instagram Downloader on port %d (debug=%s)", port, debug)
    app.run(debug=debug, host="0.0.0.0", port=port)