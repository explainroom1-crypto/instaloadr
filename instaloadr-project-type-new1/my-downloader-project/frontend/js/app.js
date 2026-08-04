/**
 * app.js — Frontend-to-Backend bridge.
 */

const PRODUCTION_API_BASE_URL = "http://129.121.126.99:5000";
const LOCAL_API_BASE_URL = "http://localhost:5000";

const API_BASE_URL =
  window.DOWNLOADER_API_BASE_URL ||
  (["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? LOCAL_API_BASE_URL
    : PRODUCTION_API_BASE_URL);

function $(sel, root = document) {
  return root.querySelector(sel);
}

function setStatus(el, message, kind) {
  if (!el) return;
  el.textContent = message;
  el.className = `status-line show ${kind}`;
}

function clearStatus(el) {
  if (!el) return;
  el.textContent = "";
  el.className = "status-line";
}

const PATH_PATTERNS = {
  post: /^\/(p|reel)\/[\w-]+\/?/i,
  video: /^\/(p|reel|tv)\/[\w-]+\/?/i,
  reel: /^\/(reel|reels)\/[\w-]+\/?/i,
  story: /^\/stories\/[\w.\-]+\/?/i,
  audio: /^\/(reel|reels|p)\/[\w-]+\/?/i,
  dp: /^\/(?!p\/|reel\/|reels\/|stories\/)[\w.]+\/?$/i,
};

const MEDIA_TYPE_LABELS = {
  post: "a post",
  video: "a video",
  reel: "a Reel",
  story: "a Story",
  audio: "a Reel or video",
  dp: "a profile",
};

function validateInstagramUrl(value, mediaType) {
  let parsed;
  try {
    parsed = new URL(value.trim());
  } catch {
    return "That doesn't look like a valid URL.";
  }
  if (!/(^|\.)instagram\.com$/i.test(parsed.hostname)) {
    return "That doesn't look like an instagram.com link.";
  }
  const pattern = PATH_PATTERNS[mediaType];
  if (pattern && !pattern.test(parsed.pathname)) {
    return `That's an Instagram link, but not ${MEDIA_TYPE_LABELS[mediaType] || "the right type of"} link — check you're on the right page.`;
  }
  return null;
}

const FRAME_TYPE_LABELS = {
  image: "Instagram photo",
  photo: "Instagram photo",
  video: "Instagram video",
  reel: "Instagram Reel",
  story: "Instagram Story",
  audio: "Instagram audio",
  dp: "Instagram profile picture",
};

function renderFrames(strip, items) {
  strip.innerHTML = "";
  items.forEach((item, i) => {
    const frame = document.createElement("div");
    frame.className = "frame";
    const rawType = (item.media_type || "").toLowerCase();
    const typeLabel = FRAME_TYPE_LABELS[rawType] || "Instagram media";
    const frameText = `${typeLabel} preview — frame ${i + 1}`;
    frame.innerHTML = `
      <div class="thumb">
        ${item.thumbnail_url
          ? `<img src="${item.thumbnail_url}" alt="${frameText}" title="${frameText}" loading="lazy" decoding="async" style="width:100%;height:100%;object-fit:cover;">`
          : `FRAME ${String(i + 1).padStart(2, "0")}`}
      </div>
      <div class="frame-foot">
        <span>${(item.media_type || "media").toUpperCase()}${item.width ? ` · ${item.width}×${item.height}` : ""}</span>
        <button type="button" class="dl-btn" data-download-url="${item.download_url}" data-media-type="${item.media_type || ""}"${item.audio_url ? ` data-audio-url="${item.audio_url}"` : ""}>Save</button>
      </div>
    `;
    strip.appendChild(frame);
  });
}

async function downloadSingleItem(button) {
  const cdnUrl = button.dataset.downloadUrl;
  const audioUrl = button.dataset.audioUrl;
  const originalLabel = button.textContent;
  const isVideo = button.dataset.mediaType === "mp4" || button.dataset.mediaType === "reel";

  button.disabled = true;
  button.textContent = "Connecting…";

  const streamUrl = audioUrl
    ? `${API_BASE_URL}/api/stream-merged?video_url=${encodeURIComponent(cdnUrl)}&audio_url=${encodeURIComponent(audioUrl)}`
    : `${API_BASE_URL}/api/stream?url=${encodeURIComponent(cdnUrl)}`;

  try {
    const res = await fetch(streamUrl);

    if (!res.ok) {
      window.open(cdnUrl, "_blank", "noopener");
      button.textContent = originalLabel;
      button.disabled = false;
      return;
    }
    if (!res.body) throw new Error("download failed");

    const total = Number(res.headers.get("content-length")) || 0;
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;

    button.textContent = isVideo ? "Streaming Video…" : "Downloading…";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      if (total) {
        button.textContent = `${Math.min(99, Math.round((received / total) * 100))}%`;
      }
    }

    const blob = new Blob(chunks);
    const blobUrl = URL.createObjectURL(blob);
    const ext = button.dataset.mediaType === "mp4" ? "mp4" : (button.dataset.mediaType || "jpg");
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `instaloadr-frame.${ext}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    button.textContent = "Saved ✓";
  } catch (err) {
    console.error(err);
    button.textContent = "Failed — retry";
    button.disabled = false;
    return;
  }

  setTimeout(() => {
    button.textContent = originalLabel;
    button.disabled = false;
  }, 1500);
}

async function downloadZip({ url, mediaType, statusEl, zipButton }) {
  const originalLabel = zipButton.textContent;
  zipButton.disabled = true;
  zipButton.textContent = "Zipping…";
  setStatus(statusEl, "Bundling every frame into a .zip…", "info");

  try {
    const res = await fetch(`${API_BASE_URL}/api/bundle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, media_type: mediaType }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setStatus(statusEl, data.detail || "Couldn't build the zip.", "error");
      return;
    }

    const blob = await res.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "instaloadr-download.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus(statusEl, "Zip downloaded.", "info");
  } catch (err) {
    setStatus(statusEl, "Couldn't reach the backend for the zip download.", "error");
    console.error(err);
  } finally {
    zipButton.disabled = false;
    zipButton.textContent = originalLabel;
  }
}

