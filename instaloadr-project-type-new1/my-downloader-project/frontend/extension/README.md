# InstaLoadr browser extension

A minimal MV3 popup that reads the current tab's URL and calls the same
backend `/api/fetch` endpoint the website uses.

## Load locally

**Chrome:** `chrome://extensions` → enable Developer Mode → "Load unpacked" → select this `extension/` folder.

**Firefox:** `about:debugging#/runtime/this-firefox` → "Load Temporary Add-on" → select `manifest.json`.

## Before shipping

- Set `API_BASE_URL` in `popup.js` to your deployed backend, and make
  sure that backend's `CORS_ALLOWED_ORIGINS` allows extension origins
  (`chrome-extension://<id>` / `moz-extension://<id>`) if you call it
  directly from the popup rather than through a background script.
- Add a real `icon-48.png` (referenced in `manifest.json`).
- Chrome Web Store / Firefox Add-ons both require a review before
  public listing — read their respective developer policies before
  submitting, particularly around scraping third-party sites.
