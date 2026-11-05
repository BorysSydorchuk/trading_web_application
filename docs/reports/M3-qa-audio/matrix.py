"""M3-13 timing matrix: Whisper settings x recordings, end to end through the running app.

Starts the API once and, per (round, config), a fresh worker with the config's WHISPER_* env
(all set explicitly so .env cannot leak in), uploads one warm-up note (discarded), then each
recording in a shuffled order: upload -> poll until done -> POST /api/trades/{id}/extract.
Configs are shuffled per round (seeded) to spread laptop throttling over all cells.
CPU temperature / performance is logged with typeperf every 5 s.

Usage (from backend/, QA DB only, never the real one):
    .venv/Scripts/python.exe ../docs/reports/M3-qa-audio/matrix.py <out_dir> <trade_id> <warmup> <file>...
Needs DATABASE_URL, MT5_SOURCE, MT5_PASSWORD_*, DATA_DIR in the environment. Writes
<out_dir>/results.jsonl (incl. transcripts: keep out_dir outside the repo), worker logs, perf.csv.
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
PY = str(Path(".venv/Scripts/python.exe").resolve())
ROUNDS = 3
SEED = 20261105
POLL_S = 0.25
OLD = {"WHISPER_VAD_FILTER": "true", "WHISPER_CONDITION_ON_PREVIOUS_TEXT": "true",
       "WHISPER_TEMPERATURES": "0,0.2,0.4,0.6,0.8,1.0", "WHISPER_CPU_THREADS": "0"}
NEW = {"WHISPER_VAD_FILTER": "true", "WHISPER_CONDITION_ON_PREVIOUS_TEXT": "false",
       "WHISPER_TEMPERATURES": "0.0,0.4", "WHISPER_CPU_THREADS": "auto"}
NEWCOND = {**NEW, "WHISPER_CONDITION_ON_PREVIOUS_TEXT": "true"}
CONFIGS = {f"{name}_b{beam}": {**env, "WHISPER_BEAM_SIZE": str(beam)}
           for name, env in (("old", OLD), ("new", NEW), ("newcond", NEWCOND)) for beam in (1, 5)}
COMMON = {"WHISPER_MODEL": "small", "WHISPER_COMPUTE_TYPE": "int8", "WHISPER_LANGUAGE": "uk"}
DONE_RE = re.compile(r"Audio note (\d+) transcribed: audio ([\d.]+) s, transcription ([\d.]+) s, "
                     r"wall ([\d.]+) s, RTF ([\d.]+) \((.*)\)")


def req(method, path, body=None, ctype=None, timeout=180):
    r = urllib.request.Request(BASE + path, data=body, method=method)
    if ctype:
        r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def wait_health():
    for _ in range(120):
        try:
            if req("GET", "/api/health", timeout=2)[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit("API not healthy")


def run_note(trade_id, path, extract):
    data = Path(path).read_bytes()
    t0 = time.perf_counter()
    st, n = req("POST", f"/api/trades/{trade_id}/audio", data, "audio/ogg")
    t_up = time.perf_counter() - t0
    if st != 201:
        raise SystemExit(f"upload {st} {n}")
    while n["status"] not in ("done", "failed"):
        time.sleep(POLL_S)
        n = req("GET", f"/api/audio/{n['id']}")[1]
    t_done = time.perf_counter() - t0
    out = {"note_id": n["id"], "status": n["status"], "error": n["error_code"], "upload_s": t_up,
           "upload_to_done_s": t_done, "duration": n["duration_seconds"], "transcript": n["transcript"]}
    if extract and n["status"] == "done":
        t1 = time.perf_counter()
        st, r = req("POST", f"/api/trades/{trade_id}/extract",
                    json.dumps({"text": n["transcript"]}).encode(), "application/json")
        out["extract_s"] = time.perf_counter() - t1
        out["extract_status"] = st
        if st != 200:  # recorded, not fatal (e.g. an invalid AI key): transcription timings still count
            out["extract_error"] = (r or {}).get("error", {}).get("code") if isinstance(r, dict) else r
        if st == 200:
            out["extract_fields"] = sorted((r.get("fields") or {}).keys())
            out["total_s"] = t_done + out["extract_s"]
    return out


def worker_line(log, note_id):
    for _ in range(20):
        for m in DONE_RE.finditer(log.read_text(encoding="utf-8", errors="replace")):
            if int(m.group(1)) == note_id:
                return {"w_audio": float(m.group(2)), "w_transcr": float(m.group(3)),
                        "w_wall": float(m.group(4)), "w_rtf": float(m.group(5)), "w_settings": m.group(6)}
        time.sleep(0.25)
    return {}


def start(args, env, log_name, out):
    f = open(out / log_name, "w", encoding="utf-8")
    return subprocess.Popen(args, env=env, stdout=f, stderr=subprocess.STDOUT)


def main():
    out, trade_id, warmup, files = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    perf = subprocess.Popen(["typeperf", r"\Thermal Zone Information(*)\Temperature",
                             r"\Thermal Zone Information(*)\% Passive Limit",
                             r"\Processor Information(_Total)\% Processor Performance",
                             r"\Processor Information(_Total)\% Processor Utility",
                             "-si", "5", "-f", "CSV", "-o", str(out / "perf.csv"), "-y"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base_env = {**os.environ, **COMMON, **CONFIGS["new_b1"], "LOG_DIR": str(out / "logs-api")}
    api = start([PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                base_env, "api.out", out)
    results = out / "results.jsonl"
    try:
        wait_health()
        for rnd in range(1, ROUNDS + 1):
            order = list(CONFIGS)
            rng.shuffle(order)
            for cfg in order:
                logdir = out / f"logs-r{rnd}-{cfg}"
                env = {**os.environ, **COMMON, **CONFIGS[cfg], "LOG_DIR": str(logdir)}
                worker = start([PY, "-m", "app.worker"], env, f"worker-r{rnd}-{cfg}.out", out)
                try:
                    session = [("warmup", warmup)] + [("run", f) for f in rng.sample(files, len(files))]
                    for kind, f in session:
                        ts = time.strftime("%H:%M:%S")
                        r = run_note(trade_id, f, extract=(kind == "run"))
                        r.update(worker_line(logdir / "worker.log", r["note_id"]))
                        r.update({"round": rnd, "config": cfg, "kind": kind, "file": Path(f).name, "start": ts})
                        with results.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                        print(f"r{rnd} {cfg:10} {kind:6} {Path(f).name} {ts} done={r['upload_to_done_s']:.1f}s "
                              f"transcr={r.get('w_transcr')} total={r.get('total_s', 0):.1f}s", flush=True)
                finally:
                    worker.terminate()
                    worker.wait(30)
    finally:
        api.terminate()
        api.wait(30)
        perf.terminate()


main()
