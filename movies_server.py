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
from functools import wraps
from PIL import Image, ImageTk
from flask import Flask, render_template, send_from_directory, send_file, abort, request, jsonify, after_this_request, session, redirect, url_for
import tkinter as tk
from tkinter import filedialog

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- CONFIGURATION ---
PORT = 8000
TMDB_API_KEY = "5ca06765ae8916dfe1431ad86b05a7f4"  # Your Key
SHARED_DIR = ""
SERVER_URL = ""
SERVER_PIN = ""
ZIP_JOBS = {}

# --- HELPER: Clean Filename ---
def parse_movie_name(filename):
    name = os.path.splitext(filename)[0]
    is_tv = bool(re.search(r'\b(S\d+|Season)\b', name, re.IGNORECASE))
    match = re.search(r'\b(19|20)\d{2}\b', name)
    year = None
    if match:
        year = match.group(0)
        name = name[:match.start()]
    
    name = name.replace('.', ' ').replace('_', ' ').replace('(', '').replace(')', '').replace('[', '').replace(']', '')
    junk_words = ["1080p", "720p", "480p", "4k", "2160p", "UHD", "HDR", "Bluray", "WebRip", "Web-DL", "HDTV", "CAM", "TS", "H264", "H265", "x264", "x265", "AAC", "DDP5", "PSA", "RARBG", "YIFY"]
    for word in junk_words:
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        name = pattern.sub('', name)

    return name.strip(), year, is_tv

# --- HELPER: Fetch Metadata ---
def get_metadata(filename, folder_path, is_folder=False):
    meta_dir = os.path.join(folder_path, ".meta")
    if not os.path.exists(meta_dir): os.makedirs(meta_dir)
    json_path = os.path.join(meta_dir, f"{filename}.json")
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except:
            pass

    if not TMDB_API_KEY or "PASTE" in TMDB_API_KEY:
        return {"title": filename, "poster": None, "year": ""}

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
            poster_path = media.get('poster_path')
            local_poster = None
            if poster_path:
                try:
                    img_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    img_data = requests.get(img_url).content
                    img_name = f"{filename}.jpg"
                    with open(os.path.join(meta_dir, img_name), 'wb') as f: f.write(img_data)
                    local_poster = f"/metadata_img/{urllib.parse.quote(os.path.relpath(os.path.join(meta_dir, img_name), SHARED_DIR))}"
                except: pass

            final_title = media.get('name') if is_tv else media.get('title')
            final_date = media.get('first_air_date') if is_tv else media.get('release_date')
            final_year = final_date[:4] if final_date else year

            data = {"title": final_title, "year": final_year, "poster": local_poster, "rating": media.get('vote_average'), "is_tv": is_tv}
            with open(json_path, 'w') as f: json.dump(data, f)
            return data
    except Exception as e: print(f"Error fetching {filename}: {e}")

    failed_data = {"title": title, "poster": None, "year": year}
    with open(json_path, 'w') as f: json.dump(failed_data, f)
    return failed_data

def get_size_format(b):
    for unit in ["", "K", "M", "G", "T"]:
        if b < 1024: return f"{b:.1f}{unit}B"
        b /= 1024

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if SERVER_PIN and not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ZIP TASK ---
def background_zip_task(job_id, source_dir, temp_dir):
    try:
        base_name = os.path.basename(source_dir)
        zip_filename = f"{base_name}.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
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
        ZIP_JOBS[job_id]['progress'] = 100
        ZIP_JOBS[job_id]['status'] = 'ready'
        ZIP_JOBS[job_id]['filepath'] = zip_path
    except: ZIP_JOBS[job_id]['status'] = 'error'

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
    
    sort_by = request.args.get('sort', 'name')
    full_path = os.path.join(SHARED_DIR, subpath)
    if not os.path.exists(full_path): return abort(404)

    items_list = []
    try:
        for name in os.listdir(full_path):
            if name.startswith('.'): continue
            f_path = os.path.join(full_path, name)
            if name.lower().endswith(('.srt', '.vtt', '.json', '.jpg', '.png', '.zip', '.py', '.txt', '.exe')): continue 

            try:
                stats = os.stat(f_path)
                is_dir = os.path.isdir(f_path)
                item_rel = os.path.join(subpath, name).replace("\\", "/")
                
                items_list.append({
                    "name": name, "is_dir": is_dir,
                    "url": f"/view/{item_rel}" if is_dir else f"/play/{item_rel}",
                    "id": name.replace(" ", "_").replace(".", "_"), 
                    "size_raw": stats.st_size, "size": get_size_format(stats.st_size),
                    "time_raw": stats.st_mtime, "time": time.strftime('%d %b', time.localtime(stats.st_mtime))
                })
            except OSError: continue
    except Exception: pass

    # --- NEW: COUNT LOGIC ---
    total_folders = sum(1 for i in items_list if i['is_dir'])
    total_files = sum(1 for i in items_list if not i['is_dir'])

    if sort_by == "date": items_list.sort(key=lambda x: x['time_raw'], reverse=True)
    elif sort_by == "size": items_list.sort(key=lambda x: x['size_raw'], reverse=True)
    else: items_list.sort(key=lambda x: x['name'].lower())

    return render_template('index.html', items=items_list, current_path=subpath, 
                           parent_path=os.path.dirname(subpath).replace("\\", "/"), sort_by=sort_by,
                           count_folders=total_folders, count_files=total_files) # Pass counts to HTML
    if sort_by == "date": items_list.sort(key=lambda x: x['time_raw'], reverse=True)
    elif sort_by == "size": items_list.sort(key=lambda x: x['size_raw'], reverse=True)
    else: items_list.sort(key=lambda x: x['name'].lower())

    return render_template('index.html', items=items_list, current_path=subpath, 
                           parent_path=os.path.dirname(subpath).replace("\\", "/"), sort_by=sort_by)

