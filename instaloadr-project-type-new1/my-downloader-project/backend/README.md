# Backend — Instagram Downloader API

FastAPI service that resolves a public Instagram link (post, reel, or
story) into direct, downloadable media URLs for the frontend.

## Stack
- FastAPI + Uvicorn
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) for extraction (actively
  maintained, handles Instagram's frequent frontend changes for you)
- `slowapi` for per-IP rate limiting

## Project layout
```
backend/
├── app/
│   ├── main.py                 # App entry point, CORS + rate limit wiring
│   ├── api/routes/
│   │   ├── fetch.py            # POST /api/fetch — link → media items
│   │   └── health.py           # GET /health
│   └── core/
│       ├── config.py           # Settings (env vars)
│       └── security.py         # Rate limiter + CORS config
├── requirements.txt
└── README.md
```

## Local setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: copy .env.example to .env and adjust values
uvicorn app.main:app --reload --port 8000
```
Visit `http://localhost:8000/docs` for interactive API docs.

## Configuration (environment variables)
| Variable                  | Default                                      | Purpose |
|----------------------------|-----------------------------------------------|---------|
| `ENVIRONMENT`              | `development`                                 | `development` \| `staging` \| `production`. Controls CORS defaults (see below) |
| `CORS_ALLOWED_ORIGINS`     | `""`                                          | Comma-separated list of frontend origins allowed to call this API. **Additive** in development (on top of built-in localhost defaults); **required, no wildcard fallback** in production |
| `RATE_LIMIT_PER_MINUTE`    | `30`                                           | Requests per IP per minute — general default for routes without their own limit (currently just `/health`) |
| `DOWNLOAD_RATE_LIMIT_PER_MINUTE` | `5`                                     | Requests per IP per minute on the scraping-backed routes: `/api/fetch`, `/api/bundle`, `/api/stream`. This is the number that actually protects your bandwidth/proxy costs |
| `REQUEST_TIMEOUT_SECONDS`  | `20`                                           | Timeout for the extraction call |
| `MAX_ITEMS_PER_REQUEST`    | `20`                                           | Cap on media items returned per link (carousels) |
| `COOKIES_FILE`             | unset                                          | Path to a `cookies.txt` (Netscape format) — see note below |
| `MOCK_MODE`                | `false`                                        | When `true`, `/api/fetch` returns canned placeholder data instead of running real extraction — see below |
| `FETCH_CACHE_TTL_SECONDS`  | `300`                                          | How long a resolved link is cached before re-extracting. `0` disables caching |
| `FETCH_CACHE_MAX_ENTRIES`  | `500`                                          | Max cached links held in memory at once (oldest evicted first) |

### Result caching

`/api/fetch` caches resolved results per (URL, media type) for
`FETCH_CACHE_TTL_SECONDS` (see `app/core/cache.py`). This is a
performance and reliability optimization, not an anti-detection
measure: it doesn't change what gets requested from Instagram or how,
it just avoids re-running a full yt-dlp extraction when the same link
gets pasted again a few seconds or minutes later (double-clicks, page
refreshes, a few different visitors hitting the same viral post). The
cache is in-process only — if you run more than one backend instance
behind a load balancer, swap `TTLCache` for a Redis-backed
implementation with the same `get`/`set` interface so instances share
a cache instead of each keeping its own.

### Mock mode — testing the plumbing before the scraper

Set `MOCK_MODE=true` to stand up the entire request path — frontend →
CORS → rate limiter → routing → response shape — against a real
deployed backend (Render, etc.) without touching yt-dlp or Instagram at
all. `/api/fetch` will return a fixed set of placeholder image/video
URLs shaped exactly like the real response. `GET /health` reports the
current `mock_mode` value so you can confirm at a glance which mode a
given deployment is running in. Flip it back to `false` once you've
confirmed the pipes work end to end.

### CORS across environments

`app/core/config.py` is the single place that decides what origins are
trusted, driven entirely by `ENVIRONMENT`:
- **development**: a small set of common localhost ports (5500, 3000)
  are allowed automatically, plus anything you add to
  `CORS_ALLOWED_ORIGINS`.
- **staging / production**: no defaults, no `"*"` fallback. You must
  set `CORS_ALLOWED_ORIGINS` to your real deployed frontend URL(s)
  (e.g. `https://yourapp.pages.dev,https://yourdomain.com`). If it's
  left empty in production the API logs a warning and serves CORS to
  no origins at all — it fails closed rather than silently wide open.

## API

### `GET /health`
Uptime/status check for load balancers and monitoring.

### `POST /api/fetch`
```json
{ "url": "https://www.instagram.com/reel/XXXXXXX/", "media_type": "reel" }
```
Response:
```json
{
  "source_url": "...",
  "items": [
    { "media_type": "mp4", "download_url": "...", "thumbnail_url": "...", "width": 1080, "height": 1920, "duration": 12.4 }
  ]
}
```
Errors return a JSON `detail` message with an appropriate HTTP status
(422 for unresolvable links, 404 for no media found, 429 for rate limiting).

### `POST /api/bundle`
Same request body as `/api/fetch`. Resolves the link, fetches every
media file **concurrently**, and streams back a single `.zip`
(`Content-Type: application/zip`). Used for the "download all" button
on multi-photo carousels. Individual files that fail to download are
skipped rather than failing the whole zip; if *none* succeed, returns
502.

### `GET /api/stream?url=...`
Proxies a single media file straight from Instagram's CDN to the
browser, chunk by chunk — nothing is buffered to disk or held fully in
memory server-side. `url` must be a `cdninstagram.com` or `fbcdn.net`
host (anything else is rejected); that allowlist exists specifically so
this endpoint can't become an open proxy for arbitrary URLs. Use it
when a direct CDN link from `/api/fetch` won't load in-browser on its
own (expired signed URL, referrer checks); otherwise, linking straight
to `download_url` is simpler and doesn't cost your server bandwidth.

## Important limitations & responsible use

- **`media_type: "dp"` (profile picture) is not implemented for real
  extraction yet.** It works in mock mode (for testing the frontend
  tab/UI), but with `MOCK_MODE=false` the API returns a `501` with a
  clear "coming soon" message rather than pretending to work. Profile
  pictures need a different extraction path than yt-dlp's post/reel
  extractor (they're not "post" URLs), which hasn't been built.
- **`media_type: "audio"`** extracts a genuine audio-only stream when
  yt-dlp finds one; when Instagram's response only offers a muxed
  video+audio format (the common case), you'll get the video file back
  instead of a pure audio one. Splitting audio out of a muxed file
  needs an `ffmpeg` step (the Docker image already includes `ffmpeg`
  for this reason) — that's a reasonable next addition but isn't wired
  up yet.

- **Public content only.** This service does not attempt to bypass
  Instagram's login walls or anti-bot protections. Private accounts and
  private posts will not resolve.
- **Stories often require an authenticated session**, even for public
  accounts — this is an Instagram platform behavior, not something this
  project works around. If you need to fetch your *own* Stories, you can
  set `COOKIES_FILE` to a cookies export from an account you control.
  Never use shared, purchased, or scraped credentials.
- **Respect copyright and Instagram's Terms of Service.** Build features
  (like the notices on the frontend pages) that steer people toward
  saving their own content or content they have explicit permission to
  reuse, not toward mass-redistributing other creators' work.
- **`yt-dlp` will need periodic updates.** Instagram changes its
  frontend regularly; pin a recent `yt-dlp` version and update it when
  extraction starts failing (`pip install -U yt-dlp`).

## Deployment

### Docker
```bash
cd backend
docker compose up --build -d
```
Uses the included `Dockerfile` + `docker-compose.yml`. Set your real
values in `.env` (copy from `.env.example`) before starting — compose
reads it via `env_file`.

### Render / Google Cloud Run
Point at `backend/`, build command `pip install -r requirements.txt`,
start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set
env vars in the platform's dashboard (`ENVIRONMENT=production`,
`CORS_ALLOWED_ORIGINS=<your frontend url>`, etc.) rather than relying
on a committed `.env`.

### Self-hosted VPS (Hetzner, DigitalOcean, etc.)
Run the container (or `uvicorn` directly) bound to `127.0.0.1:8000`,
then put Nginx in front for TLS termination. A starting point is in
`nginx.conf.example` — copy it to `/etc/nginx/sites-available/`, adjust
`server_name`, symlink into `sites-enabled`, then:
```bash
sudo certbot --nginx -d api.yourdomain.com
```
Certbot obtains and auto-renews the Let's Encrypt cert and rewrites the
config's SSL block for you the first time it runs.

