// functions/vlm_vision_function/tests/video.test.js
import { jest } from "@jest/globals";

const mockInsertSegment = jest.fn(async () => ({ ROWID: "100" }));
const mockGetSegments = jest.fn(async () => [
  { segment_id: "cam0_20260413143000", camera_id: 0, start_time: 1712500000, end_time: 1712500300, duration: 300, file_size: 75000000, cloud_url: "https://cloud.example.com/cam0.mp4", expires_at: 1717684000 },
]);
const mockDeleteExpired = jest.fn(async () => ({ deleted: 2, segment_ids: ["seg_old1", "seg_old2"] }));
const mockInsertClip = jest.fn(async () => ({ ROWID: "200" }));
const mockGetClipByEvent = jest.fn(async (_, eventId) => {
  if (eventId === "evt001") {
    return { clip_id: "clip_evt001", event_id: "evt001", segment_id: "seg001", clip_start_sec: 25, clip_end_sec: 55, cloud_url: "https://cloud.example.com/clip.mp4", generated_at: 1712500100, retained_indefinitely: true };
  }
  return null;
});

jest.unstable_mockModule("../services/video_datastore.js", () => ({
  insertVideoSegment: mockInsertSegment,
  getVideoSegments: mockGetSegments,
  deleteExpiredSegments: mockDeleteExpired,
  insertEvidenceClip: mockInsertClip,
  getEvidenceClipByEvent: mockGetClipByEvent,
}));

const { default: buildVideoRouter } = await import("../routes/video.js");

import express from "express";
import request from "supertest";

function makeApp() {
  const app = express();
  app.use(express.json());
  const mockCatalyst = { datastore: () => ({}), zcql: () => ({}) };
  app.use("/video", buildVideoRouter(mockCatalyst));
  return app;
}

// ── Video Segments ──────────────────────────────────────────

describe("POST /video/segments", () => {
  beforeEach(() => mockInsertSegment.mockClear());

  test("registers a segment and returns 200", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/segments")
      .send({
        segment_id: "cam0_20260413143000",
        camera_id: 0,
        start_time: 1712500000,
        end_time: 1712500300,
        duration: 300,
        file_size: 75000000,
        cloud_url: "https://cloud.example.com/cam0.mp4",
        expires_at: 1717684000,
      });

    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    expect(mockInsertSegment).toHaveBeenCalledTimes(1);
  });

  test("returns 400 when segment_id is missing", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/segments")
      .send({ cloud_url: "https://cloud.example.com/test.mp4" });
    expect(res.status).toBe(400);
  });

  test("returns 400 when cloud_url is missing", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/segments")
      .send({ segment_id: "seg001" });
    expect(res.status).toBe(400);
  });
});

describe("GET /video/segments", () => {
  test("returns segments list", async () => {
    const app = makeApp();
    const res = await request(app).get("/video/segments?limit=10");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.segments)).toBe(true);
    expect(res.body.count).toBe(1);
    expect(res.body.segments[0].segment_id).toBe("cam0_20260413143000");
  });

  test("passes camera_id filter", async () => {
    const app = makeApp();
    await request(app).get("/video/segments?camera_id=0&limit=5");
    expect(mockGetSegments).toHaveBeenCalled();
  });
});

describe("DELETE /video/segments/expired", () => {
  test("deletes expired segments", async () => {
    const app = makeApp();
    const res = await request(app).delete("/video/segments/expired");
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    expect(res.body.deleted).toBe(2);
  });
});

// ── Evidence Clips ──────────────────────────────────────────

describe("POST /video/clips", () => {
  beforeEach(() => mockInsertClip.mockClear());

  test("registers a clip and returns 200", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/clips")
      .send({
        clip_id: "clip_evt001",
        event_id: "evt001",
        segment_id: "seg001",
        clip_start_sec: 25,
        clip_end_sec: 55,
        cloud_url: "https://cloud.example.com/clip.mp4",
        generated_at: 1712500100,
      });

    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    expect(mockInsertClip).toHaveBeenCalledTimes(1);
  });

  test("returns 400 when required fields missing", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/clips")
      .send({ clip_id: "clip_x" });
    expect(res.status).toBe(400);
  });
});

describe("GET /video/clips/:event_id", () => {
  test("returns clip for existing event", async () => {
    const app = makeApp();
    const res = await request(app).get("/video/clips/evt001");
    expect(res.status).toBe(200);
    expect(res.body.clip.event_id).toBe("evt001");
    expect(res.body.clip.cloud_url).toBe("https://cloud.example.com/clip.mp4");
  });

  test("returns 404 for unknown event", async () => {
    const app = makeApp();
    const res = await request(app).get("/video/clips/evt999");
    expect(res.status).toBe(404);
  });
});

describe("POST /video/extract", () => {
  test("queues extraction request", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/extract")
      .send({ event_id: "evt001", segment_id: "seg001", offset_sec: 30 });

    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
    expect(res.body.extraction.status).toBe("queued");
  });

  test("returns 400 when fields missing", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/video/extract")
      .send({ event_id: "evt001" });
    expect(res.status).toBe(400);
  });
});
