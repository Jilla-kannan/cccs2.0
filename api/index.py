import sys
import os

# Make sure the root directory is on the path so we can import app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app
