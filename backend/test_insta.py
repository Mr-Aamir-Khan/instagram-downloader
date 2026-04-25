import re
import requests as req

def extract_photo_post(url: str) -> dict:
    match = re.search(r'/p/([^/]+)', url)
    if not match:
        print("❌ Shortcode nahi mila URL se")
        return {}
    
    shortcode = match.group(1)
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    print(f"📡 Embed URL: {embed_url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
    }
    
    resp = req.get(embed_url, headers=headers, timeout=15)
    print(f"📶 Status code: {resp.status_code}")
    
    if resp.status_code != 200:
        print("❌ Request fail hua")
        return {}
    
    html = resp.text
    print(f"📄 HTML length: {len(html)} chars")
    
    print("\n--- HTML snippet (first 500 chars) ---")
    print(html[:500])
    print("--- HTML snippet (last 500 chars) ---")
    print(html[-500:])
    
    # Pattern 1
    img_match = re.search(r'"display_url":"([^"]+)"', html)
    if img_match:
        print(f"\n✅ Pattern 1 match: {img_match.group(1)[:100]}")
    else:
        print("\n❌ Pattern 1 (display_url) nahi mila")
    
    # Pattern 2
    img_match2 = re.search(r'<img[^>]+src="(https://[^"]*cdninstagram[^"]+)"', html)
    if img_match2:
        print(f"✅ Pattern 2 match: {img_match2.group(1)[:100]}")
    else:
        print("❌ Pattern 2 (cdninstagram img tag) nahi mila")

    # Pattern 3
    img_match3 = re.search(r'src="(https://[^"]*(?:cdninstagram|fbcdn)[^"]+\.jpg[^"]*)"', html)
    if img_match3:
        print(f"✅ Pattern 3 match: {img_match3.group(1)[:100]}")
    else:
        print("❌ Pattern 3 (fbcdn/cdninstagram jpg) nahi mila")

    return {}

url = "https://www.instagram.com/p/DXgZIgsCJcL/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ=="
print(f"🔍 Testing URL: {url}\n")
extract_photo_post(url)