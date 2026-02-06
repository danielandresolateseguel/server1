from app import create_app
from waitress import serve
import os

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting production server on port {port} using Waitress...")
    # threads=6 is a good starting point for a mix of I/O and CPU
    serve(app, host='0.0.0.0', port=port, threads=6)
