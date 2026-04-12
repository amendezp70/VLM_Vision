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

## 13. Out of Scope

- Customer-facing portal (internal search only for now)
- Multi-factory deployment (single installation)
- Real-time streaming to cloud (only recorded segments uploaded)
- Automatic dispute filing (manual process using evidence clips)
- Integration with ERP/WMS beyond existing Modula client