function initDownloader({ formSelector, mediaType }) {
  const form = $(formSelector);
  if (!form) return;

  const input = $("input[type='url'], input[type='text']", form);
  const button = $("button[type='submit']", form);
  const statusEl = form.parentElement.querySelector(".status-line");
  const sheet = form.parentElement.querySelector(".contact-sheet");
  const strip = sheet ? sheet.querySelector(".frame-strip") : null;

  if (strip) {
    strip.addEventListener("click", (e) => {
      const btn = e.target.closest(".dl-btn");
      if (btn) downloadSingleItem(btn);
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = input.value.trim();
    clearStatus(statusEl);

    if (!url) {
      setStatus(statusEl, "Paste a link before fetching.", "error");
      return;
    }
    const validationError = validateInstagramUrl(url, mediaType);
    if (validationError) {
      setStatus(statusel, validationError, "error");
      return;
    }

    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Fetching…";
    setStatus(statusEl, "Contacting the loader…", "info");
    if (strip) strip.innerHTML = "";

    try {
      const res = await fetch(`${API_BASE_URL}/api/fetch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, media_type: mediaType }),
      });

      const data = await res.json();

      if (!res.ok) {
        setStatus(statusEl, data.detail || "Couldn't process that link.", "error");
        return;
      }

      if (!data.items || data.items.length === 0) {
        setStatus(statusEl, "No downloadable media found at that link.", "warn");
        return;
      }

      setStatus(statusEl, `Ready — ${data.items.length} frame(s) found.`, "info");
      if (strip) renderFrames(strip, data.items);

      const zipButton = form.parentElement.querySelector("[data-zip-all]");
      if (zipButton) {
        if (data.items.length > 1) {
          zipButton.hidden = false;
          zipButton.onclick = () =>
            downloadZip({ url, mediaType, statusEl, zipButton });
        } else {
          zipButton.hidden = true;
        }
      }
    } catch (err) {
      setStatus(
        statusEl,
        "Couldn't reach the backend. Check that the API is running and reachable.",
        "error"
      );
      console.error(err);
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });
}

function initPasteButtons() {
  document.querySelectorAll("[data-paste-btn]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = btn.closest(".loader-slot")?.querySelector("input");
      if (!input) return;
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          input.value = text.trim();
          input.focus();
        }
      } catch {
        input.focus();
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-downloader]").forEach((form) => {
    initDownloader({
      formSelector: `#${form.id}`,
      mediaType: form.dataset.downloader,
    });
  });
  initPasteButtons();
});