@app.route('/api/metadata')
@login_required
def metadata_api():
    filename = request.args.get('file')
    subpath = request.args.get('path', '')
    is_dir = request.args.get('is_dir') == 'true'
    
    if is_dir: folder_location = os.path.join(SHARED_DIR, subpath)
    else: folder_location = os.path.join(SHARED_DIR, subpath)

    data = get_metadata(filename, folder_location, is_folder=is_dir)
    return jsonify(data)

@app.route('/metadata_img/<path:img_rel_path>')
def serve_poster(img_rel_path):
    return send_file(os.path.join(SHARED_DIR, img_rel_path))

@app.route('/play/<path:filepath>')
@login_required
def play(filepath):
    filename = os.path.basename(filepath)
    directory = os.path.dirname(os.path.join(SHARED_DIR, filepath))
    encoded_filepath = urllib.parse.quote(filepath)
    
    vlc_protocol_link = f"vlc://{SERVER_URL}/download/{encoded_filepath}"
    stream_url = f"{SERVER_URL}/download/{encoded_filepath}"

    base_name = os.path.splitext(filename)[0].lower()
    subtitles = []
    try:
        for f in os.listdir(directory):
            if f.lower().startswith(base_name) and f.lower().endswith(('.srt', '.vtt')):
                label = "English" if "eng" in f.lower() else "Subtitle"
                rel_path = os.path.relpath(os.path.join(directory, f), SHARED_DIR).replace("\\", "/")
                subtitles.append({"src": f"/download/{rel_path}", "label": label, "lang": "en"})
    except: pass

    file_id = filename.replace(" ", "_").replace(".", "_")
    return render_template('player.html', filepath=filepath, filename=filename, file_id=file_id, 
                           subtitles=subtitles, vlc_link=vlc_protocol_link, stream_url=stream_url)

@app.route('/download/<path:filename>')
@login_required
def download(filename):
    response = send_from_directory(SHARED_DIR, filename)
    if filename.lower().endswith('.vtt'): response.headers['Content-Type'] = 'text/vtt'
    elif filename.lower().endswith('.srt'): response.headers['Content-Type'] = 'text/plain' 
    return response

@app.route('/api/start_zip/<path:subpath>')
@login_required
def start_zip(subpath):
    target_dir = os.path.join(SHARED_DIR, subpath)
    if not os.path.exists(target_dir): return jsonify({"error": "Path not found"}), 404
    job_id = str(uuid.uuid4()); ZIP_JOBS[job_id] = {'progress': 0, 'status': 'processing'}
    threading.Thread(target=background_zip_task, args=(job_id, target_dir, tempfile.gettempdir())).start()
    return jsonify({"job_id": job_id})

@app.route('/api/zip_status/<job_id>')
def zip_status(job_id): return jsonify(ZIP_JOBS.get(job_id) or {"error": "Job not found"})

@app.route('/api/download_zip_result/<job_id>')
@login_required
def download_zip_result(job_id):
    job = ZIP_JOBS.get(job_id)
    if not job or job['status'] != 'ready': abort(404)
    file_path = job['filepath']
    @after_this_request
    def cleanup(response):
        try: os.remove(file_path); del ZIP_JOBS[job_id]
        except: pass
        return response
    return send_file(file_path, as_attachment=True)

