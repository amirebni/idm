// MyDM Downloader 2.2 - background service worker
const PORTS = [17890, 17891, 17892, 17893, 17894, 17895, 17896, 17897, 17898, 17899];
const MEDIA_EXT = new Set(["mp4", "m4v", "webm", "mkv", "mov", "avi", "flv", "wmv",
  "mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac"]);
const AUDIO_EXT = new Set(["mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac"]);
const SKIP_EXT = new Set(["m3u8", "mpd", "ts", "m4s", "vtt", "srt", "key"]);
const TYPE_EXT = { "video/mp4": "mp4", "video/webm": "webm", "video/x-matroska": "mkv",
  "video/quicktime": "mov", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a",
  "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/ogg": "ogg", "audio/webm": "webm",
  "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac" };

const extOf = (u) => {
  try { return ((new URL(u).pathname.match(/\.([a-z0-9]{2,5})$/i) || [])[1] || "").toLowerCase(); }
  catch (e) { return ""; }
};

// ---------- remember the media files each tab has requested ----------
let chain = Promise.resolve();
function remember(tabId, item) {
  chain = chain.then(async () => {
    const key = "m" + tabId;
    const got = await chrome.storage.session.get(key);
    const list = (got[key] || []).filter((x) => x.url !== item.url);
    list.push(item);
    await chrome.storage.session.set({ [key]: list.slice(-30) });
  }).catch(() => {});
}

function skipped(tabId, url, why) {
  chain = chain.then(async () => {
    const key = "s" + tabId;
    const got = await chrome.storage.session.get(key);
    const list = (got[key] || []).filter((x) => x.url !== url);
    list.push({ url, why, t: Date.now() });
    await chrome.storage.session.set({ [key]: list.slice(-12) });
  }).catch(() => {});
}

// HLS / DASH manifests: remember them, and note whether it is the "master" (quality list) one
async function addManifest(d, type) {
  let master = /dash\+xml/.test(type);
  try {
    const text = await (await fetch(d.url, { credentials: "include" })).text();
    master = master || text.includes("#EXT-X-STREAM-INF") || text.includes("<MPD");
  } catch (e) { /* keep the guess */ }
  remember(d.tabId, { url: d.url, type, size: 0, ext: "mp4", kind: "video", stream: true, master, t: Date.now() });
}

