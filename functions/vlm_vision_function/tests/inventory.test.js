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
