# VLM Vision — Catalyst Cloud Functions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Zoho Catalyst serverless functions that receive pick events from the local PC, store them in Catalyst Datastore, sync inventory adjustments to Zoho Inventory, fire alerts on wrong/short picks via Zoho Cliq, and serve the model registry endpoint.

**Architecture:** A new Catalyst Advanced I/O function (`vlm_vision_function`) alongside the existing `email_ai_assistant_function`. Express routes handle pick sync, model registry, alert dispatch, and inventory reconciliation. Catalyst Datastore stores pick history. Zoho Inventory REST API handles stock adjustments. Zoho Cliq incoming webhook fires alerts.

**Tech Stack:** Node.js 20, Express, zcatalyst-sdk-node, Zoho Inventory REST API v1, Zoho Cliq webhook

---

## File Structure

```
functions/
└── vlm_vision_function/
    ├── catalyst-config.json     # NEW: Catalyst function config
    ├── package.json             # NEW: dependencies
    ├── index.js                 # NEW: Express app — route wiring + Catalyst bootstrap
    ├── routes/
    │   ├── picks.js             # NEW: POST /picks/sync — receive + store pick events
    │   ├── models.js            # NEW: GET /models/latest — model version registry
    │   ├── alerts.js            # NEW: POST /alerts/pick — fire Cliq alert for wrong/short picks
    │   └── inventory.js         # NEW: POST /inventory/adjust — Zoho Inventory adjustment
    ├── services/
    │   ├── datastore.js         # NEW: Catalyst Datastore CRUD for pick_events table
    │   ├── zoho_inventory.js    # NEW: Zoho Inventory API client with retry logic
    │   └── cliq_alert.js        # NEW: Zoho Cliq webhook sender
    └── tests/
        ├── datastore.test.js    # NEW: unit tests for datastore service
        ├── picks.test.js        # NEW: unit tests for picks route
        ├── inventory.test.js    # NEW: unit tests for inventory service
        └── alerts.test.js       # NEW: unit tests for alert service
catalyst.json                    # MODIFY: add vlm_vision_function to targets
```

**Dependency on Plans 1–3:** The local PC's `CloudSyncClient` calls `POST /picks/sync` and `GET /models/latest` — these are the endpoints we implement here.

---

## Task 1: Scaffold vlm_vision_function

**Files:**
- Modify: `catalyst.json`
- Create: `functions/vlm_vision_function/catalyst-config.json`
- Create: `functions/vlm_vision_function/package.json`
- Create: `functions/vlm_vision_function/index.js`

- [ ] **Step 1: Register the new function in catalyst.json**

In the root `catalyst.json`, add `"vlm_vision_function"` to the targets array:

```json
{
  "functions": {
    "targets": [
      "email_ai_assistant_function",
      "vlm_vision_function"
    ],
    "ignore": [],
    "source": "functions"
  },
  "client": {
    "source": "client"
  }
}
```

- [ ] **Step 2: Create catalyst-config.json**

```json
{
  "deployment": {
    "name": "vlm_vision_function",
    "stack": "node20",
    "type": "advancedio",
    "env_variables": {
      "ZOHO_INVENTORY_ORG_ID": "",
      "ZOHO_CLIQ_WEBHOOK_URL": "",
      "MODEL_CURRENT_VERSION": "v1",
      "MODEL_DOWNLOAD_URL": ""
    }
  },
  "execution": {
    "main": "index.js"
  }
}
```

- [ ] **Step 3: Create package.json**

```json
{
  "name": "vlm_vision_function",
  "version": "1.0.0",
  "main": "index.js",
  "type": "module",
  "scripts": {
    "test": "node --experimental-vm-modules node_modules/.bin/jest --forceExit"
  },
  "dependencies": {
    "cors": "^2.8.5",
    "express": "^4.22.1",
    "zcatalyst-sdk-node": "latest"
  },
  "devDependencies": {
    "@jest/globals": "^29.7.0",
    "jest": "^29.7.0"
  }
}
```

- [ ] **Step 4: Create index.js with Express skeleton**

```javascript
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
```

- [ ] **Step 5: Install dependencies**

```bash
cd functions/vlm_vision_function && npm install
```

- [ ] **Step 6: Commit**

```bash
git add catalyst.json functions/vlm_vision_function/catalyst-config.json functions/vlm_vision_function/package.json functions/vlm_vision_function/index.js
git commit -m "feat: vlm-catalyst scaffold vlm_vision_function with Express skeleton"
```

