import os
import json
import re
import requests
import zipfile
import urllib.parse

# --- GLOBAL CONFIGURATION ---
class ServerConfig:
    PORT = 8000
    TMDB_API_KEY = "5ca06765ae8916dfe1431ad86b05a7f4"
    SHARED_DIR = ""
    SERVER_URL = ""
    SERVER_PIN = ""
    ZIP_JOBS = {}
    CONNECTED_CLIENTS = {}
    CONFIG_FILE = "settings.json"

    @staticmethod
    def load_settings():
        if os.path.exists(ServerConfig.CONFIG_FILE):
            try:
                with open(ServerConfig.CONFIG_FILE, 'r') as f: 
                    return json.load(f).get("last_folder", "")
            except: pass
        return ""

    @staticmethod
    def save_settings(path):
        try:
            with open(ServerConfig.CONFIG_FILE, 'w') as f:
                json.dump({"last_folder": path}, f)
        except: pass

# --- LOGIC FUNCTIONS ---
def parse_movie_name(filename):
    name = os.path.splitext(filename)[0]
    is_tv = bool(re.search(r'\b(S\d+|Season)\b', name, re.IGNORECASE))
    match = re.search(r'\b(19|20)\d{2}\b', name)
    year = None
    if match:
        year = match.group(0)
        name = name[:match.start()]
    name = re.sub(r'[\.\_\[\]\(\)]', ' ', name)
    junk_words = ["1080p", "720p", "480p", "4k", "HDR", "Bluray", "WebRip", "x265", "AAC", "RARBG", "PSA", "YIFY"]
    for word in junk_words:
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        name = pattern.sub('', name)
    return name.strip(), year, is_tv

def get_metadata(filename, folder_path, is_folder=False):
    meta_dir = os.path.join(folder_path, ".meta")
    if not os.path.exists(meta_dir): os.makedirs(meta_dir)
    json_path = os.path.join(meta_dir, f"{filename}.json")
    
    # Check Cache
    if os.path.exists(json_path):
        try: 
            with open(json_path, 'r') as f: 
                data = json.load(f)
                if 'backdrop' in data: return data
        except: pass

    if not ServerConfig.TMDB_API_KEY:
        return {"title": filename, "poster": None, "year": "", "overview": "", "backdrop": None}

    title, year, is_tv_guess = parse_movie_name(filename)
    is_tv = True if is_folder else is_tv_guess
    endpoint = "tv" if is_tv else "movie"
    search_url = f"https://api.themoviedb.org/3/search/{endpoint}?api_key={ServerConfig.TMDB_API_KEY}&query={urllib.parse.quote(title)}"
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
                    return f"/metadata_img/{urllib.parse.quote(os.path.relpath(os.path.join(meta_dir, fname), ServerConfig.SHARED_DIR))}"
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
    
    return {"title": title, "poster": None, "year": year, "overview": "", "backdrop": None}

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
                            if total_size > 0: ServerConfig.ZIP_JOBS[job_id]['progress'] = int((processed_size / total_size) * 100)
        ServerConfig.ZIP_JOBS[job_id].update({'progress': 100, 'status': 'ready', 'filepath': zip_path})
    except: ServerConfig.ZIP_JOBS[job_id]['status'] = 'error'

def get_size_format(b):
    for unit in ["", "K", "M", "G", "T"]:
        if b < 1024: return f"{b:.1f}{unit}B"
        b /= 1024