import os
import socket
import threading
import time
import qrcode
import urllib.parse
import zipfile
import uuid
import tempfile
import re
import json
import requests
import sys
import re
from functools import wraps
from datetime import datetime
from PIL import Image, ImageTk

# UI Libraries
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk 
import pystray
from pystray import MenuItem as item

from flask import Flask, render_template, send_from_directory, send_file, abort, request, jsonify, after_this_request, session, redirect, url_for

# --- APP SETUP ---
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

app.secret_key = os.urandom(24)

# --- CONFIGURATION ---
PORT = 8000
TMDB_API_KEY = "5ca06765ae8916dfe1431ad86b05a7f4" 
SHARED_DIR = ""
SERVER_URL = ""
SERVER_PIN = ""
ZIP_JOBS = {}
CONNECTED_CLIENTS = {}
CONFIG_FILE = "settings.json"

# --- TRACKING VISITOR (FIXED: Now logs Localhost too) ---
@app.before_request
def track_visitor():
    try:
        ip = request.remote_addr
        # Get Device Info
        device = request.user_agent.platform
        if not device: device = "Browser"
        else: device = device.capitalize()
        
        # Log everyone (Removed the 127.0.0.1 filter so you can see yourself)
        CONNECTED_CLIENTS[ip] = {
            'device': device,
            'last_seen': datetime.now().strftime("%H:%M:%S")
        }
    except: pass

# --- METADATA ENGINE ---
def parse_movie_name(filename):
    name = os.path.splitext(filename)[0]
    is_tv = bool(re.search(r'\b(S\d+|Season)\b', name, re.IGNORECASE))
    match = re.search(r'\b(19|20)\d{2}\b', name)
    year = None
    if match:
        year = match.group(0)
        name = name[:match.start()]
    name = name.replace('.', ' ').replace('_', ' ').replace('(', '').replace(')', '').replace('[', '').replace(']', '')
    junk_words = ["1080p", "720p", "480p", "4k", "HDR", "Bluray", "WebRip", "x265", "AAC", "RARBG", "PSA", "YIFY"]
    for word in junk_words:
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        name = pattern.sub('', name)
    return name.strip(), year, is_tv

def get_metadata(filename, folder_path, is_folder=False):
    meta_dir = os.path.join(folder_path, ".meta")
    if not os.path.exists(meta_dir): os.makedirs(meta_dir)
    json_path = os.path.join(meta_dir, f"{filename}.json")
    
    # 1. Check Cache
    if os.path.exists(json_path):
        try: 
            with open(json_path, 'r') as f: 
                data = json.load(f)
                # If cache is old (missing backdrop), ignore it and fetch again
                if 'backdrop' in data: return data
        except: pass

    if not TMDB_API_KEY:
        return {"title": filename, "poster": None, "year": "", "overview": "", "backdrop": None}

    title, year, is_tv_guess = parse_movie_name(filename)
    is_tv = True if is_folder else is_tv_guess
    endpoint = "tv" if is_tv else "movie"
    search_url = f"https://api.themoviedb.org/3/search/{endpoint}?api_key={TMDB_API_KEY}&query={urllib.parse.quote(title)}"
    if year and not is_tv: search_url += f"&year={year}"

    try:
        response = requests.get(search_url, timeout=3).json()
        results = response.get('results')
        if results:
            media = results[0]
            
            def dl_img(path, suffix):
                if not path: return None
                try:
                    url = f"https://image.tmdb.org/t/p/w500{path}"
                    data = requests.get(url).content
                    fname = f"{filename}{suffix}.jpg"
                    with open(os.path.join(meta_dir, fname), 'wb') as f: f.write(data)
                    return f"/metadata_img/{urllib.parse.quote(os.path.relpath(os.path.join(meta_dir, fname), SHARED_DIR))}"
                except: return None

            data = {
                "title": media.get('name') if is_tv else media.get('title'),
                "year": (media.get('first_air_date') if is_tv else media.get('release_date') or "")[:4],
                "poster": dl_img(media.get('poster_path'), ""),
                "backdrop": dl_img(media.get('backdrop_path'), "_bg"),
                "rating": media.get('vote_average'),
                "overview": media.get('overview'),
                "is_tv": is_tv
            }
            with open(json_path, 'w') as f: json.dump(data, f)
            return data
    except Exception as e: print(f"Meta Error: {e}")
    
    # Fail safe
    failed = {"title": title, "poster": None, "year": year, "overview": "", "backdrop": None}
    with open(json_path, 'w') as f: json.dump(failed, f)
    return failed