---

## Task 2: Datastore Service

**Files:**
- Create: `functions/vlm_vision_function/services/datastore.js`
- Create: `functions/vlm_vision_function/tests/datastore.test.js`

- [ ] **Step 1: Write the failing tests**

```javascript
// functions/vlm_vision_function/tests/datastore.test.js
import { jest } from "@jest/globals";
import { insertPickEvent, getPickEvents, getPickStats } from "../services/datastore.js";

function mockTable() {
  const rows = [];
  return {
    insertRow: jest.fn(async (row) => {
      rows.push({ ROWID: String(rows.length + 1), ...row });
      return { ROWID: String(rows.length) };
    }),
    _rows: rows,
  };
}

function mockZCQL() {
  return {
    executeZCQLQuery: jest.fn(async (query) => {
      if (query.includes("COUNT")) {
        return [{ pick_events: { count: 42 } }];
      }
      return [
        {
          pick_events: {
            ROWID: "1",
            order_id: "PO-001",
            sku: "STL-P-100-BK",
            result: "correct",
            bay_id: 1,
            worker_id: "jmartinez",
            timestamp: 1712500000,
          },
        },
      ];
    }),
  };
}

function mockCatalystApp() {
  const table = mockTable();
  const zcql = mockZCQL();
  return {
    datastore: () => ({
      table: (name) => {
        if (name === "pick_events") return table;
        throw new Error(`Unknown table: ${name}`);
      },
    }),
    zcql: () => zcql,
    _table: table,
    _zcql: zcql,
  };
}

describe("datastore service", () => {
  test("insertPickEvent calls table.insertRow with correct fields", async () => {
    const catalystApp = mockCatalystApp();
    const event = {
      order_id: "PO-001",
      sku: "STL-P-100-BK",
      qty_picked: 1,
      bay_id: 1,
      worker_id: "jmartinez",
      result: "correct",
      timestamp: 1712500000,
    };

    const result = await insertPickEvent(catalystApp, event);

    expect(catalystApp._table.insertRow).toHaveBeenCalledTimes(1);
    const insertedRow = catalystApp._table.insertRow.mock.calls[0][0];
    expect(insertedRow.order_id).toBe("PO-001");
    expect(insertedRow.sku).toBe("STL-P-100-BK");
    expect(insertedRow.result).toBe("correct");
    expect(result).toBeDefined();
  });

  test("getPickEvents queries ZCQL with limit", async () => {
    const catalystApp = mockCatalystApp();
    const events = await getPickEvents(catalystApp, { limit: 50 });

    expect(catalystApp._zcql.executeZCQLQuery).toHaveBeenCalledTimes(1);
    const query = catalystApp._zcql.executeZCQLQuery.mock.calls[0][0];
    expect(query).toContain("pick_events");
    expect(query).toContain("50");
    expect(events.length).toBe(1);
    expect(events[0].order_id).toBe("PO-001");
  });

  test("getPickStats returns count", async () => {
    const catalystApp = mockCatalystApp();
    const stats = await getPickStats(catalystApp);

    expect(stats.total).toBe(42);
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd functions/vlm_vision_function && npx jest tests/datastore.test.js --forceExit
```

Expected: `Cannot find module '../services/datastore.js'`

- [ ] **Step 3: Implement datastore.js**

```javascript
// functions/vlm_vision_function/services/datastore.js
/**
 * Catalyst Datastore operations for the pick_events table.
 *
 * Table schema (create in Catalyst console):
 *   pick_events: order_id (text), sku (text), qty_picked (int),
 *                bay_id (int), worker_id (text), result (text),
 *                timestamp (bigint)
 */

export async function insertPickEvent(catalystApp, event) {
  const table = catalystApp.datastore().table("pick_events");
  return table.insertRow({
    order_id: event.order_id,
    sku: event.sku,
    qty_picked: event.qty_picked,
    bay_id: event.bay_id,
    worker_id: event.worker_id,
    result: event.result,
    timestamp: event.timestamp,
  });
}

export async function getPickEvents(catalystApp, { limit = 50, result = null } = {}) {
  const zcql = catalystApp.zcql();
  let query = `SELECT * FROM pick_events ORDER BY timestamp DESC LIMIT ${limit}`;
  if (result) {
    query = `SELECT * FROM pick_events WHERE result = '${result}' ORDER BY timestamp DESC LIMIT ${limit}`;
  }
  const rows = await zcql.executeZCQLQuery(query);
  return rows.map((r) => r.pick_events);
}

export async function getPickStats(catalystApp) {
  const zcql = catalystApp.zcql();
  const rows = await zcql.executeZCQLQuery(
    "SELECT COUNT(ROWID) AS count FROM pick_events"
  );
  return { total: rows[0]?.pick_events?.count ?? 0 };
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd functions/vlm_vision_function && npx jest tests/datastore.test.js --forceExit
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add functions/vlm_vision_function/services/datastore.js functions/vlm_vision_function/tests/datastore.test.js
git commit -m "feat: vlm-catalyst Datastore service for pick_events CRUD"
```

