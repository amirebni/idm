import os, re, sys, json, time, shutil, mimetypes, threading, subprocess
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse, unquote
import requests

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
CAT_COL = {"Video": "#8b5cf6", "Music": "#ec4899", "Documents": "#3b82f6",
           "Compressed": "#f59e0b", "Programs": "#10b981", "Images": "#06b6d4",
           "Other": "#6b7280"}
EXTS = set(EXT2CAT) | {"torrent", "bin", "img"}
RUNNING = ("Waiting", "Connecting", "Downloading")
ACTIONS = ["Do nothing", "Exit MyDM", "Lock screen", "Log off", "Sleep", "Hibernate",
           "Restart", "Shut down", "Shut down (force close apps)"]
WIN = sys.platform.startswith("win")
SCHED = {"start_on": False, "start": "02:00", "stop_on": False, "stop": "07:00",
         "daily": True, "action": "Do nothing", "on_finish": False}
CFG = {"folder": str(Path.home() / "Downloads"), "segments": 8, "parallel": 3,
       "limit_kb": 0, "proxy_mode": "system", "proxy": "", "watch": True,
       "autostart": False, "subfolders": True, "popup": True, "sound": False,
       "theme": "system", "geom": "", "sched": dict(SCHED),
       "ytq": "1080p", "cookies": "", "watch_media": False}
JOBS = []
FONT, SC = "TkDefaultFont", 1.0

LIGHT = dict(dark=False, bg="#f3f4f6", panel="#ffffff", fg="#111827", sub="#6b7280",
             accent="#2563eb", accent2="#1d4ed8", border="#e0e3e8", sel="#e8f0fe",
             hdr="#eceff3", hover="#f7f8fa", ok="#15803d", err="#dc2626", bar="#e5e7eb")
DARK = dict(dark=True, bg="#13151a", panel="#1b1e25", fg="#e5e7eb", sub="#8b93a1",
            accent="#3b82f6", accent2="#2563eb", border="#2a2f39", sel="#222c42",
            hdr="#232730", hover="#21252d", ok="#4ade80", err="#f87171", bar="#2c313c")
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


def ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except Exception:
        return None


def res_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, name)
    return p if os.path.exists(p) else None


def ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


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


def ydl_opts(**extra):
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "windowsfilenames": True,
         "socket_timeout": 30, "retries": 5, "fragment_retries": 5}
    ff = ffmpeg_path()
    if ff:
        o["ffmpeg_location"] = ff
    qjs = res_path("qjs.exe" if WIN else "qjs")
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
    size = lambda f: (f.get("filesize") or f.get("filesize_approx") or 0) if f else 0
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
                         audio=False, mp3=False, h=h))
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
    root.configure(bg=P["bg"])


