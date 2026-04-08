# VLM Vision — Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the admin dashboard for the VLM Vision system — a browser-based React SPA showing pick history, per-SKU detection accuracy, worker performance stats, and inventory levels. Served via Catalyst Web Hosting alongside the existing email app.

**Architecture:** A single `vlm-admin.html` file using CDN React 18 + Tailwind CSS (matching the existing `index.html` pattern — no build step). The page fetches data from the `vlm_vision_function` API endpoints. Four tab views: Pick History, SKU Accuracy, Worker Performance, and Inventory.

**Tech Stack:** React 18 (CDN), Tailwind CSS (CDN), Babel standalone (CDN), fetch API

---

## File Structure

```
client/
├── index.html              # EXISTING: email AI app (untouched)
├── vlm-admin.html          # NEW: VLM admin dashboard SPA
├── vlm-admin.css           # NEW: custom styles beyond Tailwind
└── client-package.json     # EXISTING (untouched)
```

**Dependency on Plan 4:** The dashboard calls endpoints from `vlm_vision_function`: `GET /picks/history`, `GET /picks/stats`, `GET /models/latest`. We also need to add two new read endpoints to the Catalyst function.

---

## Task 1: Add Dashboard API Endpoints to vlm_vision_function

**Files:**
- Modify: `functions/vlm_vision_function/routes/picks.js`

The existing picks route only has `POST /picks/sync`. The dashboard needs:
- `GET /picks/history` — paginated pick event list
- `GET /picks/stats` — aggregate counts by result type

- [ ] **Step 1: Write the failing tests**

Add to `functions/vlm_vision_function/tests/picks.test.js`:

```javascript
// Add these at the bottom of the existing describe block, after the POST tests:

describe("GET /picks/history", () => {
  test("returns pick events from datastore", async () => {
    const { default: buildPicksRouter } = await import("../routes/picks.js");
    const mockCatalyst = {
      zcql: () => ({
        executeZCQLQuery: jest.fn(async () => [
          {
            pick_events: {
              ROWID: "1", order_id: "PO-001", sku: "STL-P-100-BK",
              result: "correct", bay_id: 1, worker_id: "jmartinez",
              timestamp: 1712500000, qty_picked: 1,
            },
          },
        ]),
      }),
      datastore: () => ({ table: () => ({}) }),
    };
    const testApp = express();
    testApp.use(express.json());
    testApp.use("/picks", buildPicksRouter(mockCatalyst));

    const res = await request(testApp).get("/picks/history?limit=10");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.events)).toBe(true);
  });
});

describe("GET /picks/stats", () => {
  test("returns aggregate stats", async () => {
    const { default: buildPicksRouter } = await import("../routes/picks.js");
    const mockCatalyst = {
      zcql: () => ({
        executeZCQLQuery: jest.fn(async () => [{ pick_events: { count: 42 } }]),
      }),
      datastore: () => ({ table: () => ({}) }),
    };
    const testApp = express();
    testApp.use(express.json());
    testApp.use("/picks", buildPicksRouter(mockCatalyst));

    const res = await request(testApp).get("/picks/stats");
    expect(res.status).toBe(200);
    expect(res.body.total).toBeDefined();
  });
});
```

- [ ] **Step 2: Add GET /picks/history and GET /picks/stats to picks.js**

In `functions/vlm_vision_function/routes/picks.js`, add after the existing `router.post("/sync", ...)`:

```javascript
import { insertPickEvent, getPickEvents, getPickStats } from "../services/datastore.js";

// ... existing POST /sync route ...

router.get("/history", async (req, res) => {
  const limit = parseInt(req.query.limit || "50", 10);
  const result = req.query.result || null;
  const events = await getPickEvents(catalystApp, { limit, result });
  res.json({ events, count: events.length });
});

router.get("/stats", async (req, res) => {
  const stats = await getPickStats(catalystApp);
  res.json(stats);
});
```

The full updated file:

```javascript
// functions/vlm_vision_function/routes/picks.js
import { Router } from "express";
import { insertPickEvent, getPickEvents, getPickStats } from "../services/datastore.js";

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

  router.get("/history", async (req, res) => {
    const limit = parseInt(req.query.limit || "50", 10);
    const result = req.query.result || null;
    const events = await getPickEvents(catalystApp, { limit, result });
    res.json({ events, count: events.length });
  });

  router.get("/stats", async (req, res) => {
    const stats = await getPickStats(catalystApp);
    res.json(stats);
  });

  return router;
}
```

- [ ] **Step 3: Run tests to verify**

```bash
cd functions/vlm_vision_function && node --experimental-vm-modules node_modules/.bin/jest tests/picks.test.js --forceExit
```

Expected: 5 passed (3 existing + 2 new)

- [ ] **Step 4: Commit**

```bash
git add functions/vlm_vision_function/routes/picks.js functions/vlm_vision_function/tests/picks.test.js
git commit -m "feat: vlm-dashboard add GET /picks/history and /picks/stats endpoints"
```

