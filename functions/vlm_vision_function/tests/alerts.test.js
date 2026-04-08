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