def get_size_format(b):
    for unit in ["", "K", "M", "G", "T"]:
        if b < 1024: return f"{b:.1f}{unit}B"
        b /= 1024

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if SERVER_PIN and not session.get('authenticated'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ZIP TASK ---
def background_zip_task(job_id, source_dir, temp_dir):
    try:
        base_name = os.path.basename(source_dir)
        zip_path = os.path.join(temp_dir, f"{base_name}.zip")
        total_size = 0
        files_to_zip = []
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if '.meta' in root: continue
                fp = os.path.join(root, file)
                try:
                    s = os.path.getsize(fp)
                    total_size += s
                    files_to_zip.append((fp, os.path.relpath(fp, source_dir), s))
                except: pass
        processed_size = 0
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname, file_size in files_to_zip:
                z_info = zipfile.ZipInfo(filename=arcname); z_info.compress_type = zipfile.ZIP_DEFLATED
                with zf.open(z_info, mode='w') as dest_file:
                    with open(file_path, 'rb') as src_file:
                        while True:
                            chunk = src_file.read(1024 * 1024 * 10)
                            if not chunk: break
                            dest_file.write(chunk)
                            processed_size += len(chunk)
                            if total_size > 0: ZIP_JOBS[job_id]['progress'] = int((processed_size / total_size) * 100)
        ZIP_JOBS[job_id].update({'progress': 100, 'status': 'ready', 'filepath': zip_path})
    except: ZIP_JOBS[job_id]['status'] = 'error'

# --- HELPER: Settings ---
def load_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f).get("last_folder", "")
        except:
            pass
    return ""
def save_settings(path):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"last_folder": path}, f)
    except:
        pass

# --- ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('pin') == SERVER_PIN:
            session['authenticated'] = True
            return redirect(url_for('index'))
        else: return render_template('login.html', error="Incorrect PIN")
    return render_template('login.html')

@app.route('/')
@app.route('/view/')
@app.route('/view/<path:subpath>')
@login_required
def index(subpath=""):
    global SHARED_DIR
    if not SHARED_DIR: return "Select folder in the app first."
    full_path = os.path.join(SHARED_DIR, subpath)
    if not os.path.exists(full_path): return abort(404)
    items_list = []
    try:
        for name in os.listdir(full_path):
            if name.startswith('.'): continue
            f_path = os.path.join(full_path, name)
            if name.lower().endswith(('.srt', '.vtt', '.json', '.jpg', '.png', '.zip', '.py', '.txt', '.exe', '.spec')): continue 
            try:
                stats = os.stat(f_path)
                is_dir = os.path.isdir(f_path)
                item_rel = os.path.join(subpath, name).replace("\\", "/")
                items_list.append({
                    "name": name, "is_dir": is_dir,
                    "url": f"/view/{item_rel}" if is_dir else f"/play/{item_rel}",
                    "id": re.sub(r'\W+', '', name),
                    "size_raw": stats.st_size, "size": get_size_format(stats.st_size),
                    "time_raw": stats.st_mtime, "time": time.strftime('%d %b', time.localtime(stats.st_mtime))
                })
            except: continue
    except: pass
    
    total_folders = sum(1 for i in items_list if i['is_dir'])
    total_files = sum(1 for i in items_list if not i['is_dir'])
    sort_by = request.args.get('sort', 'name')
    if sort_by == "date": items_list.sort(key=lambda x: x['time_raw'], reverse=True)
    elif sort_by == "size": items_list.sort(key=lambda x: x['size_raw'], reverse=True)
    else: items_list.sort(key=lambda x: x['name'].lower())
    return render_template('index.html', items=items_list, current_path=subpath, parent_path=os.path.dirname(subpath).replace("\\", "/"), sort_by=sort_by, count_folders=total_folders, count_files=total_files)

