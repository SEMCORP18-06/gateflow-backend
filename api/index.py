import sys
import os

# Add root directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app

# Export app & handler for Vercel ASGI serverless runtime
app = app
handler = app
