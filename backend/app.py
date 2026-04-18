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
CORS(app)

# Simple cache
_cache = {}

# ─────────────────────────────────────────────
# Validate Instagram URL
# ─────────────────────────────────────────────
def is_instagram_url(url: str) -> bool:
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))


# ─────────────────────────────────────────────
# Extract video info using yt-dlp
# ─────────────────────────────────────────────
def extract_video_info(url: str) -> dict:
    if url in _cache:
        return _cache[url]

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "best",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    video_url = info.get("url") or ""
    if not video_url and info.get("formats"):
        video_url = info["formats"][-1].get("url", "")

    result = {
        "success": True,
        "title": info.get("title") or "Instagram Video",
        "thumbnail": info.get("thumbnail") or "",
        "download_url": video_url,
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or "",
    }

    _cache[url] = result
    return result


# ─────────────────────────────────────────────
# Home Route (browser ke liye)
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return "Instagram Downloader API is running 🚀"


# ─────────────────────────────────────────────
# API Route (POST request)
# ─────────────────────────────────────────────
@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True)

    if not data or "url" not in data:
        return jsonify({"success": False, "error": "Missing 'url' field"}), 400

    url = data["url"].strip()

    if not url:
        return jsonify({"success": False, "error": "URL cannot be empty"}), 400

    if not is_instagram_url(url):
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 422

    try:
        time.sleep(0.5)  # optional delay
        result = extract_video_info(url)
        return jsonify(result)
    except yt_dlp.utils.DownloadError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────
# Run App (Local only)
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)