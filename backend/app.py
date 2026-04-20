"""
Instagram Video/Photo/Story Downloader - Flask Backend
Supports: Reels, Posts, Photos, Carousel, Stories
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

def is_story_url(url: str) -> bool:
    """Check if URL is a story URL."""
    return "/stories/" in url

def extract_media_info(url: str) -> dict:
    """Extract media information from Instagram URL"""
    
    if len(_cache) > 50:
        _cache.clear()
    
    if url in _cache:
        print(f"Returning cached result for: {url}")
        return _cache[url]

    is_story = is_story_url(url)
    print(f"Processing URL: {url}, is_story: {is_story}")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "best",
        "extractor_args": {
            "instagram": {
                "include_ads": False,
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        print(f"Extracted info keys: {info.keys()}")
        
        download_url = ""
        media_type = "unknown"
        thumbnail = info.get("thumbnail", "")
        uploader = info.get("uploader", "") or info.get("uploader_id", "")
        title = info.get("title", "Instagram Media")
        ext = ""
        duration = info.get("duration")
        
        # Story specific handling
        if is_story or "story" in title.lower():
            print("Processing as Story...")
            media_type = "story"
            
            # For stories, check entries first
            if "entries" in info and info["entries"]:
                for entry in info["entries"]:
                    # Video story
                    if entry.get("url") and entry.get("ext") in ["mp4", "webm"]:
                        download_url = entry["url"]
                        media_type = "video"
                        ext = entry.get("ext", "mp4")
                        if entry.get("thumbnail"):
                            thumbnail = entry["thumbnail"]
                        break
                    # Photo story
                    elif entry.get("url") and entry.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                        download_url = entry["url"]
                        media_type = "photo"
                        ext = entry.get("ext", "jpg")
                        if entry.get("thumbnail"):
                            thumbnail = entry["thumbnail"]
                        break
                    elif entry.get("thumbnail"):
                        download_url = entry["thumbnail"]
                        media_type = "photo"
                        ext = "jpg"
                        break
            
            # If no entries, check direct URL
            if not download_url:
                if info.get("url") and info.get("ext") in ["mp4", "webm"]:
                    download_url = info["url"]
                    media_type = "video"
                    ext = info.get("ext", "mp4")
                elif info.get("url") and info.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                    download_url = info["url"]
                    media_type = "photo"
                    ext = info.get("ext", "jpg")
                elif info.get("thumbnail"):
                    download_url = info["thumbnail"]
                    media_type = "photo"
                    ext = "jpg"
            
            # Update uploader for stories
            if not uploader and "uploader_id" in info:
                uploader = info["uploader_id"]
            elif not uploader and "channel" in info:
                uploader = info["channel"]
                
            if not title or title == "Instagram Media":
                title = f"Instagram Story by {uploader}" if uploader else "Instagram Story"
        
        # Regular post/reel handling (if not story or story handled)
        if not download_url:
            # Check for entries (carousel/sidecar posts)
            if "entries" in info and info["entries"]:
                print(f"Carousel post detected with {len(info['entries'])} items")
                entry = info["entries"][0]
                
                if entry.get("url") and entry.get("ext") in ["mp4", "webm"]:
                    download_url = entry["url"]
                    media_type = "video"
                    ext = entry.get("ext", "mp4")
                elif entry.get("url") and entry.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                    download_url = entry["url"]
                    media_type = "photo"
                    ext = entry.get("ext", "jpg")
                elif entry.get("thumbnail"):
                    download_url = entry["thumbnail"]
                    media_type = "photo"
                    ext = "jpg"
                elif "formats" in entry and entry["formats"]:
                    for fmt in entry["formats"]:
                        if fmt.get("ext") in ["jpg", "jpeg", "png", "webp"]:
                            download_url = fmt.get("url", "")
                            media_type = "photo"
                            ext = fmt.get("ext", "jpg")
                            break
                        elif fmt.get("ext") in ["mp4"]:
                            download_url = fmt.get("url", "")
                            media_type = "video"
                            ext = "mp4"
                            break
                
                if entry.get("thumbnail"):
                    thumbnail = entry["thumbnail"]
                    
            else:
                # Single post
                print(f"Single post detected")
                
                if info.get("url"):
                    url_ext = info.get("ext", "").lower()
                    
                    if url_ext in ["mp4", "webm", "mov"]:
                        download_url = info["url"]
                        media_type = "video"
                        ext = url_ext
                    elif url_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                        download_url = info["url"]
                        media_type = "photo"
                        ext = url_ext
                
                if not download_url and "formats" in info:
                    best_image = None
                    best_image_quality = 0
                    best_video = None
                    
                    for fmt in info["formats"]:
                        fmt_ext = fmt.get("ext", "").lower()
                        
                        if fmt_ext in ["jpg", "jpeg", "png", "webp"]:
                            quality = fmt.get("height", 0) or fmt.get("quality", 0)
                            if quality > best_image_quality:
                                best_image = fmt.get("url", "")
                                best_image_quality = quality
                                ext = fmt_ext
                        elif fmt_ext in ["mp4"] and fmt.get("vcodec") != "none":
                            if not best_video:
                                best_video = fmt.get("url", "")
                    
                    if best_image:
                        download_url = best_image
                        media_type = "photo"
                    elif best_video:
                        download_url = best_video
                        media_type = "video"
                        ext = "mp4"
                
                if not download_url:
                    if info.get("display_url"):
                        download_url = info["display_url"]
                        media_type = "photo"
                        ext = "jpg"
                    elif info.get("thumbnail"):
                        download_url = info["thumbnail"]
                        media_type = "photo"
                        ext = "jpg"
        
        # Detect media type from URL if still unknown
        if media_type == "unknown" and download_url:
            url_lower = download_url.lower()
            if any(x in url_lower for x in [".jpg", ".jpeg", ".png", ".webp", "format=jpg", "format=png"]):
                media_type = "photo"
                ext = "jpg"
            elif any(x in url_lower for x in [".mp4", ".webm"]):
                media_type = "video"
                ext = "mp4"
        
        # Clean up extension
        if not ext and download_url:
            if "jpg" in download_url or "jpeg" in download_url or "png" in download_url:
                ext = "jpg"
            elif "mp4" in download_url:
                ext = "mp4"
            else:
                ext = "jpg" if media_type == "photo" else "mp4"
        
        # Get better thumbnail
        if not thumbnail and "thumbnails" in info:
            thumbnails = info.get("thumbnails", [])
            if thumbnails:
                best_thumb = max(thumbnails, key=lambda x: x.get("preference", 0) or x.get("height", 0))
                thumbnail = best_thumb.get("url", "")
        
        # Set media_type to "story" for frontend if it was a story
        if is_story and media_type in ["photo", "video"]:
            display_type = "story"
        else:
            display_type = media_type
        
        result = {
            "success": True,
            "title": title[:200] if title else "Instagram Media",
            "thumbnail": thumbnail,
            "download_url": download_url,
            "media_type": display_type,
            "duration": duration,
            "uploader": uploader or "",
            "ext": ext.replace(".", ""),
            "is_story": is_story,
        }
        
        print(f"Final result: media_type={display_type}, is_story={is_story}, ext={ext}")
        
        _cache[url] = result
        return result
        
    except yt_dlp.utils.DownloadError as e:
        print(f"yt-dlp DownloadError: {str(e)}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
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
            "error": "Invalid Instagram URL. Please paste a valid reel, post, or story link."
        }), 422
    
    try:
        time.sleep(0.3)
        result = extract_media_info(url)
        
        if not result.get("download_url"):
            return jsonify({
                "success": False,
                "error": "Could not extract media. The content might be private, expired, or deleted."
            }), 404
            
        return jsonify(result), 200
        
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        print(f"DownloadError: {error_msg}")
        
        if "login" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "Instagram requires login. Private content not accessible."
            }), 403
        elif "not found" in error_msg.lower() or "deleted" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "Content not found or has been deleted."
            }), 404
        elif "story" in error_msg.lower() and "expired" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "Story has expired. Stories are only available for 24 hours."
            }), 404
        else:
            return jsonify({
                "success": False,
                "error": f"Extraction failed: {error_msg[:150]}"
            }), 502
        
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error: {error_msg}")
        return jsonify({
            "success": False,
            "error": f"Error: {error_msg[:150]}"
        }), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok", 
        "cache_size": len(_cache)
    }), 200

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Instagram Downloader API",
        "version": "3.0",
        "supports": ["reels", "posts", "photos", "carousel", "stories"],
        "endpoints": {
            "POST /download": "Extract media info",
            "GET /health": "Health check"
        }
    }), 200

# Keep-alive using urllib (no requests needed)
import threading
import urllib.request

def keep_alive():
    while True:
        time.sleep(840)  # 14 minutes
        try:
            urllib.request.urlopen("https://instagram-downloader-t0pq.onrender.com/health", timeout=10)
            print("Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)