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
