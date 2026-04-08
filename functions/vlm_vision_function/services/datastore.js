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
