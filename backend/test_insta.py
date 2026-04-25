import re
import requests as req

url = "https://www.instagram.com/p/DXQWkrXiG65/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ=="

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

# Priority 1
img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+dst-jpg_e15_fr[^"]+)"', html)
# Priority 2
if not img_match:
    img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+p1080x1080[^"]+)"', html)
# Priority 3
if not img_match:
    img_match = re.search(r'"(https://[^"]+t51\.82787-15[^"]+\.jpg[^"]+)"', html)

if img_match:
    img_url = img_match.group(1).replace("&amp;", "&").replace("\\/", "/")
    print(f"✅ Image URL:\n{img_url}\n")

    # Ab ye URL actually accessible hai?
    r2 = req.get(img_url, headers={"Referer": "https://www.instagram.com/"}, timeout=10)
    print(f"📶 Image fetch status: {r2.status_code}")
    print(f"📦 Content-Type: {r2.headers.get('Content-Type')}")
    print(f"📏 Content-Length: {r2.headers.get('Content-Length')} bytes")
else:
    print("❌ No image found")

# Title/uploader bhi check karo
title_match = re.search(r'"caption":"([^"]{0,200})"', html)
user_match = re.search(r'"username":"([^"]+)"', html)
print(f"\n👤 Username: {user_match.group(1) if user_match else 'NOT FOUND'}")
print(f"📝 Caption: {title_match.group(1)[:80] if title_match else 'NOT FOUND'}")