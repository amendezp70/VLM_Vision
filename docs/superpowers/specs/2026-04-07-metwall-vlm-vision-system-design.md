# Metwall VLM Vision System — Design Spec

**Date:** 2026-04-07
**Client:** Metwall Design Solutions Inc.
**Status:** Approved for implementation

---

## 1. Problem Statement

Metwall uses Modula Vertical Lift Modules (VLMs) for parts storage and picking. Workers manually identify and pick parts from trays, with no automated verification. This leads to pick errors, inaccurate inventory, and no audit trail. The system must provide real-time computer vision at each picking bay to identify parts, guide picks, verify correctness, and sync inventory to Zoho.

---

## 2. Scope

- 2 Modula VLM units, each with a dedicated camera and LED light
- 150 SKUs across part types: steel profiles, aluminum profiles, door locks, shims, gaskets, screws
- Parts exist in multiple colors; color is part of the SKU identity
- Real-time pick verification (not batch)
- Integration with Zoho Inventory via REST API
- Existing product catalog photos available for model training

---

## 3. Architecture: Hybrid Edge-Cloud

Two layers operate together. The local PC handles real-time detection and display. The cloud handles model management, Zoho sync, analytics, and alerts.

### 3.1 Local PC (on-site, shared across both bays)

One PC serves both Modula units over the local network.

**Components:**

| Component | Responsibility |
|---|---|
| Camera Agent | Captures frames from both cameras at 5–10 fps via OpenCV |
| YOLO Detector | Runs YOLOv8n ONNX model on CPU; detects SKU + color + count per frame |
| Pick Verifier | Compares before/after frames to identify which part was removed; matches against active pick order |
| Display Overlay Server | WebSocket server pushing live bounding boxes and pick instructions to each bay's browser-based overlay |
| Offline Queue | SQLite store for confirmed picks; syncs to cloud when internet is restored |
| Modula WMS Client | Receives pick orders from Modula WMS API; triggers tray request |

**Hardware spec (minimum):**
- Intel i7 (12th gen+) or equivalent
- 16 GB RAM
- 512 GB SSD
- No GPU required (ONNX CPU inference is sufficient at 5–10 fps)
- Windows 10/11 or Ubuntu 22.04

### 3.2 Cloud (FastAPI backend + React dashboard)

Deployed on AWS or Google Cloud Run (containerized, auto-scaling).

**Components:**

| Component | Responsibility |
|---|---|
| Model Registry | Stores versioned ONNX models; pushes updates to local PC on new release |
| Training Pipeline | Accepts uploaded part images; runs YOLOv8 fine-tuning; validates mAP; promotes model on pass |
| Zoho Sync Service | Converts confirmed picks to Zoho Inventory API calls; handles retries and conflict resolution |
| Alert Service | Fires wrong-pick and short-pick notifications via email or Zoho Cliq webhook |
| Admin Dashboard | React web app for pick history, per-SKU detection accuracy, worker performance, and inventory levels |

### 3.3 Hardware per Bay

| Item | Spec | Notes |
|---|---|---|
| Camera | 4K USB (e.g. Logitech BRIO or industrial equivalent) | Mounted overhead, ~60 cm above tray |
| Lighting | LED ring light | Eliminates shadows; consistent illumination |
| Display | Modula WMS PC screen at each bay | Browser overlay runs alongside Modula WMS; no Modula software modification |
| Network | Wired LAN to local PC | Wireless acceptable as fallback |

---

## 4. Pick Workflow (Step by Step)

1. Modula WMS sends pick order to local PC (SKU, qty, tray ID)
2. Modula retrieves tray; camera scans contents as tray arrives
3. YOLO Detector identifies all parts on tray (SKU, color, count)
4. Display Overlay highlights target part with gold bounding box and arrow
5. Worker picks part
6. Pick Verifier detects count change; confirms correct SKU was removed
7. On correct pick: display shows green confirmation; Zoho Inventory decremented; next pick loaded
8. On wrong pick: display shows red alert; supervisor notified via Zoho Cliq; Zoho not updated
9. On internet outage: pick recorded to SQLite offline queue; syncs automatically on reconnect

---

## 5. Worker Display

Browser-based overlay running full-screen on the Modula bay's existing PC screen.

