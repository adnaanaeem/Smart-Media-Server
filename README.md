# 🎬 Smart Movies Server

A lightweight, Python-based tool to share your movie collection over your local Wi-Fi network with a Netflix-style interface.

![Screenshot](https://github.com/user-attachments/assets/bb18ea20-3d80-4ffb-b03f-600e461e25ba)

![Screenshot](https://github.com/user-attachments/assets/2b0f5a53-a813-4634-9947-e75d54547377)

![Screenshot](https://github.com/user-attachments/assets/7ecf64fe-1508-4085-a073-c7a3686a991b)

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

```pyinstaller --noconsole --onefile --icon=static/favicon.ico --name="Smart Movies Server" --add-data "templates;templates" --add-data "static;static" movies_server.py```

📄 License
This project is open-source under the MIT License.