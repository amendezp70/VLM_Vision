// functions/vlm_vision_function/services/video_datastore.js
/**
 * Catalyst Datastore operations for video_segments and evidence_clips tables.
 *
 * ACTUAL table schemas (verified in the Catalyst console):
 *   video_segments: segment_id (varchar), camera_id (bigint), zone_id (bigint),
 *                   start_time (datetime), end_time (datetime),
 *                   cloud_url (text), uploaded (boolean), expires_at (date)
 *
 *   evidence_clips: clip_id (varchar), event_id (fk), box_id (fk), pallet_id (fk),
 *                   clip_start (datetime), clip_end (datetime),
 *                   cloud_url (text), retained_indefinitely (boolean)
 *
 * NOTE: the local agent sends timestamps as POSIX epoch seconds (numbers).
 * The datetime/date columns need real date strings, so we convert here.
 */

// ---- helpers -------------------------------------------------------------

/** epoch seconds (number) -> "YYYY-MM-DD HH:MM:SS" for datetime columns */
function toDateTime(epochSeconds) {
  if (epochSeconds == null || epochSeconds === "") return null;
  const n = Number(epochSeconds);
  if (!isFinite(n)) return null;
  const d = new Date(n * 1000);
  const pad = (x) => String(x).padStart(2, "0");
  return (
    d.getUTCFullYear() +
    "-" + pad(d.getUTCMonth() + 1) +
    "-" + pad(d.getUTCDate()) +
    " " + pad(d.getUTCHours()) +
    ":" + pad(d.getUTCMinutes()) +
    ":" + pad(d.getUTCSeconds())
  );
}

/** epoch seconds (number) -> "YYYY-MM-DD" for date columns */
function toDate(epochSeconds) {
  if (epochSeconds == null || epochSeconds === "") return null;
  const n = Number(epochSeconds);
  if (!isFinite(n)) return null;
  const d = new Date(n * 1000);
  const pad = (x) => String(x).padStart(2, "0");
  return (
    d.getUTCFullYear() +
    "-" + pad(d.getUTCMonth() + 1) +
    "-" + pad(d.getUTCDate())
  );
}

/** drop keys whose value is undefined/null so we never write phantom columns */
function clean(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined && v !== null) out[k] = v;
  }
  return out;
}

// ---- Video Segments ------------------------------------------------------

export async function insertVideoSegment(catalystApp, segment) {
  const table = catalystApp.datastore().table("video_segments");
  const row = clean({
    segment_id: segment.segment_id,
    camera_id: segment.camera_id,
    zone_id: segment.zone_id,
    start_time: toDateTime(segment.start_time),
    end_time: toDateTime(segment.end_time),
    cloud_url: segment.cloud_url,
    uploaded: segment.uploaded ?? true,
    expires_at: toDate(segment.expires_at),
  });
  return table.insertRow(row);
}

export async function getVideoSegments(catalystApp, { camera_id, start, end, limit = 50 } = {}) {
  const zcql = catalystApp.zcql();
  const conditions = [];
  if (camera_id != null) conditions.push(`camera_id = ${camera_id}`);
  if (start) conditions.push(`start_time >= '${toDateTime(start)}'`);
  if (end) conditions.push(`end_time <= '${toDateTime(end)}'`);

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  const query = `SELECT * FROM video_segments ${where} ORDER BY start_time DESC LIMIT ${limit}`;
  const rows = await zcql.executeZCQLQuery(query);
  return rows.map((r) => r.video_segments);
}

export async function getVideoSegmentById(catalystApp, segmentId) {
  const zcql = catalystApp.zcql();
  const rows = await zcql.executeZCQLQuery(
    `SELECT * FROM video_segments WHERE segment_id = '${segmentId}' LIMIT 1`
  );
  return rows.length > 0 ? rows[0].video_segments : null;
}

export async function deleteExpiredSegments(catalystApp, now) {
  const zcql = catalystApp.zcql();
  const cutoff = toDate(now);
  const rows = await zcql.executeZCQLQuery(
    `SELECT ROWID, segment_id FROM video_segments WHERE expires_at < '${cutoff}'`
  );
  if (rows.length === 0) return { deleted: 0 };

  const table = catalystApp.datastore().table("video_segments");
  const rowIds = rows.map((r) => r.video_segments.ROWID);
  for (const id of rowIds) {
    await table.deleteRow(id);
  }
  return { deleted: rowIds.length, segment_ids: rows.map((r) => r.video_segments.segment_id) };
}

// ---- Evidence Clips ------------------------------------------------------

export async function insertEvidenceClip(catalystApp, clip) {
  const table = catalystApp.datastore().table("evidence_clips");
  // Accept either clip_start/clip_end or the older clip_start_sec/clip_end_sec
  // names from the agent, so both payload shapes work.
  const start = clip.clip_start ?? clip.clip_start_sec;
  const end = clip.clip_end ?? clip.clip_end_sec;
  const row = clean({
    clip_id: clip.clip_id,
    event_id: clip.event_id,
    box_id: clip.box_id,
    pallet_id: clip.pallet_id,
    clip_start: toDateTime(start),
    clip_end: toDateTime(end),
    cloud_url: clip.cloud_url,
    retained_indefinitely: clip.retained_indefinitely ?? true,
  });
  return table.insertRow(row);
}

export async function getEvidenceClipByEvent(catalystApp, eventId) {
  const zcql = catalystApp.zcql();
  const rows = await zcql.executeZCQLQuery(
    `SELECT * FROM evidence_clips WHERE event_id = '${eventId}' LIMIT 1`
  );
  return rows.length > 0 ? rows[0].evidence_clips : null;
}

export async function getEvidenceClips(catalystApp, { limit = 50 } = {}) {
  const zcql = catalystApp.zcql();
  const rows = await zcql.executeZCQLQuery(
    `SELECT * FROM evidence_clips ORDER BY clip_start DESC LIMIT ${limit}`
  );
  return rows.map((r) => r.evidence_clips);
}