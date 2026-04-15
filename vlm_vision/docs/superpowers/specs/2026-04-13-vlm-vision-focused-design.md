# VLM Vision — Pick Verification, Video Evidence & Robotic Picking

**Date:** 2026-04-13
**Status:** Draft
**Scope:** Process 1 (Bay Agent) + Process 3 (Video Recorder) + Phase 2 (Robotic Picking)
**Prepared for:** Metwall Design Solutions Inc.

---

## Part A — System Overview

### 1. Purpose & Business Goals

VLM Vision is an AI-powered system for Metwall's Modula VLM (Vertical Lift Module) warehouse operations. It combines real-time pick verification, continuous video evidence recording, and automated robotic picking.

**Business objectives:**
- **Verify picks** — AI camera confirms operators/robots pick the correct part from the correct tray
- **Video evidence** — Continuous recording creates timestamped proof of every pick for dispute resolution
- **Automate picking** — Cobot arm replaces manual picking of 3m aluminum profiles, achieving 2.5-3.75x throughput
- **Offline resilience** — System never stops, even without internet; data syncs when connection restores

### 2. System Architecture

Three separate processes sharing a core library, backed by Zoho Catalyst cloud.

**Process 1 — VLM Bay Agent (existing):**
- Camera capture, YOLO detection, pick verification
- Modula WMS integration, WebSocket overlay display
- Offline queue + cloud sync

**Process 3 — Video Recorder (new):**
- Continuous H.264 multi-camera recording
- 5-minute segment splitting + cloud upload
- 60-day retention + on-demand evidence clip extraction

**Phase 2 — Robotic Picking (new):**
- 6-axis cobot arm (UR20 / FANUC CRX-25iA)
- Vacuum gripper for 3m aluminum profiles
- Camera detection → arm trajectory → vertical dolly rack placement

**Shared Core Library:**
- camera_agent, detector, offline_queue, cloud_sync_client, config, models, display_server

**Cloud Backend (Zoho Catalyst):**
- Datastore: pick_events, video_segments, evidence_clips
- File Store: video segments, evidence clips, ONNX models
- Functions: picks sync, model registry, video management, evidence extraction

**Inter-process communication:**
- SQLite event queue (same pattern as existing offline_queue)
- Filesystem signals for clip extraction requests

---

## Part B — Process 1: VLM Bay Agent (Existing)

### 3. Architecture & Modules

The Bay Agent runs as a single process with one thread per bay. It captures frames, detects parts, verifies picks, and syncs results to the cloud.

| Module | File | Responsibility |
|--------|------|---------------|
| CameraAgent | `camera_agent.py` | Captures frames from USB camera, manages frame queue |
| Detector | `detector.py` | Dual-backend YOLO inference (ultralytics + onnxruntime fallback) |
| PickVerifier | `pick_verifier.py` | Compares before/after detections, determines pick result |
| ModulaClient | `modula_client.py` | HTTP client for Modula WMS (fetch order, confirm pick) |
| OfflineQueue | `offline_queue.py` | SQLite queue for unsynced pick events |
| CloudSyncClient | `cloud_sync_client.py` | HTTP client for Catalyst cloud endpoints |
| ModelRegistry | `model_registry.py` | Polls cloud for ONNX model updates, hot-swaps detector |
| SyncWorker | `sync_worker.py` | Background daemon (syncs picks every 30s, polls models every 1hr) |
| DisplayServer | `display_server.py` | FastAPI with WebSocket + MJPEG endpoints |
| FrameStore | `frame_store.py` | Thread-safe frame buffer per bay |
| Models | `models.py` | Dataclasses: BayStatus, Detection, PickOrder, PickEvent |
| Config | `config.py` | Configuration from environment variables |

**Entry point:** `python -m local_agent.main`

### 4. Detection & Pick Verification

**Camera Setup:**
- Platform-aware backend: AVFoundation (macOS), DirectShow (Windows), V4L2 (Linux)
- Resolution tiers: 4K → 1080p → 720p (auto-fallback)
- Frame rate: configurable (default 10 FPS)
- Frame queue: 3 frames max (drops oldest to stay current)

**Detection (metwall.onnx):**
- Model: YOLOv8n trained on 150 SKU classes
- Class format: `SKU__color` (e.g., `STL-P-100-BK__black`)
- Input: 640×640px, confidence threshold 0.25, IOU threshold 0.45
- Backend 1: ultralytics (dev/Docker)
- Backend 2: pure onnxruntime (standalone Mac app)

**Detection output:**
```
Detection(sku, color, confidence, bbox=(x1, y1, x2, y2))
```

