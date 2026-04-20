"""
Instagram Video/Photo Downloader - Flask Backend
Uses yt-dlp to extract media metadata
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import time
import os

app = Flask(__name__)

# CORS configuration
CORS(app, resources={r"/*": {"origins": "*"}})

# Simple in-memory cache
_cache = {}

def is_instagram_url(url: str) -> bool:
    """Validate that the URL is an Instagram reel/post/story link."""
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))

def extract_media_info(url: str) -> dict:
    """Extract media information from Instagram URL"""
    
    if url in _cache:
        return _cache[url]

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,  # Get full info
        "format": "best",
        "extractor_args": {
            "instagram": {"include_ads": False}
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        download_url = ""
        media_type = "unknown"
        thumbnail = info.get("thumbnail", "")
        uploader = info.get("uploader", "")
        title = info.get("title", "Instagram Media")
        
        # Handle different content types
        if "entries" in info and info["entries"]:
            # Multi-post (carousel) - get first item
            entry = info["entries"][0]
            
            # Check for video
            if entry.get("url") and entry.get("ext") in ["mp4", "webm"]:
                download_url = entry["url"]
                media_type = "video"
            
            # Check for image
            elif entry.get("url") and entry.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                download_url = entry["url"]
                media_type = "photo"
            
            # Fallback to thumbnail/display_url
            elif entry.get("thumbnail"):
                download_url = entry["thumbnail"]
                media_type = "photo"
            
            # Get thumbnail from entry if available
            if entry.get("thumbnail"):
                thumbnail = entry["thumbnail"]
                
        else:
            # Single post
            if info.get("url"):
                ext = info.get("ext", "").lower()
                
                # Video formats
                if ext in ["mp4", "webm", "mov"]:
                    download_url = info["url"]
                    media_type = "video"
                
                # Image formats
                elif ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                    download_url = info["url"]
                    media_type = "photo"
            
            # If no direct URL, check formats
            if not download_url and "formats" in info:
                # Try to find best quality video
                for fmt in info["formats"]:
                    if fmt.get("vcodec") != "none" and fmt.get("acodec") != "none":
                        download_url = fmt.get("url", "")
                        media_type = "video"
                        break
                    elif fmt.get("vcodec") == "none":  # Audio only - skip
                        continue
                
                # If still no URL, look for image format
                if not download_url:
                    for fmt in info["formats"]:
                        if fmt.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                            download_url = fmt.get("url", "")
                            media_type = "photo"
                            break
            
            # Fallback to thumbnail if everything else fails
            if not download_url and info.get("thumbnail"):
                download_url = info["thumbnail"]
                media_type = "photo"
        
        # Additional metadata extraction
        # Try to get better quality thumbnail
        if not thumbnail and "thumbnails" in info:
            thumbnails = info.get("thumbnails", [])
            if thumbnails:
                # Get highest resolution thumbnail
                best_thumb = max(thumbnails, key=lambda x: x.get("preference", 0))
                thumbnail = best_thumb.get("url", "")
        
        result = {
            "success": True,
            "title": title,
            "thumbnail": thumbnail,
            "download_url": download_url,
            "media_type": media_type,  # Must be "photo" or "video"
            "duration": info.get("duration"),
            "uploader": uploader,
            "ext": download_url.split(".")[-1].split("?")[0] if download_url else "",  # jpg, mp4, etc.
}
        
        _cache[url] = result
        return result
        
    except Exception as e:
        raise e

# API Endpoint: POST /download
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
            "error": "Invalid Instagram URL"
        }), 422
    
    try:
        time.sleep(0.3)  # Small delay to avoid rate limiting
        result = extract_media_info(url)
        return jsonify(result), 200
        
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "login" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "Instagram requires login. Private content not accessible."
            }), 403
        return jsonify({
            "success": False,
            "error": f"Extraction failed: {error_msg[:100]}"
        }), 502
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error: {str(e)[:100]}"
        }), 500

# Health check
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# Root route
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Instagram Downloader API",
        "endpoints": {
            "POST /download": "Extract media info",
            "GET /health": "Health check"
        }
    }), 200

# Keep-alive for Render
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)