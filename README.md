# ReelRipper — Instagram Video Downloader

A full-stack Instagram video downloader. Paste a Reel/Post URL → get a direct
download link. No file is stored on the server — yt-dlp extracts the stream URL
on-the-fly.

```
project/
├── backend/
│   ├── app.py           ← Flask API (Python)
│   └── requirements.txt
└── frontend/
    └── index.html       ← Single-file UI (HTML + CSS + JS)
```

---

## 1. Backend Setup

### Requirements
- Python 3.9+
- pip

### Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

Or manually:

```bash
pip install flask flask-cors yt-dlp
```

### Start the server

```bash
python app.py
```

The API will be available at **http://localhost:5000**

---

## 2. Frontend Setup

No build step required — it's a plain HTML file.

Simply **open `frontend/index.html`** in your browser.

> Make sure the backend is running first. The frontend talks to
> `http://localhost:5000` by default. You can change this at the top of the
> `<script>` block in `index.html`:
> ```js
> const API_BASE = "http://localhost:5000";
> ```

---

## 3. Usage

1. Open `frontend/index.html` in your browser
2. Paste an Instagram Reel/Post URL, e.g.
   `https://www.instagram.com/reel/XXXXXXXXX/`
3. Click **Fetch**
4. See the thumbnail and title, then click **Download Video**

---

## API Reference

### `POST /download`

**Request body:**
```json
{ "url": "https://www.instagram.com/reel/XXXXXXXXX/" }
```

**Success response:**
```json
{
  "success": true,
  "title": "Video title",
  "thumbnail": "https://...",
  "download_url": "https://...direct-video-stream...",
  "duration": 30,
  "uploader": "username"
}
```

**Error response:**
```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

### `GET /health`

Returns `{"status": "ok"}` — useful for uptime checks.

---

## Notes

- The video URL returned by yt-dlp is a **temporary CDN link** from Instagram's
  servers. It will expire after a few minutes — open it immediately.
- Only **public** posts can be extracted. Private accounts will fail.
- Instagram may rate-limit or block repeated requests from the same IP.
- For production use, consider adding a proxy/cookie support via yt-dlp options.