**Pick verification flow:**
1. Modula WMS sends active pick order (order_id, sku, qty, tray_id)
2. Camera captures "before" frame → detector runs → before detections
3. Wait 1.5 seconds for operator/robot to pick
4. Camera captures "after" frame → detector runs → after detections
5. PickVerifier compares before/after SKU counts:
   - **correct** — Expected SKU removed, qty matches order
   - **short** — Expected SKU removed, qty less than ordered
   - **wrong** — Different SKU removed
6. PickEvent generated → queued in SQLite → synced to cloud

**Data model:**
```
PickEvent(order_id, sku, qty_picked, bay_id, worker_id, result, timestamp, synced)
```

### 5. Configuration & Integration

**Environment variables (.env):**

| Variable | Default | Description |
|----------|---------|-------------|
| MODEL_PATH | (required) | Path to metwall.onnx |
| CAMERA_BAY1 | 0 | Camera device ID for bay 1 |
| CAMERA_BAY2 | 1 | Camera device ID for bay 2 |
| MODULA_WMS_URL | (required) | Modula WMS API base URL |
| CLOUD_SYNC_URL | (required) | Catalyst cloud endpoint |
| DETECTION_FPS | 10 | Detection loop frame rate |
| WEBSOCKET_PORT | 8765 | Display overlay port |
| DB_PATH | picks.db | SQLite offline queue path |
| MODEL_DIR | models | ONNX model directory |
| SYNC_INTERVAL_SEC | 30 | Cloud sync frequency |
| MODEL_POLL_INTERVAL_SEC | 3600 | Model update check frequency |

**Integrations:**
- **Modula WMS:** REST API — fetch active orders, confirm picks
- **Zoho Catalyst:** Push pick events via `/picks/sync`, check model updates via `/models/latest`
- **Display Overlay:** WebSocket broadcast of bay status, detections, pick results
- **MJPEG Stream:** `/bay/{bay_id}/video` for live camera feed

**Resilience:**
- Detection/recording always continues even if cloud is unreachable
- Unsynced picks stay in SQLite OfflineQueue
- SyncWorker retries every 30 seconds
- Zero data loss during network outages

---

## Part C — Process 3: Video Recorder (New)

### 6. Video Pipeline

Three-stage flow: record locally → upload to cloud → extract clips on demand.

**Stage 1 — Local Recording:**
- H.264 encoding via OpenCV VideoWriter
- Resolution: 1920×1080 (Full HD), configurable up to 4K
- Frame rate: 15 FPS (configurable)
- Bitrate: ~2 Mbps per camera
- Split into 5-minute segments per camera
- Filename: `cam{id}_{YYYY-MM-DD}_{HH-mm-ss}.mp4`

**Stage 2 — Cloud Upload:**
- Background upload queue (non-blocking to recording)
- Uploads completed segments to Catalyst File Store
- Retry on network failure (exponential backoff, same pattern as pick sync)
- Mark `uploaded=true` in local DB after success

**Stage 3 — Evidence Clip Extraction (on-demand):**
- User searches for an event in admin dashboard
- System locates event → video_segment_id + video_offset_sec
- Extracts ±30 second clip from the segment
- Clip uploaded separately to cloud, retained indefinitely
- Returns cloud_url for in-browser playback

**Modules:**

| Module | File | Responsibility |
|--------|------|---------------|
| MultiCameraRecorder | `video/multi_camera_recorder.py` | Continuous H.264 capture from all cameras |
| VideoSegmenter | `video/video_segmenter.py` | Splits recordings into 5-minute MP4 segments |
| CloudUploader | `video/cloud_uploader.py` | Background upload queue with retry |
| RetentionManager | `video/retention_manager.py` | Enforces 60-day retention, deletes expired segments |
| ClipExtractor | `video/clip_extractor.py` | On-demand ±30s evidence clip extraction |

**Data models:**

```
VideoSegment(segment_id, camera_id, zone_id, start_time, end_time,
             duration, file_path, cloud_url, file_size, uploaded, expires_at)

EvidenceClip(clip_id, event_id, video_segment_id, clip_start, clip_end,
             cloud_url, generated_at, retained_indefinitely)
```

### 7. Storage Estimates & Retention

| Parameter | Value |
|-----------|-------|
| Cameras | 2 (bay cameras), expandable |
| Resolution | 1920×1080 |
| Frame rate | 15 FPS |
| Bitrate | ~2 Mbps per camera |
| Per camera per hour | ~900 MB |
| 2 cameras × 10hr shift | ~18 GB/day |
| 60-day retention | ~1.1 TB rolling |
| Segment size (5 min) | ~75 MB |
| Evidence clip (60s) | ~15 MB |

