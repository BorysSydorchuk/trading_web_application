"""Upload an audio file to a trade, poll the note until done/failed, optionally extract."""
import json, sys, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8000"

def req(method, path, body=None, ctype=None, timeout=120):
    r = urllib.request.Request(BASE + path, data=body, method=method)
    if ctype: r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if resp.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw

def poll(note_id, t0):
    last = None
    while True:
        st, n = req("GET", f"/api/audio/{note_id}")
        key = (n["status"], n["progress"])
        if key != last:
            print(f"  +{time.perf_counter()-t0:6.1f}s {n['status']} progress={n['progress']}", flush=True)
            last = key
        if n["status"] in ("done", "failed"):
            return n
        time.sleep(0.5)

def main():
    trade_id, path, ctype = sys.argv[1], sys.argv[2], sys.argv[3]
    extract = len(sys.argv) > 4 and sys.argv[4] == "extract"
    data = open(path, "rb").read()
    t0 = time.perf_counter()
    st, n = req("POST", f"/api/trades/{trade_id}/audio", data, ctype)
    print(f"upload {st} in {time.perf_counter()-t0:.2f}s id={n.get('id') if isinstance(n, dict) else n}")
    if st != 201: print(n); return
    n = poll(n["id"], t0)
    t_done = time.perf_counter() - t0
    print(f"UPLOAD->{n['status']} {t_done:.1f}s duration={n['duration_seconds']} error={n['error_code']}")
    if n["status"] == "done":
        print("TRANSCRIPT:", (n["transcript"] or "")[:300])
    if extract and n["status"] == "done":
        t1 = time.perf_counter()
        st, r = req("POST", f"/api/trades/{trade_id}/extract", json.dumps({"text": n["transcript"]}).encode(), "application/json")
        te = time.perf_counter() - t1
        summary = r if st != 200 else {k: (v if k != "fields" else f"{len(v)} fields") for k, v in r.items() if k in ("fields", "missing_required", "dropped")}
        print(f"EXTRACT {st} {te:.1f}s -> {json.dumps(summary, ensure_ascii=False)[:600]}")
        print(f"TOTAL upload->done->extracted {t_done+te:.1f}s")
    print("NOTE_ID", n["id"])

main()
