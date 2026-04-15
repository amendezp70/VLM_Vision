# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — single-file macOS executable for VLM Vision.

Produces ONE file:  dist/vlm-vision
Run it from the folder that contains .env and models/
"""
import os

block_cipher = None

project_dir = os.path.abspath(os.path.join(SPECPATH, '..'))
overlay_dir = os.path.join(project_dir, 'overlay')

hidden_imports = [
    'local_agent', 'local_agent.main', 'local_agent.camera_agent',
    'local_agent.config', 'local_agent.detector', 'local_agent.display_server',
    'local_agent.frame_store', 'local_agent.models', 'local_agent.cloud_sync_client',
    'local_agent.model_registry', 'local_agent.modula_client',
    'local_agent.offline_queue', 'local_agent.pick_verifier', 'local_agent.sync_worker',
    'cv2',
    'onnxruntime', 'onnxruntime.capi', 'onnxruntime.capi._pybind_state',
    'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'fastapi', 'starlette', 'starlette.routing', 'starlette.staticfiles',
    'starlette.websockets', 'starlette.responses',
    'httpx', 'httpx._transports', 'httpx._transports.default',
    'anyio', 'anyio._backends', 'anyio._backends._asyncio',
    'h11', 'wsproto', 'multipart', 'python_multipart',
]

excludes = [
    'ultralytics', 'torch', 'torchvision', 'torchaudio',
    'tensorflow', 'tensorboard', 'transformers',
    'scipy', 'pandas', 'matplotlib', 'sympy',
    'IPython', 'jupyter', 'notebook',
    'PIL.ImageQt', 'tkinter',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
]

a = Analysis(
    [os.path.join(project_dir, 'scripts', 'app_launcher.py')],
    pathex=[project_dir],
    binaries=[],
    datas=[(overlay_dir, 'overlay')],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # pack binaries INTO the exe
    a.zipfiles,      # pack zips INTO the exe
    a.datas,         # pack data INTO the exe
    [],
    name='vlm-vision',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,     # show terminal output (useful for logs)
    target_arch=None,
)
