# VLM Vision — Traceability Module Design Spec

**Date:** 2026-04-11
**Status:** Approved
**Module:** Packing-to-Shipping Traceability & Evidence System
**Relationship:** New module within existing VLM Vision product

---

## 1. Purpose & Business Goals

Build a traceability system that captures video evidence of the entire packing-to-shipping process at Metwall. The system generates verifiable proof that products were correctly packed, labeled, palletized, and loaded onto trucks.

**Business objectives:**
- Generate visual evidence of every shipment to resolve customer/retailer disputes
- Reduce claims of missing or incorrect items by providing timestamped video proof
- Protect against non-payment disputes with irrefutable loading evidence
- Dual barcode verification (camera + scanner) to catch labeling errors before shipping

## 2. System Architecture

### 2.1 Modular Services (Three Processes)

The traceability module runs as three separate processes sharing a core library. This isolates video recording (resource-intensive) from AI inference and keeps the existing VLM Bay Agent untouched.

**Process 1 — VLM Bay Agent (existing, unchanged):**
- CameraAgent (bay cameras)
- Detector (YOLOv8 ONNX — metwall.onnx)
- PickVerifier, ModulaClient
- Display overlay (WebSocket)

**Process 2 — Traceability Agent (new):**
- ZoneManager — orchestrates 5 zones
- BarcodeReader — camera-based (YOLO + pyzbar) and USB scanner input
- PalletTracker — tracks pallet assembly start/end, box count
- EventCorrelator — matches camera + scanner barcodes within 5s window
- EvidenceGenerator — requests clip extraction from video recorder
- Detector — loads barcode.onnx, box_state.onnx, pallet.onnx

**Process 3 — Video Recorder (new):**
- MultiCameraRecorder — continuous H.264 capture from all zone cameras
- VideoSegmenter — splits recordings into 5-minute segments
- CloudUploader — background upload to Catalyst File Store with retry
- RetentionManager — enforces 60-day retention, deletes expired segments
- ClipExtractor — extracts ±30s evidence clips on demand

**Shared Core Library (refactored from existing modules):**
- camera_agent, detector, offline_queue, cloud_sync_client, config, models, display_server

**Inter-process communication:**
- SQLite event queue (same pattern as existing offline_queue)
- Filesystem signals for clip extraction requests (write request → clip appears)

### 2.2 Cloud Backend (Zoho Catalyst)

Extends the existing Catalyst deployment:
- **Functions:** New routes for events, shipments, pallets, boxes, evidence clips, video segments
- **Datastore:** New tables for shipments, pallets, boxes, zone_events, video_segments, evidence_clips
- **File Store:** Video segment storage (5-min MP4 files), evidence clip storage
- **Admin Dashboard:** 3 new tabs (Traceability Search, Live Zones, Video Archive)

## 3. Camera Zones (Configurable)

Zones are fully configurable — add, remove, or reorder them to match any manufacturing process. Each installation defines its own flow via a `zones.json` config file. The system ships with a library of **zone types** that can be composed into any sequence.

### 3.1 Zone Types (Built-in Library)

Each zone type defines its capabilities: which AI models it loads, what events it generates, and what hardware it supports.

| Zone Type | Purpose | AI Models | Events | Hardware |
|-----------|---------|-----------|--------|----------|
| `vlm_pick` | Modula VLM bay pick verification | metwall.onnx | pick_correct, pick_wrong, pick_short | Bay camera |
| `packing` | Box packing + content verification | metwall.onnx, box_state.onnx | box_packed, content_detected, barcode_applied | Camera |
| `barcode_scan` | Barcode reading + dual verification | barcode.onnx + pyzbar | barcode_scanned, barcode_camera_read, barcode_match/mismatch | Camera + USB scanner (optional) |
| `sealing` | Confirm box is sealed/taped | box_state.onnx | box_sealed, seal_verified | Camera |
| `crating` | Crating/special packaging verification | box_state.onnx | crate_packed, crate_sealed | Camera |
| `quality_check` | Visual quality inspection checkpoint | (custom model) | qc_passed, qc_failed, qc_flagged | Camera |
| `pallet_assembly` | Track boxes placed on pallets | pallet.onnx | pallet_started, box_placed_on_pallet, pallet_completed | Camera |
| `staging` | Staging area / holding before loading | pallet.onnx | pallet_staged, pallet_released | Camera |
| `truck_loading` | Confirm pallet loaded + departure | pallet.onnx | pallet_loaded, shipment_departed | Camera |
| `custom` | User-defined zone with custom events | (configurable) | (configurable) | Camera |

