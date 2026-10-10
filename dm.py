import os, re, sys, json, math, time, queue, shutil, mimetypes, threading, subprocess
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse, unquote, urljoin
import requests

def _bundled_modules():
    """Never called. It only lists every standard-library module that yt-dlp (loaded from its zip
    file at run time) can use, so that PyInstaller keeps them inside the exe."""
    import _winapi, abc, array, asyncio, atexit, base64, binascii, bisect, calendar, codecs
    import collections, collections.abc, concurrent.futures, contextlib, contextvars, copy
    import ctypes, ctypes.util, ctypes.wintypes, dataclasses, datetime, email.header
    import email.message, email.parser, email.utils, encodings.idna, encodings.utf_8_sig, enum
    import errno, fcntl, fileinput, functools, getpass, glob, hashlib, heapq, hmac
    import html.entities, html.parser, http, http.client, http.cookiejar, http.cookies
    import http.server, importlib, importlib.abc, importlib.machinery, importlib.resources
    import importlib.util, inspect, io, itertools, locale, logging, math, mimetypes, msvcrt
    import netrc, operator, optparse, pathlib, pkgutil, platform, pty, quopri, random, secrets
    import shlex, signal, socket, sqlite3, ssl, string, struct, sysconfig, tempfile, textwrap
    import tokenize, traceback, types, typing, unicodedata, urllib, urllib.error, urllib.parse
    import urllib.request, urllib.response, uuid, warnings, winreg, xml.etree.ElementTree
    import zipfile, zipimport, zlib

try:
    from tkinterdnd2 import TkinterDnD, DND_TEXT, DND_FILES
    BaseTk = TkinterDnD.Tk
except Exception:
    TkinterDnD, BaseTk = None, tk.Tk

DATA = Path(os.environ.get("MYDM_HOME") or Path.home() / ".mydm")
STATE = DATA / "state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
CATS = {
    "Video": "mp4 mkv avi mov wmv flv webm ts m4v mpg mpeg 3gp",
    "Music": "mp3 flac wav aac ogg m4a wma opus",
    "Documents": "pdf doc docx xls xlsx ppt pptx txt epub csv rtf",
    "Compressed": "zip rar 7z tar gz bz2 xz",
    "Programs": "exe msi dmg pkg apk deb rpm iso",
    "Images": "jpg jpeg png gif webp bmp svg tif tiff",
}
EXT2CAT = {e: c for c, s in CATS.items() for e in s.split()}
CAT_LIST = list(CATS) + ["Other"]
CAT_COL = {"Video": "#7286cc", "Music": "#c574a1", "Documents": "#628aca",
           "Compressed": "#c39953", "Programs": "#4d9b85", "Images": "#57a2af",
           "Other": "#85919e"}
EXTS = set(EXT2CAT) | {"torrent", "bin", "img", "m3u8", "mpd"}
RUNNING = ("Waiting", "Connecting", "Downloading")
ACTIONS = ["Do nothing", "Exit MyDM", "Lock screen", "Log off", "Sleep", "Hibernate",
           "Restart", "Shut down", "Shut down (force close apps)"]
WIN = sys.platform.startswith("win")
VERSION = "2.6"
EXT_ID = "njeclpgnkpobfkiefclomnolojaacned"          # fixed ID of the bundled browser extension
PORTS = range(17890, 17900)
SCHED = {"start_on": False, "start": "02:00", "stop_on": False, "stop": "07:00",
         "daily": True, "action": "Do nothing", "on_finish": False}
CFG = {"folder": str(Path.home() / "Downloads"), "segments": 8, "parallel": 3,
       "limit_kb": 0, "proxy_mode": "system", "proxy": "", "watch": True,
       "autostart": False, "subfolders": True, "popup": True, "sound": False,
       "theme": "system", "density": "compact", "geom": "", "sched": dict(SCHED), "bridge": True,
       "ytq": "1080p", "cookies": "", "watch_media": False, "clip_mode": "ask"}
JOBS = []
FONT, SC = "TkDefaultFont", 1.0

# Semantic desktop design tokens, shared by all windows.
LIGHT = dict(dark=False, bg="#f4f5f7", panel="#ffffff", fg="#1b1d22", sub="#737782",
             accent="#2f6df0", accent2="#2559cc", border="#e2e4e9", sel="#e8f0ff",
             hdr="#eceef2", hover="#eef1f7", ok="#1f9e66", err="#d93a45", bar="#dfe2e8", warn="#d98a1b")
DARK = dict(dark=True, bg="#0b0b0c", panel="#141416", fg="#e9eaee", sub="#8b8d96",
            accent="#4c8dff", accent2="#3a78e8", border="#232327", sel="#18212f",
            hdr="#0f0f11", hover="#121217", ok="#3ecf8e", err="#ff5a5f", bar="#26262b", warn="#f2a33a")
P = dict(LIGHT)


def S(x):
    return int(x * SC)


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def fmt_eta(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def clean(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "file"


def category(name):
    return EXT2CAT.get(os.path.splitext(name)[1].lstrip(".").lower(), "Other")


def unique(folder, name, taken):
    base, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 1
    while os.path.exists(p) or os.path.exists(p + ".part") or p in taken:
        p = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return p


def mix(a, b, t):
    x = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    y = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(p + (q - p) * t) for p, q in zip(x, y))


def fit(text, font, width):
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "...") > width:
        text = text[:-1]
    return text + "..."


def rrect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def http_get(url, **kw):
    s = requests.Session()
    mode = CFG["proxy_mode"]
    s.trust_env = mode == "system"          # system = Windows proxy settings + env vars
    if mode == "manual" and CFG["proxy"].strip():
        p = CFG["proxy"].strip()
        if "://" not in p:
            p = "http://" + p
        s.proxies = {"http": p, "https": p}
    r = s.get(url, **kw)
    r._sess = s
    return r


def system_proxy():
    try:
        import urllib.request
        p = urllib.request.getproxies()
        return p.get("https") or p.get("http") or p.get("socks") or ""
    except Exception:
        return ""


class Cancel(Exception):
    pass


def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else \
        os.path.dirname(os.path.abspath(__file__))


def find(name):
    """Look for a helper file next to the program, or in the per-user data folder."""
    for d in (str(DATA), app_dir()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def ffmpeg_path():
    return find("ffmpeg.exe" if WIN else "ffmpeg") or shutil.which("ffmpeg")


_YT = [None, False, ""]
_YT_LOCK = threading.Lock()


def ytdlp():
    """yt-dlp is a single zip file next to the program (or a newer one in the user folder),
    so it can be updated from inside the app without rebuilding anything."""
    with _YT_LOCK:
        if _YT[1]:
            return _YT[0]
        _YT[1] = True
        _YT[2] = "the file 'yt-dlp' was not found next to MyDM.exe"
        for p in (str(DATA / "yt-dlp"), os.path.join(app_dir(), "yt-dlp")):
            if os.path.isfile(p):
                sys.path.insert(0, p)
                try:
                    import yt_dlp
                    _YT[0] = yt_dlp
                    return yt_dlp
                except Exception as ex:
                    _YT[2] = f"{type(ex).__name__}: {ex}"
                    sys.path.remove(p)
                    for k in [k for k in sys.modules if k.startswith("yt_dlp")]:
                        del sys.modules[k]
        try:
            import yt_dlp
            _YT[0] = yt_dlp
        except Exception:
            pass
        return _YT[0]


def update_engine():
    """Download the newest yt-dlp into the user folder. Returns (ok, message)."""
    try:
        r = http_get("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp", timeout=60)
        r.raise_for_status()
        data = r.content
        if data[:2] != b"PK" or len(data) < 1_000_000:
            raise IOError("unexpected download")
        DATA.mkdir(exist_ok=True)
        tmp = DATA / "yt-dlp.new"
        tmp.write_bytes(data)
        os.replace(tmp, DATA / "yt-dlp")
        return True, "Updated. Restart MyDM to use the new version."
    except Exception as ex:
        return False, "Update failed: " + str(ex)[:120]


def is_stream_url(u):
    return os.path.splitext(urlparse(u).path)[1].lower() in (".m3u8", ".mpd")


_IES = []


def is_media(url):
    """True when yt-dlp has a dedicated extractor for this link (YouTube, Aparat, ...)."""
    global _IES
    if not ytdlp() or os.path.splitext(urlparse(url).path)[1].lstrip(".").lower() in EXTS:
        return False
    try:
        if not _IES:
            from yt_dlp.extractor import gen_extractor_classes
            _IES = [c for c in gen_extractor_classes() if c.IE_NAME != "generic"]
        return any(c.suitable(url) for c in _IES)
    except Exception:
        return False


def http_proxy():
    """HTTP proxy for ffmpeg (it cannot use SOCKS)."""
    m = CFG["proxy_mode"]
    if m == "direct":
        return ""
    p = CFG["proxy"].strip() if m == "manual" else system_proxy()
    if not p or p.startswith("socks"):
        return ""
    return p if "://" in p else "http://" + p


def ydl_opts(**extra):
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "windowsfilenames": True,
         "socket_timeout": 30, "retries": 5, "fragment_retries": 5}
    ff = ffmpeg_path()
    if ff:
        o["ffmpeg_location"] = ff
    qjs = find("qjs.exe" if WIN else "qjs")
    if qjs:
        o["js_runtimes"] = {"quickjs": {"path": qjs}}
    mode = CFG["proxy_mode"]
    if mode == "direct":
        o["proxy"] = ""
    elif mode == "manual" and CFG["proxy"].strip():
        p = CFG["proxy"].strip()
        o["proxy"] = p if "://" in p else "http://" + p
    if CFG["cookies"]:
        o["cookiesfrombrowser"] = (CFG["cookies"],)
    o.update(extra)
    return o


def vsel(h, ff):
    c = f"[height<={h}]" if h else ""
    if ff:   # separate video + audio streams, merged by ffmpeg (prefers H.264 + AAC = plays everywhere)
        return f"bv*{c}[vcodec^=avc1]+ba[ext=m4a]/bv*{c}+ba/b{c}"
    return f"b{c}"


def default_choice():
    q, ff = CFG["ytq"], bool(ffmpeg_path())
    if q.startswith("Audio"):
        return ("ba/b", True, ff) if ff else ("ba[ext=m4a]/ba/b", True, False)
    return vsel(int(q[:-1]) if q[:-1].isdigit() else 0, ff), False, False


