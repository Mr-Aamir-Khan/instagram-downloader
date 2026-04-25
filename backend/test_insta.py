import re
import requests as req

url = "https://www.instagram.com/p/DXgZIgsCJcL/"

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

# Saare fbcdn/cdninstagram URLs nikalo
all_urls = re.findall(r'https://[^\s"\'\\]+(?:cdninstagram|fbcdn)[^\s"\'\\]+', html)

print(f"Total URLs found: {len(all_urls)}\n")
for i, u in enumerate(all_urls):
    # Unescape
    u = u.replace("\\u0026", "&").replace("\\/", "/")
    print(f"[{i}] {u[:120]}")