### 3.2 Zone Configuration (zones.json)

Each installation defines its flow as an ordered list of zones:

```json
{
  "zones": [
    {
      "zone_id": 1,
      "name": "VLM Bay Pick",
      "type": "vlm_pick",
      "cameras": [0, 1],
      "enabled": true,
      "models": ["metwall.onnx"],
      "scanner": null
    },
    {
      "zone_id": 2,
      "name": "Packing Station",
      "type": "packing",
      "cameras": [2],
      "enabled": true,
      "models": ["metwall.onnx", "box_state.onnx"],
      "scanner": null
    },
    {
      "zone_id": 3,
      "name": "Conveyor Scan",
      "type": "barcode_scan",
      "cameras": [3],
      "enabled": true,
      "models": ["barcode.onnx"],
      "scanner": "/dev/ttyUSB0"
    },
    {
      "zone_id": 4,
      "name": "Box Sealing",
      "type": "sealing",
      "cameras": [4],
      "enabled": true,
      "models": ["box_state.onnx"],
      "scanner": null
    },
    {
      "zone_id": 5,
      "name": "Pallet Assembly",
      "type": "pallet_assembly",
      "cameras": [5],
      "enabled": true,
      "models": ["pallet.onnx"],
      "scanner": null
    },
    {
      "zone_id": 6,
      "name": "Truck Loading",
      "type": "truck_loading",
      "cameras": [6],
      "enabled": true,
      "models": ["pallet.onnx"],
      "scanner": null
    }
  ]
}
```

### 3.3 Example Configurations

**Metwall Full Flow (6 zones):**
`vlm_pick → packing → barcode_scan → sealing → pallet_assembly → truck_loading`

**Simple Warehouse (3 zones):**
`packing → barcode_scan → truck_loading`

**With Crating (7 zones):**
`vlm_pick → packing → crating → barcode_scan → sealing → pallet_assembly → truck_loading`

**Quality-Critical (5 zones):**
`packing → quality_check → barcode_scan → pallet_assembly → truck_loading`

### 3.4 Metwall Default Configuration

The default `zones.json` ships with this flow:

| Order | Zone Type | Name | Cameras | Scanner |
|-------|-----------|------|---------|---------|
| 1 | vlm_pick | VLM Bay Pick | Bay cameras (0, 1) | — |
| 2 | packing | Packing Station | Camera 2 | — |
| 3 | barcode_scan | Conveyor Scan | Camera 3 | USB scanner |
| 4 | sealing | Box Sealing | Camera 4 | — |
| 5 | pallet_assembly | Pallet Assembly | Camera 5 | — |
| 6 | truck_loading | Truck Loading | Camera 6 | — |

### 3.5 Dynamic Zone Management

- Zones can be enabled/disabled without restarting (hot-config via admin dashboard)
- New zone types can be added by creating a ZoneType plugin (Python class implementing the ZoneHandler interface)
- Zone order defines the expected flow — events are validated against the sequence
- A zone can have multiple cameras (e.g., pallet assembly might use 2 angles)
- Custom event types can be defined per zone for non-standard processes

## 4. Data Model

### 4.1 Entities

**Shipment:**
- shipment_id (PK), customer, order_ref, truck_plate
- departure_time, status, created_at

**Pallet:**
- pallet_id (PK), shipment_id (FK), pallet_number
- assembly_start, assembly_end, box_count
- loaded_at, status

