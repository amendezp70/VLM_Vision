// functions/vlm_vision_function/services/video_datastore.js
/**
 * Catalyst Datastore operations for video_segments and evidence_clips tables.
 *
 * Table schemas (create in Catalyst console):
 *   video_segments: segment_id (text), camera_id (int), start_time (bigint),
 *                   end_time (bigint), duration (double), file_size (bigint),
 *                   cloud_url (text), expires_at (bigint)
 *
 *   evidence_clips: clip_id (text), event_id (text), segment_id (text),
 *                   clip_start_sec (double), clip_end_sec (double),
 *                   cloud_url (text), generated_at (bigint),
 *                   retained_indefinitely (boolean)
 */

// ── Video Segments ──────────────────────────────────────────────

export async function insertVideoSegment(catalystApp, segment) {
  const table = catalystApp.datastore().table("video_segments");
  return table.insertRow({
    segment_id: segment.segment_id,
    camera_id: segment.camera_id,
    start_time: segment.start_time,
    end_time: segment.end_time,
    duration: segment.duration,
    file_size: segment.file_size,
    cloud_url: segment.cloud_url,
    expires_at: segment.expires_at,
  });
}

export async function getVideoSegments(catalystApp, { camera_id, start, end, limit = 50 } = {}) {
  const zcql = catalystApp.zcql();
  const conditions = [];
  if (camera_id != null) conditions.push(`camera_id = ${camera_id}`);
  if (start) conditions.push(`start_time >= ${start}`);
  if (end) conditions.push(`end_time <= ${end}`);

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
  const rows = await zcql.executeZCQLQuery(
    `SELECT ROWID, segment_id FROM video_segments WHERE expires_at > 0 AND expires_at < ${now}`
  );
  if (rows.length === 0) return { deleted: 0 };

  const table = catalystApp.datastore().table("video_segments");
  const rowIds = rows.map((r) => r.video_segments.ROWID);
  for (const id of rowIds) {
    await table.deleteRow(id);
  }
  return { deleted: rowIds.length, segment_ids: rows.map((r) => r.video_segments.segment_id) };
}

// ── Evidence Clips ──────────────────────────────────────────────

export async function insertEvidenceClip(catalystApp, clip) {
  const table = catalystApp.datastore().table("evidence_clips");
  return table.insertRow({
    clip_id: clip.clip_id,
    event_id: clip.event_id,
    segment_id: clip.segment_id,
    clip_start_sec: clip.clip_start_sec,
    clip_end_sec: clip.clip_end_sec,
    cloud_url: clip.cloud_url,
    generated_at: clip.generated_at,
    retained_indefinitely: clip.retained_indefinitely ?? true,
  });
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
    `SELECT * FROM evidence_clips ORDER BY generated_at DESC LIMIT ${limit}`
  );
  return rows.map((r) => r.evidence_clips);
}