**Retention policy:**

| Content | Location | Duration |
|---------|----------|----------|
| Video segments | Cloud (Catalyst File Store) | 60 days, auto-deleted |
| Video segments | Local (factory machine) | 24 hours, cleaned after upload |
| Evidence clips | Cloud | Indefinite (disputes never expire) |
| Event metadata | Catalyst Datastore | Forever |

### 8. Resilience & Offline Operation

- Recording **never stops**, even if cloud is unreachable
- Segments queue locally and upload when connection restores
- 24-hour local buffer ensures no data loss during outages
- Same offline-queue retry pattern as existing pick sync
- If segment contains an important event, mark for indefinite retention

**Configuration variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| VIDEO_ENABLED | true | Enable video recording |
| VIDEO_FPS | 15 | Recording frame rate |
| VIDEO_RESOLUTION | 1920x1080 | Recording resolution |
| VIDEO_SEGMENT_MINUTES | 5 | Segment duration |
| VIDEO_LOCAL_BUFFER_HOURS | 24 | Local retention before cleanup |
| VIDEO_RETENTION_DAYS | 60 | Cloud retention period |
| VIDEO_CODEC | h264 | Video codec |
| VIDEO_BITRATE | 2000000 | Target bitrate (bps) |
| EVIDENCE_CLIP_MARGIN_SEC | 30 | Clip extraction window (±seconds) |

---

## Part D — Phase 2: Robotic Picking (New)

### 9. Robot Hardware

#### 9.1 Robot Arm Selection

A 6-axis collaborative robot arm grips aluminum profiles from the VLM tray, rotates 90° (horizontal → vertical) using its wrist joint, and places them directly into a vertical dolly rack — no tilting table needed.

**Parts handled:**
- Material: Aluminum extrusion profiles
- Length: 3 – 3.3 meters
- Width: 100mm
- Height: 20mm
- Weight: ≤ 5kg
- Surface: Smooth, flat, rigid — ideal for vacuum grip

**Recommended models:**

| Model | Reach | Payload | Price | Fit |
|-------|-------|---------|-------|-----|
| **UR20** | 1750mm | 20kg | ~$58K | Best balance of reach + payload |
| FANUC CRX-25iA | 1889mm | 25kg | ~$55K | Most reach + payload headroom |
| FANUC CRX-20iA/L | 1418mm | 20kg | ~$50K | Good fit, solid reach |

#### 9.2 Vacuum Gripper

- 500mm vacuum bar with 3-4 foam/rubber suction cups
- Grips center section of 100mm-wide aluminum profiles
- Venturi vacuum generator (no external compressor needed)
- Vacuum pressure sensor confirms grip before lifting (threshold: ≥80 kPa)
- Won't scratch aluminum surface
- Quick-release tool changer for future gripper additions

#### 9.3 Vertical Dolly Rack

- Wheeled rack with locking casters (operator rolls to next station)
- 10-15 vertical slots with rubber-padded dividers
- Slot width: 25mm (accommodates 20mm profile + clearance)
- Height: 3.5m (accommodates 3.3m profiles)
- Slot occupancy sensors (optical) confirm placement
- Rack ID barcode for traceability
- 2 racks per station (one filling, one being transported)

#### 9.4 Physical Layout

```
Top-Down View:

    ┌─────────────┐
    │  MODULA VLM  │
    │    Bay       │     ┌─────────┐
    │  ┌────────┐  │     │         │
    │  │  Tray  │  │     │  DOLLY  │
    │  │Opening │◄─┼──►  │  RACK   │
    │  │        │  │  ▲  │(vertical│
    │  └────────┘  │  │  │ slots)  │
    │              │  │  │         │
    └─────────────┘  │  └─────────┘
                     │
                   ┌─┴─┐
                   │ARM│  ← Robot base (floor-mounted)
                   │ ● │
                   └───┘

    ◄── 1.5m ──►◄─ 1.5m ─►

    Swing clearance: 1.5m radius around arm base
    Camera: Mounted above tray opening (existing VLM Vision camera)
    Floor space: ~4m² + swing clearance
```

### 10. Pick Sequence

#### 10.1 Three-Step Pick Cycle

**Step 1 — Camera Detects (~0.5s)**
1. Modula WMS presents tray with pick order
2. VLM Vision camera captures frame
3. YOLO detector identifies SKU + bounding box
4. Bounding box coordinates → tray slot XY position (via calibration matrix)
5. Pick command sent to robot controller: `{slot_x, slot_y, sku, qty}`

