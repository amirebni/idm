// MyDM Downloader 2.3 - content script
(() => {
  if (window.__mydmLoaded) return;
  window.__mydmLoaded = true;

  const L = {
    fa: { dir: "rtl", video: "می‌خواهید این ویدیو را دانلود کنید؟", audio: "می‌خواهید این موسیقی را دانلود کنید؟",
          dl: "دانلود", later: "بعداً", never: "برای این سایت نشان نده", sent: "به MyDM ارسال شد ✓",
          sentSite: "در MyDM باز شد؛ کیفیت را آنجا انتخاب کنید ✓",
          fail: "برنامهٔ MyDM باز نیست.", browser: "دانلود با مرورگر",
          noengine: "موتور ویدیویی MyDM بارگذاری نشده است (در MyDM: تنظیمات ← Video را ببینید)." },
    en: { dir: "ltr", video: "Download this video?", audio: "Download this music?",
          dl: "Download", later: "Not now", never: "Don't ask on this site", sent: "Sent to MyDM ✓",
          sentSite: "Opened in MyDM - choose the quality there ✓",
          fail: "MyDM is not running.", browser: "Download with browser",
          noengine: "MyDM's video engine did not load (see Settings > Video in MyDM)." },
  };
  const SKIP = new Set(["m3u8", "mpd", "ts", "m4s"]);
  const VIDEO_HOSTS = /(^|\.)(youtube\.com|youtu\.be|aparat\.com|vimeo\.com|dailymotion\.com|instagram\.com|tiktok\.com|twitch\.tv)$/;
  const CSS = `
    *{box-sizing:border-box}
    .bar{position:fixed;z-index:2147483647;display:flex;align-items:center;gap:12px;padding:9px 12px;
      border-radius:14px;font:14px/1.35 "Segoe UI",Tahoma,Arial,sans-serif;color:#fff;overflow:hidden;
      background:rgba(20,24,31,.95);border:1px solid rgba(255,255,255,.14);
      box-shadow:0 10px 30px rgba(0,0,0,.4);animation:in .25s ease-out}
    @keyframes in{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:none}}
    @keyframes shrink{from{width:100%}to{width:0}}
    .logo{flex:none;width:32px;height:32px;border-radius:9px;background:#2563eb;display:grid;place-items:center}
    .txt{flex:1;min-width:0}
    .t1{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .t2{opacity:.65;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .ok{color:#4ade80;font-weight:600}.err{color:#f87171}
    button{font:inherit;border:0;border-radius:9px;padding:7px 15px;cursor:pointer;color:#fff;
      background:rgba(255,255,255,.13);flex:none}
    button:hover{filter:brightness(1.2)}
    button.pri{background:#2563eb;font-weight:600}
    .x{padding:3px 8px;background:transparent;opacity:.6;font-size:18px;line-height:1}
    .never{background:none;padding:0;font-size:11px;opacity:.55;text-decoration:underline;display:block;margin-top:2px}
    .prog{position:absolute;bottom:0;left:0;height:3px;width:100%;background:#3b82f6;
      animation:shrink 15s linear forwards}
    .bar:hover .prog{animation-play-state:paused}`;
  const ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M10.5 3h3v8h4.2L12 17.2 6.3 11h4.2z"/><rect x="5" y="19" width="14" height="2" rx="1"/></svg>';

  let cfg = { enabled: true, lang: "fa", blocked: [] };
  const load = () => chrome.storage.sync.get(cfg, (v) => { cfg = { ...cfg, ...v }; });
  load();
  chrome.storage.onChanged.addListener(load);

  const offered = new Map();
  let closeCurrent = null;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const extOf = (u) => { try { return ((new URL(u).pathname.match(/\.([a-z0-9]{2,5})$/i) || [])[1] || "").toLowerCase(); } catch (e) { return ""; } };
  const fmtSize = (n) => n >= 1073741824 ? (n / 1073741824).toFixed(1) + " GB" : n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";

  document.addEventListener("play", (e) => onPlay(e.target), true);

  async function onPlay(el) {
    if (!(el instanceof HTMLMediaElement) || !cfg.enabled) return;
    if (cfg.blocked.includes(location.hostname)) return;
    if (el.muted && (el.loop || el.autoplay)) return;        // decorative background video
    if (isFinite(el.duration) && el.duration < 15) return;   // UI sounds, tiny clips
    const media = el.tagName === "AUDIO" ? "audio" : "video";
    try {
      const r = await chrome.runtime.sendMessage({ type: "supports", url: location.href });
      if (r && r.site) return offer(el, { url: location.href, media, mode: "site", ext: "", size: 0 });
      // a video site, but MyDM or its video engine is not available: say so instead of staying silent
      if (r && VIDEO_HOSTS.test(location.hostname) && (!r.app || !r.engine)) {
        return offer(el, { url: location.href, media, mode: "msg", msg: r.app ? "noengine" : "fail", ext: "", size: 0 });
      }
    } catch (e) { /* extension reloaded */ }
    for (let i = 0; i < 6; i++) {
      const c = await pick(el);
      if (c) return offer(el, c);
      await sleep(700);
    }
  }

  async function pick(el) {
    const media = el.tagName === "AUDIO" ? "audio" : "video";
    const direct = el.currentSrc || el.src || "";
    if (/^https?:/i.test(direct) && !SKIP.has(extOf(direct))) {
      return { url: direct, media, mode: "file", ext: extOf(direct), size: 0 };
    }
    let list = [];
    try { list = (await chrome.runtime.sendMessage({ type: "media" })) || []; } catch (e) { return null; }
    const recent = list.filter((x) => Date.now() - x.t < 180000);
    const files = recent.filter((x) => !x.stream && x.kind === media).sort((a, b) => b.size - a.size || b.t - a.t);
    // players ask for the master playlist first: prefer one seen in the last 30 s (earliest), else the newest
    const fresh = recent.filter((x) => x.stream && Date.now() - x.t < 30000);
    const streams = fresh.length ? fresh.sort((a, b) => (b.master - a.master) || a.t - b.t)
                                 : recent.filter((x) => x.stream).sort((a, b) => (b.master - a.master) || b.t - a.t);
    const f = files[0], st = streams[0];
    // a big plain file wins; otherwise take the stream (HLS/DASH) the player is using
    const x = f && (f.size >= 3145728 || !st) ? f : st || f;
    return x ? { url: x.url, media: x.kind, mode: x.stream ? "stream" : "file", ext: x.ext, size: x.size } : null;
  }

  function offer(el, c) {
    const key = c.url.split("#")[0];
    if (offered.has(key) && Date.now() - offered.get(key) < 300000) return;
    offered.set(key, Date.now());
    showBar(el, c);
  }

  function showBar(el, c) {
    if (closeCurrent) closeCurrent();
    const t = L[cfg.lang] || L.fa;
    const host = document.createElement("div");
    host.id = "mydm-bar-host";
    host.style.cssText = "all:initial";
    const root = host.attachShadow({ mode: "open" });
    try { const s = new CSSStyleSheet(); s.replaceSync(CSS); root.adoptedStyleSheets = [s]; }
    catch (e) { const st = document.createElement("style"); st.textContent = CSS; root.appendChild(st); }
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.dir = t.dir;
    const title = (document.title || "").replace(/\s+/g, " ").trim().slice(0, 120);
    const ext = c.mode === "stream" ? "mp4" : c.ext || (c.media === "audio" ? "mp3" : "mp4");
    const name = title ? title + "." + ext : "";
    const shown = c.mode === "site" ? title : name || decodeURIComponent(c.url.split("?")[0].split("/").pop() || "");
    bar.innerHTML = `<div class="logo">${ICON}</div>
      <div class="txt"><div class="t1"></div><div class="t2"></div></div>
      <span class="acts"></span><button class="x" title="×">×</button><div class="prog"></div>`;
    const $ = (s) => bar.querySelector(s);
    $(".t1").textContent = c.media === "audio" ? t.audio : t.video;
    $(".t2").textContent = shown + (c.size ? "  ·  " + fmtSize(c.size) : "");
    const acts = $(".acts");
    const mk = (cls, text, fn) => { const b = document.createElement("button"); if (cls) b.className = cls; b.textContent = text; b.onclick = fn; return b; };
    const nv = mk("never", t.never, () => {
      cfg.blocked = [...new Set([...cfg.blocked, location.hostname])];
      chrome.storage.sync.set({ blocked: cfg.blocked });
      close();
    });
    if (c.mode === "msg") {
      $(".t1").className = "t1 err"; $(".t1").textContent = t[c.msg]; $(".t2").textContent = "";
      acts.append(mk("", t.later, close));
    } else {
      acts.append(mk("pri", t.dl, send), mk("", t.later, close));
      $(".txt").appendChild(nv);
    }
    $(".x").onclick = close;
    root.appendChild(bar);
    document.documentElement.appendChild(host);

    let alive = true, raf = 0, timer = setTimeout(close, 15000);
    bar.addEventListener("mouseenter", () => clearTimeout(timer));
    bar.addEventListener("mouseleave", () => { timer = setTimeout(close, 6000); });
    function place() {
      if (!alive) return;
      const r = el.getBoundingClientRect();
      const big = r.width >= 260 && r.height >= 140;
      const w = big ? Math.min(r.width - 16, 640) : Math.min(window.innerWidth - 24, 640);
      const left = big ? Math.max(r.left, 0) + 8 + (r.width - 16 - w) / 2 : (window.innerWidth - w) / 2;
      const top = big ? Math.min(Math.max(r.top, 0) + 8, window.innerHeight - 70) : 12;
      bar.style.cssText = `left:${left}px;top:${top}px;width:${w}px;`;
      host.style.display = document.fullscreenElement ? "none" : "";
      raf = requestAnimationFrame(place);
    }
    place();
    function close() { alive = false; clearTimeout(timer); cancelAnimationFrame(raf); host.remove(); if (closeCurrent === close) closeCurrent = null; }
    closeCurrent = close;

    async function send() {
      clearTimeout(timer);
      bar.querySelector(".prog").remove();
      acts.textContent = "";
      nv.remove();
      let res = null;
      try {
        res = await chrome.runtime.sendMessage({ type: "download", url: c.url, referer: location.href,
                                                  name, action: "start", kind: c.mode });
      } catch (e) { /* extension reloaded */ }
      const t1 = $(".t1");
      if (res && res.ok) {
        t1.className = "t1 ok"; t1.textContent = c.mode === "site" ? t.sentSite : t.sent;
        setTimeout(close, 3000);
      } else {
        t1.className = "t1 err"; t1.textContent = t.fail;
        acts.append(mk("pri", t.browser, () => {
          chrome.runtime.sendMessage({ type: "browserDownload", url: c.url });
          close();
        }));
        timer = setTimeout(close, 9000);
      }
    }
  }
})();
