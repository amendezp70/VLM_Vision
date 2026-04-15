# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for VLM Vision macOS .app bundle.

Keeps the bundle lean by explicitly listing only the imports
the app actually uses, avoiding torch/transformers bloat.
"""
import os
pass  # no extra hook imports needed

block_cipher = None

project_dir = os.path.abspath(os.path.join(SPECPATH, '..'))
overlay_dir = os.path.join(project_dir, 'overlay')

# No ultralytics data needed — using pure onnxruntime backend
ultralytics_datas = []

hidden_imports = [
    # Core app
    'local_agent',
    'local_agent.main',
    'local_agent.camera_agent',
    'local_agent.config',
    'local_agent.detector',
    'local_agent.display_server',
    'local_agent.frame_store',
    'local_agent.models',
    'local_agent.cloud_sync_client',
    'local_agent.model_registry',
    'local_agent.modula_client',
    'local_agent.offline_queue',
    'local_agent.pick_verifier',
    'local_agent.sync_worker',
    # OpenCV
    'cv2',
    # ONNX inference only (no ultralytics/torch in standalone build)
    'onnxruntime',
    'onnxruntime.capi',
    'onnxruntime.capi._pybind_state',
    # Web server
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'starlette',
    'starlette.routing',
    'starlette.staticfiles',
    'starlette.websockets',
    'starlette.responses',
    # HTTP client
    'httpx',
    'httpx._transports',
    'httpx._transports.default',
    # Async
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    # Misc
    'h11',
    'wsproto',
    'multipart',
    'python_multipart',
]

# Exclude heavy unused packages
excludes = [
    'ultralytics',
    'torch',
    'torchvision',
    'torchaudio',
    'tensorflow',
    'tensorboard',
    'transformers',
    'scipy',
    'pandas',
    'matplotlib',
    'sympy',
    'IPython',
    'jupyter',
    'notebook',
    'PIL.ImageQt',
    'tkinter',
    'PyQt5',
    'PyQt6',
    'PySide2',
    'PySide6',
    'wx',
]

a = Analysis(
    [os.path.join(project_dir, 'scripts', 'app_launcher.py')],
    pathex=[project_dir],
    binaries=[],
    datas=[
        (overlay_dir, 'overlay'),
    ] + ultralytics_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VLM Vision',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,  # Use native arch (arm64 on Apple Silicon, x86_64 on Intel)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='VLM Vision',
)

app = BUNDLE(
    coll,
    name='VLM Vision.app',
    icon=None,
    bundle_identifier='com.dhar.vlm-vision',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleName': 'VLM Vision',
        'NSCameraUsageDescription': 'VLM Vision needs camera access for pick verification.',
    },
)
