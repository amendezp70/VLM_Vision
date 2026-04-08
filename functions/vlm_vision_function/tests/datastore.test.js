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
