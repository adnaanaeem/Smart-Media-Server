import os
import sys
from flask import Flask

# Setup Paths for PyInstaller support
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    # Assumes templates/static are in the root folder, one level up from 'app'
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

app.secret_key = os.urandom(24)

# Import routes at the end to avoid circular imports
from app import routes