def quality_options(info, ff):
    fm = info.get("formats") or []
    has = lambda f, k: f.get(k) not in (None, "none")
    dur0 = info.get("duration") or 0

    def size(f):
        if not f:
            return 0
        n = f.get("filesize") or f.get("filesize_approx") or 0
        if not n and dur0 and (f.get("tbr") or f.get("vbr") or f.get("abr")):
            n = int((f.get("tbr") or (f.get("vbr") or 0) + (f.get("abr") or 0)) * 125 * dur0)
        return int(n)
    vids = [f for f in fm if has(f, "vcodec") and f.get("height")]
    auds = [f for f in fm if has(f, "acodec") and not has(f, "vcodec")]
    aud = max(auds, key=lambda f: f.get("abr") or 0, default=None)
    opts = []
    for h in sorted({f["height"] for f in vids}, reverse=True)[:10]:
        c = [f for f in vids if f["height"] == h]
        if not ff:
            c = [f for f in c if has(f, "acodec")]
            if not c:
                continue
        pref = [f for f in c if str(f.get("vcodec")).startswith("avc")] or c
        b = max(pref, key=lambda f: f.get("tbr") or 0)
        vc = str(b.get("vcodec"))
        codec = ("H.264" if vc.startswith("avc") else "VP9" if "vp" in vc else
                 "AV1" if "av01" in vc else (b.get("ext") or "").upper())
        sz = size(b) + (0 if has(b, "acodec") else size(aud))
        opts.append(dict(label=f"{h}p", detail=codec, size=sz, fmt=vsel(h, ff),
                         audio=False, mp3=False, h=h, w=b.get("width") or 0,
                         bitrate=(b.get("tbr") or 0) * 125))
    # sizes that are all identical are a sign of bad data from the site: estimate again
    if len(opts) > 1 and len({o["size"] for o in opts}) == 1:
        for o in opts:
            o["size"] = int(o["bitrate"] * dur0) if o["bitrate"] and dur0 else 0
        if len({o["size"] for o in opts}) == 1:
            base = opts[0]["size"] or 0
            top = max(o["h"] * (o["w"] or o["h"] * 16 // 9) for o in opts) or 1
            for o in opts:
                o["size"] = int(base * (o["h"] * (o["w"] or o["h"] * 16 // 9)) / top) if base else 0
    dur = info.get("duration") or 0
    if ff:
        opts.append(dict(label="Audio only", detail="MP3  192 kbps", size=int(dur * 24000),
                         fmt="ba/b", audio=True, mp3=True, h=0))
    if auds or not vids:
        opts.append(dict(label="Audio only", detail="M4A  original", size=size(aud),
                         fmt="ba[ext=m4a]/ba/b", audio=True, mp3=False, h=0))
    return opts


def pick_default(opts):
    q = CFG["ytq"]
    if q.startswith("Audio"):
        return next((i for i, o in enumerate(opts) if o["audio"]), 0)
    if q == "Best" or not q[:-1].isdigit():
        return 0
    vid = [i for i, o in enumerate(opts) if not o["audio"]]
    return next((i for i in vid if opts[i]["h"] <= int(q[:-1])), vid[-1] if vid else 0)


def hls_choices(job):
    """Quality list of an HLS master playlist (empty = nothing to choose, just take the best)."""
    try:
        text = http_get(job.url, headers=job.hdrs(), timeout=20).text
        if "#EXT-X-STREAM-INF" not in text:
            return []
        lines = text.splitlines()
        opts = []
        for ln, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF:"):
                continue
            a = line.split(":", 1)[1]
            link = next((x.strip() for x in lines[ln + 1:] if x.strip() and not x.startswith("#")), "")
            bw = int((re.search(r"(?<![A-Z-])BANDWIDTH=(\d+)", a) or [0, 0])[1])
            avg = int((re.search(r"AVERAGE-BANDWIDTH=(\d+)", a) or [0, 0])[1])
            r = re.search(r"RESOLUTION=(\d+)x(\d+)", a)
            hh = int(r.group(2)) if r else 0
            ww = int(r.group(1)) if r else 0
            opts.append(dict(label=f"{hh}p" if hh else f"{(avg or bw) // 1000} kbps",
                             detail=(f"{ww}x{hh}   " if r else "") + f"{(avg or bw) / 1e6:.1f} Mbps",
                             size=0, fmt=f"p:{len(opts)}", audio=False, mp3=False,
                             h=hh or (avg or bw) // 1000, bw=bw, avg=avg, w=ww, link=link))
        if len(opts) < 2:
            return []

        def dur_of(o):                  # real length of this variant's own playlist
            try:
                t = http_get(urljoin(job.url, o["link"]), headers=job.hdrs(), timeout=15).text
                return sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", t))
            except Exception:
                return 0
        with ThreadPoolExecutor(max_workers=4) as ex:
            durs = list(ex.map(dur_of, opts))
        fallback = max(durs) if any(durs) else job.stream_info()
        for o, d in zip(opts, durs):
            o["size"] = int((o["avg"] or o["bw"]) * (d or fallback) / 8)
        if len({o["avg"] or o["bw"] for o in opts}) == 1:   # site reports one bitrate for everything
            top = max(o["h"] * (o["w"] or 1) for o in opts) or 1
            for o in opts:
                o["size"] = int(o["size"] * (o["h"] * (o["w"] or 1)) / top)
        for o in opts:
            o.pop("link", None)
        opts.sort(key=lambda o: (o["h"], o["bw"]), reverse=True)
        return opts
    except Exception:
        return []


def stem(name):
    base, ext = os.path.splitext(name)
    return base if ext.lower() in (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".ts") else name


# ============================================================ browser bridge
def ext_dir():
    return os.path.join(app_dir(), "extension")


def open_chrome_ext():
    open_path(ext_dir())
    try:
        if WIN:
            subprocess.Popen(["cmd", "/c", "start", "", "chrome", "chrome://extensions"],
                             creationflags=0x08000000)
        else:
            subprocess.Popen(["xdg-open", "chrome://extensions"])
    except Exception:
        pass


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False       # on Windows this stops a second program from sharing the port
    daemon_threads = True


def start_bridge(inbox):
    """Tiny local web server (127.0.0.1 only) that the browser extension talks to."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def host_ok(self):
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def origin_ok(self):
            return (CFG["bridge"] and self.host_ok()
                    and self.headers.get("Origin") == "chrome-extension://" + EXT_ID)

        def reply(self, code, obj=None):
            body = json.dumps(obj).encode() if obj is not None else b""
            self.send_response(code)
            if self.origin_ok():
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(204 if self.origin_ok() else 403)

        def do_GET(self):
            if self.path == "/ping" and self.host_ok():
                self.reply(200, {"app": "MyDM", "version": VERSION, "engine": bool(ytdlp())})
            else:
                self.reply(404)

        def do_POST(self):
            if self.path not in ("/add", "/supports"):
                return self.reply(404)
            if not self.origin_ok():
                return self.reply(403)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 200000:
                    return self.reply(413)
                d = json.loads(self.rfile.read(n))
                m = {k: re.sub(r"[\r\n]+", " ", str(d.get(k) or ""))[:4000]
                     for k in ("url", "referer", "cookie", "ua", "name", "action", "kind")}
                ls = d.get("urls") if isinstance(d.get("urls"), list) else []
                m["urls"] = [re.sub(r"\s+", "", str(x))[:2000] for x in ls[:300]
                             if str(x).startswith(("http://", "https://"))]
                if not m["url"] and m["urls"]:
                    m["url"] = m["urls"][0]
                if not m["url"].startswith(("http://", "https://")):
                    return self.reply(400)
            except Exception:
                return self.reply(400)
            if self.path == "/supports":
                return self.reply(200, {"site": is_media(m["url"]), "engine": bool(ytdlp())})
            inbox.put(m)
            self.reply(200, {"ok": True})

    for port in PORTS:
        try:
            srv = _Server(("127.0.0.1", port), H)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port
    return None, 0


def open_path(p, select=False):
    try:
        if WIN:
            if select and os.path.exists(p):
                subprocess.Popen(f'explorer /select,"{os.path.normpath(p)}"')
            else:
                os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p] if select else ["open", p])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(p) if select else p])
    except Exception:
        pass


def system_dark():
    try:
        if WIN:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True)
            return "Dark" in r.stdout
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                           capture_output=True, text=True)
        return "dark" in r.stdout
    except Exception:
        return False


def titlebar(win, dark):
    if not WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        v = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4) == 0:
                break
    except Exception:
        pass


def set_startup(on):
    if not (WIN and getattr(sys, "frozen", False)):
        return
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                           winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(k, "MyDM", 0, winreg.REG_SZ, f'"{sys.executable}" --min')
        else:
            winreg.DeleteValue(k, "MyDM")
    except Exception:
        pass


def power_cmd(action):
    if WIN:
        return {"Lock screen": ["rundll32.exe", "user32.dll,LockWorkStation"],
                "Log off": ["shutdown", "/l"],
                "Sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                "Hibernate": ["shutdown", "/h"],
                "Restart": ["shutdown", "/r", "/t", "0"],
                "Shut down": ["shutdown", "/s", "/t", "0"],
                "Shut down (force close apps)": ["shutdown", "/s", "/f", "/t", "0"]}.get(action)
    return {"Lock screen": ["loginctl", "lock-session"], "Sleep": ["systemctl", "suspend"],
            "Hibernate": ["systemctl", "hibernate"], "Restart": ["systemctl", "reboot"],
            "Shut down": ["systemctl", "poweroff"],
            "Shut down (force close apps)": ["systemctl", "poweroff", "-f"]}.get(action)


def init_fonts(root):
    global FONT
    fams = set(tkfont.families(root))
    FONT = next((f for f in ("Segoe UI", "SF Pro Text", "Inter", "Helvetica Neue", "Ubuntu",
                             "DejaVu Sans") if f in fams),
                tkfont.nametofont("TkDefaultFont").actual("family"))
    for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(n).configure(family=FONT, size=10)


def apply_theme(root):
    dark = system_dark() if CFG["theme"] == "system" else CFG["theme"] == "dark"
    P.clear()
    P.update(DARK if dark else LIGHT)
    st = ttk.Style(root)
    st.theme_use("clam")
    flat = dict(lightcolor=P["panel"], darkcolor=P["panel"], bordercolor=P["border"])
    st.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["panel"],
                 troughcolor=P["bar"], focuscolor=P["bg"], font=(FONT, 10))
    st.configure("TFrame", background=P["bg"])
    st.configure("TLabel", background=P["bg"], foreground=P["fg"])
    st.configure("Sub.TLabel", foreground=P["sub"])
    st.configure("TMenubutton", background=P["panel"], foreground=P["fg"],
                 padding=(S(11), S(7)), relief="flat", borderwidth=1, **flat)
    st.configure("TButton", background=P["panel"], foreground=P["fg"], padding=(S(11), S(7)),
                 relief="flat", borderwidth=1, width=0, **flat)
    st.map("TButton", background=[("active", P["sel"]), ("disabled", P["bg"])],
           foreground=[("disabled", P["sub"])])
    acc = dict(lightcolor=P["accent"], darkcolor=P["accent"], bordercolor=P["accent"])
    st.configure("Accent.TButton", background=P["accent"], foreground="#ffffff", **acc)
    st.map("Accent.TButton", background=[("active", P["accent2"])],
           foreground=[("disabled", "#ffffff")])
    for w in ("TEntry", "TSpinbox"):
        st.configure(w, fieldbackground=P["panel"], foreground=P["fg"], insertcolor=P["fg"],
                     arrowcolor=P["sub"], padding=S(7), **flat)
    st.configure("TCombobox", fieldbackground=P["panel"], background=P["panel"],
                 foreground=P["fg"], arrowcolor=P["sub"], padding=S(5), **flat)
    st.map("TCombobox", fieldbackground=[("readonly", P["panel"])],
           foreground=[("readonly", P["fg"])], selectbackground=[("readonly", P["panel"])],
           selectforeground=[("readonly", P["fg"])])
    root.option_add("*TCombobox*Listbox.background", P["panel"])
    root.option_add("*TCombobox*Listbox.foreground", P["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    st.configure("TCheckbutton", background=P["bg"], foreground=P["fg"])
    st.map("TCheckbutton", background=[("active", P["bg"])])
    st.configure("Treeview", background=P["panel"], fieldbackground=P["panel"],
                 foreground=P["fg"], rowheight=S(32), borderwidth=0, **flat)
    st.map("Treeview", background=[("selected", P["sel"])], foreground=[("selected", P["fg"])])
    st.configure("Treeview.Heading", background=P["hdr"], foreground=P["sub"], relief="flat",
                 padding=(S(8), S(7)), font=(FONT, 9, "bold"), bordercolor=P["hdr"],
                 lightcolor=P["hdr"], darkcolor=P["hdr"])
    st.configure("TScrollbar", background=P["hdr"], troughcolor=P["bg"], arrowcolor=P["sub"],
                 bordercolor=P["bg"], lightcolor=P["hdr"], darkcolor=P["hdr"], gripcount=0)
    st.map("TScrollbar", background=[("active", P["border"])])
    st.configure("Horizontal.TProgressbar", background=P["accent"], troughcolor=P["bar"],
                 thickness=S(10), lightcolor=P["accent"], darkcolor=P["accent"],
                 bordercolor=P["bar"])
    st.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    st.configure("TNotebook.Tab", background=P["hdr"], foreground=P["sub"], borderwidth=0,
                 padding=(S(16), S(8)), font=(FONT, 10))
    st.map("TNotebook.Tab", background=[("selected", P["panel"])],
           foreground=[("selected", P["accent"])])
    root.configure(bg=P["bg"])


def make_icon():
    img = tk.PhotoImage(width=64, height=64)
    img.put(LIGHT["accent"], to=(0, 0, 64, 64))
    img.put("#ffffff", to=(26, 12, 38, 34))
    for i in range(14):
        img.put("#ffffff", to=(18 + i, 32 + i, 46 - i, 33 + i))
    img.put("#ffffff", to=(16, 50, 48, 54))
    return img


# ===================================================================== engine
class Limiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.nxt = 0.0

    def wait(self, n, ev):
        rate = CFG["limit_kb"] * 1024
        if rate <= 0:
            return
        with self.lock:
            now = time.monotonic()
            self.nxt = max(self.nxt, now) + n / rate
            delay = self.nxt - now
        if delay > 0:
            ev.wait(delay)


LIM = Limiter()


class Job:
    KEYS = ("url", "folder", "name", "path", "total", "ranged", "segs", "status", "referer",
            "kind", "fmt", "audio", "mp3", "added")

    def __init__(self, url, folder, kind="file"):
        self.url, self.folder = url, folder
        self.referer, self.cookie, self.ua = "", "", ""
        self.kind, self.fmt, self.audio, self.mp3, self.note = kind, "", False, False, ""
        self.added = time.time()
        self.name = (urlparse(url).netloc.replace("www.", "") + " video" if kind != "file" else
                     clean(unquote(os.path.basename(urlparse(url).path))))
        self.path, self.total, self.ranged, self.segs = "", 0, False, []
        self.status, self.err = "Queued", None
        self.prev = self.status
        self.stop = threading.Event()
        self.id = os.urandom(4).hex()
        self.speed, self.hist = 0.0, []
        self.last = (time.monotonic(), 0)

    @property
    def done(self):
        return sum(max(0, min(p, e + 1) - s) for s, e, p in self.segs)

    @property
    def cat(self):
        if self.kind != "file":
            return "Music" if self.audio else "Video"
        return category(self.name)

    @property
    def dir(self):
        return os.path.dirname(self.path) if self.path else self.folder

    def to_dict(self):
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_dict(cls, d):
        j = cls(d["url"], d.get("folder") or CFG["folder"])
        for k in cls.KEYS[2:]:
            if k in d:
                setattr(j, k, d[k])
        if j.status != "Done":
            j.status = "Paused"
        j.prev = j.status
        return j

    def hdrs(self):
        h = dict(UA)
        if self.ua:
            h["User-Agent"] = self.ua
        if self.referer:
            h["Referer"] = self.referer
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def probe(self):
        r = http_get(self.url, headers={**self.hdrs(), "Range": "bytes=0-0"}, stream=True, timeout=30)
        try:
            r.raise_for_status()
            cr = r.headers.get("Content-Range", "")
            if r.status_code == 206 and cr.split("/")[-1].isdigit():
                total, ranged = int(cr.split("/")[-1]), True
            else:
                total, ranged = int(r.headers.get("Content-Length") or 0), False
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)',
                          r.headers.get("Content-Disposition", ""), re.I)
            ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
            return total, ranged, (clean(unquote(m.group(1))) if m else None), ctype
        finally:
            r.close()

    def run(self):
        try:
            self.err = None
            if self.kind != "file":
                (self.run_media if self.kind == "media" else self.run_stream)()
                self.status = "Done"
                return
            total, ranged, name, ctype = self.probe()
            part = self.path + ".part"
            resume = bool(self.segs and self.ranged and ranged and total == self.total
                          and self.path and os.path.exists(part))
            if not resume:
                if self.path and os.path.exists(part):
                    os.remove(part)
                self.name = name or self.name
                if not os.path.splitext(self.name)[1] and ctype:
                    self.name += mimetypes.guess_extension(ctype) or ""
                folder = os.path.join(self.folder, self.cat) if CFG["subfolders"] else self.folder
                os.makedirs(folder, exist_ok=True)
                taken = {j.path for j in JOBS if j is not self}
                self.path = unique(folder, self.name, taken)
                part = self.path + ".part"
                self.total, self.ranged = total, ranged
                if ranged and total:
                    n = max(1, min(int(CFG["segments"]), total // 262144))
                    size = total // n
                    self.segs = [[i * size, total - 1 if i == n - 1 else (i + 1) * size - 1,
                                  i * size] for i in range(n)]
                else:
                    self.segs = [[0, total - 1 if total else 2 ** 62, 0]]
                with open(part, "wb") as f:
                    if ranged and total:
                        f.truncate(total)
            self.status = "Downloading"
            if self.ranged and self.total:
                ts = [threading.Thread(target=self.seg, args=(s,), daemon=True)
                      for s in self.segs if s[2] <= s[1]]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
            else:
                self.single()
            if self.err:
                self.status = "Error: " + self.err[:60]
            elif self.stop.is_set():
                self.status = "Paused"
            elif self.ranged and self.total and any(s[2] <= s[1] for s in self.segs):
                self.status = "Error: incomplete"
            else:
                os.replace(self.path + ".part", self.path)
                self.status = "Done"
        except Exception as ex:
            self.status = ("Paused" if self.kind != "file" and self.stop.is_set()
                           else "Error: " + re.sub(r"\x1b\[[0-9;]*m", "", str(ex))[:160])

    def seg(self, s):
        tries = 0
        while not self.stop.is_set() and s[2] <= s[1]:
            before = s[2]
            try:
                h = {**self.hdrs(), "Range": f"bytes={s[2]}-{s[1]}"}
                with http_get(self.url, headers=h, stream=True, timeout=30) as r:
                    if r.status_code != 206:
                        raise IOError(f"HTTP {r.status_code}")
                    with open(self.path + ".part", "r+b") as f:
                        f.seek(s[2])
                        for c in r.iter_content(65536):
                            if self.stop.is_set():
                                return
                            c = c[: s[1] - s[2] + 1]
                            f.write(c)
                            f.flush()
                            s[2] += len(c)
                            LIM.wait(len(c), self.stop)
                            if s[2] > s[1]:
                                break
                if s[2] == before and s[2] <= s[1]:
                    raise IOError("no data received")
                tries = 0
            except Exception as ex:
                tries += 1
                if tries > 5:
                    self.err = str(ex)
                    self.stop.set()
                    return
                self.stop.wait(2 * tries)

    def single(self):
        s = self.segs[0]
        s[2] = 0
        with http_get(self.url, headers=self.hdrs(), stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(self.path + ".part", "wb") as f:
                for c in r.iter_content(65536):
                    if self.stop.is_set():
                        return
                    f.write(c)
                    s[2] += len(c)
                    LIM.wait(len(c), self.stop)
        if self.total and s[2] < self.total:
            raise IOError("connection closed early")

    # ---- video-site downloads through yt-dlp ----
    def run_media(self):
        y = ytdlp()
        if not y:
            raise RuntimeError("yt-dlp is not included in this build")
        self.note, self.base, self.expect = "", 0, 0
        folder = os.path.join(self.folder, self.cat) if CFG["subfolders"] else self.folder
        os.makedirs(folder, exist_ok=True)
        o = ydl_opts(format=self.fmt, progress_hooks=[self.hook], postprocessor_hooks=[self.phook],
                     outtmpl=os.path.join(folder, "%(title).120B [%(id)s].%(ext)s"),
                     noprogress=True)
        if self.mp3:
            o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                    "preferredquality": "192"}]
        with y.YoutubeDL(o) as ydl:
            info = ydl.extract_info(self.url, download=True)
            rd = (info or {}).get("requested_downloads") or []
            path = rd[0].get("filepath") if rd else ""
            if not path or not os.path.exists(path):
                path = ydl.prepare_filename(info)
        if not os.path.exists(path):
            raise IOError("downloaded file not found")
        self.path, self.name, self.note = path, os.path.basename(path), ""
        self.total = os.path.getsize(path)
        self.segs = [[0, self.total - 1, self.total]]

    def hook(self, d):
        if self.stop.is_set():
            raise Cancel()
        info = d.get("info_dict") or {}
        if not self.expect:
            fs = info.get("requested_formats") or [info]
            self.expect = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in fs)
        if info.get("title") and self.name.endswith(" video"):
            self.name = clean(info["title"]) + "." + ("mp3" if self.mp3 else info.get("ext") or "mp4")
        if d.get("status") == "downloading":
            self.status = "Downloading"
            cur = d.get("downloaded_bytes") or 0
            ctot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            self.total = int(max(self.expect, self.base + ctot))
            self.segs = [[0, max(self.total, 1) - 1, int(min(self.base + cur, max(self.total, 1)))]]
        elif d.get("status") == "finished":
            self.base += d.get("total_bytes") or d.get("downloaded_bytes") or 0

    def phook(self, d):
        if d.get("status") == "started":
            self.note = {"Merger": "Merging video and audio...",
                         "ExtractAudio": "Converting to MP3..."}.get(d.get("postprocessor"),
                                                                     "Finishing...")
        elif d.get("status") == "finished":
            self.note = ""

    # ---- HLS (.m3u8) and DASH (.mpd) streams through ffmpeg ----
    def stream_info(self):
        dur = 0.0
        try:
            text = http_get(self.url, headers=self.hdrs(), timeout=20).text
            var = re.findall(r"BANDWIDTH=(\d+)[^\n]*\n([^\n#][^\n]*)", text)
            if var:                                    # master playlist: look at the best variant
                link = max((int(b), l.strip()) for b, l in var)[1]
                text = http_get(urljoin(self.url, link), headers=self.hdrs(), timeout=20).text
            dur = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", text))
            if not dur:
                m = re.search(r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', text)
                if m:
                    dur = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
        except Exception:
            pass
        return dur

    def killer(self, p):
        while p.poll() is None:
            if self.stop.wait(0.3):
                try:
                    p.kill()
                except Exception:
                    pass
                return

    def run_stream(self):
        ff = ffmpeg_path()
        if not ff:
            raise RuntimeError("ffmpeg is missing")
        dur = self.stream_info()
        folder = os.path.join(self.folder, "Video") if CFG["subfolders"] else self.folder
        os.makedirs(folder, exist_ok=True)
        name = clean(stem(self.name)) if not self.name.endswith(" video") else "video"
        self.path = unique(folder, name + ".mp4", {j.path for j in JOBS if j is not self})
        tmp = self.path + ".part"
        h = self.hdrs()
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-progress", "pipe:1",
               "-nostats", "-user_agent", h.pop("User-Agent"), "-headers",
               "".join(f"{k}: {v}\r\n" for k, v in h.items())]
        if http_proxy():
            cmd += ["-http_proxy", http_proxy()]
        cmd += ["-i", self.url]
        if self.fmt.startswith("p:"):                 # a quality picked from the master playlist
            cmd += ["-map", "0:" + self.fmt]
        cmd += ["-sn", "-dn", "-c", "copy", "-f", "mp4", tmp]
        self.status, self.segs, self.total = "Downloading", [[0, 2 ** 62, 0]], 0
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace",
                             creationflags=0x08000000 if WIN else 0)
        threading.Thread(target=self.killer, args=(p,), daemon=True).start()
        size, frac, errs = 0, 0.0, []
        for line in p.stdout:
            line = line.strip()
            k, eq, v = line.partition("=")
            if not eq or " " in k:
                if line:
                    errs.append(line)
                continue
            if k == "total_size" and v.isdigit():
                size = int(v)
            elif k in ("out_time_us", "out_time_ms") and v.lstrip("-").isdigit() and dur:
                frac = min(max(int(v) / 1e6 / dur, 0.0), 1.0)
            elif k == "progress":
                if frac > 0.003 and size:
                    self.total = int(size / frac)
                    self.segs = [[0, self.total - 1, size]]
                else:
                    self.segs = [[0, 2 ** 62, size]]
        rc = p.wait()
        if self.stop.is_set() or rc != 0 or not os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
            if self.stop.is_set():
                raise Cancel()
            raise RuntimeError(errs[-1][:150] if errs else "ffmpeg failed")
        os.replace(tmp, self.path)
        self.name, self.total = os.path.basename(self.path), os.path.getsize(self.path)
        self.segs = [[0, self.total - 1, self.total]]


# ================================================================== widgets
def glyph(c, kind, cx, cy, s, col, w=None):
    """Small line icons drawn straight on a canvas. (cx, cy) = centre, s = size in pixels."""
    h = s / 2
    w = w or max(1, round(s / 11))
    L = lambda *p: c.create_line(*p, fill=col, width=w, capstyle="round", joinstyle="round")
    R = lambda *p: c.create_rectangle(*p, outline=col, width=w)
    O = lambda *p: c.create_oval(*p, outline=col, width=w)
    PG = lambda *p: c.create_polygon(*p, outline=col, fill="", width=w, joinstyle="round")
    o = lambda r: (cx - r * h, cy - r * h, cx + r * h, cy + r * h)
    if kind == "plus":
        L(cx - .6 * h, cy, cx + .6 * h, cy)
        L(cx, cy - .6 * h, cx, cy + .6 * h)
    elif kind == "play":
        PG(cx - .45 * h, cy - .65 * h, cx + .7 * h, cy, cx - .45 * h, cy + .65 * h)
    elif kind == "stop":
        R(cx - .55 * h, cy - .55 * h, cx + .55 * h, cy + .55 * h)
    elif kind == "stopall":
        O(*o(.8))
        L(cx - .3 * h, cy - .3 * h, cx + .3 * h, cy + .3 * h)
        L(cx - .3 * h, cy + .3 * h, cx + .3 * h, cy - .3 * h)
    elif kind == "trash":
        L(cx - .75 * h, cy - .45 * h, cx + .75 * h, cy - .45 * h)
        L(cx - .25 * h, cy - .45 * h, cx - .25 * h, cy - .75 * h, cx + .25 * h, cy - .75 * h, cx + .25 * h, cy - .45 * h)
        PG(cx - .55 * h, cy - .45 * h, cx - .42 * h, cy + .8 * h, cx + .42 * h, cy + .8 * h, cx + .55 * h, cy - .45 * h)
    elif kind == "eraser":
        PG(cx - .8 * h, cy + .05 * h, cx + .05 * h, cy - .8 * h, cx + .8 * h, cy - .05 * h, cx - .05 * h, cy + .8 * h)
        L(cx - .35 * h, cy - .4 * h, cx + .4 * h, cy + .35 * h)
    elif kind == "gear":
        O(*o(.3))
        O(*o(.62))
        for i in range(8):
            a = i * math.pi / 4
            L(cx + .62 * h * math.cos(a), cy + .62 * h * math.sin(a),
              cx + .92 * h * math.cos(a), cy + .92 * h * math.sin(a))
    elif kind == "clock":
        O(*o(.85))
        L(cx, cy - .5 * h, cx, cy, cx + .4 * h, cy + .25 * h)
    elif kind in ("startq", "stopq"):
        for dy in (-.6, -.05, .5):
            L(cx - .85 * h, cy + dy * h, cx + .1 * h, cy + dy * h)
        if kind == "startq":
            PG(cx + .35 * h, cy - .35 * h, cx + .9 * h, cy + .05 * h, cx + .35 * h, cy + .45 * h)
        else:
            L(cx + .4 * h, cy - .3 * h, cx + .85 * h, cy + .2 * h)
            L(cx + .4 * h, cy + .2 * h, cx + .85 * h, cy - .3 * h)
    elif kind == "layers":
        PG(cx, cy - .8 * h, cx + .85 * h, cy - .4 * h, cx, cy, cx - .85 * h, cy - .4 * h)
        L(cx - .85 * h, cy + .05 * h, cx, cy + .45 * h, cx + .85 * h, cy + .05 * h)
        L(cx - .85 * h, cy + .5 * h, cx, cy + .9 * h, cx + .85 * h, cy + .5 * h)
    elif kind == "circle":
        O(*o(.75))
    elif kind == "check":
        O(*o(.78))
        L(cx - .35 * h, cy, cx - .08 * h, cy + .3 * h, cx + .4 * h, cy - .3 * h)
    elif kind == "video":
        R(cx - .8 * h, cy - .6 * h, cx + .8 * h, cy + .6 * h)
        L(cx - .4 * h, cy - .6 * h, cx - .4 * h, cy + .6 * h)
        L(cx + .4 * h, cy - .6 * h, cx + .4 * h, cy + .6 * h)
    elif kind == "music":
        c.create_oval(cx - .65 * h, cy + .15 * h, cx - .05 * h, cy + .7 * h, fill=col, outline=col)
        L(cx - .05 * h, cy + .4 * h, cx - .05 * h, cy - .7 * h, cx + .6 * h, cy - .45 * h)
    elif kind in ("doc", "zip", "file"):
        PG(cx - .55 * h, cy - .8 * h, cx + .2 * h, cy - .8 * h, cx + .55 * h, cy - .45 * h,
           cx + .55 * h, cy + .8 * h, cx - .55 * h, cy + .8 * h)
        if kind == "doc":
            L(cx - .25 * h, cy, cx + .25 * h, cy)
            L(cx - .25 * h, cy + .35 * h, cx + .25 * h, cy + .35 * h)
        elif kind == "zip":
            L(cx, cy - .6 * h, cx, cy - .05 * h)
            R(cx - .15 * h, cy, cx + .15 * h, cy + .4 * h)
    elif kind == "app":
        R(cx - .8 * h, cy - .65 * h, cx + .8 * h, cy + .65 * h)
        L(cx - .8 * h, cy - .25 * h, cx + .8 * h, cy - .25 * h)
    elif kind == "image":
        R(cx - .8 * h, cy - .65 * h, cx + .8 * h, cy + .65 * h)
        L(cx - .8 * h, cy + .45 * h, cx - .25 * h, cy - .05 * h, cx + .1 * h, cy + .3 * h,
          cx + .4 * h, cy + .05 * h, cx + .8 * h, cy + .45 * h)
    elif kind == "sun":
        O(*o(.38))
        for i in range(8):
            a = i * math.pi / 4
            L(cx + .62 * h * math.cos(a), cy + .62 * h * math.sin(a),
              cx + .92 * h * math.cos(a), cy + .92 * h * math.sin(a))
    elif kind == "moon":
        c.create_arc(*o(.8), start=50, extent=270, style="arc", outline=col, width=w)
        L(cx + .5 * h, cy - .62 * h, cx + .05 * h, cy - .05 * h)
    elif kind == "search":
        O(cx - .75 * h, cy - .75 * h, cx + .15 * h, cy + .15 * h)
        L(cx + .1 * h, cy + .1 * h, cx + .75 * h, cy + .75 * h)


class MenuBar(tk.Frame):
    def __init__(self, parent, items, on_theme):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.labels = []
        for title, menu in items:
            l = tk.Label(self, text=title, padx=S(12), pady=S(9), font=(FONT, 10), cursor="hand2", bd=0)
            l.pack(side="left")
            l.bind("<Enter>", lambda e, l=l: l.configure(bg=P["hover"]))
            l.bind("<Leave>", lambda e, l=l: l.configure(bg=P["bg"]))
            l.bind("<Button-1>", lambda e, l=l, m=menu: self.pop(l, m))
            self.labels.append(l)
        self.theme = tk.Canvas(self, width=S(46), height=S(34), highlightthickness=0, bd=0, cursor="hand2")
        self.theme.pack(side="right")
        self.theme.bind("<Button-1>", lambda e: on_theme())

    def pop(self, l, m):
        try:
            m.tk_popup(l.winfo_rootx(), l.winfo_rooty() + l.winfo_height())
        finally:
            m.grab_release()

    def restyle(self):
        self.configure(bg=P["bg"])
        for l in self.labels:
            l.configure(bg=P["bg"], fg=P["fg"])
        t = self.theme
        t.delete("all")
        t.configure(bg=P["bg"])
        glyph(t, "sun" if P["dark"] else "moon", S(23), S(17), S(17), P["sub"], 2)


class Toolbar(tk.Canvas):
    BTNS = [("add", "plus", "Add URL"), None,
            ("resume", "play", "Resume"), ("stop", "stop", "Stop"), ("stopall", "stopall", "Stop All"), None,
            ("delete", "trash", "Delete"), ("clear", "eraser", "Clear Done"), None,
            ("options", "gear", "Options"), ("sched", "clock", "Scheduler"),
            ("startq", "startq", "Start Queue"), ("stopq", "stopq", "Stop Queue")]

    def __init__(self, parent, cmds):
        super().__init__(parent, height=S(80), highlightthickness=0, bd=0)
        self.cmds, self.en, self.hover, self.hits = cmds, {}, None, []
        self.f = tkfont.Font(family=FONT, size=9)
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Motion>", self.motion)
        self.bind("<Leave>", lambda e: self.set_hover(None))
        self.bind("<Button-1>", self.click)

    def enable(self, d):
        if d != self.en:
            self.en = d
            self.redraw()

    def at(self, e):
        return next((k for x0, x1, k in self.hits if x0 <= e.x < x1), None)

    def set_hover(self, k):
        if k != self.hover:
            self.hover = k
            self.configure(cursor="hand2" if k and self.en.get(k, True) else "")
            self.redraw()

    def motion(self, e):
        self.set_hover(self.at(e))

    def click(self, e):
        k = self.at(e)
        if k and self.en.get(k, True):
            self.cmds[k]()

    def redraw(self):
        self.delete("all")
        self.configure(bg=P["bg"])
        self.hits = []
        x, bw = S(14), S(74)
        for b in self.BTNS:
            if b is None:
                self.create_line(x + S(5), S(20), x + S(5), S(62), fill=P["border"])
                x += S(10)
                continue
            key, ic, label = b
            on = self.en.get(key, True)
            col = P["accent"] if key == "add" else P["err"] if key in ("stop", "stopall") else P["fg"]
            if not on:
                col = mix(P["sub"], P["bg"], .4)
            mid = x + bw // 2
            if self.hover == key and on:
                rrect(self, x, S(6), x + bw, S(74), S(8), fill=P["hover"], outline="")
            if key == "add":
                rrect(self, mid - S(19), S(9), mid + S(19), S(47), S(8), fill=mix(P["accent"], P["bg"], .82), outline="")
            glyph(self, ic, mid, S(28), S(20), col, 2)
            self.create_text(mid, S(60), text=label, font=self.f, fill=col if on else mix(P["sub"], P["bg"], .4))
            self.hits.append((x, x + bw, key))
            x += bw


class SearchBox(tk.Frame):
    HINT = "Search downloads"

    def __init__(self, parent, on_change):
        super().__init__(parent, bd=0, highlightthickness=1)
        self.on_change, self.empty = on_change, True
        self.icon = tk.Canvas(self, width=S(32), height=S(36), highlightthickness=0, bd=0)
        self.icon.pack(side="left")
        self.e = tk.Entry(self, relief="flat", bd=0, highlightthickness=0, font=(FONT, 10), width=26)
        self.e.pack(side="left", fill="both", expand=True, padx=(0, S(10)), pady=S(8))
        self.e.bind("<FocusIn>", self._in)
        self.e.bind("<FocusOut>", self._out)
        self.e.bind("<KeyRelease>", lambda e: self.on_change())
        self.e.bind("<Escape>", lambda e: (self.clear(), self.on_change()))
        self.e.insert(0, self.HINT)

    def _in(self, _=None):
        if self.empty:
            self.e.delete(0, "end")
            self.empty = False
        self.restyle()

    def _out(self, _=None):
        if not self.e.get():
            self.empty = True
            self.e.insert(0, self.HINT)
        self.restyle()

    def value(self):
        return "" if self.empty else self.e.get().strip()

    def clear(self):
        self.e.delete(0, "end")
        self.empty = False
        self._out()

    def restyle(self):
        self.configure(bg=P["panel"], highlightbackground=P["border"], highlightcolor=P["accent"])
        self.icon.configure(bg=P["panel"])
        self.icon.delete("all")
        glyph(self.icon, "search", S(17), S(18), S(15), P["sub"], 2)
        self.e.configure(bg=P["panel"], fg=P["sub"] if self.empty else P["fg"], insertbackground=P["fg"])


CAT_GLYPH = {"Video": "video", "Music": "music", "Documents": "doc", "Compressed": "zip",
             "Programs": "app", "Images": "image", "Other": "file"}
CAT_NAME = {"Documents": "Document", "Programs": "Program"}


class Side(tk.Canvas):
    def __init__(self, parent, on_pick):
        super().__init__(parent, width=S(214), highlightthickness=0, bd=0)
        self.on_pick, self.cur, self.counts, self.rows = on_pick, "all", {}, []
        self.f = tkfont.Font(family=FONT, size=10)
        self.fh = tkfont.Font(family=FONT, size=8, weight="bold")
        self.bind("<Button-1>", self.click)
        self.bind("<Configure>", lambda e: self.redraw())

    def items(self):
        c = self.counts
        rows = [("h", "CATEGORIES", None, 0), ("all", "All Downloads", "layers", 0)]
        for cat in CAT_LIST:
            if c.get("c:" + cat, 0) or self.cur == "c:" + cat:
                rows.append(("c:" + cat, CAT_NAME.get(cat, cat), CAT_GLYPH[cat], 1))
        return rows + [("unfinished", "Unfinished", "circle", 0), ("completed", "Finished", "check", 0),
                       ("h", "QUEUES", None, 0), ("queue", "Main queue", "clock", 0)]

    def set_counts(self, counts):
        if counts != self.counts:
            self.counts = counts
            self.redraw()

    def click(self, e):
        for y0, y1, key in self.rows:
            if y0 <= e.y < y1:
                self.cur = key
                self.on_pick(key)
                self.redraw()
                return

    def redraw(self):
        self.delete("all")
        self.configure(bg=P["bg"])
        W, y = self.winfo_width(), S(6)
        self.rows = []
        for key, label, ic, lvl in self.items():
            if key == "h":
                y += S(10)
                self.create_text(S(18), y + S(8), anchor="w", text=label, fill=P["sub"], font=self.fh)
                y += S(24)
                continue
            h = S(36)
            on = key == self.cur
            if on:
                rrect(self, S(4), y, W - S(4), y + h - S(2), S(6), fill=P["sel"], outline="")
            col = P["accent"] if on else P["sub"] if lvl else P["fg"]
            cy = y + (h - S(2)) // 2
            glyph(self, ic, S(24) + lvl * S(14), cy, S(15), col, 1 if lvl else 2)
            self.create_text(S(44) + lvl * S(14), cy, anchor="w", text=label, font=self.f,
                             fill=P["accent"] if on else P["fg"])
            self.create_text(W - S(16), cy, anchor="e", text=str(self.counts.get(key, 0)),
                             fill=P["sub"], font=self.f)
            self.rows.append((y, y + h, key))
            y += h


class JobList(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, highlightthickness=0, bd=0, takefocus=1)
        self.app, self.jobs, self.sel, self.anchor = app, [], set(), None
        self.off, self.hover, self.drop, self.sb = 0, None, False, None
        self.fn = tkfont.Font(family=FONT, size=10)
        self.fs = tkfont.Font(family=FONT, size=9)
        self.fh = tkfont.Font(family=FONT, size=8, weight="bold")
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self.click)
        self.bind("<Double-1>", self.double)
        for b in ("<Button-3>", "<Button-2>"):
            self.bind(b, self.rclick)
        self.bind("<Motion>", self.motion)
        self.bind("<Leave>", lambda e: self.set_hover(None))
        self.bind("<Delete>", lambda e: app.remove())
        self.bind("<Control-a>", lambda e: self.select_all())

    @property
    def RH(self):                       # row height follows the "Download list size" setting
        return S(40) if CFG.get("density", "compact") == "compact" else S(54)

    @property
    def HH(self):
        return S(40)

    # --- model
    def set_jobs(self, jobs):
        self.jobs = jobs
        ids = {j.id for j in jobs}
        self.sel &= ids
        self.redraw()

    def selected(self):
        return [j for j in self.jobs if j.id in self.sel]

    def select_all(self):
        self.sel = {j.id for j in self.jobs}
        self.redraw()
        self.app.update_tb()

    def total_h(self):
        return len(self.jobs) * self.RH + S(4)

    def view_h(self):
        return max(1, self.winfo_height() - self.HH)

    def yview(self, *a):
        if a[0] == "moveto":
            self.off = int(float(a[1]) * self.total_h())
        else:
            step = self.RH if a[2] == "units" else self.view_h() * 9 // 10
            self.off += int(a[1]) * step
        self.redraw()

    def scroll_px(self, d):
        self.off += d
        self.redraw()

    # --- events
    def idx_at(self, y):
        if y < self.HH:
            return None
        i = (y - self.HH + self.off) // self.RH
        return i if 0 <= i < len(self.jobs) else None

    def click(self, e):
        self.focus_set()
        i = self.idx_at(e.y)
        if i is None:
            self.sel.clear()
        else:
            j = self.jobs[i]
            ids = [x.id for x in self.jobs]
            if e.state & 0x1 and self.anchor in ids:
                a = ids.index(self.anchor)
                self.sel = set(ids[min(a, i): max(a, i) + 1])
            elif e.state & 0x4:
                self.sel ^= {j.id}
                self.anchor = j.id
            else:
                self.sel, self.anchor = {j.id}, j.id
        self.redraw()
        self.app.update_tb()

    def rclick(self, e):
        self.focus_set()
        i = self.idx_at(e.y)
        if i is None:
            return
        if self.jobs[i].id not in self.sel:
            self.sel, self.anchor = {self.jobs[i].id}, self.jobs[i].id
            self.redraw()
            self.app.update_tb()
        try:
            self.app.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.app.menu.grab_release()

    def double(self, e):
        i = self.idx_at(e.y)
        if i is not None:
            self.app.dbl(self.jobs[i])

    def motion(self, e):
        i = self.idx_at(e.y)
        self.set_hover(self.jobs[i].id if i is not None else None)

    def set_hover(self, jid):
        if jid != self.hover:
            self.hover = jid
            self.redraw()

    # --- drawing
    def cols(self, W):
        pad = S(8)
        d = W - pad - S(84)
        r = d - S(104)
        l = r - S(88)
        s = l - S(224)
        z = s - S(96)
        return dict(name=S(18), size=z, status=s, left=l, rate=r, date=d)

    def stripes(self, x0, x1, y0, y1, col):
        per, h = S(10), y1 - y0
        x = x0 - h - per + int(time.time() * 20) % per
        while x < x1:
            xa, ya, xb, yb = x, y1, x + h, y0
            if xa < x0:
                ya, xa = y1 - (x0 - xa), x0
            if xb > x1:
                yb, xb = y0 + (xb - x1), x1
            if xa < xb:
                self.create_line(xa, ya, xb, yb, fill=col, width=S(2))
            x += per

    def row(self, j, y, W, X):
        RH = self.RH
        sel, hov = j.id in self.sel, self.hover == j.id
        if sel or hov:
            self.create_rectangle(0, y, W, y + RH, fill=P["sel"] if sel else P["hover"], outline="")
        self.create_line(0, y + RH - 1, W, y + RH - 1, fill=P["border"])
        cy = y + RH // 2
        glyph(self, CAT_GLYPH[j.cat], X["name"] + S(9), cy, S(18), P["fg"] if sel else P["sub"], 1)
        self.create_text(X["name"] + S(34), cy, anchor="w", font=self.fn, fill=P["fg"],
                         text=fit(j.name, self.fn, X["size"] - X["name"] - S(46)))
        d, t, st = j.done, j.total, j.status
        self.create_text(X["size"], cy, anchor="w", font=self.fs, fill=P["fg"],
                         text=human(t or d) if (t or d) else "—")
        sx, bw, bh = X["status"], S(104), S(6)
        err, run = st.startswith("Error"), st in RUNNING
        if st == "Done":
            glyph(self, "check", sx + S(8), cy, S(15), P["ok"], 1)
            self.create_text(sx + S(24), cy, anchor="w", text="Complete", font=self.fs, fill=P["ok"])
        else:
            by0 = cy - bh // 2
            rrect(self, sx, by0, sx + bw, by0 + bh, S(3), fill=P["bar"], outline="")
            pct = min(100.0, d * 100 / t) if t else 0.0
            col = (P["err"] if err else P["accent"] if run else P["warn"] if st == "Paused" else P["sub"])
            w = int(bw * pct / 100)
            if run and not t and st == "Downloading":
                w = bw
            if w > S(6) and st not in ("Queued", "Waiting"):
                rrect(self, sx, by0, sx + w, by0 + bh, S(3), fill=col, outline="")
                if run:
                    self.stripes(sx + S(2), sx + w - S(2), by0 + 1, by0 + bh - 1, mix(col, "#ffffff", .3))
            if j.note and st == "Downloading":
                txt = fit(j.note, self.fs, S(88))
            elif err:
                txt = "Error"
            elif st == "Downloading":
                txt = f"{pct:.1f}%" if t else "Downloading"
            elif st in ("Waiting", "Queued"):
                txt = "Queued"
            else:
                txt = st if st != "Connecting" else "Connecting"
            self.create_text(sx + S(198), cy, anchor="e", text=txt, font=self.fs,
                             fill=P["fg"] if run else P["err"] if err else P["sub"])
        left = fmt_eta((t - d) / j.speed) if st == "Downloading" and j.speed > 1 and t else "—"
        rate = f"{human(j.speed)}/s" if st == "Downloading" and j.speed else "—"
        self.create_text(X["left"], cy, anchor="w", text=left, font=self.fs, fill=P["sub"] if left == "—" else P["fg"])
        self.create_text(X["rate"], cy, anchor="w", text=rate, font=self.fs, fill=P["sub"] if rate == "—" else P["fg"])
        self.create_text(X["date"], cy, anchor="w", font=self.fs, fill=P["sub"],
                         text=time.strftime("%b %d", time.localtime(j.added)) if j.added else "")

    def redraw(self):
        self.delete("all")
        self.configure(bg=P["bg"])
        W, H, HH = self.winfo_width(), self.winfo_height(), self.HH
        self.off = max(0, min(self.off, max(0, self.total_h() - (H - HH))))
        X = self.cols(W)
        if not self.jobs:
            self.create_text(W // 2, H // 2 + S(10), text="Nothing here yet", fill=P["fg"], font=(FONT, 14, "bold"))
            self.create_text(W // 2, H // 2 + S(40), fill=P["sub"], font=self.fs,
                             text="Click Add URL, copy links anywhere, or drop them onto this window")
        else:
            i0 = max(0, self.off // self.RH)
            i1 = min(len(self.jobs), (self.off + H - HH) // self.RH + 1)
            for i in range(i0, i1):
                self.row(self.jobs[i], HH + i * self.RH - self.off, W, X)
        self.create_rectangle(0, 0, W, HH, fill=P["bg"], outline="")
        self.create_line(0, HH - 1, W, HH - 1, fill=P["border"])
        for k, t in (("name", "FILE NAME"), ("size", "SIZE"), ("status", "STATUS"),
                     ("left", "TIME LEFT"), ("rate", "SPEED"), ("date", "DATE")):
            self.create_text(X[k], HH // 2, anchor="w", text=t, font=self.fh, fill=P["sub"])
        if self.drop:
            rrect(self, S(6), S(6), W - S(6), H - S(6), S(14), fill=mix(P["accent"], P["bg"], .88),
                  outline=P["accent"], width=2, dash=(6, 4))
            self.create_text(W // 2, H // 2, text="Drop links here to download", fill=P["accent"],
                             font=(FONT, 16, "bold"))
        if self.sb:
            T, V = max(self.total_h(), 1), self.view_h()
            self.sb.set(self.off / T, min(1.0, (self.off + V) / T))


class AddDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Add URL")
        self.configure(bg=P["bg"])
        self.transient(app.root)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=S(18))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Add download links", font=(FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(f, text="Paste one or more links, one per line.", style="Sub.TLabel").pack(
            anchor="w", pady=(0, S(8)))
        self.t = tk.Text(f, width=64, height=7, wrap="none", relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=P["border"], highlightcolor=P["accent"], bg=P["panel"],
                         fg=P["fg"], insertbackground=P["fg"], font=(FONT, 10), padx=S(8), pady=S(8))
        self.t.pack(fill="both", expand=True)
        try:                                    # start with the links on the clipboard, if any
            self.t.insert("1.0", "\n".join(app.urls_in(app.root.clipboard_get())))
        except tk.TclError:
            pass
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(S(14), 0))
        ttk.Button(row, text="Add", style="Accent.TButton", command=self.go).pack(side="right")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Control-Return>", lambda e: self.go())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        r = app.root
        self.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2)}"
                      f"+{r.winfo_rooty() + S(110)}")
        titlebar(self, P["dark"])
        self.t.focus_set()

    def go(self):
        text = self.t.get("1.0", "end")
        self.destroy()
        self.app.offer(self.app.urls_in(text))


class Pop(tk.Toplevel):
    def __init__(self, app, job):
        super().__init__(app.root)
        self.app, self.job, self.mode = app, job, None
        self.resizable(False, False)
        self.configure(bg=P["bg"])
        self.protocol("WM_DELETE_WINDOW", self.hide)
        W = S(500)
        body = ttk.Frame(self, padding=S(18))
        body.pack(fill="both", expand=True)
        self.name = ttk.Label(body, text=job.name, font=(FONT, 12, "bold"), wraplength=W)
        self.name.pack(anchor="w")
        u = job.url if len(job.url) < 76 else job.url[:75] + "..."
        ttk.Label(body, text=u, style="Sub.TLabel").pack(anchor="w", pady=(0, S(8)))
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.pct = ttk.Label(row, text="0%", font=(FONT, 24, "bold"))
        self.pct.pack(side="left")
        self.stat = ttk.Label(row, text="", style="Sub.TLabel")
        self.stat.pack(side="right", anchor="s", pady=(0, S(4)))
        self.bar = ttk.Progressbar(body, maximum=100, length=W)
        self.bar.pack(fill="x", pady=(S(6), S(10)))
        ttk.Label(body, text="Connections", style="Sub.TLabel").pack(anchor="w")
        self.cv = tk.Canvas(body, width=W, height=S(14), highlightthickness=0, bd=0)
        self.cv.pack(fill="x", pady=(S(3), S(10)))
        ttk.Label(body, text="Speed", style="Sub.TLabel").pack(anchor="w")
        self.gv = tk.Canvas(body, width=W, height=S(56), highlightthickness=0, bd=0)
        self.gv.pack(fill="x", pady=(S(3), S(10)))
        grid = ttk.Frame(body)
        grid.pack(fill="x")
        self.v = {}
        for i, k in enumerate(("Size", "Downloaded", "Speed", "Time left", "Save to")):
            ttk.Label(grid, text=k, style="Sub.TLabel").grid(row=i, column=0, sticky="nw", pady=S(2))
            self.v[k] = ttk.Label(grid, text="", wraplength=S(380), justify="left")
            self.v[k].grid(row=i, column=1, sticky="w", padx=S(16))
        self.btns = ttk.Frame(body)
        self.btns.pack(fill="x", pady=(S(14), 0))
        self.refresh()
        self.update_idletasks()
        r, n = app.root, len(app.pops)
        x = r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2) + S(28) * n
        y = r.winfo_rooty() + max(0, (r.winfo_height() - self.winfo_reqheight()) // 4) + S(28) * n
        self.geometry(f"+{x}+{y}")
        titlebar(self, P["dark"])
        self.attributes("-topmost", True)
        self.after(400, self.untop)

    def untop(self):
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass

    def hide(self):
        self.app.pops.pop(self.job.id, None)
        self.destroy()

    def retheme(self):
        self.configure(bg=P["bg"])
        titlebar(self, P["dark"])
        self.refresh()

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        for w in self.btns.winfo_children():
            w.destroy()
        j, a = self.job, self.app

        def b(text, cmd, side="left", accent=False):
            ttk.Button(self.btns, text=text, command=cmd,
                       style="Accent.TButton" if accent else "TButton").pack(
                side=side, padx=(0, 8) if side == "left" else (8, 0))

        if mode == "run":
            b("\u275a\u275a  Pause", lambda: a.pause_jobs([j]))
            b("Hide", self.hide, "right")
        elif mode == "done":
            b("Open file", lambda: open_path(j.path), accent=True)
            b("Open folder", lambda: open_path(j.path, select=True))
            b("Close", self.hide, "right")
        else:
            b("\u25b6  Resume", lambda: a.start([j]), accent=True)
            b("Close", self.hide, "right")

    def draw(self):
        c, j = self.cv, self.job
        c.delete("all")
        c.configure(bg=P["bar"])
        W, H = max(c.winfo_width(), 10), c.winfo_height()
        if j.total and j.segs:
            T = j.total
            for s, e, p in j.segs:
                x0, x1 = s * W // T, min(W, (e + 1) * W // T)
                end = x1 - 2 if x1 < W else x1
                fill = min(end, x0 + (min(p, e + 1) - s) * W // T)
                c.create_rectangle(x0, 0, end, H, fill=P["border"], outline="")
                if fill > x0:
                    c.create_rectangle(x0, 0, fill, H, fill=P["accent"], outline="")
        g = self.gv
        g.delete("all")
        g.configure(bg=P["bar"])
        W, H = max(g.winfo_width(), 10), g.winfo_height()
        h = j.hist[-90:]
        if len(h) >= 2:
            m = (max(h) * 1.15) or 1
            pts = []
            for i, v in enumerate(h):
                pts += [W - (len(h) - 1 - i) * W / 89, H - 3 - (H - 8) * v / m]
            g.create_polygon([pts[0], H] + pts + [pts[-2], H], fill=mix(P["accent"], P["bar"], .6),
                             outline="")
            g.create_line(pts, fill=P["accent"], width=2, smooth=True)

    def refresh(self):
        j, d = self.job, self.job.done
        done = j.status == "Done"
        pct = 100 if done else (d * 100 // j.total if j.total else 0)
        self.set_mode("run" if j.status in RUNNING else "done" if done else "idle")
        known = bool(j.total) or done
        self.title(f"{pct}%  {j.name}" if known else j.name)
        self.name.config(text=j.name)
        self.pct.config(text=f"{pct}%" if known else "...")
        self.bar.config(value=pct)
        sp = f"{human(j.speed)}/s" if j.speed else ""
        self.stat.config(text="Download complete" if done else j.status + (f"   {sp}" if sp else ""))
        v = self.v
        v["Size"].config(text=human(j.total) if j.total else "Unknown")
        v["Downloaded"].config(text=human(d))
        v["Speed"].config(text=sp or "-")
        v["Time left"].config(text=fmt_eta((j.total - d) / j.speed) if j.speed > 1 and j.total else "-")
        v["Save to"].config(text=j.dir)
        self.draw()


class BatchDialog(tk.Toplevel):
    def __init__(self, app, urls, start, ctx=None):
        super().__init__(app.root)
        self.app, self.urls, self.ctx = app, urls, ctx
        self.title("Link found" if len(urls) == 1 else f"{len(urls)} links found")
        self.configure(bg=P["bg"])
        self.transient(app.root)
        f = ttk.Frame(self, padding=S(16))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Choose what to download", font=(FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(f, text="Click a row to check or uncheck it.", style="Sub.TLabel").pack(
            anchor="w", pady=(0, S(8)))
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.tv = ttk.Treeview(box, columns=("type", "host"), show="tree headings",
                               selectmode="none", height=10)
        self.tv.heading("#0", text="File", anchor="w")
        self.tv.heading("type", text="Type", anchor="w")
        self.tv.heading("host", text="From", anchor="w")
        self.tv.column("#0", width=S(330))
        self.tv.column("type", width=S(110), stretch=False)
        self.tv.column("host", width=S(190), stretch=False)
        sb = ttk.Scrollbar(box, command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)
        self.on, self.names = {}, {}
        for i, u in enumerate(urls):
            p = urlparse(u)
            base = os.path.basename(p.path)
            vid = is_media(u) or is_stream_url(u)
            name = p.netloc + " video" if vid else clean(unquote(base)) if base else p.netloc
            dup = any(j.url == u for j in JOBS)
            k = str(i)
            self.on[k], self.names[k] = not dup, name
            self.tv.insert("", "end", iid=k, text="", values=(
                "Video" if vid else category(name), p.netloc + ("  (in list)" if dup else "")))
            self.mark(k)
        self.tv.bind("<Button-1>", self.toggle)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(S(12), 0))
        ttk.Button(row, text="Select all", command=lambda: self.setall(True)).pack(side="left")
        ttk.Button(row, text="Select none", command=lambda: self.setall(False)).pack(
            side="left", padx=6)
        ttk.Button(row, text="Download selected", style="Accent.TButton",
                   command=lambda: self.go(True)).pack(side="right")
        ttk.Button(row, text="Add to list", command=lambda: self.go(False)).pack(
            side="right", padx=6)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        self.update_idletasks()
        r = app.root
        self.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2)}"
                      f"+{r.winfo_rooty() + S(70)}")
        titlebar(self, P["dark"])
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))

    def mark(self, k):
        self.tv.item(k, text=("\u2611  " if self.on[k] else "\u2610  ") + self.names[k])

    def toggle(self, e):
        k = self.tv.identify_row(e.y)
        if k:
            self.on[k] = not self.on[k]
            self.mark(k)

    def setall(self, v):
        for k in self.on:
            self.on[k] = v
            self.mark(k)

    def go(self, start):
        chosen = [u for i, u in enumerate(self.urls) if self.on[str(i)]]
        self.destroy()
        if chosen:
            self.app.add_many(chosen, auto=start, ctx=self.ctx)


class FetchDialog(tk.Toplevel):
    def __init__(self, app, url, fn=None, then=None):
        super().__init__(app.root)
        self.app, self.url, self.res, self.dead = app, url, {}, False
        self.fn, self.then = fn, then
        self.title("MyDM")
        self.configure(bg=P["bg"])
        self.resizable(False, False)
        self.transient(app.root)
        f = ttk.Frame(self, padding=S(22))
        f.pack()
        ttk.Label(f, text="Getting video information...", font=(FONT, 11, "bold")).pack(anchor="w")
        ttk.Label(f, text=url if len(url) < 60 else url[:59] + "...", style="Sub.TLabel").pack(
            anchor="w", pady=(2, S(12)))
        pb = ttk.Progressbar(f, mode="indeterminate", length=S(380))
        pb.pack()
        pb.start(12)
        ttk.Button(f, text="Cancel", command=self.cancel).pack(anchor="e", pady=(S(14), 0))
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.update_idletasks()
        r = app.root
        self.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2)}"
                      f"+{r.winfo_rooty() + S(120)}")
        titlebar(self, P["dark"])
        threading.Thread(target=self.work, daemon=True).start()
        self.poll()

    def work(self):
        try:
            if self.fn:
                self.res["info"] = self.fn()
            else:
                with ytdlp().YoutubeDL(ydl_opts(extract_flat="in_playlist", skip_download=True)) as ydl:
                    self.res["info"] = ydl.sanitize_info(ydl.extract_info(self.url, download=False))
        except Exception as ex:
            self.res["err"] = str(ex)

    def cancel(self):
        self.dead = True
        self.destroy()

    def poll(self):
        if self.dead:
            return
        if not self.res:
            self.after(150, self.poll)
            return
        self.dead = True
        self.destroy()
        if "info" in self.res:
            (self.then or self.app.show_media)(self.url, self.res["info"])
            return
        msg = re.sub(r"\x1b\[[0-9;]*m", "", self.res["err"]).strip()[:350]
        low = msg.lower()
        if "sign in" in low or "bot" in low:
            msg += "\n\nTip: Settings > Browser cookies > Firefox (while logged in to the site)."
        elif any(k in low for k in ("getaddrinfo", "timed out", "connection", "proxy", "unreachable")):
            msg += "\n\nTip: if the site is blocked, turn on your VPN / set the proxy in Settings."
        messagebox.showerror("Could not read this video", msg)


class MediaDialog(tk.Toplevel):
    def __init__(self, app, url, info, opts):
        super().__init__(app.root)
        self.app, self.url, self.info, self.opts = app, url, info, opts
        self.title("Download video")
        self.configure(bg=P["bg"])
        self.transient(app.root)
        f = ttk.Frame(self, padding=S(18))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=info.get("title") or url, font=(FONT, 12, "bold"),
                  wraplength=S(520)).pack(anchor="w")
        bits = [info.get("uploader") or info.get("channel") or "",
                fmt_eta(info["duration"]) if info.get("duration") else ""]
        ttk.Label(f, text="  \u00b7  ".join(b for b in bits if b), style="Sub.TLabel").pack(
            anchor="w", pady=(2, S(12)))
        ttk.Label(f, text="Choose quality", font=(FONT, 10, "bold")).pack(anchor="w", pady=(0, S(4)))
        self.tv = ttk.Treeview(f, columns=("detail", "size"), show="tree headings",
                               selectmode="browse", height=min(len(opts), 9))
        for c, t, w in (("#0", "Quality", 150), ("detail", "Format", 170), ("size", "Size", 110)):
            self.tv.heading(c, text=t, anchor="w")
            self.tv.column(c, width=S(w), stretch=c == "#0")
        for i, o in enumerate(opts):
            self.tv.insert("", "end", iid=str(i), text="  " + o["label"], values=(
                o["detail"], ("~" + human(o["size"])) if o["size"] else "-"))
        self.tv.pack(fill="x")
        i = str(pick_default(opts))
        self.tv.selection_set(i)
        self.tv.focus(i)
        self.tv.bind("<Double-1>", lambda e: self.go(True))
        if not ffmpeg_path():
            ttk.Label(f, style="Sub.TLabel", wraplength=S(520),
                      text="ffmpeg was not found, so only ready-made files (up to 720p) are offered."
                      ).pack(anchor="w", pady=(S(8), 0))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(S(16), 0))
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="left")
        ttk.Button(row, text="Download now", style="Accent.TButton",
                   command=lambda: self.go(True)).pack(side="right")
        ttk.Button(row, text="Add to list", command=lambda: self.go(False)).pack(side="right", padx=8)
        self.update_idletasks()
        r = app.root
        self.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2)}"
                      f"+{r.winfo_rooty() + S(70)}")
        titlebar(self, P["dark"])
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))

    def go(self, start):
        s = self.tv.selection()
        if s:
            self.destroy()
            self.app.add_media(self.url, self.info, self.opts[int(s[0])], start)


class Countdown(tk.Toplevel):
    def __init__(self, app, action, why, seconds=30):
        super().__init__(app.root)
        self.app, self.action, self.why, self.n, self.dead = app, action, why, seconds, False
        self.title("MyDM")
        self.configure(bg=P["bg"])
        self.resizable(False, False)
        self.lbl = ttk.Label(self, padding=S(24), font=(FONT, 11), justify="center")
        self.lbl.pack()
        ttk.Button(self, text="Cancel", command=self.cancel).pack(pady=(0, S(16)))
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.geometry(f"+{app.root.winfo_rootx() + S(120)}+{app.root.winfo_rooty() + S(120)}")
        titlebar(self, P["dark"])
        self.attributes("-topmost", True)
        self.step()

    def cancel(self):
        self.dead = True
        self.destroy()

    def step(self):
        if self.dead:
            return
        if self.n <= 0:
            self.destroy()
            cmd = power_cmd(self.action)
            if cmd:
                try:
                    subprocess.Popen(cmd, creationflags=0x08000000 if WIN else 0)
                except Exception:
                    pass
            return
        self.lbl.config(text=f"{self.why}\n\n{self.action} in {self.n} s")
        self.n -= 1
        self.after(1000, self.step)


# ======================================================================== app
class App:
    def __init__(self, root):
        self.root = root
        self.pops, self.session, self.flt, self.fired = {}, set(), "all", {}
        self.pending, self.closing, self.dragging = None, False, False
        self.inbox = queue.Queue()
        self.srv, self.port = start_bridge(self.inbox)
        self.last_clip, self.note, self.note_until, self.ticks = "", "", 0, 0
        self.load()
        root.title("MyDM " + VERSION)
        root.geometry(CFG["geom"] or f"{S(1220)}x{S(780)}")
        root.minsize(S(1100), S(520))
        init_fonts(root)
        apply_theme(root)
        self.icon = make_icon()
        root.iconphoto(True, self.icon)
        try:
            self.last_clip = root.clipboard_get()
        except tk.TclError:
            pass

        self.menus, self.lines = [], []
        self.status, self.speed_txt, self.sched_txt = tk.StringVar(), tk.StringVar(), tk.StringVar()

        def line(parent, **pk):
            f = tk.Frame(parent, bd=0, highlightthickness=0, **({"height": 1} if pk.get("fill") == "x" else {"width": 1}))
            f.pack(**pk)
            self.lines.append(f)
            return f

        def menu(items):
            m = tk.Menu(root, tearoff=0)
            for it in items:
                if it is None:
                    m.add_separator()
                else:
                    m.add_command(label=it[0], command=it[1])
            self.menus.append(m)
            return m

        def theme_menu():
            m = tk.Menu(root, tearoff=0)
            for lab, key in (("System", "system"), ("Light", "light"), ("Dark", "dark")):
                m.add_command(label="Theme: " + lab, command=lambda k=key: self.set_theme(k))
            m.add_separator()
            for lab, key in (("Compact", "compact"), ("Comfortable", "comfortable")):
                m.add_command(label="List size: " + lab, command=lambda k=key: self.set_density(k))
            self.menus.append(m)
            return m

        stop_running = lambda: self.pause_jobs([j for j in JOBS if j.status in RUNNING])
        stop_queued = lambda: self.pause_jobs([j for j in JOBS if j.status == "Waiting"])
        tasks = menu([("Add URL...", self.add), ("Paste links", self.paste), None,
                      ("Import downloads...", self.imp), ("Export downloads...", self.exp), None,
                      ("Scheduler", self.scheduler), ("Options", self.settings), None,
                      ("Exit MyDM", self.close)])
        files = menu([("Open file", self.open_file), ("Open folder", self.openf),
                      ("Show progress window", self.show_pop), ("Copy link", self.copy_link)])
        downs = menu([("Resume", lambda: self.start(self.selected())),
                      ("Stop", lambda: self.pause_jobs(self.selected())), ("Stop all", stop_running), None,
                      ("Start queue", lambda: self.start(JOBS)), ("Stop queue", stop_queued), None,
                      ("Download again", self.redo), ("Remove from list", self.remove),
                      ("Remove and delete file", lambda: self.remove(True)), None,
                      ("Clear completed downloads", self.clear)])
        helpm = menu([("Open extension folder", lambda: open_path(ext_dir())),
                      ("Open Chrome extensions page", open_chrome_ext),
                      ("Update video engine", self.update_engine_bg), None,
                      ("About MyDM", self.about)])
        self.menubar = MenuBar(root, [("Tasks", tasks), ("File", files), ("Downloads", downs),
                                      ("View", theme_menu()), ("Help", helpm)], self.toggle_theme)
        self.menubar.pack(fill="x")
        line(root, fill="x")

        trow = tk.Frame(root, bd=0, highlightthickness=0)
        trow.pack(fill="x")
        self.trow = trow
        self.tb = Toolbar(trow, {
            "add": self.add, "resume": lambda: self.start(self.selected()),
            "stop": lambda: self.pause_jobs(self.selected()), "stopall": stop_running,
            "delete": self.remove, "clear": self.clear, "options": self.settings,
            "sched": self.scheduler, "startq": lambda: self.start(JOBS), "stopq": stop_queued})
        self.search = SearchBox(trow, self.refilter)
        self.search.pack(side="right", padx=(S(8), S(18)), pady=S(20))
        self.tb.pack(side="left", fill="x", expand=True)
        line(root, fill="x")

        foot = tk.Frame(root, bd=0, highlightthickness=0)
        foot.pack(side="bottom", fill="x")
        self.foot = foot
        self.flbls = [tk.Label(foot, textvariable=self.status, bd=0, padx=S(18), pady=S(7), font=(FONT, 9)),
                      tk.Label(foot, textvariable=self.speed_txt, bd=0, padx=S(18), pady=S(7), font=(FONT, 9)),
                      tk.Label(foot, textvariable=self.sched_txt, bd=0, padx=S(4), pady=S(7), font=(FONT, 9))]
        self.flbls[0].pack(side="left")
        self.flbls[1].pack(side="right")
        self.flbls[2].pack(side="right")
        fl = tk.Frame(root, height=1, bd=0, highlightthickness=0)
        fl.pack(side="bottom", fill="x")
        self.lines.append(fl)

        body = tk.Frame(root, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True)
        self.body = body
        self.side = Side(body, self.set_filter)
        self.side.pack(side="left", fill="y")
        line(body, side="left", fill="y")
        right = tk.Frame(body, bd=0, highlightthickness=0)
        right.pack(side="left", fill="both", expand=True)
        self.lst = JobList(right, self)
        self.sb = ttk.Scrollbar(right, command=self.lst.yview)
        self.lst.sb = self.sb
        self.sb.pack(side="right", fill="y")
        self.lst.pack(side="left", fill="both", expand=True)
        root.bind_all("<MouseWheel>", self.wheel)
        root.bind_all("<Button-4>", self.wheel)
        root.bind_all("<Button-5>", self.wheel)
        root.bind("<Control-v>", self.ctrl_v)

        self.menu = tk.Menu(root, tearoff=0)
        for label, cmd in [("Start / Resume", self.start), ("Pause", self.pause), (None, None),
                           ("Open file", self.open_file), ("Open folder", self.openf),
                           ("Show progress window", self.show_pop), ("Copy link", self.copy_link),
                           (None, None), ("Download again", self.redo), ("Remove from list", self.remove),
                           ("Remove and delete file", lambda: self.remove(True))]:
            self.menu.add_separator() if not label else self.menu.add_command(
                label=label, command=cmd)

        if TkinterDnD:
            try:
                for w in (root, self.lst, self.side):
                    w.drop_target_register(DND_TEXT, DND_FILES)
                    w.dnd_bind("<<Drop>>", self.on_drop)
                    w.dnd_bind("<<DropEnter>>", lambda e: self.drag(True))
                    w.dnd_bind("<<DropLeave>>", lambda e: self.drag(False))
            except Exception:
                pass

        self.retheme()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, lambda: titlebar(root, P["dark"]))
        if "--min" in sys.argv:
            root.iconify()
        threading.Thread(target=lambda: is_media("https://example.com/x"), daemon=True).start()
        self.tick()

    # ---- theme ----
    def retheme(self):
        apply_theme(self.root)
        for m in self.menus + [self.menu]:
            m.configure(bg=P["panel"], fg=P["fg"], activebackground=P["sel"],
                        activeforeground=P["accent"], bd=0, relief="flat")
        for f in (self.trow, self.foot, self.body, self.lst.master):
            f.configure(bg=P["bg"])
        for f in self.lines:
            f.configure(bg=P["border"])
        for l in self.flbls:
            l.configure(bg=P["bg"], fg=P["sub"])
        self.menubar.restyle()
        self.search.restyle()
        titlebar(self.root, P["dark"])
        self.tb.redraw()
        self.side.redraw()
        self.lst.redraw()
        for p in self.pops.values():
            p.retheme()

    def set_theme(self, t):
        CFG["theme"] = t
        self.save()
        self.retheme()

    def toggle_theme(self):
        self.set_theme("light" if P["dark"] else "dark")

    def set_density(self, d):
        CFG["density"] = d
        self.save()
        self.lst.redraw()

    def about(self):
        messagebox.showinfo("About MyDM", f"MyDM {VERSION}\n\n" + self.video_status())

    def update_engine_bg(self):
        self.say("Updating the video engine...")
        threading.Thread(target=lambda: self.say(update_engine()[1]), daemon=True).start()

    def ctrl_v(self, e):
        if not isinstance(self.root.focus_get(), (tk.Entry, tk.Text, ttk.Entry)):
            self.paste()

    def refilter(self):
        self.lst.off = 0
        self.lst.set_jobs([j for j in JOBS if self.match(j)])

    def update_tb(self):
        sel = self.selected()
        can = lambda j: j.status in ("Queued", "Paused") or j.status.startswith("Error")
        self.tb.enable({"resume": any(can(j) for j in sel), "stop": any(j.status in RUNNING for j in sel),
                        "stopall": any(j.status in RUNNING for j in JOBS), "delete": bool(sel),
                        "clear": any(j.status == "Done" for j in JOBS),
                        "startq": any(can(j) for j in JOBS),
                        "stopq": any(j.status == "Waiting" for j in JOBS)})

    # ---- state ----
    def load(self):
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            CFG.update(d.get("cfg", {}))
            CFG["sched"] = {**SCHED, **CFG.get("sched", {})}
            for x in d.get("jobs", []):
                try:
                    JOBS.append(Job.from_dict(x))
                except Exception:
                    pass
        except Exception:
            pass

    def save(self):
        try:
            DATA.mkdir(exist_ok=True)
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"cfg": CFG, "jobs": [j.to_dict() for j in JOBS]}),
                           encoding="utf-8")
            os.replace(tmp, STATE)
        except Exception:
            pass

    def close(self):
        self.closing = True
        for j in JOBS:
            j.stop.set()
        try:
            CFG["geom"] = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
        except tk.TclError:
            pass
        try:
            self.srv and self.srv.server_close()
        except Exception:
            pass
        time.sleep(0.4)
        self.save()
        self.root.destroy()

    # ---- adding links ----
    def say(self, text):
        self.note, self.note_until = text, time.time() + 6

    def urls_in(self, text):
        return list(dict.fromkeys(re.findall(r'https?://[^\s<>"\']+', text)))

    def add_many(self, urls, auto=False, ctx=None):
        new = []
        for u in urls:
            if not any(j.url == u for j in JOBS):
                kind = "stream" if is_stream_url(u) else "media" if is_media(u) else "file"
                j = Job(u, CFG["folder"], kind)
                if kind == "media":
                    j.fmt, j.audio, j.mp3 = default_choice()
                elif ctx:
                    j.referer, j.cookie, j.ua = ctx.get("referer", ""), ctx.get("cookie", ""), ctx.get("ua", "")
                JOBS.append(j)
                new.append(j)
        self.say(f"{len(new)} new link(s) added" if urls else "No valid link found")
        if new:
            self.save()
            if auto:
                self.start(new)
        return new

    def offer(self, urls, start=False):
        urls = list(dict.fromkeys(urls))
        if not urls:
            self.say("No link found")
        elif len(urls) == 1 and is_media(urls[0]):
            self.media_flow(urls[0])
        elif len(urls) == 1:
            self.add_many(urls, auto=start)
        else:
            BatchDialog(self, urls, start)

    def media_flow(self, url):
        if not ytdlp():
            messagebox.showerror("Video", "The video engine did not load:\n" + _YT[2])
        elif any(j.url == url for j in JOBS):
            self.say("This video is already in the list")
        else:
            FetchDialog(self, url)

    def show_media(self, url, info):
        if info.get("_type") == "playlist":
            urls = [e.get("url") or e.get("webpage_url") for e in info.get("entries") or [] if e]
            urls = [u for u in urls if u and u.startswith("http")]
            if urls and messagebox.askyesno(
                    "Playlist", f"\"{info.get('title') or 'Playlist'}\" has {len(urls)} videos.\n\n"
                                "Add all of them to the list with your default quality?"):
                self.add_many(urls)
            return
        opts = quality_options(info, bool(ffmpeg_path()))
        if opts:
            MediaDialog(self, url, info, opts)
        else:
            messagebox.showerror("Video", "No downloadable formats were found for this link.")

    def add_media(self, url, info, opt, start):
        j = info.get("_job")
        if j:                                          # HLS stream with the chosen quality
            j.fmt = opt["fmt"]
        else:
            j = Job(url, CFG["folder"], "media")
            j.fmt, j.audio, j.mp3 = opt["fmt"], opt["audio"], opt["mp3"]
            j.name = clean(info.get("title") or j.name) + (".mp3" if opt["mp3"] else
                                                           ".m4a" if opt["audio"] else ".mp4")
        JOBS.append(j)
        self.save()
        if start:
            self.start([j])

    def add(self):
        AddDialog(self)

    def paste(self):
        try:
            self.offer(self.urls_in(self.root.clipboard_get()))
        except tk.TclError:
            self.say("Clipboard is empty")

    def imp(self):
        p = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            with open(p, encoding="utf-8", errors="ignore") as f:
                self.offer(self.urls_in(f.read()))

    def exp(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if not p:
            return
        only = messagebox.askyesno("Export", "Export only unfinished links?\n(No = all links)")
        urls = [j.url for j in JOBS if not only or j.status != "Done"]
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(urls))
        self.say(f"{len(urls)} link(s) exported")

    def from_browser(self, m):
        url, kind = m["url"], m.get("kind") or "file"
        if kind == "site":                       # a page the video engine understands (YouTube, Aparat...)
            self.root.deiconify()
            self.media_flow(url)
            return
        if kind == "links":                      # right-click on a selection: every link inside it
            self.root.deiconify()
            self.root.lift()
            urls = list(dict.fromkeys(m.get("urls") or [url]))
            ctx = {"referer": m["referer"], "cookie": m["cookie"], "ua": m["ua"]}
            if len(urls) == 1 and not is_media(urls[0]):
                self.add_many(urls, auto=True, ctx=ctx)
            elif len(urls) == 1:
                self.media_flow(urls[0])
            else:
                BatchDialog(self, urls, True, ctx)
            return
        if kind == "link" and is_media(url):      # right-click on a link to a video site
            self.root.deiconify()
