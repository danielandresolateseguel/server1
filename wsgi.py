import os
import sys

# Ensure project root is in path
sys.path.append(os.getcwd())

from app import create_app
from waitress import serve

app = create_app()

if __name__ == "__main__":
    try:
        port = int(os.environ.get('PORT', 5000))
        print(f"DEBUG: App object: {app}", flush=True)
        print(f"Starting production server on port {port} using Waitress...", flush=True)
        serve(app, host='0.0.0.0', port=port, threads=6)
        print("DEBUG: Server stopped (serve returned).", flush=True)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
