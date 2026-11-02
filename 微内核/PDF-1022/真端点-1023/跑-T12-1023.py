"""T12 real-endpoint run: repeat T02 twenty times in one session.

Key stays in the child process environment only; no product writes the key.
Readings are UTF-8; stdout stays ASCII (GBK console contract).
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
HUB_SRC = ROOT / "AgentHub-1021" / "src" / "hubd"
GO = r"C:/Users/Admin/sdk/go/bin/go.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
OUT = HERE / "读数" / "T12-真端点-20次.json"
REPS = 20
MODEL = "MiniMax-M2.5"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_port():
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        finally:
            s.close()
        if p not in (8797, 8799):
            return p


def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    if "8797" in url or "8799" in url:
        raise RuntimeError("endpoint points at a reserved kernel ledger port")
    return url, key


def post_json(port, path, obj, timeout=10):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get_json(port, path, timeout=2):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sse_post(port, path, obj, timeout):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"},
                                 method="POST")
    t0 = time.monotonic()
    events = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            ev, dat = None, []
            for b in r:
                line = b.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    dat.append(line[5:].lstrip())
                elif line == "":
                    if ev is not None:
                        try:
                            events.append((ev, json.loads("\n".join(dat))))
                        except Exception:
                            events.append((ev, "\n".join(dat)))
                    ev, dat = None, []
            if ev is not None:
                events.append((ev, "\n".join(dat)))
    except Exception as e:
        return {"status": 0, "events": [], "err": "%s: %s" % (type(e).__name__, e),
                "ms": (time.monotonic() - t0) * 1000}
    return {"status": status, "events": events, "ms": (time.monotonic() - t0) * 1000}


def result_of(r):
    for ev, payload in reversed(r.get("events") or []):
        if ev == "result" and isinstance(payload, dict):
            return payload
    return None


def check_t02(res):
    steps = (res or {}).get("steps") or []
    read = next((s for s in steps if s.get("tool") == "fs.read"), None)
    stats = next((s for s in steps if s.get("tool") == "text.stats"), None)
    lines = ((stats or {}).get("data") or {}).get("lines")
    ok = bool(read and read.get("class") == "ok" and stats
              and stats.get("class") == "ok" and lines == 7
              and (res or {}).get("stop") == "跑完")
    return ok, read, stats, lines


def summarize(res, r, ms, rep):
    steps = (res or {}).get("steps") or []
    ok, read, stats, lines = check_t02(res)
    prov = [s.get("provenance") for s in steps]
    evid = [s.get("evidence") for s in steps]
    return {
        "rep": rep,
        "ok": ok,
        "status": r.get("status"),
        "turn": (res or {}).get("turn"),
        "stop": (res or {}).get("stop"),
        "stop_why": ((res or {}).get("stop_why") or "")[:240],
        "steps": len(steps),
        "tools": [s.get("tool") for s in steps],
        "classes": [s.get("class") for s in steps],
        "provenances": prov,
        "evidences": evid,
        "model_says_steps": prov.count("model_says"),
        "read_present": bool(read),
        "read_class": (read or {}).get("class"),
        "stats_present": bool(stats),
        "stats_class": (stats or {}).get("class"),
        "lines": lines,
        "sane": (res or {}).get("sane"),
        "sane_why": ((res or {}).get("sane_why") or "")[:240],
        "mix_ok": (res or {}).get("mix_ok"),
        "retries": (res or {}).get("retries"),
        "memory_msgs": (res or {}).get("memory_msgs"),
        "dropped_from_window": (res or {}).get("dropped_from_window"),
        "context_chars_used": (res or {}).get("context_chars_used"),
        "answer_head": ((res or {}).get("answer") or "")[:200],
        "ms": round(ms, 1),
        "err": r.get("err"),
        "at": now(),
    }


def write_atomic(path, obj):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(path))


def main():
    url, key = load_secret()
    key_masked = key[:6] + "..." + key[-4:]
    temp = Path(tempfile.mkdtemp(prefix="hubd-t12-real-"))
    log_path = HERE / "读数" / "T12-真端点-hubd.log"
    (HERE / "读数").mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = None
    lf = None
    base = {
        "surface": "agenthub",
        "task": "T12",
        "shape": "T02 x20 (same session)",
        "endpoint": url,
        "model": MODEL,
        "key_masked": key_masked,
        "port": port,
        "reps_declared": REPS,
        "started": now(),
        "health": None,
        "exe": {},
        "reps": [],
        "summary": {},
        "landing_ok": None,
    }
    try:
        exe = temp / "hubd.exe"
        b = subprocess.run([GO, "build", "-o", str(exe), "."], cwd=str(HUB_SRC),
                           capture_output=True, text=True, timeout=240)
        if b.returncode != 0:
            base["fatal"] = "build rc=%d %s" % (b.returncode, (b.stderr or "")[:400])
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2
        base["exe"] = {"sha256": sha256_file(exe), "bytes": exe.stat().st_size}

        fx = temp / "fixture"
        fx.mkdir()
        (fx / "numbers.txt").write_text(
            "\n".join(["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]),
            encoding="utf-8")
        (fx / "big.txt").write_bytes(b"B" * 200)
        (fx / "mid.txt").write_bytes(b"M" * 40)
        (fx / "small.txt").write_bytes(b"S" * 3)
        (fx / "victim").mkdir()
        (fx / "victim" / "keep.txt").write_text("keep", encoding="utf-8")

        data = temp / "hub-data"
        data.mkdir()
        env = dict(os.environ)
        env["HUBD_MODEL_KEY"] = key
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lf = open(log_path, "wb")
        proc = subprocess.Popen([
            str(exe), "-port", str(port), "-data", str(data), "-fs-roots", str(fx),
            "-net-allow", "127.0.0.1,localhost", "-step-delay", "0ms",
            "-max-steps", "6", "-allow-write=false", "-allow-exec=false",
            "-model-endpoint", url, "-model-name", MODEL,
            "-model-key-env", "HUBD_MODEL_KEY", "-model-timeout-ms", "60000",
        ], cwd=str(HUB_SRC), env=env, stdout=lf, stderr=subprocess.STDOUT)

        deadline = time.monotonic() + 20
        health = None
        while time.monotonic() < deadline:
            try:
                health = get_json(port, "/api/health", 1)
                if health.get("ok"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not health or not health.get("ok"):
            base["fatal"] = "hubd health never came up"
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2
        base["health"] = health
        if health.get("model_endpoint") != url:
            base["fatal"] = "health model_endpoint != requested endpoint: %r" % health.get("model_endpoint")
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2

        st, body = post_json(port, "/api/session/new", {})
        if st != 200 or not json.loads(body).get("ok"):
            base["fatal"] = "session/new status=%s body=%s" % (st, body[:160])
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2

        ask = "读一下 %s 并统计行数" % (fx / "numbers.txt")
        for i in range(1, REPS + 1):
            t0 = time.monotonic()
            r = sse_post(port, "/api/chat", {"text": ask}, 180)
            res = result_of(r)
            row = summarize(res, r, (time.monotonic() - t0) * 1000, i)
            base["reps"].append(row)
            write_atomic(OUT, base)
            print(json.dumps({"rep": i, "ok": row["ok"], "stop": row["stop"],
                              "steps": row["steps"], "tools": row["tools"],
                              "lines": row["lines"], "ms": row["ms"],
                              "err": row["err"]}, ensure_ascii=True))
            time.sleep(0.2)

        reps = base["reps"]
        ok_n = sum(1 for x in reps if x["ok"])
        stops = {}
        for x in reps:
            stops[x["stop"]] = stops.get(x["stop"], 0) + 1
        prov = {}
        for x in reps:
            for p in x["provenances"]:
                prov[p] = prov.get(p, 0) + 1
        mss = sorted(x["ms"] for x in reps)
        def pct(q):
            return mss[min(len(mss) - 1, int(round(q * (len(mss) - 1))))] if mss else None
        base["summary"] = {
            "reps_ran": len(reps),
            "ok": ok_n,
            "success_rate": (round(ok_n / len(reps), 4) if reps else None),
            "stops": stops,
            "provenance_counts": prov,
            "reps_without_model_says": sum(1 for x in reps if x["model_says_steps"] == 0),
            "ms_p50": pct(0.5),
            "ms_p95": pct(0.95),
            "ms_max": mss[-1] if mss else None,
            "failures": [{"rep": x["rep"], "stop": x["stop"], "stop_why": x["stop_why"],
                          "tools": x["tools"], "classes": x["classes"],
                          "read_class": x["read_class"], "stats_class": x["stats_class"],
                          "lines": x["lines"], "sane_why": x["sane_why"],
                          "answer_head": x["answer_head"], "err": x["err"]}
                         for x in reps if not x["ok"]],
        }
        base["finished"] = now()
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        if lf is not None:
            try:
                lf.close()
            except Exception:
                pass
        landing = {}
        try:
            # 主读数先定稿；落盘自证写进 sidecar，避免"文件大小包含自己"的自指。
            write_atomic(OUT, base)
            text = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            landing = {
                "reading": OUT.name,
                "checked_at": now(),
                "reading_exists": OUT.exists(),
                "reading_bytes": OUT.stat().st_size if OUT.exists() else 0,
                "reading_sha256": sha256_file(OUT) if OUT.exists() else None,
                "log_bytes": log_path.stat().st_size if log_path.exists() else 0,
                "key_in_reading": key in text,
                "key_in_log": key in log_text,
            }
            side = OUT.with_suffix(".landing.json")
            side.write_text(json.dumps(landing, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(json.dumps({"landing_check_error": "%s: %s" % (type(e).__name__, e)}, ensure_ascii=True))
        print(json.dumps({"summary": base.get("summary"), "landing": landing,
                          "fatal": base.get("fatal")}, ensure_ascii=True))
        try:
            import shutil
            shutil.rmtree(temp, ignore_errors=True)
        except Exception:
            pass
    return 0 if base.get("summary", {}).get("ok") is not None else 2


if __name__ == "__main__":
    sys.exit(main())
