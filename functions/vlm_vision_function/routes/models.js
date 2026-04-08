// functions/vlm_vision_function/routes/models.js
import { Router } from "express";

export default function buildModelsRouter() {
  const router = Router();

  router.get("/latest", (_req, res) => {
    const version = process.env.MODEL_CURRENT_VERSION || "v1";
    const url = process.env.MODEL_DOWNLOAD_URL || "";

    if (!url) {
      return res.status(404).json({ error: "No model URL configured" });
    }

    res.json({ version, url });
  });

  return router;
}
