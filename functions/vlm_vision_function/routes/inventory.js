// functions/vlm_vision_function/routes/inventory.js
import { Router } from "express";
import { adjustInventory } from "../services/zoho_inventory.js";

export default function buildInventoryRouter() {
  const router = Router();

  router.post("/adjust", async (req, res) => {
    const { sku, qty, reason, access_token } = req.body;
    if (!sku || !qty || !access_token) {
      return res.status(400).json({ error: "sku, qty, and access_token are required" });
    }

    const result = await adjustInventory(access_token, { sku, qty, reason: reason || "VLM pick" });

    if (result.ok) {
      res.json({ adjusted: true, sku, qty });
    } else {
      res.status(502).json({ adjusted: false, error: "Zoho API error", details: result.data });
    }
  });

  return router;
}
