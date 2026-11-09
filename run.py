import os
import sys
from pathlib import Path
import uvicorn

# Ensure backend folder is in Python path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print("=" * 60)
    print(f"Starting InstaClip Server at http://localhost:{port}")
    print(f"Access from your phone on the same Wi-Fi via your LAN IP:")
    print(f"   http://<YOUR_COMPUTER_IP>:{port}")
    print("=" * 60)
    uvicorn.run("main:app", host=host, port=port, reload=False, app_dir=str(BACKEND_DIR))