chrome.webRequest.onHeadersReceived.addListener((d) => {
  if (d.tabId < 0 || (d.statusCode !== 200 && d.statusCode !== 206)) return;
  const h = {};
  for (const x of d.responseHeaders || []) h[x.name.toLowerCase()] = x.value || "";
  const type = (h["content-type"] || "").split(";")[0].trim().toLowerCase();
  const ext = extOf(d.url);
  if (/mpegurl|dash\+xml/.test(type) || ext === "m3u8" || ext === "mpd") { addManifest(d, type); return; }
  const generic = type === "" || type === "application/octet-stream" || type === "binary/octet-stream";
  const isMedia = type.startsWith("video/") || type.startsWith("audio/") || (generic && MEDIA_EXT.has(ext));
  if (!isMedia) return;
  if (SKIP_EXT.has(ext)) { skipped(d.tabId, d.url, "seg"); return; }
  // adaptive-streaming pieces (YouTube etc.) are not complete files
  if (/googlevideo\.com\/videoplayback/.test(d.url)) { skipped(d.tabId, d.url, "yt"); return; }
  if (/[?&](range|bytestart)=/i.test(d.url)) { skipped(d.tabId, d.url, "chunk"); return; }
  let size = 0;
  const cr = h["content-range"];
  if (cr && /\/(\d+)$/.test(cr)) size = +RegExp.$1;
  else if (h["content-length"] && d.statusCode === 200) size = +h["content-length"];
  if (size && size < 150 * 1024) { skipped(d.tabId, d.url, "small"); return; }   // UI sounds, tiny clips
  const kind = type.startsWith("audio/") || AUDIO_EXT.has(ext) ? "audio" : "video";
  remember(d.tabId, { url: d.url, type, size, ext: TYPE_EXT[type] || ext, kind, t: Date.now() });
}, { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other"] }, ["responseHeaders"]);

chrome.tabs.onRemoved.addListener((id) => chrome.storage.session.remove(["m" + id, "s" + id]));
chrome.tabs.onUpdated.addListener((id, info) => { if (info.url) chrome.storage.session.remove(["m" + id, "s" + id]); });

// ---------- talk to the MyDM desktop app ----------
async function findApp() {
  const { port } = await chrome.storage.session.get("port");
  const order = port ? [port, ...PORTS.filter((p) => p !== port)] : PORTS;
  for (const p of order) {
    try {
      const r = await fetch(`http://127.0.0.1:${p}/ping`, { signal: AbortSignal.timeout(700) });
      const j = await r.json();
      if (j.app === "MyDM") {
        await chrome.storage.session.set({ port: p });
        return { port: p, version: j.version };
      }
    } catch (e) { /* try the next port */ }
  }
  return null;
}

// does the app's video engine (yt-dlp) know this page? (YouTube, Aparat, Varzesh3, ...)
const supCache = new Map();
async function supports(url) {
  const c = supCache.get(url);
  if (c && Date.now() - c.t < 60000) return c.v;
  const app = await findApp();
  let v = false;
  if (app) {
    try {
      const r = await fetch(`http://127.0.0.1:${app.port}/supports`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      v = !!(await r.json()).site;
    } catch (e) { /* not supported */ }
  }
  supCache.set(url, { v, t: Date.now() });
  return v;
}

async function sendToApp(m) {
  const app = await findApp();
  if (!app) return { ok: false, error: "not-running" };
  let cookie = "";
  try {
    const cs = await chrome.cookies.getAll({ url: m.url });
    cookie = cs.map((c) => c.name + "=" + c.value).join("; ");
  } catch (e) { /* no cookies */ }
  try {
    const r = await fetch(`http://127.0.0.1:${app.port}/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: m.url, referer: m.referer || "", cookie, ua: navigator.userAgent,
                             name: m.name || "", action: m.action || "start", kind: m.kind || "file" }),
    });
    return { ok: r.ok, error: r.ok ? "" : "refused" };
  } catch (e) { return { ok: false, error: "failed" }; }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "media") {
    const id = msg.tabId != null ? msg.tabId : sender.tab && sender.tab.id;
    chrome.storage.session.get("m" + id).then((g) => reply(g["m" + id] || []));
    return true;
  }
  if (msg.type === "download") { sendToApp(msg).then(reply); return true; }
  if (msg.type === "supports") { supports(msg.url).then((site) => reply({ site })); return true; }
  if (msg.type === "skipped") {
    const id = msg.tabId != null ? msg.tabId : sender.tab && sender.tab.id;
    chrome.storage.session.get("s" + id).then((g) => reply(g["s" + id] || []));
    return true;
  }
  if (msg.type === "ping") { findApp().then((a) => reply(a || null)); return true; }
  if (msg.type === "browserDownload") {
    chrome.downloads.download({ url: msg.url }).then(() => reply({ ok: true }), () => reply({ ok: false }));
    return true;
  }
});

// ---------- toolbar icon (drawn in code, so no image files are needed) ----------
function drawIcon() {
  try {
    const imageData = {};
    for (const s of [16, 32, 48, 128]) {
      const c = new OffscreenCanvas(s, s), g = c.getContext("2d");
      g.fillStyle = "#2563eb";
      g.beginPath();
      g.roundRect(0, 0, s, s, s * 0.22);
      g.fill();
      g.fillStyle = "#fff";
      g.fillRect(s * 0.42, s * 0.16, s * 0.16, s * 0.34);
      g.beginPath();
      g.moveTo(s * 0.26, s * 0.46);
      g.lineTo(s * 0.74, s * 0.46);
      g.lineTo(s * 0.5, s * 0.72);
      g.fill();
      g.fillRect(s * 0.24, s * 0.78, s * 0.52, s * 0.07);
      imageData[s] = g.getImageData(0, 0, s, s);
    }
    chrome.action.setIcon({ imageData });
  } catch (e) { /* default icon is fine */ }
}
drawIcon();
