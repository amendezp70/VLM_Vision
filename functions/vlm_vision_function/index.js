// functions/vlm_vision_function/index.js
import express from "express";
import cors from "cors";

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "vlm_vision_function" });
});

// Route imports — wired in subsequent tasks
// import picksRouter from "./routes/picks.js";
// import modelsRouter from "./routes/models.js";
// import alertsRouter from "./routes/alerts.js";
// import inventoryRouter from "./routes/inventory.js";
// app.use("/picks", picksRouter);
// app.use("/models", modelsRouter);
// app.use("/alerts", alertsRouter);
// app.use("/inventory", inventoryRouter);

export default app;
