import yt_dlp

URL = "https://www.instagram.com/reel/https://www.instagram.com/reel/DXeVirmjiEZ/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ==/"

ydl_opts = {
    "quiet": False,
    "no_warnings": False,
    "skip_download": True,
    "listformats": True,
    "cookiefile": "cookies.txt",
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.extract_info(URL, download=False)