// MyDM Downloader 2.3 - toolbar popup
const T = {
  fa: { found: "یافت‌شده در این صفحه", none: "هنوز ویدیو یا موسیقی‌ای پخش نشده است. یکی را پخش کنید.",
        set: "تنظیمات", enabled: "نمایش نوار دانلود هنگام پخش", block: "برای این سایت نشان نده", lang: "زبان",
        on: "MyDM متصل است", off: "MyDM باز نیست", noEngine: "موتور ویدیویی غیرفعال", dl: "دانلود", sent: "ارسال شد ✓", fail: "ارسال نشد",
        note: "اگر صفحه ویدیو را به‌صورت قطعه‌قطعه پخش کند (مثل یوتیوب)، MyDM آن را از طریق موتور ویدیویی خودش می‌گیرد.",
        skipped: "ردشده (چرا نوار نیامد)", why: { seg: "قطعهٔ استریم", yt: "قطعهٔ استریم یوتیوب", chunk: "بخشی از فایل", small: "فایل خیلی کوچک" } },
  en: { found: "Found on this page", none: "No video or music has played yet. Play one.",
        set: "Settings", enabled: "Show the download bar when media plays", block: "Don't ask on this site", lang: "Language",
        on: "MyDM connected", off: "MyDM is not running", noEngine: "video engine off", dl: "Download", sent: "Sent ✓", fail: "Failed",
        note: "If a page plays video in pieces (like YouTube), MyDM fetches it with its own video engine.",
        skipped: "Skipped (why no bar)", why: { seg: "stream segment", yt: "YouTube stream piece", chunk: "part of a file", small: "tiny file" } },
};
const $ = (id) => document.getElementById(id);
const fmt = (n) => n >= 1073741824 ? (n / 1073741824).toFixed(1) + " GB" : n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : n ? Math.round(n / 1024) + " KB" : "";

(async () => {
  const cfg = await chrome.storage.sync.get({ enabled: true, lang: "fa", blocked: [] });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let host = "";
  try { host = new URL(tab.url).hostname; } catch (e) { /* internal page */ }
  const t = T[cfg.lang] || T.fa;
  document.body.dir = cfg.lang === "fa" ? "rtl" : "ltr";
  $("hFound").textContent = t.found; $("hSet").textContent = t.set;
  $("lEnabled").textContent = t.enabled; $("lBlock").textContent = t.block; $("lLang").textContent = t.lang;
  $("note").textContent = t.note;
  $("enabled").checked = cfg.enabled; $("lang").value = cfg.lang; $("block").checked = cfg.blocked.includes(host);
  $("enabled").onchange = (e) => chrome.storage.sync.set({ enabled: e.target.checked });
  $("lang").onchange = async (e) => { await chrome.storage.sync.set({ lang: e.target.value }); location.reload(); };
  $("block").onchange = async (e) => {
    const s = new Set(cfg.blocked);
    e.target.checked ? s.add(host) : s.delete(host);
    cfg.blocked = [...s];
    await chrome.storage.sync.set({ blocked: cfg.blocked });
  };

  chrome.runtime.sendMessage({ type: "ping" }, (app) => {
    $("dot").className = "dot " + (app ? "on" : "off");
    $("st").textContent = app ? t.on + " (v" + app.version + ")" + (app.engine ? "" : " - " + t.noEngine) : t.off;
  });

  const list = (await chrome.runtime.sendMessage({ type: "media", tabId: tab.id })) || [];
  const skip = (await chrome.runtime.sendMessage({ type: "skipped", tabId: tab.id })) || [];
  if (skip.length) {
    const h = document.createElement("h2"); h.textContent = t.skipped; h.style.marginTop = "12px"; $("list").after(h);
    skip.slice(-4).reverse().forEach((x) => {
      const d = document.createElement("div"); d.className = "empty";
      d.textContent = (t.why[x.why] || x.why) + " · " + (x.url.split("?")[0].split("/").pop() || x.url).slice(0, 40);
      h.after(d);
    });
  }
  if (!list.length) { const d = document.createElement("div"); d.className = "empty"; d.textContent = t.none; $("list").append(d); }
  for (const m of list.slice().reverse()) {
    const row = document.createElement("div"); row.className = "item";
    const n = document.createElement("div"); n.className = "n";
    const b = document.createElement("b");
    try { b.textContent = decodeURIComponent(new URL(m.url).pathname.split("/").pop()) || m.url; } catch (e) { b.textContent = m.url; }
    const s = document.createElement("small"); s.textContent = [m.stream ? (m.master ? "HLS/DASH" : "stream") : m.kind, (m.ext || "").toUpperCase(), fmt(m.size)].filter(Boolean).join(" · ");
    n.append(b, s);
    const btn = document.createElement("button"); btn.textContent = t.dl;
    btn.onclick = async () => {
      const r = await chrome.runtime.sendMessage({ type: "download", url: m.url, referer: tab.url, name: "", action: "start", kind: m.stream ? "stream" : "file" });
      $("msg").textContent = r && r.ok ? t.sent : t.fail;
    };
    row.append(n, btn); $("list").append(row);
  }
})();
