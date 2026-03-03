"""
Vercel serverless function entry point.
Imports the FastAPI app from app/main.py and exposes it.
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

# Vercel expects a variable called 'app' or 'handler'
# FastAPI automatically provides ASGI compatibility