def make_icon():
    img = tk.PhotoImage(width=64, height=64)
    img.put("#2563eb", to=(0, 0, 64, 64))
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
    KEYS = ("url", "folder", "name", "path", "total", "ranged", "segs", "status",
            "kind", "fmt", "audio", "mp3")

    def __init__(self, url, folder, media=False):
        self.url, self.folder = url, folder
        self.kind, self.fmt, self.audio, self.mp3, self.note = (
            "media" if media else "file", "", False, False, "")
        self.name = (urlparse(url).netloc.replace("www.", "") + " video" if media else
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
        if self.kind == "media":
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

    def probe(self):
        r = http_get(self.url, headers={**UA, "Range": "bytes=0-0"}, stream=True, timeout=30)
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
            if self.kind == "media":
                self.run_media()
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
            self.status = ("Paused" if self.kind == "media" and self.stop.is_set()
                           else "Error: " + re.sub(r"\x1b\[[0-9;]*m", "", str(ex))[:160])

    def seg(self, s):
        tries = 0
        while not self.stop.is_set() and s[2] <= s[1]:
            before = s[2]
            try:
                h = {**UA, "Range": f"bytes={s[2]}-{s[1]}"}
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
        with http_get(self.url, headers=UA, stream=True, timeout=30) as r:
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


# ================================================================== widgets
class Hint(ttk.Entry):
    def __init__(self, parent, hint):
        super().__init__(parent)
        self.hint, self.empty = hint, False
        self.bind("<FocusIn>", self._in)
        self.bind("<FocusOut>", self._out)
        self._out()

    def _in(self, _=None):
        if self.empty:
            self.delete(0, "end")
            self.empty = False
        self.restyle()

    def _out(self, _=None):
        if not self.get():
            self.empty = True
            self.insert(0, self.hint)
        self.restyle()

    def restyle(self):
        self.configure(foreground=P["sub"] if self.empty else P["fg"])

    def value(self):
        return "" if self.empty else self.get()

    def clear(self):
        self.delete(0, "end")
        self.empty = False
        self._out()


class Side(tk.Canvas):
    ITEMS = ([("h", "LIBRARY"), ("all", "All downloads"), ("unfinished", "Unfinished"),
              ("completed", "Completed"), ("h", "CATEGORIES")] +
             [("c:" + c, c) for c in CAT_LIST])

    def __init__(self, parent, on_pick):
        super().__init__(parent, width=S(210), highlightthickness=0, bd=0)
        self.on_pick, self.cur, self.counts, self.rows = on_pick, "all", {}, []
        self.f = tkfont.Font(family=FONT, size=10)
        self.fh = tkfont.Font(family=FONT, size=8, weight="bold")
        self.bind("<Button-1>", self.click)
        self.bind("<Configure>", lambda e: self.redraw())

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

    def redraw(self):
        self.delete("all")
        self.configure(bg=P["bg"])
        W, y = self.winfo_width(), S(2)
        self.rows = []
        lib = {"all": P["accent"], "unfinished": "#f59e0b", "completed": P["ok"]}
        for key, label in self.ITEMS:
            if key == "h":
                y += S(12)
                self.create_text(S(14), y + S(8), anchor="w", text=label, fill=P["sub"],
                                 font=self.fh)
                y += S(22)
                continue
            h = S(36)
            if key == self.cur:
                rrect(self, S(2), y, W - S(2), y + h - S(4), S(9), fill=P["sel"], outline="")
            col = CAT_COL[key[2:]] if key.startswith("c:") else lib[key]
            cy, r = y + (h - S(4)) // 2, S(5)
            self.create_oval(S(16), cy - r, S(16) + 2 * r, cy + r, fill=col, outline="")
            self.create_text(S(36), cy, anchor="w", text=label, fill=P["fg"], font=self.f)
            self.create_text(W - S(14), cy, anchor="e", text=str(self.counts.get(key, 0)),
                             fill=P["sub"], font=self.f)
            self.rows.append((y, y + h, key))
            y += h


class JobList(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, highlightthickness=0, bd=0, takefocus=1)
        self.app, self.jobs, self.sel, self.anchor = app, [], set(), None
        self.off, self.hover, self.hits, self.drop, self.sb = 0, None, [], False, None
        self.RH = S(74)
        self.fn = tkfont.Font(family=FONT, size=10, weight="bold")
        self.fs = tkfont.Font(family=FONT, size=9)
        self.fb = tkfont.Font(family=FONT, size=8, weight="bold")
        self.fp = tkfont.Font(family=FONT, size=11, weight="bold")
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self.click)
        self.bind("<Double-1>", self.double)
        for b in ("<Button-3>", "<Button-2>"):
            self.bind(b, self.rclick)
        self.bind("<Motion>", self.motion)
        self.bind("<Leave>", lambda e: self.set_hover(None))
        self.bind("<Delete>", lambda e: app.remove())
        self.bind("<Control-a>", lambda e: self.select_all())
        self.bind("<Control-v>", lambda e: app.paste())

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

    def total_h(self):
        return len(self.jobs) * self.RH + S(8)

    def yview(self, *a):
        if a[0] == "moveto":
            self.off = int(float(a[1]) * self.total_h())
        else:
            step = self.RH // 2 if a[2] == "units" else self.winfo_height() * 9 // 10
            self.off += int(a[1]) * step
        self.redraw()

    def scroll_px(self, d):
        self.off += d
        self.redraw()

    # --- events
    def idx_at(self, y):
        i = (y + self.off - S(4)) // self.RH
        return i if 0 <= i < len(self.jobs) else None

    def hit(self, e):
        for x0, y0, x1, y1, act, jid in self.hits:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return act, jid
        return None

    def click(self, e):
        self.focus_set()
        h = self.hit(e)
        if h:
            self.app.row_action(*h)
            return
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

    def rclick(self, e):
        self.focus_set()
        i = self.idx_at(e.y)
        if i is None:
            return
        if self.jobs[i].id not in self.sel:
            self.sel, self.anchor = {self.jobs[i].id}, self.jobs[i].id
            self.redraw()
        try:
            self.app.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.app.menu.grab_release()

    def double(self, e):
        if self.hit(e):
            return
        i = self.idx_at(e.y)
        if i is not None:
            self.app.dbl(self.jobs[i])

    def motion(self, e):
        i = self.idx_at(e.y)
        self.configure(cursor="hand2" if self.hit(e) else "")
        self.set_hover(self.jobs[i].id if i is not None else None)

    def set_hover(self, jid):
        if jid != self.hover:
            self.hover = jid
            self.redraw()

    # --- drawing
    def sub(self, j):
        d, t = j.done, j.total
        if j.note and j.status == "Downloading":
            return j.note
        if j.status == "Done":
            return f"{human(t or d)}  \u00b7  Completed"
        if j.status.startswith("Error"):
            return j.status
        if j.status in ("Connecting", "Waiting"):
            return "Connecting..." if j.status == "Connecting" else "Waiting in queue"
        size = f"{human(d)} of {human(t)}" if t else human(d)
        if j.status == "Downloading":
            s = f"{size}  \u00b7  {human(j.speed)}/s" if j.speed else size
            if j.speed > 1 and t:
                s += f"  \u00b7  {fmt_eta((t - d) / j.speed)} left"
            return s
        return f"{size}  \u00b7  {j.status}"

    def pill(self, x0, y0, x1, y1, text, act, jid, accent=False):
        rrect(self, x0, y0, x1, y1, (y1 - y0) // 2, fill=P["accent"] if accent else P["bar"],
              outline="")
        self.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=text, font=self.fs,
                         fill="#ffffff" if accent else P["fg"])
        self.hits.append((x0, y0, x1, y1, act, jid))

    def row(self, j, y, W):
        sel, hov = j.id in self.sel, self.hover == j.id
        x0, x1, y0, y1 = S(2), W - S(2), y + S(4), y + self.RH - S(4)
        rrect(self, x0, y0, x1, y1, S(12),
              fill=P["sel"] if sel else P["hover"] if hov else P["panel"],
              outline=P["accent"] if sel else P["border"])
        bs = S(44)
        bx, by = x0 + S(14), (y0 + y1) // 2 - bs // 2
        rrect(self, bx, by, bx + bs, by + bs, S(11), fill=CAT_COL[j.cat], outline="")
        ext = os.path.splitext(j.name)[1].lstrip(".").upper()[:4] or (
            "MP3" if j.mp3 else "AUD" if j.audio else "VID" if j.kind == "media" else "FILE")
        self.create_text(bx + bs // 2, by + bs // 2, text=ext, fill="#ffffff", font=self.fb)

        ph, pw, gap = S(28), S(76), S(8)
        py = (y0 + y1) // 2 - ph // 2
        right = x1 - S(14)
        st = j.status
        if st == "Done":
            self.pill(right - pw, py, right, py + ph, "Open", "open", j.id, True)
            self.pill(right - 2 * pw - gap, py, right - pw - gap, py + ph, "Folder", "folder", j.id)
            left = right - 2 * pw - gap
        elif st in RUNNING:
            self.pill(right - pw, py, right, py + ph, "Pause", "pause", j.id)
            self.pill(right - 2 * pw - gap, py, right - pw - gap, py + ph, "Details", "details", j.id)
            left = right - 2 * pw - gap
        else:
            lab = "Retry" if st.startswith("Error") else "Resume" if st == "Paused" else "Start"
            self.pill(right - pw, py, right, py + ph, lab, "start", j.id, True)
            left = right - pw

        tx = bx + bs + S(16)
        d = j.done
        pct = 100 if st == "Done" else (d * 100 // j.total if j.total else 0)
        known = bool(j.total) or st == "Done"
        pw_txt = S(54)
        if known:
            self.create_text(left - S(14), y0 + S(18), anchor="e", font=self.fp,
                             text=f"{pct}%", fill=P["ok"] if st == "Done" else P["fg"])
        avail = left - S(14) - pw_txt - tx
        self.create_text(tx, y0 + S(18), anchor="w", font=self.fn, fill=P["fg"],
                         text=fit(j.name, self.fn, avail))
        err = st.startswith("Error")
        self.create_text(tx, y0 + S(38), anchor="w", font=self.fs,
                         fill=P["err"] if err else P["sub"],
                         text=fit(self.sub(j), self.fs, left - S(14) - tx))
        by0, bx1 = y1 - S(15), left - S(14)
        rrect(self, tx, by0, bx1, by0 + S(6), S(3), fill=P["bar"], outline="")
        w = int((bx1 - tx) * pct / 100)
        if w > S(6):
            col = (P["ok"] if st == "Done" else P["err"] if err else
                   P["accent"] if st in RUNNING else P["sub"])
            rrect(self, tx, by0, tx + w, by0 + S(6), S(3), fill=col, outline="")

    def redraw(self):
        self.delete("all")
        self.hits = []
        self.configure(bg=P["bg"])
        W, H = self.winfo_width(), self.winfo_height()
        self.off = max(0, min(self.off, max(0, self.total_h() - H)))
        if not self.jobs:
            self.create_text(W // 2, H // 2 - S(14), text="Nothing here yet", fill=P["fg"],
                             font=(FONT, 14, "bold"))
            self.create_text(W // 2, H // 2 + S(16), fill=P["sub"], font=self.fs,
                             text="Paste a link, copy links anywhere, or drop them onto this window")
        else:
            i0 = max(0, (self.off - S(4)) // self.RH)
            i1 = min(len(self.jobs), (self.off + H) // self.RH + 1)
            for i in range(i0, i1):
                self.row(self.jobs[i], S(4) + i * self.RH - self.off, W)
        if self.drop:
            rrect(self, S(4), S(4), W - S(4), H - S(4), S(14), fill=mix(P["accent"], P["bg"], .88),
                  outline=P["accent"], width=2, dash=(6, 4))
            self.create_text(W // 2, H // 2, text="Drop links here to download", fill=P["accent"],
                             font=(FONT, 16, "bold"))
        if self.sb:
            T = max(self.total_h(), 1)
            self.sb.set(self.off / T, min(1.0, (self.off + H) / T))


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
    def __init__(self, app, urls, start):
        super().__init__(app.root)
        self.app, self.urls = app, urls
        self.title(f"{len(urls)} links found")
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
            vid = is_media(u)
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
            self.app.add_many(chosen, auto=start)


class FetchDialog(tk.Toplevel):
    def __init__(self, app, url):
        super().__init__(app.root)
        self.app, self.url, self.res, self.dead = app, url, {}, False
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
            self.app.show_media(self.url, self.res["info"])
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
        self.last_clip, self.note, self.note_until, self.ticks = "", "", 0, 0
        self.load()
        root.title("MyDM")
        root.geometry(CFG["geom"] or f"{S(1160)}x{S(700)}")
        root.minsize(S(940), S(520))
        init_fonts(root)
        apply_theme(root)
        self.icon = make_icon()
        root.iconphoto(True, self.icon)
        try:
            self.last_clip = root.clipboard_get()
        except tk.TclError:
            pass

        hdr = ttk.Frame(root, padding=(S(16), S(14), S(16), S(8)))
        hdr.pack(fill="x")
        self.logo = self.icon.subsample(2, 2)
        ttk.Label(hdr, image=self.logo).pack(side="left")
        ttk.Label(hdr, text="MyDM", font=(FONT, 15, "bold")).pack(side="left", padx=(S(8), S(16)))
        self.entry = Hint(hdr, "Paste or drop a link here, then press Enter")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.add())
        ttk.Button(hdr, text="\uff0b  Add", style="Accent.TButton", command=self.add).pack(
            side="left", padx=(S(8), 0))

        tb = ttk.Frame(root, padding=(S(16), 0, S(16), S(10)))
        tb.pack(fill="x")
        for t, c in [("\u25b6  Start", self.start), ("\u275a\u275a  Pause", self.pause),
                     ("\u2715  Remove", self.remove), ("Clear done", self.clear),
                     ("Paste", self.paste), ("Import", self.imp), ("Export", self.exp)]:
            ttk.Button(tb, text=t, command=c).pack(side="left", padx=(0, S(6)))
        ttk.Button(tb, text="\u2699  Settings", command=self.settings).pack(side="right")
        ttk.Button(tb, text="\u23f0  Scheduler", command=self.scheduler).pack(
            side="right", padx=(0, S(6)))

        foot = ttk.Frame(root, padding=(S(16), S(4), S(16), S(10)))
        foot.pack(side="bottom", fill="x")
        self.status, self.sched_txt = tk.StringVar(), tk.StringVar()
        ttk.Label(foot, textvariable=self.status, style="Sub.TLabel").pack(side="left")
        ttk.Label(foot, textvariable=self.sched_txt, style="Sub.TLabel").pack(side="right")

        body = ttk.Frame(root, padding=(S(16), 0))
        body.pack(fill="both", expand=True)
        self.side = Side(body, self.set_filter)
        self.side.pack(side="left", fill="y", padx=(0, S(10)))
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.lst = JobList(right, self)
        self.sb = ttk.Scrollbar(right, command=self.lst.yview)
        self.lst.sb = self.sb
        self.sb.pack(side="right", fill="y")
        self.lst.pack(side="left", fill="both", expand=True)
        root.bind_all("<MouseWheel>", self.wheel)
        root.bind_all("<Button-4>", self.wheel)
        root.bind_all("<Button-5>", self.wheel)

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
        self.menu.configure(bg=P["panel"], fg=P["fg"], activebackground=P["accent"],
                            activeforeground="#ffffff", bd=0, relief="flat")
        self.entry.restyle()
        titlebar(self.root, P["dark"])
        self.side.redraw()
        self.lst.redraw()
        for p in self.pops.values():
            p.retheme()

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
        time.sleep(0.4)
        self.save()
        self.root.destroy()

    # ---- adding links ----
    def say(self, text):
        self.note, self.note_until = text, time.time() + 6

    def urls_in(self, text):
        return list(dict.fromkeys(re.findall(r'https?://[^\s<>"\']+', text)))

    def add_many(self, urls, auto=False):
        new = []
        for u in urls:
            if not any(j.url == u for j in JOBS):
                m = is_media(u)
                j = Job(u, CFG["folder"], m)
                if m:
                    j.fmt, j.audio, j.mp3 = default_choice()
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
            messagebox.showerror("Video", "yt-dlp is not included in this build.")
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
        j = Job(url, CFG["folder"], True)
        j.fmt, j.audio, j.mp3 = opt["fmt"], opt["audio"], opt["mp3"]
        j.name = clean(info.get("title") or j.name) + (".mp3" if opt["mp3"] else
                                                       ".m4a" if opt["audio"] else ".mp4")
        JOBS.append(j)
        self.save()
        if start:
            self.start([j])

    def add(self):
        self.offer(self.urls_in(self.entry.value()))
        self.entry.clear()

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

    def drag(self, on):
        if on != self.lst.drop:
            self.lst.drop = on
            self.lst.redraw()
        return "copy"

    def on_drop(self, e):
        self.drag(False)
        urls = []
        for item in self.root.tk.splitlist(e.data):
            if os.path.isfile(item):
                if os.path.splitext(item)[1].lower() in (".txt", ".url", ".lst", ".csv", ".html", ".htm"):
                    try:
                        with open(item, encoding="utf-8", errors="ignore") as f:
                            urls += self.urls_in(f.read(2_000_000))
                    except OSError:
                        pass
            else:
                urls += self.urls_in(item)
        if not urls:
            urls = self.urls_in(e.data)
        self.offer(urls, start=True)
        return "copy"

    # ---- list ops ----
    def match(self, j):
        f = self.flt
        if f == "all":
            return True
        if f == "unfinished":
            return j.status != "Done"
        if f == "completed":
            return j.status == "Done"
        return j.cat == f[2:]

    def set_filter(self, key):
        self.flt = key
        self.lst.sel.clear()
        self.lst.off = 0
        self.lst.set_jobs([j for j in JOBS if self.match(j)])

    def selected(self):
        return self.lst.selected()

    def start(self, jobs=None):
        for j in (jobs if jobs is not None else (self.selected() or JOBS)):
            if j.status in ("Queued", "Paused") or j.status.startswith("Error"):
                j.status = "Waiting"

    def pause_jobs(self, jobs):
        for j in jobs:
            if j.status != "Done":
                j.stop.set()
                if j.status == "Waiting":
                    j.status = "Paused"
        self.save()

    def pause(self):
        self.pause_jobs(self.selected() or JOBS)

    def remove(self, files=False):
        sel = self.selected()
        if files and sel and not messagebox.askyesno(
                "Delete", f"Delete {len(sel)} file(s) from disk too?"):
            return
        for j in sel:
            j.stop.set()
            if j.path:
                victim = j.path + ".part" if j.status != "Done" else (j.path if files else None)
                try:
                    victim and os.remove(victim)
                except OSError:
                    pass
            if j.id in self.pops:
                self.pops[j.id].hide()
            JOBS.remove(j)
        self.save()

    def clear(self):
        for j in [j for j in JOBS if j.status == "Done"]:
            JOBS.remove(j)
        self.save()

    def redo(self):
        for j in self.selected():
            if j.status not in RUNNING:
                if j.path and j.status != "Done":
                    try:
                        os.remove(j.path + ".part")
                    except OSError:
                        pass
                j.segs, j.path, j.speed = [], "", 0.0
                j.status = "Waiting"

    def openf(self):
        s = self.selected()
        if s and s[0].path and os.path.exists(s[0].path):
            open_path(s[0].path, select=True)
        else:
            open_path(s[0].dir if s else CFG["folder"])

    def open_file(self):
        s = self.selected()
        if s and s[0].status == "Done" and os.path.exists(s[0].path):
            open_path(s[0].path)

    def copy_link(self):
        s = self.selected()
        if s:
            t = "\n".join(j.url for j in s)
            self.root.clipboard_clear()
            self.root.clipboard_append(t)
            self.last_clip = t

    def show_pop(self):
        for j in self.selected()[:3]:
            self.open_pop(j)

    def open_pop(self, j):
        if j.id in self.pops:
            self.pops[j.id].lift()
            return
        while len(self.pops) >= 4:
            old = next((p for p in self.pops.values() if p.job.status not in RUNNING), None)
            if not old:
                return
            old.hide()
        self.pops[j.id] = Pop(self, j)

    def row_action(self, act, jid):
        j = next((x for x in JOBS if x.id == jid), None)
        if not j:
            return
        if act == "pause":
            self.pause_jobs([j])
        elif act == "start":
            self.start([j])
        elif act == "open":
            open_path(j.path)
        elif act == "folder":
            open_path(j.path, select=True) if j.path else open_path(j.folder)
        elif act == "details":
            self.open_pop(j)

    def dbl(self, j):
        if j.status == "Done" and os.path.exists(j.path):
            open_path(j.path)
        elif j.status in RUNNING:
            self.open_pop(j)
        else:
            self.start([j])

    def wheel(self, e):
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if w is self.lst:
            d = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
            self.lst.scroll_px(d * self.lst.RH // 2)

    # ---- settings ----
    def settings(self):
        w = tk.Toplevel(self.root)
        w.title("Settings")
        w.transient(self.root)
        w.resizable(False, False)
        w.configure(bg=P["bg"])
        f = ttk.Frame(w, padding=S(18))
        f.pack()
        vs = {}

        def section(r, text):
            ttk.Label(f, text=text, font=(FONT, 10, "bold")).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(S(12) if r else 0, S(4)))

        def field(r, label, key, width=40):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=S(3), padx=(0, S(14)))
            vs[key] = tk.StringVar(value=str(CFG[key]))
            e = ttk.Entry(f, textvariable=vs[key], width=width)
            e.grid(row=r, column=1, sticky="we")
            return e

        def check(r, label, key):
            vs[key] = tk.BooleanVar(value=CFG[key])
            ttk.Checkbutton(f, text=label, variable=vs[key]).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=S(2))

        section(0, "General")
        field(1, "Download folder", "folder")
        ttk.Button(f, text="...", width=3, command=lambda: vs["folder"].set(
            filedialog.askdirectory() or vs["folder"].get())).grid(row=1, column=2, padx=(S(6), 0))
        check(2, "Sort files into category folders (Video, Music, ...)", "subfolders")
        check(3, "Show a progress window when a download starts", "popup")
        check(4, "Play a sound when a download completes", "sound")
        ttk.Label(f, text="Theme").grid(row=5, column=0, sticky="w", pady=S(3))
        vs["theme"] = tk.StringVar(value=CFG["theme"].capitalize())
        ttk.Combobox(f, textvariable=vs["theme"], state="readonly", width=12,
                     values=["System", "Light", "Dark"]).grid(row=5, column=1, sticky="w")
        vs["startup"] = tk.BooleanVar(value=False)
        if WIN and getattr(sys, "frozen", False):
            ttk.Checkbutton(f, text="Start MyDM with Windows (needed for scheduled downloads)",
                            variable=vs["startup"]).grid(row=6, column=0, columnspan=3, sticky="w")
        section(7, "Connection")
        field(8, "Segments per file (1-32)", "segments", 8)
        field(9, "Parallel downloads (1-10)", "parallel", 8)
        field(10, "Speed limit KB/s (0 = unlimited)", "limit_kb", 8)
        modes = {"system": "System proxy (automatic)", "direct": "No proxy", "manual": "Manual"}
        ttk.Label(f, text="Proxy").grid(row=11, column=0, sticky="w", pady=S(3))
        vs["mode"] = tk.StringVar(value=modes[CFG["proxy_mode"]])
        cb = ttk.Combobox(f, textvariable=vs["mode"], state="readonly", width=26,
                          values=list(modes.values()))
        cb.grid(row=11, column=1, sticky="w")
        sysp = system_proxy()
        ttk.Label(f, style="Sub.TLabel", text="System proxy detected: " + (sysp or "none")
                  ).grid(row=12, column=1, sticky="w")
        pe = field(13, "Manual proxy (http://host:port or socks5://host:port)", "proxy")
        section(14, "Clipboard")
        check(15, "Watch clipboard for download links", "watch")
        check(16, "Start automatically when links are caught", "autostart")
        section(17, "Videos (YouTube and other sites)")
        ttk.Label(f, text="Default quality").grid(row=18, column=0, sticky="w", pady=S(3))
        vs["ytq"] = tk.StringVar(value=CFG["ytq"])
        ttk.Combobox(f, textvariable=vs["ytq"], state="readonly", width=14,
                     values=["Best", "1080p", "720p", "480p", "360p", "Audio (MP3)"]).grid(
            row=18, column=1, sticky="w")
        ttk.Label(f, text="Browser cookies").grid(row=19, column=0, sticky="w", pady=S(3))
        vs["cookies"] = tk.StringVar(value=CFG["cookies"] or "none")
        ttk.Combobox(f, textvariable=vs["cookies"], state="readonly", width=14,
                     values=["none", "firefox", "edge", "chrome", "brave"]).grid(
            row=19, column=1, sticky="w")
        check(20, "Offer a video download for video links copied to the clipboard", "watch_media")
        ttk.Label(f, style="Sub.TLabel", wraplength=S(430), text=self.video_status()).grid(
            row=21, column=0, columnspan=3, sticky="w", pady=(S(4), 0))

        def ok():
            try:
                seg = min(32, max(1, int(vs["segments"].get())))
                par = min(10, max(1, int(vs["parallel"].get())))
                lim = max(0, int(vs["limit_kb"].get()))
            except ValueError:
                messagebox.showerror("Settings", "Numeric fields must be numbers.")
                return
            CFG.update(segments=seg, parallel=par, limit_kb=lim,
                       folder=vs["folder"].get().strip() or CFG["folder"],
                       proxy=vs["proxy"].get().strip(), theme=vs["theme"].get().lower(),
                       proxy_mode=next(k for k, v in modes.items() if v == vs["mode"].get()),
                       subfolders=vs["subfolders"].get(), popup=vs["popup"].get(),
                       sound=vs["sound"].get(), watch=vs["watch"].get(),
                       autostart=vs["autostart"].get(), ytq=vs["ytq"].get(),
                       cookies="" if vs["cookies"].get() == "none" else vs["cookies"].get(),
                       watch_media=vs["watch_media"].get())
            if WIN and getattr(sys, "frozen", False):
                set_startup(vs["startup"].get())
            self.save()
            self.retheme()
            w.destroy()

        row = ttk.Frame(f)
        row.grid(row=22, column=0, columnspan=3, sticky="e", pady=(S(16), 0))
        ttk.Button(row, text="Cancel", command=w.destroy).pack(side="left", padx=6)
        ttk.Button(row, text="Save", style="Accent.TButton", command=ok).pack(side="left")
        self.place_dialog(w)

    def video_status(self):
        y = ytdlp()
        if not y:
            return "Video downloads: yt-dlp is missing in this build."
        v = getattr(getattr(y, "version", None), "__version__", "?")
        js = res_path("qjs.exe" if WIN else "qjs") or shutil.which("deno")
        return (f"yt-dlp {v}   |   ffmpeg: {'ok' if ffmpeg_path() else 'missing'}   |   "
                f"JS engine: {'ok' if js else 'missing (YouTube may fail)'}")

    def place_dialog(self, w):
        w.update_idletasks()
        r = self.root
        w.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - w.winfo_reqwidth()) // 2)}"
                   f"+{r.winfo_rooty() + S(50)}")
        titlebar(w, P["dark"])
        w.grab_set()

    # ---- scheduler ----
    def scheduler(self):
        s = CFG["sched"]
        w = tk.Toplevel(self.root)
        w.title("Scheduler")
        w.transient(self.root)
        w.resizable(False, False)
        w.configure(bg=P["bg"])
        f = ttk.Frame(w, padding=S(18))
        f.pack()
        ttk.Label(f, text="Scheduler", font=(FONT, 13, "bold")).grid(row=0, column=0, columnspan=4,
                                                                    sticky="w", pady=(0, S(10)))
        v = {k: tk.BooleanVar(value=s[k]) for k in ("start_on", "stop_on", "daily", "on_finish")}
        tv = {}

        def time_row(r, label, key, onkey):
            ttk.Checkbutton(f, text=label, variable=v[onkey]).grid(row=r, column=0, sticky="w", pady=S(5))
            hh, mm = s[key].split(":")
            h = tk.StringVar(value=hh)
            m = tk.StringVar(value=mm)
            ttk.Spinbox(f, from_=0, to=23, width=3, wrap=True, format="%02.0f",
                        textvariable=h).grid(row=r, column=1, padx=(S(12), 0))
            ttk.Label(f, text=":").grid(row=r, column=2)
            ttk.Spinbox(f, from_=0, to=59, width=3, wrap=True, format="%02.0f",
                        textvariable=m).grid(row=r, column=3)
            tv[key] = (h, m)

        time_row(1, "Start downloads at", "start", "start_on")
        time_row(2, "Stop downloads at", "stop", "stop_on")
        ttk.Checkbutton(f, text="Repeat every day", variable=v["daily"]).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=S(5))
        ttk.Label(f, text="When the stop time arrives, or all\ndownloads finish, do this:").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(S(10), S(4)))
        act = tk.StringVar(value=s["action"])
        ttk.Combobox(f, textvariable=act, values=ACTIONS, state="readonly", width=30).grid(
            row=5, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(f, text="Also do it when all downloads finish", variable=v["on_finish"]
                        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=S(8))
        ttk.Label(f, style="Sub.TLabel", wraplength=S(360), justify="left",
                  text="MyDM must be running and the PC awake at the start time. Power actions "
                       "show a 30 second countdown you can cancel.").grid(
            row=7, column=0, columnspan=4, sticky="w")

        def ok():
            for k in ("start", "stop"):
                h, m = tv[k]
                try:
                    s[k] = f"{min(23, max(0, int(h.get()))):02d}:{min(59, max(0, int(m.get()))):02d}"
                except ValueError:
                    pass
            for k in v:
                s[k] = v[k].get()
            s["action"] = act.get()
            self.fired.clear()
            self.save()
            w.destroy()

        row = ttk.Frame(f)
        row.grid(row=8, column=0, columnspan=4, sticky="e", pady=(S(16), 0))
        ttk.Button(row, text="Cancel", command=w.destroy).pack(side="left", padx=6)
        ttk.Button(row, text="Save", style="Accent.TButton", command=ok).pack(side="left")
        self.place_dialog(w)

    def sched_summary(self):
        s, parts = CFG["sched"], []
        if s["start_on"]:
            parts.append("start " + s["start"])
        if s["stop_on"]:
            parts.append("stop " + s["stop"])
        if s["action"] != "Do nothing" and (s["stop_on"] or s["on_finish"]):
            parts.append("then " + s["action"].lower())
        return ("\u23f0 " + ", ".join(parts)) if parts else ""

    def run_action(self, action, why):
        if action == "Do nothing":
            return
        self.save()
        if action == "Exit MyDM":
            self.close()
        elif action == "Lock screen":
            cmd = power_cmd(action)
            cmd and subprocess.Popen(cmd, creationflags=0x08000000 if WIN else 0)
        else:
            Countdown(self, action, why)

    def sched_check(self):
        s = CFG["sched"]
        n = datetime.now()
        hm, today = n.strftime("%H:%M"), n.strftime("%Y%m%d")
        if s["start_on"] and hm == s["start"] and self.fired.get("start") != today:
            self.fired["start"] = today
            jobs = [j for j in JOBS if j.status != "Done"]
            self.start(jobs)
            self.say(f"Scheduler: started {len(jobs)} download(s)")
            if not s["daily"]:
                s["start_on"] = False
                self.save()
        if s["stop_on"] and hm == s["stop"] and self.fired.get("stop") != today:
            self.fired["stop"] = today
            self.pause_jobs([j for j in JOBS if j.status in RUNNING])
            self.say("Scheduler: stopped downloads")
            self.pending = (s["action"], "Scheduled stop time reached")
            if not s["daily"]:
                s["stop_on"] = False
                self.save()

    # ---- main loop ----
    def tick(self):
        if self.closing:
            return
        now = time.monotonic()
        self.ticks += 1
        self.sched_check()
        active = [j for j in JOBS if j.status in ("Connecting", "Downloading")]
        for j in JOBS:
            if j.status == "Waiting" and len(active) < CFG["parallel"]:
                j.status = "Connecting"
                j.stop.clear()
                j.speed, j.hist, j.last = 0.0, [], (now, j.done)
                self.session.add(j.id)
                threading.Thread(target=j.run, daemon=True).start()
                active.append(j)
                shown = sum(1 for p in self.pops.values() if p.job.status in RUNNING)
                if CFG["popup"] and shown < 3:
                    self.open_pop(j)

        if CFG["watch"]:
            try:
                t = self.root.clipboard_get()
            except tk.TclError:
                t = ""
            if t and t != self.last_clip:
                self.last_clip = t
                urls = self.urls_in(t)
                known = [u for u in urls if os.path.splitext(urlparse(u).path)[1].lstrip(".").lower() in EXTS]
                if len(urls) == 1 and known:
                    self.add_many(known, auto=CFG["autostart"])
                elif len(urls) == 1 and CFG["watch_media"] and is_media(urls[0]):
                    self.media_flow(urls[0])
                elif len(urls) > 1:
                    if CFG["autostart"]:
                        self.add_many(urls, auto=True)
                    else:
                        BatchDialog(self, urls, False)

        if self.ticks % 10 == 0 and CFG["theme"] == "system" and system_dark() != P["dark"]:
            self.retheme()

        total_speed = 0.0
        counts = {k: 0 for k in ["all", "unfinished", "completed"] + ["c:" + c for c in CAT_LIST]}
        for j in JOBS:
            d = j.done
            t0, d0 = j.last
            if j.status == "Downloading":
                if now - t0 >= 1:
                    j.speed, j.last = max(0.0, (d - d0) / (now - t0)), (now, d)
                    j.hist = (j.hist + [j.speed])[-120:]
            else:
                j.speed = 0.0
            total_speed += j.speed
            counts["all"] += 1
            counts["completed" if j.status == "Done" else "unfinished"] += 1
            counts["c:" + j.cat] += 1
            if j.status != j.prev:
                if j.status == "Done" and CFG["sound"]:
                    try:
                        import winsound
                        winsound.MessageBeep()
                    except Exception:
                        self.root.bell()
                j.prev = j.status
        self.side.set_counts(counts)
        self.lst.set_jobs([j for j in JOBS if self.match(j)])
        for jid, p in list(self.pops.items()):
            try:
                p.refresh()
            except tk.TclError:
                self.pops.pop(jid, None)

        busy = any(j.status in RUNNING for j in JOBS)
        if not busy and self.session:
            mine = [j for j in JOBS if j.id in self.session]
            self.session.clear()
            s = CFG["sched"]
            if mine and all(j.status == "Done" for j in mine) and s["on_finish"] \
                    and s["action"] != "Do nothing":
                self.pending = (s["action"], "All downloads finished")
                if not (s["start_on"] or s["stop_on"]):
                    s["on_finish"] = False
                    self.save()
        if self.pending and not busy:
            act, why = self.pending
            self.pending = None
            self.run_action(act, why)

        info = f"{len(active)} active   |   {human(total_speed)}/s   |   {len(JOBS)} item(s)"
        if time.time() < self.note_until:
            info += "   -   " + self.note
        self.status.set(info)
        self.sched_txt.set(self.sched_summary())
        if self.ticks % 10 == 0:
            self.save()
        self.root.after(500, self.tick)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        root = BaseTk()
    except Exception:          # drag-and-drop library failed to load
        TkinterDnD = None
        root = tk.Tk()
    SC = max(1.0, root.winfo_fpixels("1i") / 96)
    App(root)
    root.mainloop()
