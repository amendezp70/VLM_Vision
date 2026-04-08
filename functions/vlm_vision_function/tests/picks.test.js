// functions/vlm_vision_function/tests/picks.test.js
import { jest } from "@jest/globals";

// Mock datastore before importing route
const mockInsert = jest.fn(async () => ({ ROWID: "1" }));
const mockGetEvents = jest.fn(async () => [
  { order_id: "PO-001", sku: "STL-P-100-BK", result: "correct", bay_id: 1, worker_id: "jmartinez", timestamp: 1712500000, qty_picked: 1 },
]);
const mockGetStats = jest.fn(async () => ({ total: 42, correct: 38, wrong: 3, short: 1 }));

jest.unstable_mockModule("../services/datastore.js", () => ({
  insertPickEvent: mockInsert,
  getPickEvents: mockGetEvents,
  getPickStats: mockGetStats,
}));

const { default: buildPicksRouter } = await import("../routes/picks.js");

import express from "express";
import request from "supertest";

function makeApp() {
  const app = express();
  app.use(express.json());
  const mockCatalyst = { datastore: () => ({}), zcql: () => ({}) };
  app.use("/picks", buildPicksRouter(mockCatalyst));
  return app;
}

describe("POST /picks/sync", () => {
  beforeEach(() => mockInsert.mockClear());

  test("returns 200 and inserts each event", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/picks/sync")
      .send({
        events: [
          { order_id: "PO-001", sku: "STL-P-100-BK", qty_picked: 1, bay_id: 1, worker_id: "jmartinez", result: "correct", timestamp: 1712500000 },
          { order_id: "PO-002", sku: "ALUM-P-60-SL", qty_picked: 2, bay_id: 2, worker_id: "jmartinez", result: "correct", timestamp: 1712500001 },
        ],
      })
      .set("Content-Type", "application/json");

    expect(res.status).toBe(200);
    expect(res.body.synced).toBe(2);
    expect(mockInsert).toHaveBeenCalledTimes(2);
  });

  test("returns 400 when events array is missing", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/picks/sync")
      .send({})
      .set("Content-Type", "application/json");
    expect(res.status).toBe(400);
  });

  test("returns 400 when events is empty", async () => {
    const app = makeApp();
    const res = await request(app)
      .post("/picks/sync")
      .send({ events: [] })
      .set("Content-Type", "application/json");
    expect(res.status).toBe(400);
  });
});

describe("GET /picks/history", () => {
  test("returns pick events", async () => {
    const app = makeApp();
    const res = await request(app).get("/picks/history?limit=10");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.events)).toBe(true);
    expect(res.body.events.length).toBe(1);
    expect(res.body.events[0].order_id).toBe("PO-001");
  });
});

describe("GET /picks/stats", () => {
  test("returns aggregate stats", async () => {
    const app = makeApp();
    const res = await request(app).get("/picks/stats");
    expect(res.status).toBe(200);
    expect(res.body.total).toBe(42);
    expect(res.body.correct).toBe(38);
  });
});
