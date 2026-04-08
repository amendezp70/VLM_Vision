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
