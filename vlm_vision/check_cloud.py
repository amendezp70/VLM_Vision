import requests, time
base = None
for line in open(".env", encoding="utf-8"):
    line = line.strip()
    if line.startswith("CATALYST_FUNCTION_BASE_URL="):
        base = line.split("=", 1)[1].strip()
        break
b = base.rstrip("/")
print("URL:", b)
h = requests.get(b + "/health", timeout=30)
print("Health:", h.status_code, h.text[:100])
ts = int(time.time())
r = requests.post(b + "/video/clips", json={
    "clip_id": f"CHECK-{ts}",
    "event_id": f"CHECK-EVT-{ts}",
    "cloud_url": "https://example.com/handoff-test",
    "clip_start": ts,
    "clip_end": ts + 60,
}, timeout=30)
print("Clip insert:", r.status_code)
print("Response:", r.text[:300])
