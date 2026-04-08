// functions/vlm_vision_function/routes/alerts.js
import { Router } from "express";
import { sendPickAlert } from "../services/cliq_alert.js";

export default function buildAlertsRouter() {
  const router = Router();

  router.post("/pick", async (req, res) => {
    const { order_id, sku, result, bay_id, worker_id } = req.body;
    if (!order_id || !sku || !result) {
      return res.status(400).json({ error: "order_id, sku, and result are required" });
    }

    const sent = await sendPickAlert({ order_id, sku, result, bay_id, worker_id });

    res.json({ alerted: sent, result });
  });

  return router;
}