@app.route('/api/metadata')
@login_required
def metadata_api():
    filename = request.args.get('file')
    subpath = request.args.get('path', '')
    is_dir = request.args.get('is_dir') == 'true'
    folder_location = os.path.join(SHARED_DIR, subpath)
    return jsonify(get_metadata(filename, folder_location, is_folder=is_dir))

@app.route('/metadata_img/<path:img_rel_path>')
def serve_poster(img_rel_path): return send_file(os.path.join(SHARED_DIR, img_rel_path))

# --- FIXED PLAY ROUTE (Cleaned up the duplicate code) ---
@app.route('/play/<path:filepath>')
@login_required
def play(filepath):
    filename = os.path.basename(filepath)
    # 1. GENERATE STRICT ID (Only Alphanumeric)
    safe_id = re.sub(r'\W+', '', filename)
    
    directory = os.path.dirname(os.path.join(SHARED_DIR, filepath))
    encoded_filepath = urllib.parse.quote(filepath)
    vlc_link = f"vlc://{SERVER_URL}/download/{encoded_filepath}"
    stream_url = f"{SERVER_URL}/download/{encoded_filepath}"
    
    # Get Metadata
    meta = get_metadata(filename, directory, is_folder=False)
    
    # File Stats
    try:
        full_path = os.path.join(SHARED_DIR, filepath)
        fsize = f"{os.path.getsize(full_path) / (1024 * 1024):.2f} MB"
    except: fsize = "Unknown"
    
    quality = "1080p" if "1080" in filename else "720p" if "720" in filename else "4K" if "2160" in filename else "SD"
    ext = os.path.splitext(filename)[1].replace('.', '').upper()

    subtitles = []
    base_name = os.path.splitext(filename)[0].lower()
    try:
        for f in os.listdir(directory):
            if f.lower().startswith(base_name) and f.lower().endswith(('.srt', '.vtt')):
                label = "English" if "eng" in f.lower() else "Subtitle"
                rel_path = os.path.relpath(os.path.join(directory, f), SHARED_DIR).replace("\\", "/")
                subtitles.append({"src": f"/download/{rel_path}", "label": label, "lang": "en"})
    except: pass
    
    # REMOVED THE OVERWRITING LINE HERE

    return render_template('player.html', 
                           filepath=filepath, 
                           filename=filename, 
                           file_id=safe_id, # Now using the correct Regex ID
                           subtitles=subtitles, 
                           vlc_link=vlc_link, 
                           stream_url=stream_url, 
                           meta=meta, 
                           file_size=fsize, 
                           quality=quality, 
                           container=ext)
    filename = os.path.basename(filepath)
    safe_id = re.sub(r'\W+', '', filename)
    directory = os.path.dirname(os.path.join(SHARED_DIR, filepath))
    encoded_filepath = urllib.parse.quote(filepath)
    vlc_link = f"vlc://{SERVER_URL}/download/{encoded_filepath}"
    stream_url = f"{SERVER_URL}/download/{encoded_filepath}"
    
    # Get Metadata
    meta = get_metadata(filename, directory, is_folder=False)
    
    # File Stats
    try:
        full_path = os.path.join(SHARED_DIR, filepath)
        fsize = f"{os.path.getsize(full_path) / (1024 * 1024):.2f} MB"
    except: fsize = "Unknown"
    
    quality = "1080p" if "1080" in filename else "720p" if "720" in filename else "4K" if "2160" in filename else "SD"
    ext = os.path.splitext(filename)[1].replace('.', '').upper()

    subtitles = []
    base_name = os.path.splitext(filename)[0].lower()
    try:
        for f in os.listdir(directory):
            if f.lower().startswith(base_name) and f.lower().endswith(('.srt', '.vtt')):
                label = "English" if "eng" in f.lower() else "Subtitle"
                rel_path = os.path.relpath(os.path.join(directory, f), SHARED_DIR).replace("\\", "/")
                subtitles.append({"src": f"/download/{rel_path}", "label": label, "lang": "en"})
    except: pass
    
    safe_id = filename.replace(" ", "").replace(".", "")
    return render_template('player.html', 
                           filepath=filepath, 
                           filename=filename, 
                           file_id=safe_id,
                           subtitles=subtitles, 
                           vlc_link=vlc_link, 
                           stream_url=stream_url, 
                           meta=meta, 
                           file_size=fsize, 
                           quality=quality, 
                           container=ext)

