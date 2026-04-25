import re
import requests as req

url = "https://www.instagram.com/p/DXgqf0vAihi/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ=="

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}

shortcode = re.search(r'/p/([^/]+)', url).group(1)
embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
resp = req.get(embed_url, headers=headers, timeout=15)
html = resp.text

# t51.82787-15 wale URLs — full URL nikalo (quotes ke beech)
all_matches = re.findall(r'"(https://[^"]+t51\.82787-15[^"]+)"', html)

print(f"Post image URLs found: {len(all_matches)}\n")
for i, u in enumerate(all_matches):
    u = u.replace("\\u0026", "&").replace("\\/", "/")
    print(f"[{i}] {u}\n")