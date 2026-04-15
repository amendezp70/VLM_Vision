"""
macOS standalone entry point for VLM Vision.

Designed to run as a single executable with zero external config files.
Just place the executable and an .onnx model file in the same folder and run.

Config priority:
  1. Environment variables (if set)
  2. .env file next to the executable (if it exists)
  3. Built-in defaults
"""
import glob
import os
import sys
import tempfile
from pathlib import Path

# ── Built-in defaults (no .env file needed) ──────────────────────────
_DEFAULTS = {
    "CAMERA_BAY1": "0",
    "CAMERA_BAY2": "1",
    "MODULA_WMS_URL": "http://modula-wms.local:8080",
    "CLOUD_SYNC_URL": "http://localhost:8080",
    "DETECTION_FPS": "10",
    "WEBSOCKET_PORT": "8765",
    "SYNC_INTERVAL_SEC": "30",
    "MODEL_POLL_INTERVAL_SEC": "3600",
}


def _find_exe_dir() -> Path:
    """Return the directory containing the executable (or script)."""
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable)
        if 'Contents' in exe.parts:
            return exe.parent.parent.parent.parent
        return exe.parent
    return Path(__file__).parent.parent


def _find_onnx_model(search_dir: Path) -> str:
    """Find the first .onnx file next to the executable."""
    patterns = [str(search_dir / "*.onnx"), str(search_dir / "models" / "*.onnx")]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return ""


def main():
    exe_dir = _find_exe_dir()

    # Load .env if it exists (optional)
    env_file = exe_dir / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                if key and value:
                    os.environ.setdefault(key.strip(), value.strip())

    # Apply built-in defaults for anything not set
    for key, value in _DEFAULTS.items():
        os.environ.setdefault(key, value)

    # Auto-find model if MODEL_PATH not set
    if "MODEL_PATH" not in os.environ:
        model = _find_onnx_model(exe_dir)
        if model:
            os.environ["MODEL_PATH"] = model
        else:
            print("=" * 50)
            print("ERROR: No .onnx model file found.")
            print(f"Place your model file next to the executable:")
            print(f"  {exe_dir}/your_model.onnx")
            print("=" * 50)
            sys.exit(1)
    elif not os.path.isabs(os.environ["MODEL_PATH"]):
        os.environ["MODEL_PATH"] = str(exe_dir / os.environ["MODEL_PATH"])

    # DB path: use a temp dir so no extra folders needed
    if "DB_PATH" not in os.environ:
        data_dir = exe_dir / "vlm_data"
        data_dir.mkdir(exist_ok=True)
        os.environ["DB_PATH"] = str(data_dir / "picks.db")

    # Model dir
    os.environ.setdefault("MODEL_DIR", str(exe_dir))

    port = os.environ.get("WEBSOCKET_PORT", "8765")
    print(f"Starting VLM Vision on http://localhost:{port}")
    print(f"Model: {os.environ['MODEL_PATH']}")

    from local_agent.main import main as run_vlm
    run_vlm()


if __name__ == "__main__":
    main()