**Box:**
- box_id (PK), barcode, pallet_id (FK), sku, qty
- packed_at, sealed_at, pallet_placed_at
- barcode_verified (bool), content_verified (bool)

**ZoneEvent:**
- event_id (PK), box_id (FK), pallet_id (FK), zone_id
- event_type, timestamp, camera_id
- barcode_camera, barcode_scanner, match_status
- confidence, video_segment_id (FK), video_offset_sec

**VideoSegment:**
- segment_id (PK), camera_id, zone_id
- start_time, end_time, duration
- file_path, cloud_url, file_size
- uploaded (bool), expires_at

**EvidenceClip:**
- clip_id (PK), event_id (FK), box_id (FK), pallet_id (FK)
- video_segment_id (FK), clip_start, clip_end
- cloud_url, generated_at
- retained_indefinitely (bool)

### 4.2 Entity Relationships

```
Shipment (1) → (N) Pallet (1) → (N) Box (1) → (N) ZoneEvent
ZoneEvent (N) → (1) VideoSegment
ZoneEvent (1) → (0..1) EvidenceClip
```

### 4.3 Event Types (by Zone Type)

Event types are defined per zone type, not per zone number. This allows any configuration to generate the correct events.

| Zone Type | Event Types |
|-----------|-------------|
| vlm_pick | pick_correct, pick_wrong, pick_short |
| packing | box_packed, content_detected, barcode_applied |
| barcode_scan | barcode_scanned, barcode_camera_read, barcode_match, barcode_mismatch |
| sealing | box_sealed, seal_verified |
| crating | crate_packed, crate_sealed |
| quality_check | qc_passed, qc_failed, qc_flagged |
| pallet_assembly | pallet_started, box_placed_on_pallet, pallet_completed |
| staging | pallet_staged, pallet_released |
| truck_loading | pallet_loaded, shipment_departed |
| custom | (user-defined) |

### 4.4 Search Indexes

- By barcode → Box → ZoneEvents → VideoSegments → EvidenceClips
- By pallet → Boxes → ZoneEvents → video timeline
- By shipment/order → Pallets → Boxes → full evidence chain
- By date range → all events, filterable by zone

## 5. Barcode Dual Verification

Any zone of type `barcode_scan` performs dual verification using two independent reads:

1. **Camera path:** Frame → YOLO barcode detection (barcode.onnx) → crop region → pyzbar decode → `barcode_camera` value
2. **Scanner path:** USB/serial barcode scanner → HID input → timestamp → `barcode_scanner` value

**EventCorrelator** matches readings within a 5-second window:
- **Match:** Both readings agree → `barcode_verified = true`
- **Mismatch:** Different values → alert event + automatic evidence clip generation
- **Partial:** Only one source read successfully → warning logged, `camera_only` or `scanner_only` status

## 6. Video Pipeline

### 6.1 Recording

- H.264 encoding via OpenCV VideoWriter
- Resolution: 1920x1080 (Full HD), configurable up to 4K
- Frame rate: 15 FPS (configurable)
- Bitrate: ~2 Mbps per camera
- Segments: 5-minute files per camera
- Filename format: `cam{id}_{YYYY-MM-DD}_{HH-mm-ss}.mp4`

### 6.2 Cloud Upload

- Background upload queue (non-blocking to recording)
- Retry on network failure (same pattern as existing pick sync)
- Mark `uploaded=true` in local DB after successful upload
- Destination: Catalyst File Store

### 6.3 Evidence Clip Extraction

- Triggered on-demand when a user searches for an event
- Locates ZoneEvent → video_segment_id + video_offset_sec
- Extracts ±30 second clip from the segment
- Clip uploaded to cloud separately
- Evidence clips retained indefinitely

### 6.4 Storage Estimates

| Parameter | Value |
|-----------|-------|
| Cameras | 5 (1 per zone) |
| Per camera per hour | ~900 MB |
| 5 cameras × 10hr shift | ~45 GB/day |
| 60-day retention | ~2.7 TB rolling |
| Segment size (5 min) | ~75 MB |
| Evidence clip (60s) | ~15 MB |