---

## Task 3: Picks Route

**Files:**
- Create: `functions/vlm_vision_function/routes/picks.js`
- Create: `functions/vlm_vision_function/tests/picks.test.js`

- [ ] **Step 1: Write the failing tests**

```javascript
// functions/vlm_vision_function/tests/picks.test.js
import { jest } from "@jest/globals";

// Mock datastore before importing route
const mockInsert = jest.fn(async () => ({ ROWID: "1" }));
jest.unstable_mockModule("../services/datastore.js", () => ({
  insertPickEvent: mockInsert,
}));

const { default: buildPicksRouter } = await import("../routes/picks.js");

import express from "express";

function makeApp() {
  const app = express();
  app.use(express.json());
  const mockCatalyst = { datastore: () => ({}), zcql: () => ({}) };
  app.use("/picks", buildPicksRouter(mockCatalyst));
  return app;
}

async function post(app, path, body) {
  const { default: request } = await import("supertest");
  return request(app).post(path).send(body).set("Content-Type", "application/json");
}

describe("POST /picks/sync", () => {
  beforeEach(() => mockInsert.mockClear());

  test("returns 200 and inserts each event", async () => {
    const app = makeApp();
    const res = await post(app, "/picks/sync", {
      events: [
        { order_id: "PO-001", sku: "STL-P-100-BK", qty_picked: 1, bay_id: 1, worker_id: "jmartinez", result: "correct", timestamp: 1712500000 },
        { order_id: "PO-002", sku: "ALUM-P-60-SL", qty_picked: 2, bay_id: 2, worker_id: "jmartinez", result: "correct", timestamp: 1712500001 },
      ],
    });

    expect(res.status).toBe(200);
    expect(res.body.synced).toBe(2);
    expect(mockInsert).toHaveBeenCalledTimes(2);
  });

  test("returns 400 when events array is missing", async () => {
    const app = makeApp();
    const res = await post(app, "/picks/sync", {});
    expect(res.status).toBe(400);
  });

  test("returns 400 when events is empty", async () => {
    const app = makeApp();
    const res = await post(app, "/picks/sync", { events: [] });
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd functions/vlm_vision_function && npm install supertest --save-dev && npx jest tests/picks.test.js --forceExit
```

Expected: `Cannot find module '../routes/picks.js'`

- [ ] **Step 3: Implement picks.js route**

```javascript
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd functions/vlm_vision_function && npx jest tests/picks.test.js --forceExit
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add functions/vlm_vision_function/routes/picks.js functions/vlm_vision_function/tests/picks.test.js
git commit -m "feat: vlm-catalyst POST /picks/sync route stores events in Datastore"
```

---

## Task 4: Model Registry Route

**Files:**
- Create: `functions/vlm_vision_function/routes/models.js`

- [ ] **Step 1: Implement models.js route**

```javascript
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
```

- [ ] **Step 2: Commit**

```bash
git add functions/vlm_vision_function/routes/models.js
git commit -m "feat: vlm-catalyst GET /models/latest returns current model version"
```

---

## Task 5: Zoho Inventory Service

**Files:**
- Create: `functions/vlm_vision_function/services/zoho_inventory.js`
- Create: `functions/vlm_vision_function/tests/inventory.test.js`

- [ ] **Step 1: Write the failing tests**

