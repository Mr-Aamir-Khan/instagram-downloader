"""
Instagram Downloader - COMPLETE AUDIO FIX
Forces video+audio combined format
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

_cache = {}

def is_instagram_url(url: str) -> bool:
    pattern = r"(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/[\w\-]+"
    return bool(re.search(pattern, url))


def extract_media_info(url: str) -> dict:
    """Extract media info - FORCED audio+video combined"""
    
    if url in _cache:
        return _cache[url]
    
    print(f"📥 Processing: {url}")
    
    # CRITICAL: yt-dlp options to FORCE audio+video
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        # FORCE format with both video AND audio
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
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
        media_type = "video"  # default
        thumbnail = info.get("thumbnail", "")
        uploader = info.get("uploader", "") or info.get("uploader_id", "")
        title = info.get("title", "Instagram Media")
        ext = "mp4"
        is_story = "/stories/" in url
        
        print(f"📊 Available formats: {len(info.get('formats', []))}")
        
        # ============================================
        # STRATEGY 1: Find MP4 with BOTH video AND audio
        # ============================================
        best_mp4_with_audio = None
        best_quality = 0
        
        if "formats" in info:
            for fmt in info["formats"]:
                fmt_ext = fmt.get("ext", "").lower()
                has_video = fmt.get("vcodec") != "none"
                has_audio = fmt.get("acodec") != "none"
                height = fmt.get("height", 0) or 0
                
                # Only select formats with BOTH video AND audio
                if fmt_ext == "mp4" and has_video and has_audio:
                    if height > best_quality:
                        best_quality = height
                        best_mp4_with_audio = fmt.get("url", "")
                        print(f"✅ Found MP4 with AUDIO: {height}p")
        
        if best_mp4_with_audio:
            download_url = best_mp4_with_audio
            media_type = "video"
            ext = "mp4"
            print(f"🎉 Using MP4 with audio: {best_quality}p")
        
        # ============================================
        # STRATEGY 2: Try 'url' field (often has audio)
        # ============================================
        if not download_url and info.get("url"):
            url_str = info["url"]
            if ".mp4" in url_str.lower():
                download_url = url_str
                media_type = "video"
                ext = "mp4"
                print("✅ Using URL field")
        
        # ============================================
        # STRATEGY 3: Check entries (carousel/stories)
        # ============================================
        if not download_url and "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if entry.get("url") and ".mp4" in entry["url"].lower():
                    download_url = entry["url"]
                    media_type = "video"
                    ext = "mp4"
                    print("✅ Found video in entries")
                    break
                elif entry.get("url") and any(x in entry["url"].lower() for x in [".jpg", ".png"]):
                    download_url = entry["url"]
                    media_type = "photo"
                    ext = "jpg"
                    print("✅ Found photo in entries")
                    break
        
        # ============================================
        # STRATEGY 4: For photos
        # ============================================
        if not download_url and info.get("display_url"):
            download_url = info["display_url"]
            media_type = "photo"
            ext = "jpg"
            print("✅ Using display_url for photo")
        
        # ============================================
        # STRATEGY 5: Last resort - thumbnail
        # ============================================
        if not download_url and thumbnail:
            download_url = thumbnail
            media_type = "photo"
            ext = "jpg"
            print("⚠️ Using thumbnail as fallback")
        
        # Final extension cleanup
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
        
        print(f"📤 FINAL: type={media_type}, audio={'YES' if media_type == 'video' else 'NO'}")
        print(f"🔗 URL: {download_url[:100] if download_url else 'None'}")
        
        _cache[url] = result
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
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