**Step 2 — Arm Picks + Rotates (~4.5s)**
1. Arm moves to tray slot XY position
2. Z-axis lowers to profile height
3. Vacuum engages — pressure sensor confirms grip (≥80 kPa)
4. Arm lifts profile clear of tray dividers
5. 6-axis wrist rotates 90° (horizontal → vertical)
6. Profile now hanging vertical, gripped at center of gravity

**Step 3 — Place in Rack (~3s)**
1. Arm traverses to next open rack slot
2. Lowers profile into slot
3. Vacuum releases
4. Slot sensor confirms profile in place
5. Arm returns to home position

**Total cycle: ~8 seconds per pick = ~450 picks/hour**
(vs. human operator ~20-30s per pick = ~120-180/hour → 2.5-3.75x improvement)

#### 10.2 Error Handling

| Error | Detection | Response |
|-------|-----------|----------|
| No grip (vacuum leak) | Pressure < 60 kPa | Retry pick, alert after 3 failures |
| Wrong part detected | Before/after YOLO mismatch | Stop, alert operator, log event |
| Part dropped mid-rotation | Vacuum pressure loss | E-stop, hold position, alert |
| Rack slot occupied | Slot occupancy sensor | Skip to next open slot |
| Rack full | All slots occupied | Pause picks, alert to swap rack |
| Arm collision | Cobot force/torque sensor | Auto-stop (built-in safety) |
| No tray presented | Camera detects no tray | Wait for Modula WMS signal |

### 11. Software Integration

#### 11.1 New Modules

```
local_agent/
├── traceability/
│   ├── zone_types/
│   │   └── robot_pick.py         # Robot pick zone handler
│   └── robot/
│       ├── robot_controller.py   # Arm motion (Modbus TCP / RTDE)
│       ├── vacuum_gripper.py     # Gripper control + pressure monitoring
│       ├── rack_manager.py       # Slot occupancy + rack ID tracking
│       └── pick_planner.py       # Bbox → tray XY → arm trajectory
```

**robot_controller.py** — Maintains TCP/Modbus connection to UR20 controller. Methods: `move_to_xyz()`, `rotate_wrist()`, `home()`, `estop()`.

**vacuum_gripper.py** — Controls vacuum solenoid, reads pressure sensor. Methods: `engage()`, `release()`, `get_pressure()`, `is_gripped()`.

**rack_manager.py** — Tracks 15 dolly rack slots. Methods: `find_next_open_slot()`, `mark_slot_filled()`, `get_rack_id()`.

**pick_planner.py** — Converts `Detection.bbox` (pixels) → `tray_slot_xy` (mm) → `arm_joint_angles` (degrees) via homography matrix from calibration.

#### 11.2 Zone Configuration (zones.json)

```json
{
  "zone_id": 1,
  "name": "VLM Robotic Pick",
  "type": "robot_pick",
  "cameras": [0],
  "models": ["metwall.onnx"],
  "robot": {
    "controller": "ur20",
    "protocol": "modbus_tcp",
    "ip": "192.168.1.100",
    "port": 502,
    "gripper": "vacuum",
    "rack_slots": 15,
    "home_position": [0, -90, 90, -90, -90, 0]
  }
}
```

#### 11.3 Events

| Event | Trigger | Data |
|-------|---------|------|
| `pick_commanded` | WMS order + camera detection | sku, tray_slot, rack_id |
| `pick_executing` | Arm starts moving | arm_position, vacuum_status |
| `pick_gripped` | Vacuum confirms grip | vacuum_pressure, grip_quality |
| `pick_rotating` | Arm rotating 90° | rotation_angle |
| `pick_placed` | Profile in rack slot | rack_slot_id, rack_id |
| `pick_verified` | Before/after detection match | sku_confirmed, confidence |
| `pick_failed` | Error in cycle | error_type, retry_count |
| `rack_full` | All slots occupied | rack_id, profile_count |
| `rack_swapped` | Operator replaced rack | old_rack_id, new_rack_id |

#### 11.4 Calibration

**Camera-to-Robot Calibration (one-time):**
1. Place checkerboard calibration target on VLM tray
2. Camera captures image → detect corners in pixels
3. Robot arm touches each corner → record XYZ position
4. Compute homography matrix (pixel → mm)
5. Store in `calibration.json`
6. Re-calibrate if camera or arm repositioned

**Tray Mapping:**
- Store divider configurations in `tray_configs.json`
- When Modula presents a tray, its ID identifies the layout
- pick_planner uses tray config to map bbox → nearest slot center

#### 11.5 Dashboard: Robot Status Panel