```javascript
// functions/vlm_vision_function/tests/inventory.test.js
import { jest } from "@jest/globals";

// Mock global fetch
global.fetch = jest.fn();

const { adjustInventory, fetchItems } = await import("../services/zoho_inventory.js");

describe("zoho_inventory service", () => {
  beforeEach(() => {
    global.fetch.mockReset();
    process.env.ZOHO_INVENTORY_ORG_ID = "org123";
  });

  test("adjustInventory sends POST with negative quantity", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ code: 0 }),
    });

    const result = await adjustInventory("access-token", {
      sku: "STL-P-100-BK",
      qty: 1,
      reason: "VLM pick PO-001",
    });

    expect(result.ok).toBe(true);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toContain("inventoryadjustments");
    expect(url).toContain("org123");
    const body = JSON.parse(opts.body);
    expect(body.line_items[0].quantity_adjusted).toBe(-1);
  });

  test("adjustInventory retries on 429", async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ code: 0 }) });

    const result = await adjustInventory("access-token", {
      sku: "STL-P-100-BK",
      qty: 1,
      reason: "VLM pick",
    });

    expect(result.ok).toBe(true);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  test("adjustInventory fails after max retries", async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 429, json: async () => ({}) });

    const result = await adjustInventory("access-token", {
      sku: "STL-P-100-BK",
      qty: 1,
      reason: "VLM pick",
    });

    expect(result.ok).toBe(false);
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  test("fetchItems returns item list", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ items: [{ sku: "STL-P-100-BK", stock_on_hand: 50 }] }),
    });

    const items = await fetchItems("access-token");
    expect(items.length).toBe(1);
    expect(items[0].sku).toBe("STL-P-100-BK");
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd functions/vlm_vision_function && npx jest tests/inventory.test.js --forceExit
```

Expected: `Cannot find module '../services/zoho_inventory.js'`

- [ ] **Step 3: Implement zoho_inventory.js**

```javascript
// functions/vlm_vision_function/services/zoho_inventory.js
/**
 * Zoho Inventory REST API client.
 * Uses fetch (Node 20 built-in) with exponential backoff on 429/5xx.
 */

const BASE_URL = "https://www.zohoapis.com/inventory/v1";
const MAX_RETRIES = 3;

async function withRetry(fn, retries = MAX_RETRIES) {
  for (let attempt = 0; attempt < retries; attempt++) {
    const resp = await fn();
    if (resp.ok) return { ok: true, data: await resp.json() };
    if (resp.status === 429 || resp.status >= 500) {
      const delay = Math.pow(2, attempt) * 500;
      await new Promise((r) => setTimeout(r, delay));
      continue;
    }
    return { ok: false, status: resp.status, data: await resp.json().catch(() => ({})) };
  }
  return { ok: false, status: 429, data: { error: "Max retries exceeded" } };
}

export async function adjustInventory(accessToken, { sku, qty, reason }) {
  const orgId = process.env.ZOHO_INVENTORY_ORG_ID;
  return withRetry(() =>
    fetch(`${BASE_URL}/inventoryadjustments?organization_id=${orgId}`, {
      method: "POST",
      headers: {
        Authorization: `Zoho-oauthtoken ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        date: new Date().toISOString().slice(0, 10),
        reason,
        line_items: [{ sku, quantity_adjusted: -qty }],
      }),
    })
  );
}

