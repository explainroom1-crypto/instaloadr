/**
 * popup.js — reads the active tab's URL and calls the same backend
 * used by the website (/api/fetch). Set API_BASE_URL to your deployed
 * backend before packaging the extension for real use.
 */
const API_BASE_URL = "http://localhost:8000"; // TODO: replace with your deployed backend URL

const urlEl = document.getElementById("url");
const btn = document.getElementById("fetchBtn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

function isInstagramUrl(value) {
  try {
    const u = new URL(value);
    return /(^|\.)instagram\.com$/.test(u.hostname);
  } catch {
    return false;
  }
}

async function getActiveTabUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.url || "";
}

async function init() {
  const tabUrl = await getActiveTabUrl();
  urlEl.textContent = tabUrl || "No active tab URL found.";

  if (isInstagramUrl(tabUrl)) {
    btn.disabled = false;
    btn.textContent = "Fetch downloads";
    btn.onclick = () => fetchDownloads(tabUrl);
  }
}

async function fetchDownloads(url) {
  btn.disabled = true;
  btn.textContent = "Fetching…";
  statusEl.textContent = "";
  resultsEl.innerHTML = "";

  try {
    const res = await fetch(`${API_BASE_URL}/api/fetch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = data.detail || "Couldn't process that link.";
      return;
    }

    statusEl.textContent = `${data.items.length} item(s) found.`;
    data.items.forEach((item, i) => {
      const a = document.createElement("a");
      a.href = item.download_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.download = "";
      a.textContent = `Frame ${i + 1} — ${item.media_type}`;
      resultsEl.appendChild(a);
    });
  } catch (err) {
    statusEl.textContent = "Couldn't reach the backend.";
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Fetch downloads";
  }
}

init();
