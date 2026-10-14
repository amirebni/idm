# MyDM

[فارسی](README.fa.md) | English

A personal IDM-style download manager for Windows (Python + tkinter) with a Chrome/Edge extension.
Project page: https://github.com/amirebni/idm

## Features

**Downloading**
- Multi-segment downloads (1-32 segments) with resume, `.part` files and a speed limit
- Parallel downloads queue, retry, "Download again"
- **Change link...** for a half-finished download: paste a new URL (links expire) and continue from where it stopped
- Categories (Compressed, Document, Music, Program, Video) with optional category folders
- Proxy: system (automatic), none, or manual (http / socks5)
- Scheduler: start/stop at a time, shutdown / sleep / hibernate / close when finished

**Video and streams**
- YouTube, Aparat, Varzesh3 and many more through yt-dlp, with a quality picker and approximate sizes (marked with `≈`)
- HLS / DASH streams through ffmpeg
- YouTube "confirm you're not a bot": the extension sends your login cookies, or use a cookies.txt / Firefox cookies
- "Download now" or "Add to list" window, Force IPv4 option

**Adding links**
- Add URL, several links at once (batch dialog), import/export of link lists (text)
- Drag and drop links from the browser
- Clipboard watcher: ask first (default) or add automatically

**Browser extension (Chrome / Edge, Manifest V3)**
- Download bar over playing video/audio; on YouTube / Aparat / streams it lists the qualities with approximate sizes right in the page, and only the one you click is sent to MyDM
- Right-click "Download with MyDM" on links and on selected text (every URL in the selection)
- Sends referer, cookies and user agent to the app

**Browser downloads and tray**
- The extension takes over the browser's own downloads (switch it off in the extension popup): the browser's download is cancelled and MyDM downloads the file instead. If MyDM is not running or refuses, the browser downloads as usual.
- Windows from the browser (quality list, progress, extension permission) appear in front of the browser, even when MyDM is hidden.
- The X button hides MyDM in the notification area (next to the clock); left-click the icon to open it, right-click for Open / Exit. Turn it off in Settings > General. A second start of MyDM just shows the running one.

**Interface**
- Table UI: menu bar, toolbar, search, category + queue sidebar, status bar
- The download progress window is compact (name, percent, bar, buttons); click *Details* to open the connections, speed graph and file info (the choice is remembered)
- Light / dark / system theme, compact or comfortable rows
- Resizable windows, columns (drag header edges) and sidebar (drag the splitter); sizes are remembered; View > Reset layout
- Settings tabs: General, Connection, Browser, Video, About
- About tab: version, short description, GitHub link and **Check for updates**

## Security, privacy and logs
- **Pairing:** the extension talks to MyDM over `127.0.0.1` only, and every request carries a secret token. The first time, MyDM shows a window asking you to allow the extension. Settings > Browser > *Reset extension pairing* makes the old token invalid.
- **Cookies:** the login cookies of the video site (YouTube...) are only sent while you download a video, can be switched off in Settings > Video, and the file is deleted automatically about 10 minutes after the last video download (and when MyDM closes, if no video download is unfinished).
- **Log:** errors and download failures are written to `%USERPROFILE%\.mydm\logs\app.log` (Help > *Open log folder*). Attach it when reporting a problem.

## Run from source
```sh
pip install "requests[socks]" tkinterdnd2
python dm.py
```
For video sites put the `yt-dlp` file, `ffmpeg.exe` and `qjs.exe` next to `dm.py` (the installer does this for you).

## Build the Windows installer
1. Push the repository to GitHub. `.github/workflows/build.yml` builds the installer with PyInstaller + Inno Setup and uploads two artifacts: `MyDM-Setup-vX` and `MyDM-Extension-vX` (the workflow also runs weekly to pick up the newest yt-dlp).
2. To publish a release (needed by **Check for updates**), push a tag:
   ```sh
   git tag v3.4
   git push origin v3.4
   ```
   The workflow attaches the installer and `MyDM_Extension.zip` to the GitHub release.

## Install the extension
Open `chrome://extensions`, enable Developer mode, choose **Load unpacked** and select the `extension` folder (the installer copies it next to the app; Settings > Browser has a button that opens it). After an update, press Reload on the extension.

## Data and settings
Everything is stored in `%USERPROFILE%\.mydm` (`state.json`, cookies, yt-dlp updates). Set `MYDM_HOME` to change the folder. The app listens only on `127.0.0.1` (ports 17890-17899) for the extension.

## Troubleshooting
- **YouTube asks to sign in**: log in to YouTube in Chrome with the extension installed, then retry. Alternatively set a cookies.txt in Settings > Video.
- **Video engine not loaded**: Settings > Video > Update video engine.
- **Extension says the app is not running**: start MyDM and keep "Accept downloads from the browser extension" ticked.
