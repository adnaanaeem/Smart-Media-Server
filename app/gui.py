import os
import socket
import threading
import qrcode
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageTk

from app import app
from app.services import ServerConfig

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
        self.btn_select = ctk.CTkButton(self.sidebar, text="Browse Folder", command=self.select_folder, fg_color="#333", border_width=1, border_color="#555")
        self.btn_select.pack(padx=20, pady=5)
        self.lbl_path = ctk.CTkLabel(self.sidebar, text="None", text_color="gray", font=("Arial", 10), wraplength=180)
        self.lbl_path.pack(padx=20)
        
        ctk.CTkLabel(self.sidebar, text="Security PIN:", anchor="w").pack(padx=20, pady=(20,0), anchor="w")
        self.entry_pin = ctk.CTkEntry(self.sidebar, show="*", placeholder_text="Optional")
        self.entry_pin.pack(padx=20, pady=5)

        self.btn_start = ctk.CTkButton(self.sidebar, text="▶ Start Server", command=self.run_server, fg_color="#28a745", hover_color="#218838", state="disabled")
        self.btn_start.pack(padx=20, pady=(30, 10))
        self.btn_stop = ctk.CTkButton(self.sidebar, text="⏹ Stop & Exit", command=self.stop_server, fg_color="#dc3545", hover_color="#c82333", state="disabled")
        self.btn_stop.pack(padx=20, pady=5)

        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        self.status_frame = ctk.CTkFrame(self.main_area, fg_color="#222"); self.status_frame.pack(fill="x", pady=10)
        self.lbl_status = ctk.CTkLabel(self.status_frame, text="Status: Offline", font=("Arial", 14), text_color="#888")
        self.lbl_status.pack(pady=10)

        self.url_frame = ctk.CTkFrame(self.main_area, fg_color="transparent"); self.url_frame.pack(fill="x", pady=10)
        self.entry_url = ctk.CTkEntry(self.url_frame, placeholder_text="Waiting...", width=300); self.entry_url.pack(side="left", padx=(0, 10))
        self.btn_copy = ctk.CTkButton(self.url_frame, text="Copy Link", width=80, command=self.copy_link, state="disabled"); self.btn_copy.pack(side="left")

        self.qr_label = ctk.CTkLabel(self.main_area, text=""); self.qr_label.pack(pady=10)

        ctk.CTkLabel(self.main_area, text="Connected Devices (Live Log)", anchor="w", font=("Arial", 12, "bold")).pack(fill="x", pady=(10,5))
        self.client_box = ctk.CTkTextbox(self.main_area, height=100, text_color="#ccc"); self.client_box.pack(fill="x"); self.client_box.configure(state="disabled")

        saved_path = ServerConfig.load_settings()
        if saved_path and os.path.exists(saved_path):
            ServerConfig.SHARED_DIR = saved_path
            self.lbl_path.configure(text=f"...{ServerConfig.SHARED_DIR[-25:]}")
            self.btn_start.configure(state="normal")
            self.lbl_status.configure(text="Status: Ready", text_color="#00aaff")
        
        self.update_monitor()

    def select_folder(self):
        path = filedialog.askdirectory()
        if path: 
            ServerConfig.SHARED_DIR = os.path.abspath(path)
            self.lbl_path.configure(text=f"...{ServerConfig.SHARED_DIR[-25:]}")
            ServerConfig.save_settings(ServerConfig.SHARED_DIR)
            self.btn_start.configure(state="normal")
            self.lbl_status.configure(text="Status: Ready", text_color="#00aaff")

    def run_server(self):
        ServerConfig.SERVER_PIN = self.entry_pin.get().strip()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
        except: ip = "127.0.0.1"
        finally: s.close()
        
        ServerConfig.SERVER_URL = f"http://{ip}:{ServerConfig.PORT}"
        
        # Start Flask in Thread
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=ServerConfig.PORT, use_reloader=False), daemon=True).start()
        
        self.btn_start.configure(state="disabled", text="Running...")
        self.btn_select.configure(state="disabled")
        self.entry_pin.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_copy.configure(state="normal")
        
        self.entry_url.delete(0, "end"); self.entry_url.insert(0, ServerConfig.SERVER_URL)
        self.lbl_status.configure(text="✅ Server is Live!", text_color="#28a745")
        
        qr = qrcode.QRCode(box_size=8, border=2); qr.add_data(ServerConfig.SERVER_URL); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").resize((150, 150), Image.Resampling.LANCZOS)
        self.tk_qr_img = ctk.CTkImage(light_image=img, dark_image=img, size=(150,150))
        self.qr_label.configure(image=self.tk_qr_img)

    def stop_server(self): self.quit_app()
    def copy_link(self): 
        self.clipboard_clear(); self.clipboard_append(ServerConfig.SERVER_URL)
        self.lbl_status.configure(text="✅ Link Copied!", text_color="#28a745")

    def update_monitor(self):
        self.client_box.configure(state="normal"); self.client_box.delete("0.0", "end")
        if not ServerConfig.CONNECTED_CLIENTS: 
            self.client_box.insert("0.0", "Waiting for connections...\n(Try connecting with your phone)")
        else:
            txt = ""
            for ip, info in ServerConfig.CONNECTED_CLIENTS.items(): 
                txt += f"[{info['last_seen']}] {info['device']} ({ip})\n"
            self.client_box.insert("0.0", txt)
        self.client_box.configure(state="disabled")
        self.after(2000, self.update_monitor)

    def minimize_to_tray(self):
        self.withdraw()
        image = Image.open(self.icon_path) if os.path.exists(self.icon_path) else Image.new('RGB', (64, 64), 'red')
        self.tray_icon = pystray.Icon("name", image, "Movie Server", (item('Open', self.show_window), item('Stop & Exit', self.quit_app)))
        self.tray_icon.run()

    def show_window(self, icon, item): 
        self.tray_icon.stop()
        self.after(0, self.deiconify)

    def quit_app(self, icon=None, item=None): 
        if hasattr(self, 'tray_icon'): self.tray_icon.stop()
        self.destroy()
        os._exit(0)