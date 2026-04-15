// functions/vlm_vision_function/routes/video.js
import { Router } from "express";
import {
  insertVideoSegment,
  getVideoSegments,
  deleteExpiredSegments,
  insertEvidenceClip,
  getEvidenceClipByEvent,
} from "../services/video_datastore.js";

export default function buildVideoRouter(catalystApp) {
  const router = Router();

  // ── Video Segments ──────────────────────────────────────────

  // Register an uploaded video segment
  router.post("/segments", async (req, res) => {
    const segment = req.body;
    if (!segment.segment_id || !segment.cloud_url) {
      return res.status(400).json({ error: "segment_id and cloud_url are required" });
    }
    const row = await insertVideoSegment(catalystApp, segment);
    res.json({ ok: true, segment: row });
  });

  // List segments with optional filters
  router.get("/segments", async (req, res) => {
    const camera_id = req.query.camera_id ? parseInt(req.query.camera_id, 10) : null;
    const start = req.query.start ? parseInt(req.query.start, 10) : null;
    const end = req.query.end ? parseInt(req.query.end, 10) : null;
    const limit = parseInt(req.query.limit || "50", 10);
    const segments = await getVideoSegments(catalystApp, { camera_id, start, end, limit });
    res.json({ segments, count: segments.length });
  });

  // Delete expired segments (called by retention manager or cron)
  router.delete("/segments/expired", async (req, res) => {
    const now = Date.now() / 1000; // POSIX epoch seconds
    const result = await deleteExpiredSegments(catalystApp, now);
    res.json({ ok: true, ...result });
  });

  // ── Evidence Clips ──────────────────────────────────────────

  // Register a generated evidence clip
  router.post("/clips", async (req, res) => {
    const clip = req.body;
    if (!clip.clip_id || !clip.event_id || !clip.cloud_url) {
      return res.status(400).json({ error: "clip_id, event_id, and cloud_url are required" });
    }
    const row = await insertEvidenceClip(catalystApp, clip);
    res.json({ ok: true, clip: row });
  });

  // Get evidence clip for a specific event
  router.get("/clips/:event_id", async (req, res) => {
    const clip = await getEvidenceClipByEvent(catalystApp, req.params.event_id);
    if (!clip) {
      return res.status(404).json({ error: "No evidence clip found for this event" });
    }
    res.json({ clip });
  });

  // Request clip extraction (queues the work — local agent picks it up)
  router.post("/extract", async (req, res) => {
    const { event_id, segment_id, offset_sec } = req.body;
    if (!event_id || !segment_id || offset_sec == null) {
      return res.status(400).json({ error: "event_id, segment_id, and offset_sec are required" });
    }
    // In production, this would write to a queue/topic that the local agent polls.
    // For now, return the extraction request as acknowledged.
    res.json({
      ok: true,
      extraction: { event_id, segment_id, offset_sec, status: "queued" },
    });
  });

  return router;
}
