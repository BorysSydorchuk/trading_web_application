"""M3-18 final end-to-end check (QA DB only). Run from backend/.

One API (port 8010) + one worker with CODE DEFAULTS for Whisper (no WHISPER_* env), 1 warm-up
note (discarded), then 3 rounds x 3 recordings (shuffled per round): upload -> poll until done
-> POST /api/trades/{id}/extract. Any failure stops the run (no retries: thermal budget).
"""
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"
PY = str(Path(".venv/Scripts/python.exe").resolve())
POLL_S = 0.25
SEED = 20261105
QA_URL = "postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal_qa_m3"


def req(method, path, body=None, ctype=None, timeout=180):
    r = urllib.request.Request(BASE + path, data=body, method=method)
    if ctype:
        r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null")
        except ValueError:
            return e.code, raw.decode("utf-8", "replace")


def run_note(trade_id, path):
    data = Path(path).read_bytes()
    t0 = time.perf_counter()
    st, n = req("POST", f"/api/trades/{trade_id}/audio", data, "audio/ogg")
    t_up = time.perf_counter() - t0
    if st != 201:
        raise SystemExit(f"STOP: upload {st} {n}")
    while n["status"] not in ("done", "failed"):
        time.sleep(POLL_S)
        n = req("GET", f"/api/audio/{n['id']}")[1]
        if time.perf_counter() - t0 > 300:
            raise SystemExit("STOP: note not done in 300 s")
    t_done = time.perf_counter() - t0
    return {"note_id": n["id"], "status": n["status"], "error": n["error_code"], "upload_s": t_up,
            "upload_to_done_s": t_done, "duration": n["duration_seconds"], "transcript": n["transcript"]}


def extract(trade_id, text):
    t1 = time.perf_counter()
    st, r = req("POST", f"/api/trades/{trade_id}/extract",
                json.dumps({"text": text}).encode(), "application/json")
    return st, r, time.perf_counter() - t1


def start(args, env, log):
    f = open(log, "w", encoding="utf-8")
    return subprocess.Popen(args, env=env, stdout=f, stderr=subprocess.STDOUT)


def main():
    out, trade_id, warmup, files = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]
    wrap = sys.argv[0].replace("final_e2e.py", "qa_worker_wrap.py")
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("WHISPER_")}
    env.update({"DATABASE_URL": QA_URL, "MT5_SOURCE": "fixture:backend/tests/fixtures/mt5/basic_week.json",
                "DATA_DIR": str(out / "data"), "LOG_DIR": str(out / "logs"),
                "QA_GLOSSARY_LOG": str(out / "glossary.jsonl"), "PYTHONUTF8": "1"})
    perf = subprocess.Popen(["typeperf", r"\Thermal Zone Information(*)\Temperature",
                             r"\Processor Information(_Total)\% Processor Performance",
                             "-si", "5", "-f", "CSV", "-o", str(out / "perf.csv"), "-y"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    api = start([PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                env, out / "api.out")
    worker = None
    results = out / "results.jsonl"
    try:
        for _ in range(120):
            try:
                if req("GET", "/api/health", timeout=2)[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit("STOP: API not healthy")
        for _ in range(40):
            st, h = req("GET", "/api/health")
            if h.get("ai", {}).get("state") != "checking":
                break
            time.sleep(0.5)
        print("HEALTH", json.dumps(h), flush=True)
        if h.get("ai", {}).get("state") != "ok":
            raise SystemExit("STOP: ai.state is not ok")
        st, t = req("GET", f"/api/trades/{trade_id}")
        print("TRADE", st, t.get("status"), "sl set:", t.get("initial_sl") is not None,
              "close:", t.get("close_time"), "symbol:", t.get("symbol"), flush=True)
        if st != 200 or t.get("status") in ("open", "needs_sl") or t.get("initial_sl") is None:
            raise SystemExit("STOP: trade not usable")
        worker = start([PY, wrap], env, out / "worker.out")
        session = [("warmup", 0, warmup)]
        rng = random.Random(SEED)
        for rnd in (1, 2, 3):
            session += [("run", rnd, f) for f in rng.sample(files, len(files))]
        for kind, rnd, f in session:
            ts = time.strftime("%H:%M:%S")
            r = run_note(trade_id, f)
            if r["status"] != "done":
                raise SystemExit(f"STOP: note failed {r}")
            if kind == "run":
                st, x, te = extract(trade_id, r["transcript"])
                r.update({"extract_status": st, "extract_s": te, "extract": x,
                          "total_s": r["upload_to_done_s"] + te})
                if st != 200:
                    with results.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({**r, "kind": kind, "round": rnd, "file": Path(f).name},
                                            ensure_ascii=False) + "\n")
                    raise SystemExit(f"STOP: extract {st} {x}")
            r.update({"kind": kind, "round": rnd, "file": Path(f).name, "start": ts})
            with results.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"{kind} r{rnd} {Path(f).name} {ts} done={r['upload_to_done_s']:.1f}s "
                  f"extract={r.get('extract_s', 0):.1f}s total={r.get('total_s', 0):.1f}s", flush=True)
    finally:
        if worker:
            worker.terminate()
            worker.wait(30)
        api.terminate()
        api.wait(30)
        perf.terminate()


main()
