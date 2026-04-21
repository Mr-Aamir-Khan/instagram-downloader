"""
Instagram Video/Photo/Story Downloader - Flask Backend (FIXED v4.0)
Fixes:
  - Photos (single + carousel) now extracted correctly
  - Stories handled properly
  - Better format selection logic
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import time
import os
import threading
import urllib.request

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

_cache = {}

def is_instagram_url(url: str) -> bool:
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))

def is_story_url(url: str) -> bool:
    return "/stories/" in url

def get_best_format(formats):
    """Pick best video or image format from formats list."""
    best_video = None
    best_video_height = 0
    best_image = None
    best_image_quality = 0

    for fmt in formats:
        ext = (fmt.get("ext") or "").lower()
        url = fmt.get("url", "")
        if not url:
            continue

        vcodec = fmt.get("vcodec") or ""
        acodec = fmt.get("acodec") or ""
        height = fmt.get("height") or 0

        # Video format (has actual video codec)
        if ext in ("mp4", "webm", "mov") and vcodec and vcodec != "none":
            if height > best_video_height:
                best_video = fmt
                best_video_height = height

        # Image format
        if ext in ("jpg", "jpeg", "png", "webp"):
            quality = height or fmt.get("quality") or 0
            if quality > best_image_quality:
                best_image = fmt
                best_image_quality = quality

    return best_video, best_image


def extract_single_entry(entry):
    """Extract download_url, media_type, ext from a single info_dict entry."""
    download_url = ""
    media_type = "unknown"
    ext = ""

    entry_url = entry.get("url", "")
    entry_ext = (entry.get("ext") or "").lower()

    # Direct URL with known extension
    if entry_url:
        if entry_ext in ("mp4", "webm", "mov"):
            return entry_url, "video", entry_ext
        if entry_ext in ("jpg", "jpeg", "png", "webp"):
            return entry_url, "photo", entry_ext

    # Try formats list
    if "formats" in entry and entry["formats"]:
        best_video, best_image = get_best_format(entry["formats"])
        if best_video:
            return best_video["url"], "video", best_video.get("ext", "mp4")
        if best_image:
            return best_image["url"], "photo", best_image.get("ext", "jpg")

    # Fallback: sniff extension from URL
    if entry_url:
        u = entry_url.lower().split("?")[0]
        if u.endswith((".mp4", ".webm")):
            return entry_url, "video", "mp4"
        if u.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return entry_url, "photo", "jpg"

    # Last resort: thumbnail as photo
    thumb = entry.get("thumbnail") or entry.get("display_url")
    if thumb:
        return thumb, "photo", "jpg"

    return download_url, media_type, ext


def extract_media_info(url: str) -> dict:
    if len(_cache) > 50:
        _cache.clear()

    if url in _cache:
        print(f"Cache hit: {url}")
        return _cache[url]

    is_story = is_story_url(url)
    print(f"Processing URL: {url} | is_story={is_story}")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        # Request best quality
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    uploader = (
        info.get("uploader")
        or info.get("uploader_id")
        or info.get("channel")
        or ""
    )
    title = info.get("title") or "Instagram Media"
    thumbnail = info.get("thumbnail") or ""
    duration = info.get("duration")

    # ── Thumbnail: pick highest-res from thumbnails list ──────────────────
    if not thumbnail and info.get("thumbnails"):
        try:
            best = max(
                info["thumbnails"],
                key=lambda x: (x.get("height") or 0) + (x.get("preference") or 0),
            )
            thumbnail = best.get("url", "")
        except Exception:
            pass

    download_url = ""
    media_type = "unknown"
    ext = ""
    carousel_urls = []  # extra items for carousel

    # ── CASE 1: Carousel / Sidecar (entries list) ─────────────────────────
    entries = info.get("entries") or []
    if entries:
        print(f"Entries found: {len(entries)}")
        for i, entry in enumerate(entries):
            u, mt, ex = extract_single_entry(entry)
            if u:
                if i == 0:
                    download_url, media_type, ext = u, mt, ex
                    if not thumbnail and entry.get("thumbnail"):
                        thumbnail = entry["thumbnail"]
                else:
                    carousel_urls.append({"url": u, "media_type": mt, "ext": ex})

    # ── CASE 2: Single item ───────────────────────────────────────────────
    if not download_url:
        download_url, media_type, ext = extract_single_entry(info)

    # ── CASE 3: Fallback — display_url or thumbnail ───────────────────────
    if not download_url:
        disp = info.get("display_url")
        if disp:
            download_url, media_type, ext = disp, "photo", "jpg"
        elif thumbnail:
            download_url, media_type, ext = thumbnail, "photo", "jpg"

    # ── Normalise ext ─────────────────────────────────────────────────────
    ext = ext.lstrip(".") if ext else ""
    if not ext:
        dl_lower = download_url.lower().split("?")[0]
        if dl_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
            ext = "jpg"
        elif dl_lower.endswith((".mp4", ".webm")):
            ext = "mp4"
        else:
            ext = "jpg" if media_type == "photo" else "mp4"

    # ── Story display type ────────────────────────────────────────────────
    display_type = media_type
    if is_story:
        display_type = "story"
        if not title or title == "Instagram Media":
            title = f"Instagram Story by @{uploader}" if uploader else "Instagram Story"

    print(
        f"Result → media_type={display_type}, ext={ext}, "
        f"url_snippet={download_url[:60]}..., carousel_items={len(carousel_urls)}"
    )

    result = {
        "success": True,
        "title": title[:200],
        "thumbnail": thumbnail,
        "download_url": download_url,
        "media_type": display_type,
        "duration": duration,
        "uploader": uploader,
        "ext": ext,
        "is_story": is_story,
        "is_carousel": bool(carousel_urls),
        "carousel_items": carousel_urls,
    }

    _cache[url] = result
    return result


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True)

    if not data or "url" not in data:
        return jsonify({"success": False, "error": "Missing 'url' field"}), 400

    url = data["url"].strip()

    if not url:
        return jsonify({"success": False, "error": "URL cannot be empty"}), 400

    if not is_instagram_url(url):
        return jsonify({
            "success": False,
            "error": "Invalid Instagram URL. Please paste a valid reel, post, or story link.",
        }), 422

    try:
        time.sleep(0.3)
        result = extract_media_info(url)

        if not result.get("download_url"):
            return jsonify({
                "success": False,
                "error": "Could not extract media. The content might be private, expired, or deleted.",
            }), 404

        return jsonify(result), 200

    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        print(f"DownloadError: {e}")

        if "login" in msg or "private" in msg:
            return jsonify({"success": False, "error": "Instagram requires login. Private content not accessible."}), 403
        if "not found" in msg or "deleted" in msg:
            return jsonify({"success": False, "error": "Content not found or has been deleted."}), 404
        if "story" in msg and "expired" in msg:
            return jsonify({"success": False, "error": "Story has expired (stories last 24 hours)."}), 404

        return jsonify({"success": False, "error": f"Extraction failed: {str(e)[:200]}"}), 502

    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"success": False, "error": f"Error: {str(e)[:200]}"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "cache_size": len(_cache)}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Instagram Downloader API",
        "version": "4.0",
        "supports": ["reels", "posts", "photos", "carousel", "stories"],
        "endpoints": {"POST /download": "Extract media info", "GET /health": "Health check"},
    }), 200


# ── Keep-alive ping ───────────────────────────────────────────────────────

def keep_alive():
    while True:
        time.sleep(840)
        try:
            urllib.request.urlopen(
                "https://instagram-downloader-t0pq.onrender.com/health", timeout=10
            )
            print("Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")


threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)