### 6.5 Retention Policy

- **Video segments:** 60 days in cloud, auto-deleted by RetentionManager
- **Local buffer:** 24 hours on factory machine, then cleaned up
- **Evidence clips:** Retained indefinitely (flagged disputes never expire)
- **Event metadata:** Kept forever in Catalyst Datastore

### 6.6 Resilience

- Recording never stops, even if cloud is unreachable
- Segments queue locally and upload when connection restores
- 24-hour local buffer ensures no data loss during outages
- Same offline-queue pattern as existing VLM pick sync

## 7. AI Models

Four ONNX models, all YOLOv8n architecture, trained via Roboflow:

| Model | Classes | Zones | Training Images | Difficulty |
|-------|---------|-------|----------------|------------|
| metwall.onnx | 150 SKU classes (SKU__color) | vlm_pick, packing | Already trained | Done |
| barcode.onnx | barcode, qr_code, label | barcode_scan | ~500 | Easy |
| box_state.onnx | box_open, box_sealed, box_taped, box_labeled | packing, sealing, crating | ~800 | Medium |
| pallet.onnx | pallet_empty, pallet_partial, pallet_full, box_on_pallet, forklift, truck_bay | pallet_assembly, staging, truck_loading | ~1,000 | Medium |

**Model management:**
- All models use existing ModelRegistry + hot-swap pattern
- Each model has its own version env var (MODEL_BARCODE_VERSION, MODEL_BOXSTATE_VERSION, MODEL_PALLET_VERSION)
- Traceability Agent loads 3 models simultaneously
- Same Roboflow training workflow as documented in existing training manual

## 8. Admin Dashboard

Three new tabs added to the existing VLM admin dashboard:

### 8.1 Traceability Search

- Search bar: barcode, pallet ID, order/shipment number, date range
- Filter by type (barcode/pallet/shipment)
- Results table: barcode, SKU, pallet, shipment, zones passed (N/total configured), barcode match status, date, actions
- Mismatches highlighted in red
- Actions: "Timeline" link → timeline view, "Clips" link → evidence playback

### 8.2 Timeline View

- Activated by clicking "Timeline" from search results
- Header: box ID, SKU, pallet, shipment
- Visual vertical timeline showing journey through all configured zones
- Each zone shows: timestamp, event details, confidence scores
- Clickable "Play Clip" button per zone → plays ±30s evidence clip in-browser
- Color-coded by zone (blue, green, orange, red, purple)

### 8.3 Live Zones

- Dynamic grid of zone cards (adapts to configured zone count) with real-time MJPEG camera feeds
- Each card shows: zone name, type, camera feed, current box/pallet info, status (Active/Waiting/Loading)
- Same WebSocket pattern as existing bay overlay but multi-zone

### 8.4 Video Archive

- Browse stored video segments by camera, zone, date
- Upload status indicators (uploaded/pending/failed)
- Manual clip extraction trigger
- Storage usage statistics

## 9. Configuration

Two config files: `.env` for global settings, `zones.json` for zone flow definition.

**zones.json** — see Section 3.2 for full format. Defines zone order, types, cameras, models, and scanners per installation.

**New environment variables** (added to existing .env):

```env
# Traceability Module
TRACEABILITY_ENABLED=true
ZONES_CONFIG_PATH=zones.json

# Barcode scanner defaults (overridden per-zone in zones.json)
BARCODE_MATCH_WINDOW_SEC=5

# Video recording
VIDEO_ENABLED=true
VIDEO_FPS=15
VIDEO_RESOLUTION=1920x1080
VIDEO_SEGMENT_MINUTES=5
VIDEO_LOCAL_BUFFER_HOURS=24
VIDEO_RETENTION_DAYS=60
VIDEO_CODEC=h264
VIDEO_BITRATE=2000000

# AI models
MODEL_BARCODE_PATH=models/barcode.onnx
MODEL_BARCODE_VERSION=v1
MODEL_BOXSTATE_PATH=models/box_state.onnx
MODEL_BOXSTATE_VERSION=v1
MODEL_PALLET_PATH=models/pallet.onnx
MODEL_PALLET_VERSION=v1

# Evidence clips
EVIDENCE_CLIP_MARGIN_SEC=30
EVIDENCE_RETAIN_INDEFINITELY=true
```

