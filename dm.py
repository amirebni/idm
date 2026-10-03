import os, re, sys, json, time, threading, subprocess
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse, unquote
import requests

DATA = Path.home() / ".mydm"
STATE = DATA / "state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
EXTS = set("zip rar 7z tar gz bz2 xz iso exe msi dmg pkg apk deb rpm mp4 mkv avi mov "
           "wmv flv webm ts mp3 flac wav aac ogg m4a pdf epub docx xlsx pptx torrent "
           "bin img".split())
CFG = {"folder": str(Path.home() / "Downloads"), "segments": 8, "parallel": 3,
       "limit_kb": 0, "proxy": "", "watch": True, "autostart": False}
JOBS = []


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def clean(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "file"


def unique(folder, name, taken):
    base, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 1
    while os.path.exists(p) or os.path.exists(p + ".part") or p in taken:
        p = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return p


def proxies():
    p = CFG["proxy"].strip()
    if not p:
        return None
    if "://" not in p:
        p = "http://" + p
    return {"http": p, "https": p}


def open_path(p):
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


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
    KEYS = ("url", "folder", "name", "path", "total", "ranged", "segs", "status")

    def __init__(self, url, folder):
        self.url, self.folder = url, folder
        self.name = clean(unquote(os.path.basename(urlparse(url).path)))
        self.path, self.total, self.ranged, self.segs = "", 0, False, []
        self.status, self.err = "Queued", None
        self.stop = threading.Event()
        self.id = os.urandom(4).hex()
        self.speed = 0.0
        self.last = (time.monotonic(), 0)

    @property
    def done(self):
        return sum(max(0, min(p, e + 1) - s) for s, e, p in self.segs)

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
        return j

    def probe(self):
        r = requests.get(self.url, headers={**UA, "Range": "bytes=0-0"}, stream=True,
                         timeout=30, proxies=proxies())
        try:
            r.raise_for_status()
            cr = r.headers.get("Content-Range", "")
            if r.status_code == 206 and cr.split("/")[-1].isdigit():
                total, ranged = int(cr.split("/")[-1]), True
            else:
                total, ranged = int(r.headers.get("Content-Length") or 0), False
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)',
                          r.headers.get("Content-Disposition", ""), re.I)
            return total, ranged, (clean(unquote(m.group(1))) if m else None)
        finally:
            r.close()

    def run(self):
        try:
            self.err = None
            total, ranged, name = self.probe()
            part = self.path + ".part"
            resume = bool(self.segs and self.ranged and ranged and total == self.total
                          and self.path and os.path.exists(part))
            if not resume:
                if self.path and os.path.exists(part):
                    os.remove(part)
                self.name = name or self.name
                taken = {j.path for j in JOBS if j is not self}
                os.makedirs(self.folder, exist_ok=True)
                self.path = unique(self.folder, self.name, taken)
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
            self.status = "Error: " + str(ex)[:60]

    def seg(self, s):
        tries = 0
        while not self.stop.is_set() and s[2] <= s[1]:
            before = s[2]
            try:
                h = {**UA, "Range": f"bytes={s[2]}-{s[1]}"}
                with requests.get(self.url, headers=h, stream=True, timeout=30,
                                  proxies=proxies()) as r:
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
        with requests.get(self.url, headers=UA, stream=True, timeout=30,
                          proxies=proxies()) as r:
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


