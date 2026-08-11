import sys
import os

# Add parent directory to path so imports like 'from backend.app import app' resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app