## 10. New Cloud Function Routes

Added to existing Express app in `/functions/vlm_vision_function/`:

| Method | Route | Purpose |
|--------|-------|---------|
| POST | /shipments | Create new shipment |
| GET | /shipments/:id | Get shipment with pallets and boxes |
| GET | /shipments/search | Search by order_ref, customer, date |
| POST | /pallets | Create/update pallet |
| GET | /pallets/:id | Get pallet with boxes and events |
| POST | /boxes | Register new box |
| GET | /boxes/:barcode | Get box by barcode with full event chain |
| POST | /events/sync | Batch sync zone events from local agent |
| GET | /events/timeline/:box_id | Get all events for a box ordered by zone |
| POST | /video/segments | Register uploaded video segment |
| GET | /video/segments | List segments by camera/zone/date |
| DELETE | /video/segments/expired | Clean up expired segments |
| POST | /evidence/clips | Register generated evidence clip |
| GET | /evidence/clips/:event_id | Get clip for an event |
| POST | /evidence/extract | Request clip extraction |

## 11. Project Structure

```
vlm_vision/
├── zones.json                   # Zone flow config (per installation)
├── local_agent/
│   ├── core/                    # Shared core (refactored from existing)
│   │   ├── camera_agent.py
│   │   ├── detector.py
│   │   ├── offline_queue.py
│   │   ├── cloud_sync_client.py
│   │   ├── config.py
│   │   └── models.py
│   ├── bay/                     # Process 1 — existing VLM bay agent
│   │   ├── main.py
│   │   ├── pick_verifier.py
│   │   ├── modula_client.py
│   │   ├── display_server.py
│   │   ├── frame_store.py
│   │   ├── model_registry.py
│   │   └── sync_worker.py
│   ├── traceability/            # Process 2 — new traceability agent
│   │   ├── main.py
│   │   ├── zone_manager.py       # Loads zones.json, orchestrates zone handlers
│   │   ├── zone_handler.py       # Base ZoneHandler interface
│   │   ├── zone_types/           # Zone type plugins
│   │   │   ├── vlm_pick.py
│   │   │   ├── packing.py
│   │   │   ├── barcode_scan.py
│   │   │   ├── sealing.py
│   │   │   ├── crating.py
│   │   │   ├── quality_check.py
│   │   │   ├── pallet_assembly.py
│   │   │   ├── staging.py
│   │   │   ├── truck_loading.py
│   │   │   └── custom.py
│   │   ├── barcode_reader.py
│   │   ├── pallet_tracker.py
│   │   ├── event_correlator.py
│   │   ├── evidence_generator.py
│   │   └── zone_display_server.py
│   └── video/                   # Process 3 — new video recorder
│       ├── main.py
│       ├── multi_camera_recorder.py
│       ├── video_segmenter.py
│       ├── cloud_uploader.py
│       ├── retention_manager.py
│       └── clip_extractor.py
├── overlay/                     # Existing bay overlay
├── client/                      # Admin dashboard (extended)
├── models/                      # ONNX model files
├── tests/
│   ├── test_bay/               # Existing tests (moved)
│   ├── test_traceability/      # New tests
│   └── test_video/             # New tests
└── scripts/
    ├── run_bay.sh              # Start Process 1
    ├── run_traceability.sh     # Start Process 2
    ├── run_video.sh            # Start Process 3
    └── run_all.sh              # Start all 3 processes
```

## 12. Testing Strategy

