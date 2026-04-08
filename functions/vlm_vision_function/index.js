// functions/vlm_vision_function/index.js
import express from "express";
import cors from "cors";
import catalyst from "zcatalyst-sdk-node";
import buildPicksRouter from "./routes/picks.js";
import buildModelsRouter from "./routes/models.js";
import buildAlertsRouter from "./routes/alerts.js";
import buildInventoryRouter from "./routes/inventory.js";

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "vlm_vision_function" });
});

// Catalyst-aware middleware: attach catalystApp to each request
app.use((req, _res, next) => {
  try {
    req.catalystApp = catalyst.initialize(req);
  } catch {
    // Running outside Catalyst (tests, local dev) — catalystApp may be null
    req.catalystApp = null;
  }
  next();
});

// Mount routes — picks needs catalystApp, passed via req
app.use("/picks", (req, res, next) => {
  const router = buildPicksRouter(req.catalystApp);
  router(req, res, next);
});
app.use("/models", buildModelsRouter());
app.use("/alerts", buildAlertsRouter());
app.use("/inventory", buildInventoryRouter());

export default app;