# --- GUI APP ---
class MovieApp:
    def __init__(self, root):
        self.root = root; self.root.title("Movie Server Control"); self.root.geometry("500x700"); self.root.resizable(False, False)
        icon_path = os.path.join("static", "favicon.ico")
        if os.path.exists(icon_path):
            try: self.root.iconbitmap(icon_path) 
            except: pass
        header_frame = tk.Frame(root, bg="#111"); header_frame.pack(fill="x")
        tk.Label(header_frame, text="🎬 Movie Server", font=("Segoe UI", 16, "bold"), bg="#111", fg="#e50914").pack(pady=15)
        self.frame_controls = tk.Frame(root); self.frame_controls.pack(pady=10)
        tk.Label(self.frame_controls, text="Step 1: Select your Movies Folder", font=("Arial", 10)).pack()
        self.btn_select = tk.Button(self.frame_controls, text="📁 Browse Folder", command=self.select_folder, width=20, bg="#ddd"); self.btn_select.pack(pady=5)
        self.lbl_path = tk.Label(self.frame_controls, text="No folder selected", fg="gray", font=("Arial", 8), wraplength=400); self.lbl_path.pack(pady=5)
        tk.Label(self.frame_controls, text="Step 2: Set PIN (Optional)", font=("Arial", 10)).pack(pady=(15, 5))
        self.pin_entry = tk.Entry(self.frame_controls, show="*", justify="center", width=15, font=("Arial", 12)); self.pin_entry.pack()
        tk.Label(self.frame_controls, text="(Leave empty for no password)", fg="gray", font=("Arial", 8)).pack()
        self.btn_start = tk.Button(root, text="▶ START SERVER", state="disabled", command=self.run_s, bg="#28a745", fg="white", font=("Arial", 11, "bold"), width=20, height=2); self.btn_start.pack(pady=10)
        self.frame_url = tk.Frame(root); self.frame_url.pack(pady=5)
        self.txt_display = tk.Text(self.frame_url, height=1, width=35, state="disabled", bg="#f4f4f4", font=("Consolas", 10)); self.txt_display.pack(side="left", padx=5)
        self.btn_copy = tk.Button(self.frame_url, text="📋 Copy", state="disabled", command=self.copy_link, bg="#007bff", fg="white"); self.btn_copy.pack(side="left")
        self.qr_label = tk.Label(root); self.qr_label.pack(pady=10)
        self.lbl_status = tk.Label(root, text="Waiting to start...", fg="#888", font=("Arial", 10, "italic")); self.lbl_status.pack(side="bottom", pady=20)

    def select_folder(self):
        global SHARED_DIR; path = filedialog.askdirectory()
        if path: SHARED_DIR = os.path.abspath(path); self.lbl_path.config(text=SHARED_DIR, fg="black"); self.btn_start.config(state="normal"); self.lbl_status.config(text="Folder selected.", fg="#007bff")

    def copy_link(self): self.root.clipboard_clear(); self.root.clipboard_append(SERVER_URL); self.lbl_status.config(text="✅ Link copied!", fg="#28a745")

    def run_s(self):
        global SERVER_URL, SERVER_PIN; SERVER_PIN = self.pin_entry.get().strip()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
        except: ip = "127.0.0.1"
        finally: s.close()
        SERVER_URL = f"http://{ip}:{PORT}"
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False), daemon=True).start()
        self.btn_start.config(text="SERVER RUNNING", state="disabled", bg="#555"); self.btn_select.config(state="disabled"); self.pin_entry.config(state="disabled"); self.btn_copy.config(state="normal"); self.txt_display.config(state="normal"); self.txt_display.delete("1.0", tk.END); self.txt_display.insert("1.0", SERVER_URL); self.txt_display.config(state="disabled")
        qr = qrcode.QRCode(box_size=8, border=2); qr.add_data(SERVER_URL); qr.make(fit=True); img = qr.make_image(fill_color="black", back_color="white").resize((180, 180), Image.Resampling.LANCZOS)
        self.tk_qr_image = ImageTk.PhotoImage(img); self.qr_label.config(image=self.tk_qr_image)
        status_msg = "✅ Server Live!"; 
        if SERVER_PIN: status_msg += f" (PIN: {SERVER_PIN})"
        self.lbl_status.config(text=status_msg, fg="#28a745")

if __name__ == "__main__": root = tk.Tk(); MovieApp(root); root.mainloop()