- Unit tests for each new module (zone_manager, barcode_reader, pallet_tracker, event_correlator, evidence_generator, video_segmenter, clip_extractor, retention_manager)
- Integration tests for barcode dual verification flow
- Integration tests for event → video segment → clip extraction pipeline
- Cloud function tests for all new routes
- End-to-end test with mock cameras simulating full zone traversal
- Same mock-first (London School TDD) approach as existing tests

---

# PHASE 2: Robotic Picking Module

## 14. Overview — Automated VLM Picking

Phase 2 adds a collaborative robot arm to one Modula VLM bay, replacing the human operator for the picking (kitting) stage of manufacturing. The robot uses VLM Vision's existing camera + AI detection as its eyes — Phase 1 builds the robot's vision system, Phase 2 adds the arms.

**What the robot does:**
- Receives pick orders from the Modula WMS (same as human operator today)
- VLM Vision camera identifies the correct SKU + exact tray slot position
- Robot arm grips the aluminum profile at its center of gravity
- Lifts, rotates 90° in air (horizontal → vertical), places into a vertical dolly rack
- VLM Vision verifies the correct part was removed (before/after detection)

**Parts handled:**
- Material: Aluminum profiles (extrusions)
- Length: 3 - 3.3 meters
- Width: 100mm
- Height: 20mm
- Weight: ≤ 5kg
- Surface: Smooth, flat, rigid — ideal for vacuum grip

## 15. Robot Hardware

### 15.1 Robot Selection: Collaborative Robot Arm

A 6-axis cobot arm eliminates the need for a separate tilting mechanism. The arm grips the profile flat from the VLM tray, rotates it 90° using its wrist joint, and places it vertically into the dolly rack — all in one motion.

**Recommended models:**

| Model | Reach | Payload | Price | Fit |
|-------|-------|---------|-------|-----|
| UR20 | 1750mm | 20kg | ~$58K | Best balance of reach + payload |
| FANUC CRX-25iA | 1889mm | 25kg | ~$55K | Most reach + payload headroom |
| FANUC CRX-20iA/L | 1418mm | 20kg | ~$50K | Good fit, solid reach |

**Why a cobot arm over a gantry system:**

| Factor | Gantry + Tilting Table | Robot Arm |
|--------|----------------------|-----------|
| Systems to build | 3 (gantry + table + transfer) | 1 |
| Steps per pick | 5 | 3 |
| Cycle time | ~12.5 seconds | ~8 seconds |
| Picks/hour | ~290 | ~450 |
| Floor space | 14m² | 4m² + swing clearance |
| Rotation | Separate tilting table | Built-in (6-axis wrist) |
| Cost | $25-40K | $55-65K |
| Maintenance | 3 systems | 1 sealed unit |
| Flexibility | Fixed to one task | Reprogrammable |
| Safety | Needs light curtains | Human-safe cobot, no cage |

### 15.2 End Effector (Gripper)

