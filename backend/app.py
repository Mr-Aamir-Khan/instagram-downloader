"""
Instagram Video Downloader - Flask Backend
Uses yt-dlp to extract video metadata (no actual download to server)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import time


app = Flask(__name__)

# Enable CORS for all routes (allows frontend to call this API from any origin)
CORS(app)

# ─────────────────────────────────────────────
# Simple in-memory cache: { url -> cached_result }
# Avoids redundant yt-dlp calls for the same URL
# ─────────────────────────────────────────────
_cache = {}

def is_instagram_url(url: str) -> bool:
    """Validate that the URL is an Instagram reel/post/story link."""
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))


def extract_video_info(url: str) -> dict:
    """
    Use yt-dlp to extract video metadata without downloading.
    Returns a dict with title, thumbnail, and best-quality video URL.
    """
    # Return cached result if available
    if url in _cache:
        return _cache[url]

    ydl_opts = {
        
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,

    # ✅ Use already merged format
    "format": "best",

    # Optional but safe
    "force_generic_extractor": False,

    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Pull out the direct playback URL
    # yt-dlp stores it in 'url' for single formats or 'requested_formats'
    video_url = info.get("url") or ""
    if not video_url and info.get("formats"):
        # Fall back to the last (best quality) format in the list
        video_url = info["formats"][-1].get("url", "")

    result = {
        "success": True,
        "title": info.get("title") or "Instagram Video",
        "thumbnail": info.get("thumbnail") or "",
        "download_url": video_url,
        "duration": info.get("duration"),        # seconds (may be None)
        "uploader": info.get("uploader") or "",
    }

    # Cache the result
    _cache[url] = result
    return result


# ─────────────────────────────────────────────
# API Endpoint: POST /download
# Body: { "url": "<instagram_link>" }
# ─────────────────────────────────────────────
@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True)

    # ── Validate request body ──
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

    # ── Extract video info via yt-dlp ──
    try:
        # Small artificial delay so the frontend loader feels natural
        time.sleep(0.5)
        result = extract_video_info(url)
        return jsonify(result), 200

    except yt_dlp.utils.DownloadError as e:
        return jsonify({
            "success": False,
            "error": f"Could not extract video: {str(e)}"
        }), 502

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }), 500


# ── Health check ──
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # Debug mode ON for local development; disable in production
    app.run(debug=True, host="0.0.0.0", port=5000)
    
import os

port = int(os.environ.get("PORT", 5000))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)