@app.route('/download/<path:filename>')
@login_required
def download(filename):
    response = send_from_directory(SHARED_DIR, filename)
    if filename.endswith('.vtt'): response.headers['Content-Type'] = 'text/vtt'
    elif filename.endswith('.srt'): response.headers['Content-Type'] = 'text/plain' 
    return response

@app.route('/api/start_zip/<path:subpath>')
@login_required
def start_zip(subpath):
    target = os.path.join(SHARED_DIR, subpath)
    if not os.path.exists(target): return jsonify({"error": "Path not found"}), 404
    jid = str(uuid.uuid4()); ZIP_JOBS[jid] = {'progress': 0, 'status': 'processing'}
    threading.Thread(target=background_zip_task, args=(jid, target, tempfile.gettempdir())).start()
    return jsonify({"job_id": jid})

@app.route('/api/zip_status/<job_id>')
def zip_status(job_id): return jsonify(ZIP_JOBS.get(job_id) or {"error": "Not Found"})

@app.route('/api/download_zip_result/<job_id>')
@login_required
def download_zip_result(job_id):
    job = ZIP_JOBS.get(job_id)
    if not job or job['status'] != 'ready': abort(404)
    fp = job['filepath']
    @after_this_request
    def cleanup(response):
        try: os.remove(fp); del ZIP_JOBS[job_id]
        except: pass
        return response
    return send_file(fp, as_attachment=True)

