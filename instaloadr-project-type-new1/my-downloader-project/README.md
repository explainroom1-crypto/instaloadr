# my-downloader-project

An Instagram content downloader: a static frontend (6 SEO-targeted
pages — Video, Photo, Reels, Story, Profile Picture, Audio) that calls
a FastAPI backend, which resolves public Instagram links into direct
media downloads. Every page has two ways to switch content type: a
collapsible "Instagram Downloader ▾" menu in the header, and a pill
tab row at the top of the hero.

```
my-downloader-project/
├── frontend/     # Deploy to Vercel / Cloudflare Pages
│   └── extension/  # Chrome/Firefox browser extension (loads separately, see its own README)
└── backend/      # Deploy to Render / Hetzner / Google Cloud
```

## Quick start

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

**Frontend:** open `frontend/index.html` with a local static server (e.g.
VS Code Live Server on port 5500) so it matches the default CORS origin,
or set `window.DOWNLOADER_API_BASE_URL` in a small inline script before
`app.js` loads if you serve it elsewhere. Then set that value to your
real backend URL before deploying.

See `backend/README.md` for full API docs, configuration, and — importantly —
the responsible-use notes on what this tool can and can't (and shouldn't)
do with private content and Stories.

## Version control & deployment

This repo is already git-initialized on branch `main` with both
`frontend/` and `backend/` tracked together, so a single push covers
both deploy targets:

```bash
# create a private repo on GitHub/GitLab first, then:
git remote add origin git@github.com:yourname/my-downloader-project.git
git push -u origin main
```

- **Frontend → Cloudflare Pages / Vercel**: point the project at the
  `frontend/` directory as the build root (no build step needed — it's
  static HTML/CSS/JS). Set `window.DOWNLOADER_API_BASE_URL` to your
  live backend URL.
- **Backend → Render**: point the service at the `backend/` directory,
  build command `pip install -r requirements.txt`, start command
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set `ENVIRONMENT=production`
  and `CORS_ALLOWED_ORIGINS` to your deployed frontend URL(s) in Render's
  environment variable settings.

## SEO

Each frontend page now has:
- A unique, keyword-targeted `<title>` and meta description (no duplicate content across `index.html` / `reels.html` / `story.html`)
- A single, correctly-nested `<h1>` per page and a logical heading order
- Canonical URL tag, `robots` meta, and Open Graph + Twitter Card meta for link previews
- `WebApplication` and `FAQPage` JSON-LD structured data (the FAQ schema is generated straight from the on-page `<details>` FAQ content, so it can't drift out of sync — Google can surface these as rich results)
- `robots.txt` and `sitemap.xml` at the frontend root
- A lightweight inline SVG favicon (`favicon.svg`)
- `loading="lazy"` on result thumbnails, `preconnect` to the font host, and `font-display: swap` to keep the pages fast (Core Web Vitals matter for ranking)

### Before you go live, do these manually
1. **Replace the placeholder domain.** `https://loadr.example.com` appears in `index.html`, `reels.html`, `story.html`, `robots.txt`, and `sitemap.xml`. Once you have a real domain:
   ```bash
   cd frontend
   grep -rl "loadr.example.com" . | xargs sed -i '' 's/loadr.example.com/yourrealdomain.com/g'
   ```
   (drop the `''` after `-i` on Linux/GNU sed).
2. **Add a real `og-image.png`** (1200×630px) at `frontend/og-image.png` — link previews on social/messaging apps use it.
3. **Submit the sitemap** to Google Search Console and Bing Webmaster Tools once deployed.
4. **Update `sitemap.xml`'s `<lastmod>`** (or add it) whenever page content changes meaningfully.

### Beyond technical SEO
Technical SEO gets you crawlable, indexable, rich-result-eligible pages — it won't by itself outrank established downloader sites for competitive terms like "instagram downloader." That mostly comes down to backlinks and content depth over time (e.g. a short guide page per use case, genuine user reviews, being listed in relevant directories). Not something code alone solves, but worth knowing going in.

## Production hardening (frontend + backend)

- **Frontend:** critical/secondary CSS split (`css/style.css` loads
  synchronously, `css/style-secondary.css` loads non-blocking via
  preload+swap), OS-level dark mode support, real per-file download
  progress (routed through the backend's `/api/stream` proxy — direct
  cross-origin fetches to Instagram's CDN aren't reliable, and the
  `download` attribute is ignored on cross-origin anchors anyway),
  client-side regex validation per page type before ever hitting the
  backend, and a dynamic API base URL (`localhost` → local dev backend,
  anything else → `PRODUCTION_API_BASE_URL` in `js/app.js`).
- **Legal pages:** `privacy.html`, `terms.html`, `disclaimer.html` are
  drafted as **templates only** — every bracketed placeholder needs
  filling in, and a lawyer should review them before you rely on them
  for ad-network approval or actual compliance.
- **Ad placeholders:** fixed-size `.ad-slot` containers reserve space
  now so dropping in a real ad script later won't cause layout shift.
- **Backend:** global exception handling (unexpected errors return a
  clean JSON message, never a stack trace or a hang), split rate limits
  (light default vs. a strict 5/min on the actual scraping-backed
  routes), a `/api/stream` zero-storage streaming proxy (CDN-host
  allowlisted so it can't become an open proxy), Docker + docker-compose
  + a sample Nginx/Certbot config for VPS deploys.

## Testing the pipes before the scraper

Before wiring up real extraction (proxy/request rotation, etc.), deploy
the backend with `MOCK_MODE=true` (see `backend/.env.example`). This
returns fixed placeholder media from `/api/fetch` so you can confirm
CORS, headers, rate limiting, and routing all work correctly between
your deployed frontend and backend — independent of whether scraping
itself is working. Check `GET /health` on the deployed backend to
confirm which environment and mode it's running in, then flip
`MOCK_MODE` off once the plumbing is verified.