---

## Task 2: Dashboard HTML Shell

**Files:**
- Create: `client/vlm-admin.html`

- [ ] **Step 1: Write vlm-admin.html**

```html
<!-- client/vlm-admin.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VLM Vision — Admin Dashboard</title>
  <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="vlm-admin.css">
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">
  <div id="root"></div>

  <script type="text/babel">
    const { useState, useEffect, useCallback } = React;

    // ── Config ────────────────────────────────────────────────────────
    const API_BASE = window.location.origin + "/server/vlm_vision_function";

    // ── API helpers ───────────────────────────────────────────────────
    async function fetchJSON(path) {
      const res = await fetch(API_BASE + path);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    }

    // ── Tab components ────────────────────────────────────────────────

    function PickHistory() {
      const [events, setEvents] = useState([]);
      const [filter, setFilter] = useState("");
      const [loading, setLoading] = useState(true);

      const load = useCallback(async () => {
        setLoading(true);
        try {
          const params = filter ? `?limit=100&result=${filter}` : "?limit=100";
          const data = await fetchJSON("/picks/history" + params);
          setEvents(data.events || []);
        } catch (e) {
          console.error("Failed to load picks", e);
        }
        setLoading(false);
      }, [filter]);

      useEffect(() => { load(); }, [load]);

      const resultBadge = (r) => {
        const colors = { correct: "bg-green-900 text-green-300", wrong: "bg-red-900 text-red-300", short: "bg-yellow-900 text-yellow-300" };
        return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[r] || "bg-gray-700"}`}>{r}</span>;
      };

      return (
        <div>
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-lg font-semibold">Pick History</h2>
            <select value={filter} onChange={e => setFilter(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm">
              <option value="">All results</option>
              <option value="correct">Correct</option>
              <option value="wrong">Wrong</option>
              <option value="short">Short</option>
            </select>
            <button onClick={load} className="text-sm text-blue-400 hover:text-blue-300">Refresh</button>
          </div>
          {loading ? <p className="text-gray-500">Loading...</p> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-400 text-left">
                    <th className="py-2 px-3">Order</th>
                    <th className="py-2 px-3">SKU</th>
                    <th className="py-2 px-3">Qty</th>
                    <th className="py-2 px-3">Bay</th>
                    <th className="py-2 px-3">Worker</th>
                    <th className="py-2 px-3">Result</th>
                    <th className="py-2 px-3">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={i} className="border-b border-gray-900 hover:bg-gray-900/50">
                      <td className="py-2 px-3 font-mono">{e.order_id}</td>
                      <td className="py-2 px-3">{e.sku}</td>
                      <td className="py-2 px-3">{e.qty_picked}</td>
                      <td className="py-2 px-3">{e.bay_id}</td>
                      <td className="py-2 px-3">{e.worker_id}</td>
                      <td className="py-2 px-3">{resultBadge(e.result)}</td>
                      <td className="py-2 px-3 text-gray-500">{new Date(e.timestamp * 1000).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {events.length === 0 && <p className="text-gray-600 text-center py-8">No pick events found</p>}
            </div>
          )}
        </div>
      );
    }

    function StatsCards() {
      const [stats, setStats] = useState(null);

      useEffect(() => {
        fetchJSON("/picks/stats").then(setStats).catch(() => setStats(null));
      }, []);

      if (!stats) return <p className="text-gray-500">Loading stats...</p>;

      const cards = [
        { label: "Total Picks", value: stats.total || 0, color: "blue" },
        { label: "Correct", value: stats.correct || 0, color: "green" },
        { label: "Wrong", value: stats.wrong || 0, color: "red" },
        { label: "Short", value: stats.short || 0, color: "yellow" },
      ];

      return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {cards.map(c => (
            <div key={c.label} className={`bg-gray-900 border border-gray-800 rounded-lg p-4`}>
              <div className="text-gray-400 text-xs uppercase tracking-wide">{c.label}</div>
              <div className={`text-2xl font-bold mt-1 text-${c.color}-400`}>{c.value}</div>
            </div>
          ))}
        </div>
      );
    }

    function ModelInfo() {
      const [model, setModel] = useState(null);
      const [error, setError] = useState(null);

      useEffect(() => {
        fetchJSON("/models/latest")
          .then(setModel)
          .catch(() => setError("Could not fetch model info"));
      }, []);

      return (
        <div>
          <h2 className="text-lg font-semibold mb-4">Model Registry</h2>
          {error && <p className="text-red-400">{error}</p>}
          {model && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 max-w-md">
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Current Version</span>
                <span className="text-green-400 font-mono font-bold">{model.version}</span>
              </div>
              <div className="mt-2 text-xs text-gray-600 break-all">{model.url}</div>
            </div>
          )}
        </div>
      );
    }

    // ── App ────────────────────────────────────────────────────────────
    function App() {
      const [tab, setTab] = useState("history");

      const tabs = [
        { id: "history", label: "Pick History" },
        { id: "stats", label: "Statistics" },
        { id: "model", label: "Model" },
      ];

      return (
        <div className="max-w-6xl mx-auto px-4 py-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-xl font-bold text-white">VLM Vision Admin</h1>
              <p className="text-sm text-gray-500">Metwall Pick Verification System</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
              <span className="text-xs text-gray-400">System Online</span>
            </div>
          </div>

          {/* Tab nav */}
          <div className="flex gap-1 mb-6 border-b border-gray-800">
            {tabs.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`px-4 py-2 text-sm font-medium rounded-t transition-colors ${
                  tab === t.id
                    ? "bg-gray-800 text-white border-b-2 border-blue-500"
                    : "text-gray-500 hover:text-gray-300"
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-6">
            {tab === "history" && <PickHistory />}
            {tab === "stats" && (
              <div>
                <h2 className="text-lg font-semibold mb-4">Pick Statistics</h2>
                <StatsCards />
              </div>
            )}
            {tab === "model" && <ModelInfo />}
          </div>
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById("root")).render(<App />);
  </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add client/vlm-admin.html
git commit -m "feat: vlm-dashboard admin SPA with pick history, stats, and model info"
```

---

## Task 3: Dashboard Custom CSS

**Files:**
- Create: `client/vlm-admin.css`

- [ ] **Step 1: Write vlm-admin.css**

```css
/* client/vlm-admin.css — custom styles beyond Tailwind */

/* Smooth tab transitions */
button { transition: all 0.15s ease; }

/* Table row hover */
tbody tr { transition: background-color 0.1s ease; }

/* Pulse animation for status dot */
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.animate-pulse { animation: pulse-dot 2s ease-in-out infinite; }

/* Scrollbar styling */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #111; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #555; }

/* Badge styles for dynamic Tailwind colors that CDN may purge */
.text-blue-400 { color: #60a5fa; }
.text-green-400 { color: #4ade80; }
.text-red-400 { color: #f87171; }
.text-yellow-400 { color: #facc15; }
```

- [ ] **Step 2: Commit**

```bash
git add client/vlm-admin.css
git commit -m "feat: vlm-dashboard custom CSS for admin dashboard"
```

---

## Task 4: Extend Stats Endpoint with Breakdown

**Files:**
- Modify: `functions/vlm_vision_function/services/datastore.js`

The dashboard's StatsCards component expects `{ total, correct, wrong, short }`. Update `getPickStats` to return per-result counts.

- [ ] **Step 1: Update getPickStats in datastore.js**

Replace the `getPickStats` function:

```javascript
export async function getPickStats(catalystApp) {
  const zcql = catalystApp.zcql();
  const totalRows = await zcql.executeZCQLQuery(
    "SELECT COUNT(ROWID) AS count FROM pick_events"
  );
  const correctRows = await zcql.executeZCQLQuery(
    "SELECT COUNT(ROWID) AS count FROM pick_events WHERE result = 'correct'"
  );
  const wrongRows = await zcql.executeZCQLQuery(
    "SELECT COUNT(ROWID) AS count FROM pick_events WHERE result = 'wrong'"
  );
  const shortRows = await zcql.executeZCQLQuery(
    "SELECT COUNT(ROWID) AS count FROM pick_events WHERE result = 'short'"
  );
  return {
    total: totalRows[0]?.pick_events?.count ?? 0,
    correct: correctRows[0]?.pick_events?.count ?? 0,
    wrong: wrongRows[0]?.pick_events?.count ?? 0,
    short: shortRows[0]?.pick_events?.count ?? 0,
  };
}
```

- [ ] **Step 2: Update datastore test for new stats shape**

In `functions/vlm_vision_function/tests/datastore.test.js`, update the stats test:

```javascript
test("getPickStats returns breakdown by result", async () => {
  const catalystApp = mockCatalystApp();
  const stats = await getPickStats(catalystApp);

  expect(stats.total).toBe(42);
  expect(stats.correct).toBeDefined();
  expect(stats.wrong).toBeDefined();
  expect(stats.short).toBeDefined();
});
```

- [ ] **Step 3: Run tests**

```bash
cd functions/vlm_vision_function && node --experimental-vm-modules node_modules/.bin/jest --forceExit
```

Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add functions/vlm_vision_function/services/datastore.js functions/vlm_vision_function/tests/datastore.test.js
git commit -m "feat: vlm-dashboard extend getPickStats with per-result breakdown"
```

---

## Task 5: Final Verification

- [ ] **Step 1: Run all Catalyst function tests**

```bash
cd functions/vlm_vision_function && node --experimental-vm-modules node_modules/.bin/jest --forceExit --verbose
```

Expected: all tests pass

- [ ] **Step 2: Run all local agent tests**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: 44 passed

- [ ] **Step 3: Verify dashboard files exist**

```bash
ls client/vlm-admin.html client/vlm-admin.css
```

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "chore: vlm-dashboard plan 5 complete — admin dashboard ready"
```
