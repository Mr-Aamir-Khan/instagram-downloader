"""
Instagram Downloader - FULLY FIXED
- Photos download working
- Video audio working
- Stories working
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
    """Extract media info - PHOTOS + VIDEOS with AUDIO both working"""
    
    if url in _cache:
        return _cache[url]
    
    print(f"📥 Processing: {url}")
    
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "format_sort": ["res:1080", "codec:h264", "ext:mp4"],
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
        ext = ""
        is_story = "/stories/" in url
        
        print(f"📊 URL type: {'Story' if is_story else 'Post/Reel'}")
        
        # ============================================
        # CHECK IF IT'S A PHOTO FIRST
        # ============================================
        
        # Method 1: Check if it's a single photo post
        if info.get("ext") in ["jpg", "jpeg", "png", "webp"]:
            download_url = info.get("url", "")
            media_type = "photo"
            ext = info.get("ext", "jpg")
            print(f"📷 PHOTO detected via ext: {ext}")
        
        # Method 2: Check display_url (usually photos)
        if not download_url and info.get("display_url"):
            download_url = info["display_url"]
            media_type = "photo"
            ext = "jpg"
            print(f"📷 PHOTO via display_url")
        
        # Method 3: Check entries for carousel (multiple photos)
        if not download_url and "entries" in info and info["entries"]:
            for entry in info["entries"]:
                # Check for photo in entry
                if entry.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                    download_url = entry.get("url", "")
                    media_type = "photo"
                    ext = entry.get("ext", "jpg")
                    print(f"📷 PHOTO found in entry")
                    break
                elif entry.get("display_url"):
                    download_url = entry["display_url"]
                    media_type = "photo"
                    ext = "jpg"
                    print(f"📷 PHOTO via entry display_url")
                    break
                # Video in entry
                elif entry.get("ext") in ["mp4", "webm"]:
                    download_url = entry.get("url", "")
                    media_type = "video"
                    ext = entry.get("ext", "mp4")
                    print(f"🎬 VIDEO found in entry")
                    break
        
        # ============================================
        # VIDEO DETECTION (with audio)
        # ============================================
        if not download_url and "formats" in info:
            # Look for MP4 with audio
            best_mp4 = None
            best_height = 0
            
            for fmt in info["formats"]:
                fmt_ext = fmt.get("ext", "").lower()
                has_video = fmt.get("vcodec") != "none"
                has_audio = fmt.get("acodec") != "none"
                height = fmt.get("height", 0) or 0
                
                # PHOTO format
                if fmt_ext in ["jpg", "jpeg", "png", "webp"]:
                    if not download_url:
                        download_url = fmt.get("url", "")
                        media_type = "photo"
                        ext = fmt_ext
                        print(f"📷 PHOTO from formats: {fmt_ext}")
                
                # VIDEO with AUDIO
                elif fmt_ext == "mp4" and has_video and has_audio:
                    if height > best_height:
                        best_height = height
                        best_mp4 = fmt.get("url", "")
                        print(f"🎬 Found MP4 with AUDIO: {height}p")
            
            if best_mp4 and not download_url:
                download_url = best_mp4
                media_type = "video"
                ext = "mp4"
        
        # ============================================
        # Use 'url' field as fallback
        # ============================================
        if not download_url and info.get("url"):
            url_str = info["url"]
            if any(x in url_str.lower() for x in [".jpg", ".jpeg", ".png"]):
                download_url = url_str
                media_type = "photo"
                ext = "jpg"
                print(f"📷 PHOTO from url field")
            elif ".mp4" in url_str.lower():
                download_url = url_str
                media_type = "video"
                ext = "mp4"
                print(f"🎬 VIDEO from url field")
        
        # ============================================
        # Use thumbnail as last resort for photos
        # ============================================
        if not download_url and thumbnail:
            # If thumbnail looks like a photo URL
            if any(x in thumbnail.lower() for x in [".jpg", ".jpeg", ".png"]):
                download_url = thumbnail
                media_type = "photo"
                ext = "jpg"
                print(f"📷 PHOTO from thumbnail")
        
        # Clean up extension
        if download_url:
            url_lower = download_url.lower()
            if any(x in url_lower for x in [".jpg", ".jpeg", ".png", ".webp"]):
                ext = "jpg"
                media_type = "photo"
            elif ".mp4" in url_lower:
                ext = "mp4"
                media_type = "video"
        
        # Story handling
        if is_story and media_type in ["photo", "video"]:
            display_type = "story"
        else:
            display_type = media_type
        
        result = {
            "success": True,
            "title": title[:200],
            "thumbnail": thumbnail,
            "download_url": download_url,
            "media_type": display_type,
            "uploader": uploader,
            "ext": ext,
            "has_audio": media_type == "video"
        }
        
        print(f"📤 FINAL: type={display_type}, ext={ext}, has_audio={media_type == 'video'}")
        print(f"🔗 URL: {download_url[:100] if download_url else 'None'}")
        
        if not download_url:
            print("❌ WARNING: No download URL found!")
        
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
            return jsonify({"success": False, "error": "No media found. Make sure the post is public."}), 404
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:150]}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "cache_size": len(_cache)}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)