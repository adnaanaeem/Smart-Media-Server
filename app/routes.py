import os
import re
from sre_parse import parse
import time
import urllib.parse
import uuid
import threading
import tempfile
from datetime import datetime
from functools import wraps

from flask import render_template, send_from_directory, send_file, abort, request, jsonify, after_this_request, session, redirect, url_for
from flask_socketio import join_room, leave_room
from app import app, socketio
from app.services import ServerConfig, get_metadata, get_size_format, background_zip_task

# --- HELPER DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if ServerConfig.SERVER_PIN and not session.get('authenticated'): 
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---
@app.before_request
def track_visitor():
    try:
        ip = request.remote_addr
        ua_string = request.headers.get('User-Agent', '')
        user_agent = parse(ua_string) # <-- Use the new library here
        
        # Format the OS and Browser information nicely
        os_info = f"{user_agent.os.family} {user_agent.os.version_string}".strip()
        browser_info = f"{user_agent.browser.family} {user_agent.browser.version_string}".strip()
        
        # Determine the general device type
        if user_agent.is_mobile: device_type = "Phone"
        elif user_agent.is_tablet: device_type = "Tablet"
        elif user_agent.is_pc: device_type = "PC"
        elif user_agent.is_bot: device_type = "Bot"
        else: device_type = "Other"

        # Store all this new information
        ServerConfig.CONNECTED_CLIENTS[ip] = {
            'device_type': device_type,
            'os': os_info,
            'browser': browser_info,
            'last_seen': datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        print(f"Error tracking visitor: {e}")
    try:
        ip = request.remote_addr
        device = request.user_agent.platform
        if not device: device = "Browser"
        else: device = device.capitalize()
        ServerConfig.CONNECTED_CLIENTS[ip] = {
            'device': device,
            'last_seen': datetime.now().strftime("%H:%M:%S")
        }
    except: pass

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('pin') == ServerConfig.SERVER_PIN:
            session['authenticated'] = True
            return redirect(url_for('index'))
        else: return render_template('login.html', error="Incorrect PIN")
    return render_template('login.html')

@app.route('/')
@app.route('/view/')
@app.route('/view/<path:subpath>')
@login_required
def index(subpath=""):
    if not ServerConfig.SHARED_DIR: return "Select folder in the app first."
    full_path = os.path.join(ServerConfig.SHARED_DIR, subpath)
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
                    "id": re.sub(r'\W+', '', name), # Strict ID Generation
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
    folder_location = os.path.join(ServerConfig.SHARED_DIR, subpath)
    return jsonify(get_metadata(filename, folder_location, is_folder=is_dir))

@app.route('/metadata_img/<path:img_rel_path>')
def serve_poster(img_rel_path): 
    return send_file(os.path.join(ServerConfig.SHARED_DIR, img_rel_path))

@app.route('/play/<path:filepath>')
@login_required
def play(filepath):
    filename = os.path.basename(filepath)
    # 1. GENERATE STRICT ID (Only Alphanumeric)
    safe_id = re.sub(r'\W+', '', filename)
    
    directory = os.path.dirname(os.path.join(ServerConfig.SHARED_DIR, filepath))
    encoded_filepath = urllib.parse.quote(filepath)
    vlc_link = f"vlc://{ServerConfig.SERVER_URL}/download/{encoded_filepath}"
    stream_url = f"{ServerConfig.SERVER_URL}/download/{encoded_filepath}"
    
    meta = get_metadata(filename, directory, is_folder=False)
    try:
        full_path = os.path.join(ServerConfig.SHARED_DIR, filepath)
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
                rel_path = os.path.relpath(os.path.join(directory, f), ServerConfig.SHARED_DIR).replace("\\", "/")
                subtitles.append({"src": f"/download/{rel_path}", "label": label, "lang": "en"})
    except: pass
    
    return render_template('player.html', 
                           filepath=filepath, filename=filename, file_id=safe_id,
                           subtitles=subtitles, vlc_link=vlc_link, stream_url=stream_url, 
                           meta=meta, file_size=fsize, quality=quality, container=ext)

@app.route('/download/<path:filename>')
@login_required
def download(filename):
    response = send_from_directory(ServerConfig.SHARED_DIR, filename)
    if filename.endswith('.vtt'): response.headers['Content-Type'] = 'text/vtt'
    elif filename.endswith('.srt'): response.headers['Content-Type'] = 'text/plain' 
    return response

@app.route('/api/start_zip/<path:subpath>')
@login_required
def start_zip(subpath):
    target = os.path.join(ServerConfig.SHARED_DIR, subpath)
    if not os.path.exists(target): return jsonify({"error": "Path not found"}), 404
    jid = str(uuid.uuid4())
    ServerConfig.ZIP_JOBS[jid] = {'progress': 0, 'status': 'processing'}
    threading.Thread(target=background_zip_task, args=(jid, target, tempfile.gettempdir())).start()
    return jsonify({"job_id": jid})

@app.route('/api/zip_status/<job_id>')
def zip_status(job_id): 
    return jsonify(ServerConfig.ZIP_JOBS.get(job_id) or {"error": "Not Found"})

@app.route('/api/download_zip_result/<job_id>')
@login_required
def download_zip_result(job_id):
    job = ServerConfig.ZIP_JOBS.get(job_id)
    if not job or job['status'] != 'ready': abort(404)
    fp = job['filepath']
    @after_this_request
    def cleanup(response):
        try: os.remove(fp); del ServerConfig.ZIP_JOBS[job_id]
        except: pass
        return response
    return send_file(fp, as_attachment=True)

@app.route('/my-list')
@login_required
def my_list():
    # Get the list of favorite IDs from the URL query parameter
    favorite_ids_str = request.args.get('ids', '')
    if not favorite_ids_str:
        return render_template('my_list.html', items=[])

    favorite_ids = favorite_ids_str.split(',')
    
    favorited_items = []
    
    # Walk through the entire shared directory to find matching files
    for root, dirs, files in os.walk(ServerConfig.SHARED_DIR):
        # Skip hidden folders
        if '.meta' in root:
            continue
            
        for name in files:
            # Generate an ID for the file in the same way the index does
            safe_id = re.sub(r'\W+', '', name)
            
            if safe_id in favorite_ids:
                # We found a match! Now get its details.
                full_path = os.path.join(root, name)
                
                # Get relative path for URL generation
                rel_path = os.path.relpath(full_path, ServerConfig.SHARED_DIR).replace("\\", "/")
                
                # Fetch metadata to get poster, title, etc.
                meta = get_metadata(name, root)

                favorited_items.append({
                    "name": name,
                    "id": safe_id,
                    "url": f"/play/{rel_path}",
                    "title": meta.get('title', name),
                    "year": meta.get('year', ''),
                    "poster": meta.get('poster', None)
                })

    return render_template('my_list.html', items=favorited_items)

# --- WATCH PARTY SOCKET.IO HANDLERS ---

@socketio.on('join_room')
def handle_join_room(data):
    """Client joins a room for a specific movie party."""
    room = data['room']
    join_room(room)
    print(f"Client joined room: {room}")

@socketio.on('player_event')
def handle_player_event(data):
    """Handles receiving an event from one client and broadcasting to others."""
    room = data['room']
    # Broadcast to all other clients in the room, but not the sender
    socketio.emit('server_event', data, to=room, include_self=False)