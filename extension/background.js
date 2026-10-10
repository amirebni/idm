// MyDM Downloader 2.4 - background service worker
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
        return { port: p, version: j.version, engine: !!j.engine };
      }
    } catch (e) { /* try the next port */ }
  }
  return null;
}

// does the app's video engine (yt-dlp) know this page? (YouTube, Aparat, Varzesh3, ...)
const supCache = new Map();
async function supports(url) {
  const c = supCache.get(url);
  if (c && Date.now() - c.t < (c.v.site ? 60000 : 3000)) return c.v;
  const app = await findApp();
  let v = { site: false, engine: !!(app && app.engine), app: !!app };
  if (app) {
    try {
      const r = await fetch(`http://127.0.0.1:${app.port}/supports`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      const j = await r.json();
      v = { site: !!j.site, engine: !!j.engine, app: true };
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
    const cs = await chrome.cookies.getAll({ url: m.cookieUrl || m.url });
    cookie = cs.map((c) => c.name + "=" + c.value).join("; ");
  } catch (e) { /* no cookies */ }
  try {
    const r = await fetch(`http://127.0.0.1:${app.port}/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: m.url, referer: m.referer || "", cookie, ua: navigator.userAgent,
                             name: m.name || "", action: m.action || "start", kind: m.kind || "file",
                             urls: m.urls || [] }),
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
  if (msg.type === "supports") { supports(msg.url).then((v) => reply(v)); return true; }
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

// ---------- right-click menu: "Download with MyDM" ----------
const fa = (chrome.i18n.getUILanguage() || "").startsWith("fa");
const MENU_TITLE = fa ? "دانلود با MyDM" : "Download with MyDM";
const MENU_LINKS = fa ? "دانلود لینک‌های انتخاب‌شده با MyDM" : "Download selected links with MyDM";

function makeMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "mydm-link", title: MENU_TITLE, contexts: ["link", "video", "audio"] });
    chrome.contextMenus.create({ id: "mydm-sel", title: MENU_LINKS, contexts: ["selection"] });
  });
}
chrome.runtime.onInstalled.addListener(makeMenus);
chrome.runtime.onStartup.addListener(makeMenus);

// runs inside the page: every link (and media source) inside the selection, plus URLs typed as text
function collectSelection() {
  const sel = getSelection(), out = [];
  if (!sel || sel.isCollapsed) return out;
  const add = (u) => {
    try {
      const x = new URL(u, location.href);
      if (/^https?:$/.test(x.protocol)) out.push(x.href);
    } catch (e) { /* not a link */ }
  };
  for (const a of document.querySelectorAll("a[href]")) {
    if (sel.containsNode(a, true)) add(a.href);
  }
  for (const m of document.querySelectorAll("video[src], audio[src], source[src]")) {
    if (sel.containsNode(m, true)) add(m.src);
  }
  for (const u of sel.toString().match(/https?:\/\/[^\s<>"']+/g) || []) add(u);
  return out;
}

function flash(tabId, ok) {
  chrome.action.setBadgeBackgroundColor({ color: ok ? "#16a34a" : "#dc2626", tabId });
  chrome.action.setBadgeText({ text: ok ? "\u2713" : "!", tabId });
  setTimeout(() => chrome.action.setBadgeText({ text: "", tabId }).catch(() => {}), 3500);
}

async function onMenu(info, tab) {
  const page = info.frameUrl || info.pageUrl || (tab && tab.url) || "";
  let r;
  if (info.menuItemId === "mydm-link") {
    const url = info.linkUrl || info.srcUrl;
    if (!url || !/^https?:/.test(url)) return;
    r = await sendToApp({ url, referer: page, kind: "link", action: "start" });
  } else if (info.menuItemId === "mydm-sel" && tab) {
    let urls = [];
    try {
      const res = await chrome.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [info.frameId || 0] }, func: collectSelection });
      urls = [...new Set(res.flatMap((x) => x.result || []))];
    } catch (e) { /* page not scriptable */ }
    if (!urls.length) urls = [...new Set((info.selectionText || "").match(/https?:\/\/[^\s<>"']+/g) || [])];
    if (!urls.length) { flash(tab.id, false); return; }
    r = await sendToApp({ url: urls[0], urls, referer: page, kind: "links", action: "start" });
  } else return;
  if (tab && tab.id >= 0) flash(tab.id, !!(r && r.ok));
}
chrome.contextMenus.onClicked.addListener((i, t) => { onMenu(i, t); });
