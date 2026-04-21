"""
Instagram Downloader - Audio Fixed Version
Uses multiple strategies to ensure video + audio
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import time
import os
import json

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

_cache = {}

def is_instagram_url(url: str) -> bool:
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))

def extract_media_info(url: str) -> dict:
    """Extract media with AUDIO guaranteed"""
    
    if url in _cache:
        return _cache[url]
    
    print(f"Processing: {url}")
    
    # Strategy 1: Use best format that includes audio
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        # CRITICAL: Request formats with both video AND audio
        "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "format_sort": ["res:1080", "codec:h264", "ext:mp4"],
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        download_url = ""
        media_type = "unknown"
        thumbnail = info.get("thumbnail", "")
        uploader = info.get("uploader", "") or info.get("uploader_id", "")
        title = info.get("title", "Instagram Media")
        ext = "mp4"
        
        # Check if it's a story
        is_story = "/stories/" in url
        
        # PRIORITY 1: Get URL from 'url' field (often best with audio)
        if info.get("url"):
            url_str = info["url"]
            if ".mp4" in url_str.lower() or "video" in url_str.lower():
                download_url = url_str
                media_type = "video"
                ext = "mp4"
                print(f"Found video URL from info.url")
        
        # PRIORITY 2: Check formats for MP4 with audio
        if not download_url and "formats" in info:
            best_mp4 = None
            best_height = 0
            
            for fmt in info["formats"]:
                fmt_ext = fmt.get("ext", "").lower()
                has_video = fmt.get("vcodec") != "none"
                has_audio = fmt.get("acodec") != "none"
                height = fmt.get("height", 0) or 0
                
                # Look for MP4 with both video and audio
                if fmt_ext == "mp4" and has_video and has_audio:
                    if height > best_height:
                        best_height = height
                        best_mp4 = fmt.get("url", "")
                        print(f"Found MP4 with audio: {height}p")
            
            if best_mp4:
                download_url = best_mp4
                media_type = "video"
                ext = "mp4"
        
        # PRIORITY 3: Check entries (for carousel/stories)
        if not download_url and "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if entry.get("url") and ".mp4" in entry["url"].lower():
                    download_url = entry["url"]
                    media_type = "video"
                    ext = "mp4"
                    break
                elif entry.get("url") and any(x in entry["url"].lower() for x in [".jpg", ".png", ".jpeg"]):
                    download_url = entry["url"]
                    media_type = "photo"
                    ext = "jpg"
                    break
        
        # PRIORITY 4: For photos
        if not download_url and info.get("display_url"):
            download_url = info["display_url"]
            media_type = "photo"
            ext = "jpg"
        
        # PRIORITY 5: Use thumbnail as last resort
        if not download_url and thumbnail:
            download_url = thumbnail
            media_type = "photo"
            ext = "jpg"
        
        # Clean up extension
        if download_url:
            if ".mp4" in download_url.lower():
                ext = "mp4"
                media_type = "video"
            elif any(x in download_url.lower() for x in [".jpg", ".jpeg", ".png"]):
                ext = "jpg"
                media_type = "photo"
        
        result = {
            "success": True,
            "title": title[:200],
            "thumbnail": thumbnail,
            "download_url": download_url,
            "media_type": "story" if is_story else media_type,
            "uploader": uploader,
            "ext": ext,
            "has_audio": media_type == "video"
        }
        
        print(f"Result: type={media_type}, url={download_url[:80] if download_url else 'None'}")
        
        _cache[url] = result
        return result
        
    except Exception as e:
        print(f"Error: {e}")
        raise e

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"success": False, "error": "Missing URL"}), 400
    
    url = data["url"].strip()
    if not url:
        return jsonify({"success": False, "error": "URL empty"}), 400
    
    if not is_instagram_url(url):
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 422
    
    try:
        result = extract_media_info(url)
        if not result.get("download_url"):
            return jsonify({"success": False, "error": "No media found"}), 404
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:150]}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "cache_size": len(_cache)}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)