New widget in admin dashboard:
- Real-time arm position (joint angles)
- Current pick order (SKU, qty remaining)
- Vacuum pressure gauge
- Rack slot occupancy grid (filled/empty)
- Pick rate (picks/hour, current vs. average)
- Error log with video timestamps
- Manual controls (pause, resume, home, e-stop)

### 12. Safety & Cost Estimate

#### 12.1 Safety

| Feature | Implementation |
|---------|---------------|
| Cobot built-in safety | Force/torque limiting, auto-stop on human contact (ISO 10218-1) |
| No safety cage | Cobots rated for human collaboration (ISO/TS 15066) |
| Swing clearance | 1.5m radius, yellow floor tape + warning signs |
| E-stop buttons | Teach pendant + wall-mounted panel |
| Vacuum fail-safe | Arm stops + holds if pressure drops during transit |
| Light indicator | Green (running), yellow (paused), red (error/e-stop) |
| Speed reduction | 50% max speed when proximity sensor detects human |

#### 12.2 Cost Estimate (Phase 2)

| Component | Description | Est. Cost (USD) |
|-----------|-------------|----------------|
| Robot arm | UR20 or FANUC CRX-25iA | $50,000 – $58,000 |
| Vacuum gripper | 500mm bar + cups + venturi + sensor | $2,000 – $3,500 |
| Tool changer | Quick-release flange | $1,500 – $2,500 |
| Vertical dolly racks (×2) | 15-slot racks with sensors | $3,000 – $5,000 |
| Slot occupancy sensors | 15x optical sensors per rack | $500 – $1,000 |
| Mounting pedestal | Floor-mounted steel base | $1,000 – $2,000 |
| Pneumatic fittings | Air supply for vacuum | $500 – $1,000 |
| Safety accessories | E-stops, light stack, floor markings | $1,000 – $1,500 |
| Calibration tools | Checkerboard target + software | $500 |
| Software integration | robot_controller, pick_planner, rack_manager | $5,000 – $8,000 |
| Installation & commissioning | Mechanical + electrical + testing | $3,000 – $5,000 |
| **TOTAL PHASE 2** | | **$68,000 – $87,000** |

---

## Appendices

### Phase 2 Prerequisites

Phase 2 depends on Process 1 being fully operational:
1. VLM Vision camera + YOLO detection running and validated at target bay
2. metwall.onnx model trained with ≥90% mAP50
3. Zone type plugin system implemented (configurable zones)
4. Pick verification (before/after detection) working reliably

### Out of Scope

- Conveyor belt traceability (5-zone system with barcode scanning, pallet tracking) — deferred
- Customer-facing evidence portal (internal search only)
- Multiple VLM bays (start with one, expand later)
- Picking non-profile parts (screws, gaskets) — future gripper additions
- Autonomous rack transport (operator rolls rack manually)
- Multi-robot coordination (single arm per bay)
- Multi-factory deployment (single installation)

### Project Structure

```
vlm_vision/
├── zones.json                   # Zone flow config (per installation)
├── calibration.json             # Camera-to-robot calibration data
├── tray_configs.json            # Modula tray divider layouts
├── local_agent/
│   ├── core/                    # Shared core (refactored)
│   │   ├── camera_agent.py
│   │   ├── detector.py
│   │   ├── offline_queue.py
│   │   ├── cloud_sync_client.py
│   │   ├── config.py
│   │   └── models.py
│   ├── bay/                     # Process 1 — VLM Bay Agent
│   │   ├── main.py
│   │   ├── pick_verifier.py
│   │   ├── modula_client.py
│   │   ├── display_server.py
│   │   ├── frame_store.py
│   │   ├── model_registry.py
│   │   └── sync_worker.py
│   ├── traceability/            # Zone type plugins + robot
│   │   ├── zone_manager.py
│   │   ├── zone_handler.py
│   │   ├── zone_types/
│   │   │   ├── vlm_pick.py
│   │   │   └── robot_pick.py
│   │   └── robot/
│   │       ├── robot_controller.py
│   │       ├── vacuum_gripper.py
│   │       ├── rack_manager.py
│   │       └── pick_planner.py
│   └── video/                   # Process 3 — Video Recorder
│       ├── main.py
│       ├── multi_camera_recorder.py
│       ├── video_segmenter.py
│       ├── cloud_uploader.py
│       ├── retention_manager.py
│       └── clip_extractor.py
├── overlay/                     # Bay overlay (HTML/CSS/JS)
├── client/                      # Admin dashboard
├── models/                      # ONNX model files
├── tests/
│   ├── test_bay/
│   ├── test_video/
│   └── test_robot/
└── scripts/
    ├── run_bay.sh
    ├── run_video.sh
    └── run_all.sh
```