**Layout:**
- Top bar: bay ID, worker name, live/offline status indicator
- Main area: live camera feed with real-time bounding boxes
  - Non-target parts: thin blue bounding box
  - Target part: gold bounding box, pulsing glow, arrow pointer, "PICK THIS" label
- Bottom bar: active pick order (SKU, description, qty needed, progress dots)
- Status bar: pick timer, remaining order items, last pick result

**States:**
- **Waiting:** tray not yet arrived; spinner shown
- **Active:** tray present; target highlighted; awaiting pick
- **Correct pick:** full-screen green flash for 1.5s; next pick loads automatically
- **Wrong pick:** full-screen red flash; audio beep; supervisor alert fired; worker must place part back before proceeding

---

## 6. Training Data Pipeline

**Initial training (one-time):**
1. Import existing catalog photos into Roboflow project
2. Label bounding boxes per SKU and color using Roboflow's annotation tool
3. Apply auto-augmentation: rotation (±30°), brightness variation, horizontal flip, partial occlusion
4. Target: 150–300 labeled instances per SKU class
5. Train YOLOv8n on cloud GPU (Google Colab or AWS p3)
6. Validate: mAP50 target ≥ 90% across all 150 SKUs
7. Export ONNX model; upload to Model Registry; push to local PC

**Adding new parts (ongoing):**
1. Upload 100+ photos of new part via Admin Dashboard
2. Cloud auto-trains incremental model update
3. On validation pass, new ONNX pushed to local PC silently

**Critical note:** Training images must include photos taken inside the actual Modula bay under real LED lighting conditions. Catalog photos alone will reduce accuracy. A one-day photo session at the bay is required before go-live.

---

## 7. Zoho Inventory Integration

**Auth:** Zoho OAuth 2.0 server-to-server (no user login prompt at runtime)

| Event | Zoho API Call |
|---|---|
| Pick confirmed | `POST /v1/inventoryadjustments` — negative quantity adjustment for picked SKU |
| New SKU added in Zoho | Webhook → trigger training pipeline notification |
| Inventory audit request | `GET /v1/items` — pull all SKUs to reconcile with local part catalog |

**Error handling:**
- HTTP 429 (rate limit): exponential backoff, max 3 retries
- HTTP 5xx: queue to SQLite offline store, retry on next sync cycle
- Stock goes negative: alert fired, no further decrements until resolved

---

## 8. Tech Stack

| Layer | Technology |
|---|---|
| Camera capture | Python 3.11, OpenCV 4.x |
| Object detection | YOLOv8n (Ultralytics), ONNX Runtime |
| Local app framework | FastAPI (WebSocket server) |
| Local data store | SQLite (offline queue) |
| Cloud API | FastAPI on Cloud Run (containerized) |
| Cloud database | PostgreSQL (pick history, audit log) |
| Admin dashboard | React 18, Tailwind CSS |
| Model training | Ultralytics YOLOv8, Roboflow |
| Model storage | AWS S3 or GCS bucket |
| Zoho integration | Zoho Inventory REST API v1, OAuth 2.0 |
| Alerts | Zoho Cliq webhook or SMTP |
| Deployment | Docker Compose (local), Cloud Run (cloud) |

---

## 9. Out of Scope

- Barcode or QR scanning (vision-only system)
- Mobile app for workers
- Integration with other Zoho products (CRM, Books, etc.) — Inventory only
- Automated robotic picking (system is advisory only; humans pick)
- Multi-site deployment (single Metwall facility)

---

## 10. Open Questions

- Which cloud provider does Metwall prefer (AWS, GCP, Azure)?
- Does the Modula WMS support webhooks or only polling for pick orders?
- What is Metwall's internet connection reliability at the facility?
- Who manages the Admin Dashboard and model retraining (internal IT or vendor)?

---

## 11. Success Criteria

| Metric | Target |
|---|---|
| Pick verification accuracy | ≥ 95% correct picks detected accurately |
| False positive rate (wrong OK) | < 1% |
| Detection latency | < 150ms from tray arrival to highlight |
| Zoho sync lag | < 5 seconds after confirmed pick |
| Offline resilience | No data loss on internet outage up to 8 hours |
| Model coverage | All 150 SKUs detected at mAP50 ≥ 90% |