# --- UI CLASS ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ModernMovieApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Smart Movie Server")
        self.geometry("750x500")
        self.icon_path = os.path.join("static", "favicon.ico")
        if os.path.exists(self.icon_path): self.iconbitmap(self.icon_path)
        self.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="🎬 MEDIA SERVER", font=("Arial", 20, "bold"), text_color="#e50914").pack(pady=30)
        
        ctk.CTkLabel(self.sidebar, text="Source Folder:", anchor="w").pack(padx=20, pady=(10,0), anchor="w")
        self.btn_select = ctk.CTkButton(self.sidebar, text="Browse Folder", command=self.select_folder, fg_color="#333", border_width=1, border_color="#555"); self.btn_select.pack(padx=20, pady=5)
        self.lbl_path = ctk.CTkLabel(self.sidebar, text="None", text_color="gray", font=("Arial", 10), wraplength=180); self.lbl_path.pack(padx=20)
        
        ctk.CTkLabel(self.sidebar, text="Security PIN:", anchor="w").pack(padx=20, pady=(20,0), anchor="w")
        self.entry_pin = ctk.CTkEntry(self.sidebar, show="*", placeholder_text="Optional"); self.entry_pin.pack(padx=20, pady=5)

        self.btn_start = ctk.CTkButton(self.sidebar, text="▶ Start Server", command=self.run_server, fg_color="#28a745", hover_color="#218838", state="disabled"); self.btn_start.pack(padx=20, pady=(30, 10))
        self.btn_stop = ctk.CTkButton(self.sidebar, text="⏹ Stop & Exit", command=self.stop_server, fg_color="#dc3545", hover_color="#c82333", state="disabled"); self.btn_stop.pack(padx=20, pady=5)

        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        self.status_frame = ctk.CTkFrame(self.main_area, fg_color="#222"); self.status_frame.pack(fill="x", pady=10)
        self.lbl_status = ctk.CTkLabel(self.status_frame, text="Status: Offline", font=("Arial", 14), text_color="#888"); self.lbl_status.pack(pady=10)

        self.url_frame = ctk.CTkFrame(self.main_area, fg_color="transparent"); self.url_frame.pack(fill="x", pady=10)
        self.entry_url = ctk.CTkEntry(self.url_frame, placeholder_text="Waiting...", width=300); self.entry_url.pack(side="left", padx=(0, 10))
        self.btn_copy = ctk.CTkButton(self.url_frame, text="Copy Link", width=80, command=self.copy_link, state="disabled"); self.btn_copy.pack(side="left")

        self.qr_label = ctk.CTkLabel(self.main_area, text=""); self.qr_label.pack(pady=10)

        ctk.CTkLabel(self.main_area, text="Connected Devices (Live Log)", anchor="w", font=("Arial", 12, "bold")).pack(fill="x", pady=(10,5))
        self.client_box = ctk.CTkTextbox(self.main_area, height=100, text_color="#ccc"); self.client_box.pack(fill="x"); self.client_box.configure(state="disabled")

        saved_path = load_settings()
        if saved_path and os.path.exists(saved_path):
            global SHARED_DIR; SHARED_DIR = saved_path; self.lbl_path.configure(text=f"...{SHARED_DIR[-25:]}"); self.btn_start.configure(state="normal"); self.lbl_status.configure(text="Status: Ready", text_color="#00aaff")
        
        self.update_monitor()

    def select_folder(self):
        global SHARED_DIR; path = filedialog.askdirectory()
        if path: SHARED_DIR = os.path.abspath(path); self.lbl_path.configure(text=f"...{SHARED_DIR[-25:]}"); save_settings(SHARED_DIR); self.btn_start.configure(state="normal"); self.lbl_status.configure(text="Status: Ready", text_color="#00aaff")

    def run_server(self):
        global SERVER_URL, SERVER_PIN; SERVER_PIN = self.entry_pin.get().strip()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
        except: ip = "127.0.0.1"
        finally: s.close()
        SERVER_URL = f"http://{ip}:{PORT}"
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False), daemon=True).start()
        self.btn_start.configure(state="disabled", text="Running..."); self.btn_select.configure(state="disabled"); self.entry_pin.configure(state="disabled"); self.btn_stop.configure(state="normal"); self.btn_copy.configure(state="normal")
        self.entry_url.delete(0, "end"); self.entry_url.insert(0, SERVER_URL); self.lbl_status.configure(text="✅ Server is Live!", text_color="#28a745")
        qr = qrcode.QRCode(box_size=8, border=2); qr.add_data(SERVER_URL); qr.make(fit=True); img = qr.make_image(fill_color="black", back_color="white").resize((150, 150), Image.Resampling.LANCZOS)
        self.tk_qr_img = ctk.CTkImage(light_image=img, dark_image=img, size=(150,150)); self.qr_label.configure(image=self.tk_qr_img)

    def stop_server(self): self.quit_app()
    def copy_link(self): self.clipboard_clear(); self.clipboard_append(SERVER_URL); self.lbl_status.configure(text="✅ Link Copied!", text_color="#28a745")
    def update_monitor(self):
        self.client_box.configure(state="normal"); self.client_box.delete("0.0", "end")
        if not CONNECTED_CLIENTS: self.client_box.insert("0.0", "Waiting for connections...\n(Try connecting with your phone)")
        else:
            txt = ""
            for ip, info in CONNECTED_CLIENTS.items(): txt += f"[{info['last_seen']}] {info['device']} ({ip})\n"
            self.client_box.insert("0.0", txt)
        self.client_box.configure(state="disabled"); self.after(2000, self.update_monitor)
    def minimize_to_tray(self):
        self.withdraw()
        image = Image.open(self.icon_path) if os.path.exists(self.icon_path) else Image.new('RGB', (64, 64), 'red')
        self.tray_icon = pystray.Icon("name", image, "Movie Server", (item('Open', self.show_window), item('Stop & Exit', self.quit_app))); self.tray_icon.run()
    def show_window(self, icon, item): self.tray_icon.stop(); self.after(0, self.deiconify)
    def quit_app(self, icon=None, item=None): 
        if hasattr(self, 'tray_icon'): self.tray_icon.stop()
        self.destroy(); os._exit(0)

if __name__ == "__main__":
    app_gui = ModernMovieApp()
    app_gui.mainloop()