class App:
    def __init__(self, root):
        self.root = root
        root.title("MyDM - Download Manager")
        root.geometry("1020x540")
        self.last_clip, self.note, self.note_until, self.ticks = "", "", 0, 0
        self.load()
        try:
            self.last_clip = root.clipboard_get()
        except tk.TclError:
            pass

        top = ttk.Frame(root)
        top.pack(fill="x", padx=6, pady=(6, 2))
        self.entry = ttk.Entry(top)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.add())
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=6, pady=2)
        for t, c in [("Add", self.add), ("Paste", self.paste), ("Import TXT", self.imp),
                     ("Export TXT", self.exp), ("Start", self.start), ("Pause", self.pause),
                     ("Remove", self.remove), ("Clear done", self.clear),
                     ("Open folder", self.openf), ("Settings", self.settings)]:
            ttk.Button(bar, text=t, command=c).pack(side="left", padx=1)

        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, padx=6, pady=4)
        cols = [("size", "Size", 90), ("prog", "Progress", 80), ("speed", "Speed", 90),
                ("eta", "ETA", 80), ("status", "Status", 200)]
        self.tv = ttk.Treeview(mid, columns=[c[0] for c in cols], show="tree headings",
                               selectmode="extended")
        self.tv.heading("#0", text="Name")
        self.tv.column("#0", width=380)
        for k, t, w in cols:
            self.tv.heading(k, text=t)
            self.tv.column(k, width=w, anchor="w")
        sb = ttk.Scrollbar(mid, command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-1>", self.dbl)
        self.tv.bind("<Delete>", lambda e: self.remove())
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status).pack(fill="x", padx=8, pady=(0, 4))

        for j in JOBS:
            self.insert(j)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    # ---- state ----
    def load(self):
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            CFG.update(d.get("cfg", {}))
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
        for j in JOBS:
            j.stop.set()
        time.sleep(0.4)
        self.save()
        self.root.destroy()

    # ---- list ops ----
    def say(self, text):
        self.note, self.note_until = text, time.time() + 6

    def urls_in(self, text):
        return re.findall(r'https?://[^\s<>"\']+', text)

    def insert(self, j):
        self.tv.insert("", "end", iid=j.id, text=j.name, values=("", "", "", "", j.status))

    def add_url(self, u):
        if any(j.url == u for j in JOBS):
            return None
        j = Job(u, CFG["folder"])
        JOBS.append(j)
        self.insert(j)
        return j

    def add_many(self, urls, auto=False):
        new = [j for j in (self.add_url(u) for u in urls) if j]
        self.say(f"{len(new)} new link(s) added" if urls else "No valid link found")
        if new:
            self.save()
            if auto:
                self.start(new)
        return new

    def selected(self):
        s = set(self.tv.selection())
        return [j for j in JOBS if j.id in s]

    def add(self):
        self.add_many(self.urls_in(self.entry.get()))
        self.entry.delete(0, "end")

    def paste(self):
        try:
            self.add_many(self.urls_in(self.root.clipboard_get()))
        except tk.TclError:
            self.say("Clipboard is empty")

    def imp(self):
        p = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            with open(p, encoding="utf-8", errors="ignore") as f:
                self.add_many(self.urls_in(f.read()))

    def exp(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if not p:
            return
        only = messagebox.askyesno("Export", "Export only unfinished links?\n(No = all links)")
        urls = [j.url for j in JOBS if not only or j.status != "Done"]
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(urls))
        self.say(f"{len(urls)} link(s) exported")

    def start(self, jobs=None):
        for j in (jobs if jobs is not None else (self.selected() or JOBS)):
            if j.status in ("Queued", "Paused") or j.status.startswith("Error"):
                j.status = "Waiting"

    def pause(self):
        for j in (self.selected() or JOBS):
            if j.status != "Done":
                j.stop.set()
                if j.status == "Waiting":
                    j.status = "Paused"
        self.save()

    def remove(self):
        for j in self.selected():
            j.stop.set()
            if j.status != "Done" and j.path:
                try:
                    os.remove(j.path + ".part")
                except OSError:
                    pass
            JOBS.remove(j)
            self.tv.delete(j.id)
        self.save()

    def clear(self):
        for j in [j for j in JOBS if j.status == "Done"]:
            JOBS.remove(j)
            self.tv.delete(j.id)
        self.save()

    def openf(self):
        s = self.selected()
        open_path(os.path.dirname(s[0].path) if s and s[0].path else CFG["folder"])

    def dbl(self, _):
        s = self.selected()
        if s:
            j = s[0]
            if j.status == "Done" and os.path.exists(j.path):
                open_path(j.path)
            else:
                open_path(j.folder)

    # ---- settings ----
    def settings(self):
        w = tk.Toplevel(self.root)
        w.title("Settings")
        w.transient(self.root)
        w.resizable(False, False)
        fields = [("Download folder", "folder"), ("Segments per file (1-32)", "segments"),
                  ("Parallel downloads (1-10)", "parallel"),
                  ("Speed limit KB/s (0 = unlimited)", "limit_kb"),
                  ("Proxy (http://host:port or socks5://host:port)", "proxy")]
        vs = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(w, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            vs[key] = tk.StringVar(value=str(CFG[key]))
            ttk.Entry(w, textvariable=vs[key], width=46).grid(row=i, column=1, padx=8, pady=4)
        ttk.Button(w, text="...", width=3, command=lambda: vs["folder"].set(
            filedialog.askdirectory() or vs["folder"].get())).grid(row=0, column=2, padx=(0, 8))
        bw, ba = tk.BooleanVar(value=CFG["watch"]), tk.BooleanVar(value=CFG["autostart"])
        ttk.Checkbutton(w, text="Watch clipboard for download links", variable=bw
                        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8)
        ttk.Checkbutton(w, text="Start automatically when a link is caught from clipboard",
                        variable=ba).grid(row=6, column=0, columnspan=2, sticky="w", padx=8)

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
                       proxy=vs["proxy"].get().strip(), watch=bw.get(), autostart=ba.get())
            self.save()
            w.destroy()

        ttk.Button(w, text="Save", command=ok).grid(row=7, column=1, sticky="e", padx=8, pady=8)

    # ---- main loop ----
    def tick(self):
        now = time.monotonic()
        self.ticks += 1
        active = [j for j in JOBS if j.status in ("Connecting", "Downloading")]
        for j in JOBS:
            if j.status == "Waiting" and len(active) < CFG["parallel"]:
                j.status = "Connecting"
                j.stop.clear()
                j.speed, j.last = 0.0, (now, j.done)
                threading.Thread(target=j.run, daemon=True).start()
                active.append(j)

        if CFG["watch"]:
            try:
                t = self.root.clipboard_get()
            except tk.TclError:
                t = ""
            if t and t != self.last_clip:
                self.last_clip = t
                urls = [u for u in self.urls_in(t) if os.path.splitext(
                    urlparse(u).path)[1].lstrip(".").lower() in EXTS]
                if urls:
                    self.add_many(urls, auto=CFG["autostart"])

        total_speed = 0.0
        for j in JOBS:
            d = j.done
            t0, d0 = j.last
            if j.status == "Downloading":
                if now - t0 >= 1:
                    j.speed, j.last = max(0.0, (d - d0) / (now - t0)), (now, d)
            else:
                j.speed = 0.0
            total_speed += j.speed
            if j.status == "Done":
                pct = "100%"
            else:
                pct = f"{d * 100 // j.total}%" if j.total else ""
            eta = ""
            if j.speed > 1 and j.total:
                s = int((j.total - d) / j.speed)
                eta = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
            try:
                self.tv.item(j.id, text=j.name, values=(
                    human(j.total) if j.total else "?", pct,
                    f"{human(j.speed)}/s" if j.speed else "", eta, j.status))
            except tk.TclError:
                pass
        info = f"{len(active)} active | {human(total_speed)}/s | {len(JOBS)} item(s)"
        if time.time() < self.note_until:
            info += "   -   " + self.note
        self.status.set(info)
        if self.ticks % 10 == 0:
            self.save()
        self.root.after(500, self.tick)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
