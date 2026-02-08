import os
import sys

# Ensure project root is in path
sys.path.append(os.getcwd())

from app import create_app
from waitress import serve

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting production server on port {port} using Waitress...")
    serve(app, host='0.0.0.0', port=port, threads=6)