export async function fetchItems(accessToken) {
  const orgId = process.env.ZOHO_INVENTORY_ORG_ID;
  const resp = await fetch(`${BASE_URL}/items?organization_id=${orgId}`, {
    headers: { Authorization: `Zoho-oauthtoken ${accessToken}` },
  });
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.items || [];
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd functions/vlm_vision_function && npx jest tests/inventory.test.js --forceExit
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add functions/vlm_vision_function/services/zoho_inventory.js functions/vlm_vision_function/tests/inventory.test.js
git commit -m "feat: vlm-catalyst Zoho Inventory adjustment service with retry logic"
```

---

## Task 6: Inventory Adjustment Route

**Files:**
- Create: `functions/vlm_vision_function/routes/inventory.js`

- [ ] **Step 1: Implement inventory.js route**

```javascript
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
```

- [ ] **Step 2: Commit**

```bash
git add functions/vlm_vision_function/routes/inventory.js
git commit -m "feat: vlm-catalyst POST /inventory/adjust route for Zoho decrements"
```

---

## Task 7: Cliq Alert Service

**Files:**
- Create: `functions/vlm_vision_function/services/cliq_alert.js`
- Create: `functions/vlm_vision_function/tests/alerts.test.js`

- [ ] **Step 1: Write the failing tests**

```javascript
// functions/vlm_vision_function/tests/alerts.test.js
import { jest } from "@jest/globals";

global.fetch = jest.fn();

const { sendPickAlert } = await import("../services/cliq_alert.js");

describe("cliq_alert service", () => {
  beforeEach(() => {
    global.fetch.mockReset();
    process.env.ZOHO_CLIQ_WEBHOOK_URL = "https://cliq.zoho.com/webhook/test";
  });

  test("sendPickAlert posts formatted message to Cliq webhook", async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, status: 200 });

    const result = await sendPickAlert({
      order_id: "PO-001",
      sku: "STL-P-100-BK",
      result: "wrong",
      bay_id: 1,
      worker_id: "jmartinez",
    });

    expect(result).toBe(true);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("https://cliq.zoho.com/webhook/test");
    const body = JSON.parse(opts.body);
    expect(body.text).toContain("PO-001");
    expect(body.text).toContain("wrong");
  });

  test("sendPickAlert returns false on network error", async () => {
    global.fetch.mockRejectedValueOnce(new Error("offline"));

    const result = await sendPickAlert({
      order_id: "PO-001",
      sku: "STL-P-100-BK",
      result: "wrong",
      bay_id: 1,
      worker_id: "jmartinez",
    });

    expect(result).toBe(false);
  });

  test("sendPickAlert skips correct picks", async () => {
    const result = await sendPickAlert({
      order_id: "PO-001",
      sku: "STL-P-100-BK",
      result: "correct",
      bay_id: 1,
      worker_id: "jmartinez",
    });

    expect(result).toBe(true);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd functions/vlm_vision_function && npx jest tests/alerts.test.js --forceExit
```

Expected: `Cannot find module '../services/cliq_alert.js'`

- [ ] **Step 3: Implement cliq_alert.js**

```javascript
// functions/vlm_vision_function/services/cliq_alert.js
/**
 * Sends pick alerts to Zoho Cliq via incoming webhook.
 * Only fires for wrong or short picks — correct picks are silent.
 */

export async function sendPickAlert({ order_id, sku, result, bay_id, worker_id }) {
  if (result === "correct") return true;

  const webhookUrl = process.env.ZOHO_CLIQ_WEBHOOK_URL;
  if (!webhookUrl) return false;

  const emoji = result === "wrong" ? "🔴" : "🟡";
  const label = result === "wrong" ? "WRONG PICK" : "SHORT PICK";

  const message = {
    text: `${emoji} *${label}* — Order ${order_id}\nSKU: ${sku} | Bay ${bay_id} | Worker: ${worker_id}\nResult: ${result}`,
  };

  try {
    const resp = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message),
    });
    return resp.ok;
  } catch {
    return false;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd functions/vlm_vision_function && npx jest tests/alerts.test.js --forceExit
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add functions/vlm_vision_function/services/cliq_alert.js functions/vlm_vision_function/tests/alerts.test.js
git commit -m "feat: vlm-catalyst Cliq webhook alerts for wrong/short picks"
```

---

## Task 8: Alerts Route

**Files:**
- Create: `functions/vlm_vision_function/routes/alerts.js`

- [ ] **Step 1: Implement alerts.js route**

```javascript
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
```

- [ ] **Step 2: Commit**

```bash
git add functions/vlm_vision_function/routes/alerts.js
git commit -m "feat: vlm-catalyst POST /alerts/pick route fires Cliq notifications"
```

---

## Task 9: Wire All Routes into index.js

**Files:**
- Modify: `functions/vlm_vision_function/index.js`

- [ ] **Step 1: Rewrite index.js with all routes wired**

```javascript
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
```

- [ ] **Step 2: Run all tests**

```bash
cd functions/vlm_vision_function && npx jest --forceExit
```

Expected: all tests pass (3 datastore + 3 picks + 4 inventory + 3 alerts = 13)

- [ ] **Step 3: Commit**

```bash
git add functions/vlm_vision_function/index.js
git commit -m "feat: vlm-catalyst wire all routes into Express app"
```

---

## Task 10: Final Verification

- [ ] **Step 1: Run all Catalyst function tests**

```bash
cd functions/vlm_vision_function && npx jest --forceExit --verbose
```

Expected: 13 passed

- [ ] **Step 2: Run all local agent tests to confirm no regression**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: 44 passed

- [ ] **Step 3: Verify file structure**

```bash
ls functions/vlm_vision_function/routes/*.js
ls functions/vlm_vision_function/services/*.js
ls functions/vlm_vision_function/tests/*.js
```

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "chore: vlm-catalyst plan 4 complete — 13 function tests + 44 local tests passing"
```
