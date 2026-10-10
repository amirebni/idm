# MyDM 2.8

Personal IDM-style download manager for Windows (Python/tkinter) with a Chrome/Edge extension.

## Features
- Multi-segment downloads with resume, speed limit, proxy (system/manual), scheduler with power actions
- Video sites through yt-dlp (YouTube, Aparat, ...), HLS/DASH streams through ffmpeg, quality picker with sizes
- Clipboard watcher (ask or add automatically), drag and drop, import/export of link lists
- Browser extension: download bar for playing media, right-click "Download with MyDM" on links and on selected text
- Table UI: menu bar, toolbar, search, categories and queue sidebar, light/dark theme, compact/comfortable rows

## Run
```sh
pip install "requests[socks]" tkinterdnd2
python dm.py
```

## Build the Windows installer
Push the repository to GitHub. `.github/workflows/build.yml` builds `MyDM_Setup_v2.8.exe` and the extension artifact.

## Install the extension
Open `chrome://extensions`, enable Developer mode, choose Load unpacked and select the `extension` folder (or Reload it after an update).
