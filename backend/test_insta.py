import yt_dlp

url = "https://www.instagram.com/p/DXhQ5WXjE1O/"

with yt_dlp.YoutubeDL({"quiet": False, "skip_download": True, "cookiefile": "cookies.txt"}) as ydl:
    info = ydl.extract_info(url, download=False)

print("TOP LEVEL KEYS:", list(info.keys()))
print("url:", info.get("url"))
print("ext:", info.get("ext"))
print("display_url:", info.get("display_url"))
print("thumbnail:", info.get("thumbnail"))
print("thumbnails:", info.get("thumbnails"))

if info.get("formats"):
    print("\nFORMATS:")
    for f in info["formats"]:
        print(f"  id={f.get('id')} ext={f.get('ext')} url={f.get('url','')[:80]}")