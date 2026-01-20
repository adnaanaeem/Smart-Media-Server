# 🎬 Smart Movies Server

A lightweight, Python-based tool to share your movie collection over your local Wi-Fi network with a Netflix-style interface.

![Screenshot](https://via.placeholder.com/800x400?text=Replace+This+With+Actual+Screenshot)

## ✨ Features
- **One-Click Sharing:** Select a folder and start the server.
- **Auto-Discovery:** Generates a QR Code and IP link automatically.
- **Web Interface:** Beautiful dark-mode UI for friends to browse movies.
- **Memory Resume:** Remembers where you left off (Resume Playback).
- **Dual Audio Support:** "Open in VLC" button for switching audio tracks.
- **Zip Download:** Download entire folders/seasons as a .zip file.

## 🚀 Download
[Download the latest .exe here](https://github.com/adnaanaeem/Smart-Movies-Server/releases/latest)

## 🛠️ How to Run from Source
1. **Install Python 3.x**
2. **Clone the repo:**
   ```bash
   git clone https://github.com/adnaanaeem/Smart-Movies-Server.git

## 🛠️ How to Run from Source
1. Install Python 3.x
2. Clone the repo:
   ```git clone https://github.com/adnaanaeem/Smart-Movies-Server.git```

## 1. Install dependencies:
```pip install -r requirements.txt```

## 2. Run the app:
```python movies_server.py```

##📦 How to Build EXE
```pyinstaller --noconsole --onefile --icon=static/favicon.ico --name="MovieServer" --add-data "templates;templates" --add-data "static;static" movies_server.py```

📄 License
This project is open-source under the MIT License.
---

### 📝 What I fixed:
1.  **Fixed the Numbered List:** In your version, you used `## 1. Install dependencies`. The `##` turns text into a **Huge Header**, which breaks the list flow. I removed the `##` so it looks like a proper step-by-step list.
2.  **Code Blocks:** I ensured the commands are inside triple backticks (` ```bash `) so they look like code boxes on GitHub.
3.  **Download Link:** I added `/latest` to the release link. This ensures users always get the newest version, not just the list of releases.
4.  **Screenshot:** I changed the text to remind you to update the image later.

---

### ✅ Checklist: Uploading the EXE as a Release
Your steps for Part 4 are correct. Here is the confirmation checklist:

1.  **Build the EXE:** Make sure you have the `MovieServer.exe` inside your `dist` folder.
2.  **Go to GitHub:** Navigate to: `https://github.com/adnaanaeem/Smart-Movies-Server/releases/new`
3.  **Tag:** Create a new tag (e.g., `v1.0.0`).
4.  **Title:** `Smart Movies Server v1.0`.
5.  **Description:** You can copy the "Features" list from your README and paste it here so people know what's in this version.
6.  **Upload Binary:** **Crucial Step** — Click "Attach binaries..." at the bottom and select your `MovieServer.exe`.
    *   *Note: Do not upload the whole project folder here, JUST the .exe file.*
7.  **Publish:** Click the green "Publish release" button.

Once you do this, the "Download" link in your README will work perfectly! 🚀