"""
Instagram Video Downloader - Flask Backend
Uses yt-dlp to extract video metadata (no actual download to server)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import time
import os

app = Flask(__name__)

# ✅ CORS - Render pe sahi kaam karne ke liye
CORS(app, resources={r"/*": {"origins": "*"}})

# Simple in-memory cache
_cache = {}


def is_instagram_url(url: str) -> bool:
    """Validate that the URL is an Instagram reel/post/story link."""
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))


def extract_video_info(url: str) -> dict:
    if url in _cache:
        return _cache[url]

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "best",
        "extractor_args": {
            "instagram": {"include_ads": False}
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    download_url = ""
    media_type = "video"

    # ✅ 1. Carousel (multiple posts)
    if "entries" in info and info["entries"]:
        entry = info["entries"][0]

        # 🎥 video
        if entry.get("url") and entry.get("ext") == "mp4":
            download_url = entry["url"]
            media_type = "video"

        # 📸 image (IMPORTANT)
        elif entry.get("display_url"):
            download_url = entry["display_url"]
            media_type = "image"

        elif entry.get("thumbnail"):
            download_url = entry["thumbnail"]
            media_type = "image"

    # ✅ 2. Single post
    else:
        # 🎥 video
        if info.get("url") and info.get("ext") == "mp4":
            download_url = info["url"]
            media_type = "video"

        # 📸 image
        elif info.get("display_url"):
            download_url = info["display_url"]
            media_type = "image"

        elif info.get("thumbnail"):
            download_url = info["thumbnail"]
            media_type = "image"

    result = {
        "success": True,
        "title": info.get("title") or "Instagram Media",
        "thumbnail": info.get("thumbnail") or "",
        "download_url": download_url,
        "media_type": media_type,
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or "",
    }

    _cache[url] = result
    return result

# ─────────────────────────────────────────────
# API Endpoint: POST /download
# Body: { "url": "<instagram_link>" }
# ─────────────────────────────────────────────
@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True)

    if not data or "url" not in data:
        return jsonify({"success": False, "error": "Missing 'url' field in request body."}), 400

    url = data["url"].strip()

    if not url:
        return jsonify({"success": False, "error": "URL cannot be empty."}), 400

    if not is_instagram_url(url):
        return jsonify({
            "success": False,
            "error": "Invalid Instagram URL. Please paste a valid reel, post, or TV link."
        }), 422

    try:
        time.sleep(0.5)
        result = extract_video_info(url)
        return jsonify(result), 200

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        # ✅ Instagram login required error ko handle karo
        if "login" in error_msg.lower() or "cookies" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "Instagram ne login maang raha hai. Private post ya stories ke liye cookies required hain."
            }), 403
        return jsonify({
            "success": False,
            "error": f"Video extract nahi ho saka: {error_msg}"
        }), 502

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }), 500


# ── Health check ──
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Server chal raha hai!"}), 200


# ✅ Root route - 404 fix ke liye
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Instagram Downloader API",
        "endpoints": {
            "POST /download": "Video info extract karo",
            "GET /health": "Server status check karo"
        }
    }), 200

import threading
import urllib.request

def keep_alive():
    while True:
        time.sleep(840)  # 14 minutes
        try:
            urllib.request.urlopen("https://instagram-downloader-t0pq.onrender.com/health")
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()
# ✅ FIXED: Single main block, port pehle define karo
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)