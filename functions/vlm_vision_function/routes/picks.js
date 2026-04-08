// functions/vlm_vision_function/routes/picks.js
import { Router } from "express";
import { insertPickEvent } from "../services/datastore.js";

export default function buildPicksRouter(catalystApp) {
  const router = Router();

  router.post("/sync", async (req, res) => {
    const { events } = req.body;
    if (!Array.isArray(events) || events.length === 0) {
      return res.status(400).json({ error: "events array is required and must not be empty" });
    }

    const results = [];
    for (const event of events) {
      const row = await insertPickEvent(catalystApp, event);
      results.push(row);
    }

    res.json({ synced: results.length, ok: true });
  });

  return router;
}