Vacuum gripper bar attached to the arm's tool flange:
- 500mm vacuum bar with 3-4 suction cups (grips center section of profile)
- Venturi vacuum generator (no external compressor needed — uses the arm's pneumatic line)
- Vacuum pressure sensor confirms grip before lifting
- Foam/rubber cup material — won't scratch aluminum surface
- Quick-release tool changer for future gripper swaps

### 15.3 Vertical Dolly Rack

- Wheeled rack with locking casters
- 10-15 vertical slots with rubber-padded dividers
- Slot width: 25mm (accommodates 20mm profile with clearance)
- Height: 3.5m (accommodates 3.3m profiles)
- Slot occupancy sensors (optical or mechanical) confirm placement
- Rack ID barcode for traceability (which profiles on which rack)
- Operator rolls loaded rack to packing zone (Zone 2 in traceability flow)

### 15.4 Physical Layout

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
                   │ARM│  ← Robot base
                   │ ● │    (floor-mounted)
                   └───┘
                   
    ◄── 1.5m ──►◄─ 1.5m ─►
    
    Swing clearance: 1.5m radius around arm base
    Camera: Mounted above tray opening (existing VLM Vision camera)
```

## 16. Pick Sequence

### 16.1 Three-Step Pick Cycle

**Step 1 — Camera Detects (0.5s)**
1. Modula WMS presents tray with pick order
2. VLM Vision camera captures frame
3. YOLO detector identifies SKU + bounding box
4. Bounding box coordinates → tray slot XY position
5. Pick command sent to robot controller: `{slot_x, slot_y, sku, qty}`

**Step 2 — Arm Picks + Rotates (4.5s)**
1. Arm moves to tray slot XY position
2. Z-axis lowers to profile height
3. Vacuum engages — pressure sensor confirms grip
4. Arm lifts profile clear of tray dividers
5. 6-axis wrist rotates 90° (horizontal → vertical)
6. Profile now hanging vertical, gripped at center of gravity

**Step 3 — Place in Rack (3s)**
1. Arm traverses to next open rack slot
2. Lowers profile into slot
3. Vacuum releases
4. Slot sensor confirms profile in place
5. Arm returns to home position

**Total cycle: ~8 seconds per pick = ~450 picks/hour**

### 16.2 Error Handling

| Error | Detection | Response |
|-------|-----------|----------|
| Vacuum leak (no grip) | Pressure sensor < threshold | Retry pick, alert after 3 failures |
| Wrong part detected | Before/after YOLO mismatch | Stop, alert operator, log event |
| Part dropped during rotation | Vacuum pressure loss mid-cycle | E-stop, alert, log with video |
| Rack slot occupied | Slot occupancy sensor | Skip to next open slot |
| Rack full | All slot sensors occupied | Pause picks, alert operator to swap rack |
| Arm collision | Cobot force/torque sensor | Auto-stop (built-in cobot safety) |
| VLM tray not presented | No tray detected by camera | Wait for Modula WMS signal |

## 17. VLM Vision Software Integration

### 17.1 New Zone Type: `robot_pick`

Added to the configurable zone type library:

```json
{
  "zone_id": 1,
  "name": "VLM Robotic Pick",
  "type": "robot_pick",
  "cameras": [0],
  "enabled": true,
  "models": ["metwall.onnx"],
  "scanner": null,
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

### 17.2 New Module: `robot_controller.py`

```
local_agent/
└── traceability/
    ├── zone_types/
    │   └── robot_pick.py         # Robot pick zone handler
    └── robot/
        ├── robot_controller.py   # Arm motion commands (Modbus/RTDE)
        ├── vacuum_gripper.py     # Gripper control + pressure monitoring
        ├── rack_manager.py       # Track slot occupancy + rack ID
        └── pick_planner.py       # Convert bbox → tray XY → arm trajectory
```

**Key integration point:** The existing `Detector` output (`Detection.bbox`) is converted by `pick_planner.py` into arm trajectory coordinates:

```
Detection.bbox (px) → tray_slot_xy (mm) → arm_joint_angles (degrees)
```

This uses a one-time calibration: pixel-to-millimeter mapping from camera frame to physical tray coordinates.

### 17.3 Events

| Event | Trigger | Data |
|-------|---------|------|
| `pick_commanded` | WMS order received, camera detected part | sku, tray_slot, rack_id |
| `pick_executing` | Arm starts moving to tray | arm_position, vacuum_status |
| `pick_gripped` | Vacuum pressure confirms grip | vacuum_pressure, grip_quality |
| `pick_rotating` | Arm rotating profile to vertical | rotation_angle |
| `pick_placed` | Profile placed in rack slot | rack_slot_id, rack_id |
| `pick_verified` | Before/after detection confirms correct part removed | sku_confirmed, confidence |
| `pick_failed` | Any error in pick cycle | error_type, retry_count |
| `rack_full` | All slots occupied | rack_id, profile_count |
| `rack_swapped` | Operator replaced full rack with empty | old_rack_id, new_rack_id |

### 17.4 Dashboard: Robot Status Panel

New widget in the Live Zones tab:

- Real-time arm position visualization (joint angles)
- Current pick order (SKU, qty remaining)
- Vacuum pressure gauge
- Rack slot occupancy grid (filled/empty)
- Pick rate (picks/hour, current vs. average)
- Error log with video timestamps
- Manual override controls (pause, resume, home, e-stop)

## 18. Calibration & Setup

### 18.1 Camera-to-Robot Calibration

One-time procedure to map camera pixels to robot arm coordinates:

1. Place calibration target (checkerboard) on VLM tray
2. Camera captures image → detect checkerboard corners
3. Robot arm touches each corner → record arm XYZ position
4. Compute homography matrix (pixel → mm transformation)
5. Store calibration in `calibration.json`
6. Re-calibrate if camera or arm is repositioned

### 18.2 Tray Mapping

- Modula VLM trays have fixed divider positions
- Map each divider configuration to slot coordinates
- Store in `tray_configs.json` — one entry per tray layout
- When Modula presents a tray, its ID identifies the configuration

## 19. Safety

- **Cobot safety:** UR20/FANUC CRX have built-in force/torque limiting — auto-stops on human contact
- **No safety cage required** — cobots are rated for human collaboration (ISO 10218-1, ISO/TS 15066)
- **Swing clearance zone:** 1.5m radius around arm base marked on floor with yellow tape
- **E-stop buttons:** One on robot controller, one on wall-mounted panel
- **Vacuum fail-safe:** If vacuum pressure drops below threshold during transit, arm stops and holds position (profile doesn't drop)
- **Light indicator:** Green (running), yellow (paused/waiting), red (error/e-stop)
- **Speed reduction:** Arm operates at 50% max speed when proximity sensor detects human in workspace

## 20. Cost Estimate (Phase 2)

| Component | Description | Est. Cost (USD) |
|-----------|-------------|----------------|
| Robot arm | UR20 or FANUC CRX-25iA | $50,000 - $58,000 |
| Vacuum gripper | 500mm bar + cups + venturi generator | $2,000 - $3,500 |
| Tool changer | Quick-change flange (for future grippers) | $1,500 - $2,500 |
| Vertical dolly rack | 15-slot rack with sensors, 2 units | $3,000 - $5,000 |
| Robot controller | Teach pendant + I/O module | Included with arm |
| Slot occupancy sensors | 15x optical/mechanical sensors per rack | $500 - $1,000 |
| Mounting pedestal | Floor-mounted steel base for arm | $1,000 - $2,000 |
| Pneumatic fittings | Air supply for vacuum (if no factory air) | $500 - $1,000 |
| Safety accessories | E-stops, light stack, floor markings | $1,000 - $1,500 |
| Calibration tools | Checkerboard target, software setup | $500 |
| Software integration | robot_controller, pick_planner, rack_manager | $5,000 - $8,000 |
| Installation & commissioning | Mechanical + electrical + testing | $3,000 - $5,000 |
| **TOTAL** | | **$68,000 - $87,000** |

## 21. Phase 2 Prerequisites

Phase 2 depends on Phase 1 being operational:
- VLM Vision camera + YOLO detection must be running and validated at the target bay
- `metwall.onnx` model must be trained with ≥90% mAP50
- Zone type plugin system must be implemented (configurable zones)
- Pick verification (before/after detection) must be working

## 22. Out of Scope (Phase 2)

- Multiple VLM bays (start with one, expand later)
- Picking non-profile parts (screws, gaskets, hardware) — future gripper additions
- Autonomous rack transport (operator rolls rack manually)
- Integration with Modula's internal shuttle control (uses existing WMS API)
- Multi-robot coordination (single arm per bay)

---

## 23. Out of Scope (Overall)

- Customer-facing portal (internal search only for now)
- Multi-factory deployment (single installation)
- Real-time streaming to cloud (only recorded segments uploaded)
- Automatic dispute filing (manual process using evidence clips)
- Integration with ERP/WMS beyond existing Modula client
