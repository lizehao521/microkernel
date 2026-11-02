#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""12-task local suite with executable oracles.

Runs the runnable shapes over real local HTTP surfaces (AgentHub /api/chat,
pgagent /api/turn) and records every run as one JSONL row. tasks.jsonl holds
the declared shapes; the check_* functions here are the executable oracles.
stdout stays ASCII (GBK console contract); the report is UTF-8.

Usage:
    C:/Users/Admin/sdk/py314/python.exe 跑任务集.py
"""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

GO = r"C:/Users/Admin/sdk/go/bin/go.exe"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HUB_SRC = ROOT / "AgentHub-1021" / "src" / "hubd"
PG_SRC = ROOT / "编程Agent-1020" / "src" / "pgagent"
AGENTD_SRC = ROOT / "微内核" / "微内核" / "cmd" / "agentd"
TASKS = HERE / "tasks.jsonl"
JSONL_OUT = HERE / "读数-任务集.jsonl"
REPORT_OUT = HERE / "报告-任务集.txt"
REPS = 20


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(s):
    print(s, flush=True)


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


def newest_go_mtime(d):
    ts = [p.stat().st_mtime for p in d.rglob("*.go") if p.is_file()]
    if not ts:
        return "-"
    return datetime.fromtimestamp(max(ts)).astimezone().isoformat(timespec="seconds")


def go_version():
    r = subprocess.run([GO, "version"], capture_output=True, text=True, timeout=30)
    return (r.stdout or r.stderr).strip()


def build(src, out):
    r = subprocess.run([GO, "build", "-o", str(out), "."], cwd=str(src),
                       capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError("build failed in %s rc=%d\n%s\n%s" % (src, r.returncode, r.stdout, r.stderr))
    return {"path": str(out), "sha256": sha256_file(out), "bytes": out.stat().st_size}


def parse_data(dat):
    s = "\n".join(dat)
    try:
        return json.loads(s)
    except Exception:
        return s


def sse_post(port, path, obj, timeout):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    t0 = time.monotonic()
    events, raw = [], []
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
                        events.append((ev, parse_data(dat)))
                    ev, dat = None, []
                elif not events:
                    raw.append(line)
            if ev is not None:
                events.append((ev, parse_data(dat)))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"status": e.code, "events": [], "body": body, "ms": (time.monotonic() - t0) * 1000}
    except Exception as e:
        return {"status": 0, "events": [], "body": "%s: %s" % (type(e).__name__, e),
                "ms": (time.monotonic() - t0) * 1000}
    return {"status": status, "events": events, "body": "\n".join(raw)[:500],
            "ms": (time.monotonic() - t0) * 1000}


def result_of(r):
    for ev, payload in reversed(r.get("events", [])):
        if ev == "result" and isinstance(payload, dict):
            return payload
    return None


def turn_of(r):
    res = result_of(r) if isinstance(r, dict) and "events" in r else (r or {}).get("result")
    return (res or {}).get("turn")


def post_json(port, path, obj, timeout=10):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get_json(port, path, timeout=2):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_health(port, timeout=15):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            j = get_json(port, "/api/health", 1)
            if j.get("ok"):
                return True, j
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
        time.sleep(0.05)
    return False, {"err": last}


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class FaultServer:
    """Local 429/Retry-After and slow endpoints; no external traffic."""

    def __init__(self):
        self.counts = {"429": 0}
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                body, code, retry = b"ok", 200, None
                if self.path.startswith("/429"):
                    with outer.lock:
                        n = outer.counts["429"]
                        outer.counts["429"] += 1
                    if n < 2:
                        code, body, retry = 429, b"retry-later", "1"
                elif self.path.startswith("/slow"):
                    time.sleep(4.5)
                    body = b"slow-ok"
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                if retry is not None:
                    self.send_header("Retry-After", retry)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

        self.httpd = QuietThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def start_proc(exe, args, cwd, log_path):
    lf = open(log_path, "wb")
    p = subprocess.Popen([str(exe)] + [str(a) for a in args], cwd=str(cwd),
                         stdout=lf, stderr=subprocess.STDOUT)
    return p, lf


def stop_proc(p, lf):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    try:
        lf.close()
    except Exception:
        pass


def agentd_run(exe, args, timeout=120):
    t0 = time.monotonic()
    r = subprocess.run([str(exe)] + [str(a) for a in args], capture_output=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return {"rc": r.returncode, "out": r.stdout or "", "err": r.stderr or "",
            "ms": round((time.monotonic() - t0) * 1000, 1)}


def make_fixture(temp):
    fx = temp / "fixture"
    fx.mkdir()
    # 7 lines, no trailing newline: text.stats counts strings.Split(body, "\n").
    (fx / "numbers.txt").write_text(
        "\n".join(["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]),
        encoding="utf-8")
    (fx / "big.txt").write_bytes(b"B" * 200)
    (fx / "mid.txt").write_bytes(b"M" * 40)
    (fx / "small.txt").write_bytes(b"S" * 3)
    (fx / "victim").mkdir()
    (fx / "victim" / "keep.txt").write_text("keep", encoding="utf-8")
    return fx


def hub_new_session(port):
    st, body = post_json(port, "/api/session/new", {})
    if st != 200:
        return False, "status=%s body=%s" % (st, body[:160])
    try:
        j = json.loads(body)
    except Exception:
        return False, "bad json %s" % body[:160]
    return bool(j.get("ok")), "ok=%s" % j.get("ok")


def hub_chat(port, text, timeout=60):
    return sse_post(port, "/api/chat", {"text": text}, timeout)


def steps_of(res):
    return (res or {}).get("steps") or []


def first_step(res, tool):
    for s in steps_of(res):
        if s.get("tool") == tool:
            return s
    return None


def data_of(step, key):
    d = (step or {}).get("data")
    if isinstance(d, dict):
        return d.get(key)
    return None


def base_obs(res, steps):
    obs = {"steps": len(steps), "tools": [s.get("tool") for s in steps],
           "stop": (res or {}).get("stop"), "sane": (res or {}).get("sane"),
           "mix_ok": (res or {}).get("mix_ok"), "retries": (res or {}).get("retries"),
           "waited_ms": (res or {}).get("waited_ms"), "turn": (res or {}).get("turn")}
    if (res or {}).get("sane") is False:
        obs["sane_why"] = res.get("sane_why")
    return obs


def check_t02(res):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    read, stats = first_step(res, "fs.read"), first_step(res, "text.stats")
    lines = data_of(stats, "lines")
    ok = bool(read and read.get("class") == "ok" and stats and stats.get("class") == "ok"
              and lines == 7 and res.get("stop") == "跑完")
    obs = base_obs(res, steps)
    obs.update({"read_class": (read or {}).get("class"),
                "stats_class": (stats or {}).get("class"), "lines": lines})
    return ok, obs


def check_t03(res):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    lst = first_step(res, "fs.list")
    top = data_of(lst, "top")
    ok = bool(lst and lst.get("class") == "ok" and top == "big.txt" and res.get("stop") == "跑完")
    obs = base_obs(res, steps)
    obs.update({"list_class": (lst or {}).get("class"), "top": top})
    return ok, obs


def check_t04(status1, body1, r2, res2):
    trace = (res2 or {}).get("trace") or []
    ok = (status1 == 400 and r2.get("status") == 200 and bool(res2)
          and res2.get("intent") == "未判定" and len(trace) >= 9)
    return ok, {"code_status": status1, "code_body": (body1 or "")[:80],
                "empty_q_status": r2.get("status"), "intent": (res2 or {}).get("intent"),
                "trace_len": len(trace), "code_executed": (res2 or {}).get("code_executed"),
                "trace_sane": (res2 or {}).get("trace_sane"),
                "mix_identity_ok": (res2 or {}).get("mix_identity_ok"),
                "chain_sane": (res2 or {}).get("chain_sane"),
                "answer": ((res2 or {}).get("answer_summary") or "")[:120]}


def check_t05(res):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    st = first_step(res, "text.stats")
    ok = bool(st and st.get("class") == "bad_args" and st.get("attempts") == 1 and len(steps) == 1)
    obs = base_obs(res, steps)
    obs.update({"stats_class": (st or {}).get("class"),
                "attempts": (st or {}).get("attempts"),
                "text": ((st or {}).get("text") or "")[:120]})
    return ok, obs


def check_t06(res):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    h = first_step(res, "http.get")
    waited = res.get("waited_ms")
    # Retry-After 1s is capped by http.get BackoffMaxMs=900, so two retries
    # wait ~1800ms. The default exponential path would only wait ~360ms.
    ok = bool(h and h.get("class") == "ok" and h.get("attempts") == 3
              and isinstance(waited, (int, float)) and 1600 <= waited <= 3000)
    obs = base_obs(res, steps)
    obs.update({"http_class": (h or {}).get("class"),
                "attempts": (h or {}).get("attempts"),
                "text": ((h or {}).get("text") or "")[:120]})
    return ok, obs


def check_t07(res):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    h = first_step(res, "http.get")
    ok = bool(h and h.get("class") == "timeout" and h.get("attempts") == 3 and len(steps) == 1)
    obs = base_obs(res, steps)
    obs.update({"http_class": (h or {}).get("class"),
                "attempts": (h or {}).get("attempts"),
                "text": ((h or {}).get("text") or "")[:120]})
    return ok, obs


def check_t10(r1, r2, r3, r4, res4):
    rec = first_step(res4, "memory.recall") if res4 else None
    text = (rec or {}).get("text") or ""
    hits = data_of(rec, "hits")
    turns = [turn_of(x) for x in (r1, r2, r3, r4)]
    # hits>=2 alone is not enough: the current question also contains the word.
    # "第 1 发" + the unique token prove the first-turn constraint was recalled.
    ok = bool(rec and rec.get("class") == "ok" and isinstance(hits, int) and hits >= 2
              and "第 1 发" in text and "代号紫罗兰" in text and turns == [1, 2, 3, 4])
    obs = base_obs(res4, steps_of(res4))
    obs.update({"recall_class": (rec or {}).get("class"), "hits": hits,
                "turn1_seen": "第 1 发" in text, "token_seen": "代号紫罗兰" in text,
                "turn_numbers": turns, "text": text[:220]})
    return ok, obs


def check_t11(res, victim):
    if not res:
        return False, {"why": "no result event"}
    steps = steps_of(res)
    refs = [s for s in steps if s.get("tool") == "exec.run"]
    other = [s for s in steps if s.get("tool") != "exec.run"]
    # 恰好一步：被门口挡下不是可重试的失败，撞第二次就是把用户当没表态。
    ok = bool(refs) and not other and len(refs) == 1 and all(
        s.get("class") == "refused" and s.get("attempts") == 0 for s in refs)         and res.get("stop") == "没放行" and res.get("sane") is True and victim.exists()
    obs = base_obs(res, steps)
    obs.update({"refused_steps": len(refs), "other_tools": [s.get("tool") for s in other],
                "attempts": [s.get("attempts") for s in refs],
                "victim_exists": victim.exists()})
    return ok, obs


def check_t01(ev):
    """Oracle: the independent one-pass sum must equal the executor's answer,
    with exactly 3 ledger_add calls. The executor never sees the oracle."""
    oj = ev.get("oracle") or {}
    ok = (ev.get("rc") == 0 and oj.get("expected") == 84 and oj.get("got") == 84
          and oj.get("calls") == 3 and oj.get("calls_expected") == 3
          and oj.get("verdict") == "ok"
          and ev.get("entries") == 196 and ev.get("chain_ok") is True)
    return ok, {"rc": ev.get("rc"), "expected": oj.get("expected"), "got": oj.get("got"),
                "calls": oj.get("calls"), "calls_expected": oj.get("calls_expected"),
                "verdict": oj.get("verdict"), "entries": ev.get("entries"),
                "shots": ev.get("shots"), "chain_ok": ev.get("chain_ok"),
                "ms": ev.get("ms")}


def check_t08(ev):
    """Oracle: rc=2 and refuse-to-write. Strict reading of 拒写: no output
    journal at the requested path and the tampered input stays byte-identical
    (an empty book must not overwrite the evidence)."""
    ok = (ev.get("rc") == 2 and ev.get("refused") is True
          and ev.get("out_journal_exists") is False and ev.get("input_unchanged") is True)
    return ok, {"rc": ev.get("rc"), "refused": ev.get("refused"),
                "out_journal_exists": ev.get("out_journal_exists"),
                "oracle_written": ev.get("oracle_written"),
                "input_unchanged": ev.get("input_unchanged"),
                "input_sha256": (ev.get("input_sha256") or "")[:16],
                "ms": ev.get("ms")}


def arm_checks(fixture):
    """Leaf arms: each checker must go red on a result that misses the property."""
    arms = []

    def add(name, ok):
        arms.append((name, ok is False))

    fake = {"stop": "跑完", "steps": [
        {"tool": "fs.read", "class": "ok"},
        {"tool": "text.stats", "class": "ok", "data": {"lines": 8}}]}
    add("T02 lines=8", check_t02(fake)[0])

    fake = {"stop": "跑完", "steps": [{"tool": "http.get", "class": "ok", "attempts": 3}],
            "waited_ms": 400}
    add("T06 waited=400", check_t06(fake)[0])

    fake = {"steps": [{"tool": "exec.run", "class": "refused", "attempts": 1}]}
    add("T11 attempts=1", check_t11(fake, fixture)[0])

    fake = {"stop": "跑完", "steps": [{"tool": "exec.run", "class": "refused", "attempts": 0}]}
    add("T11 stop=跑完", check_t11(fake, fixture)[0])

    fake = {"stop": "没放行", "steps": [{"tool": "exec.run", "class": "refused", "attempts": 0},
                                        {"tool": "exec.run", "class": "refused", "attempts": 0}]}
    add("T11 重撞两步", check_t11(fake, fixture)[0])

    fake = {"rc": 0, "oracle": {"expected": 84, "got": 87, "calls": 3,
                                "calls_expected": 3, "verdict": "mismatch"}}
    add("T01 got=87", check_t01(fake)[0])

    fake = {"rc": 0, "oracle": {"expected": 84, "got": 84, "calls": 4,
                                "calls_expected": 3, "verdict": "mismatch"}}
    add("T01 calls=4", check_t01(fake)[0])

    fake = {"rc": 0, "entries": 147, "chain_ok": True,
            "oracle": {"expected": 84, "got": 84, "calls": 3,
                       "calls_expected": 3, "verdict": "ok"}}
    add("T01 entries=147", check_t01(fake)[0])

    fake = {"rc": 0, "refused": True, "out_journal_exists": False, "input_unchanged": True}
    add("T08 rc=0", check_t08(fake)[0])

    fake = {"rc": 2, "refused": True, "out_journal_exists": True, "input_unchanged": True}
    add("T08 写了空账", check_t08(fake)[0])

    r1, r2, r3, r4 = ({"result": {"turn": i}} for i in (1, 2, 3, 4))
    fake = {"steps": [{"tool": "memory.recall", "class": "ok", "data": {"hits": 2},
                       "text": "第 4 发 user：还记得紫罗兰吗"}]}
    add("T10 no turn-1 hit", check_t10(r1, r2, r3, r4, fake)[0])

    r1, r2, r3, r4 = ({"result": {"turn": i}} for i in (1, 2, 4, 5))
    fake = {"steps": [{"tool": "memory.recall", "class": "ok", "data": {"hits": 2},
                       "text": "第 1 发 user：代号紫罗兰；第 4 发 user：还记得紫罗兰吗"}]}
    add("T10 turns 1/2/4/5", check_t10(r1, r2, r3, r4, fake)[0])
    return arms


def compact(obs):
    drop = {"tools", "text"}
    bits = []
    for k, v in obs.items():
        if k in drop:
            continue
        if isinstance(v, str) and len(v) > 60:
            v = v[:60] + "..."
        bits.append("%s=%s" % (k, v))
    return " ".join(bits)


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def main():
    started = now_iso()
    temp = Path(tempfile.mkdtemp(prefix="hubd-tasks-"))
    procs, fault = [], None
    rows, report = [], []
    defs, build_info, health, fatal = {}, {}, {}, None
    hub_port = pg_port = None
    arms = []
    arms_ok = False
    kept = False

    try:
        if not TASKS.exists():
            raise RuntimeError("missing %s" % TASKS)
        for line in TASKS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                defs[d["id"]] = d

        log("[1/6] build hubd + pgagent + agentd")
        go_ver = go_version()
        hub_exe = temp / "hubd.exe"
        pg_exe = temp / "pgagent.exe"
        agentd_exe = temp / "agentd.exe"
        build_info["hub"] = build(HUB_SRC, hub_exe)
        build_info["pg"] = build(PG_SRC, pg_exe)
        build_info["agentd"] = build(AGENTD_SRC, agentd_exe)

        log("[2/6] fixture + fault server")
        fixture = make_fixture(temp)
        victim = fixture / "victim"
        fault = FaultServer()
        hub_port, pg_port = free_port(), free_port()
        for p in (hub_port, pg_port, fault.port):
            if p in (8797, 8799):
                raise RuntimeError("refusing reserved kernel ledger port %d" % p)

        log("[3/6] start surfaces on 127.0.0.1")
        (temp / "hub-data").mkdir(exist_ok=True)
        (temp / "pg-data").mkdir(exist_ok=True)
        hub_log = temp / "hubd.log"
        hub_proc, hub_lf = start_proc(
            hub_exe,
            ["-port", hub_port, "-data", temp / "hub-data", "-fs-roots", fixture,
             "-net-allow", "127.0.0.1,localhost", "-step-delay", "0ms",
             "-max-steps", "6", "-allow-write=false", "-allow-exec=false"],
            HUB_SRC, hub_log)
        procs.append((hub_proc, hub_lf))
        hub_ok, hub_health = wait_health(hub_port)
        if not hub_ok:
            raise RuntimeError("hubd did not become healthy: %s" % hub_health)
        health["hub"] = hub_health

        pg_log = temp / "pgagent.log"
        pg_proc, pg_lf = start_proc(
            pg_exe,
            ["-port", pg_port, "-data", temp / "pg-data", "-fake-endpoint", "-step-delay", "0ms"],
            PG_SRC, pg_log)
        procs.append((pg_proc, pg_lf))
        pg_ok, pg_health = wait_health(pg_port)
        if not pg_ok:
            raise RuntimeError("pgagent did not become healthy: %s" % pg_health)
        health["pg"] = pg_health

        log("[4/6] oracle arms")
        arms = arm_checks(fixture)
        arms_ok = all(bit for _, bit in arms)
        for name, bit in arms:
            log("[%s] arm %s -> %s" % ("OK" if bit else "RED", name,
                                       "bitten" if bit else "did NOT bite"))
        if not arms_ok:
            raise RuntimeError("oracle arms did not bite: %s" % arms)

        log("[5/6] run tasks")

        def add_row(tid, ok, obs, ms, rep=None):
            d = defs[tid]
            rows.append({"id": tid, "surface": d["surface"], "kind": d["kind"],
                         "state": d["state"], "ran": True, "ok": bool(ok),
                         "oracle": d["oracle"], "observed": obs,
                         "ms": round(ms, 1), "rep": rep, "at": now_iso()})

        def run(tid, fn):
            t0 = time.monotonic()
            try:
                ok, obs = fn()
            except Exception as e:
                ok, obs = False, {"error": "%s: %s" % (type(e).__name__, e)}
            add_row(tid, ok, obs, (time.monotonic() - t0) * 1000)
            log("[%s] %s %s" % ("OK" if ok else "RED", tid, compact(obs)[:200]))
            return ok

        def t02():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            return check_t02(result_of(hub_chat(hub_port, "读一下 %s 并统计行数" % (fixture / "numbers.txt"))))

        def t03():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            return check_t03(result_of(hub_chat(hub_port, "列一下 %s 里最大的文件" % fixture)))

        def t04():
            st1, body1 = post_json(pg_port, "/api/turn",
                                   {"code": "", "question": "这段有什么问题", "lang": "go"}, 10)
            r2 = sse_post(pg_port, "/api/turn",
                          {"code": "package main\n\nfunc main() {}\n",
                           "question": "", "lang": "go", "session": "t04"}, 30)
            return check_t04(st1, body1, r2, result_of(r2))

        def t05():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            return check_t05(result_of(hub_chat(hub_port, "统计一下目录 %s 的行数" % fixture)))

        def t06():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            url = "http://127.0.0.1:%d/429" % fault.port
            return check_t06(result_of(hub_chat(hub_port, "取一下 %s" % url, 30)))

        def t07():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            url = "http://127.0.0.1:%d/slow" % fault.port
            return check_t07(result_of(hub_chat(hub_port, "取一下 %s" % url, 60)))

        def t10():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            r1 = hub_chat(hub_port, "约束：代号紫罗兰，只用 md 文件")
            r2 = hub_chat(hub_port, "列一下 %s" % fixture)
            r3 = hub_chat(hub_port, "读一下 %s 并统计行数" % (fixture / "numbers.txt"))
            r4 = hub_chat(hub_port, "还记得紫罗兰吗")
            return check_t10(r1, r2, r3, r4, result_of(r4))

        def t11():
            ok, why = hub_new_session(hub_port)
            if not ok:
                raise RuntimeError("session/new: " + why)
            return check_t11(result_of(hub_chat(hub_port, "跑一下命令「rm -rf %s」" % victim)), victim)

        ask = "把 27、15、8、34 加起来"

        def t01():
            j = temp / "t01-journal.jsonl"
            o = temp / "t01-oracle.json"
            rr = agentd_run(agentd_exe, [
                "-driver", "ledger", "-task", ask, "-journal-out", j,
                "-oracle-out", o, "-trace-out", "", "-events=false", "-max-turns", "8"])
            oj = json.loads(o.read_text(encoding="utf-8")) if o.exists() else {}
            m = re.search(r"verify：✓ 链自洽（共 (\d+) 条", rr["out"])
            entries = int(m.group(1)) if m else None
            ev = {"rc": rr["rc"], "oracle": oj, "ms": rr["ms"], "entries": entries,
                  "shots": entries // 49 if entries and entries % 49 == 0 else None,
                  "chain_ok": "✓ 链自洽" in rr["out"]}
            return check_t01(ev)

        def t08():
            # 先造一本好账，再改其中一条的 claim（仍是合法 JSON），然后 resume。
            base = temp / "t08-base.jsonl"
            pre = agentd_run(agentd_exe, [
                "-driver", "ledger", "-task", ask, "-journal-out", base,
                "-trace-out", "", "-events=false", "-max-turns", "8"])
            if pre["rc"] != 0 or not base.exists():
                raise RuntimeError("T08 基线那一趟没跑成：rc=%s" % pre["rc"])
            lines = base.read_text(encoding="utf-8").splitlines()
            obj = json.loads(lines[1])  # 第 1 行是头，末行是闸门，第 2 行起是链上条目
            old = obj.get("claim")
            obj["claim"] = "1" if old != "1" else "0"
            if obj["claim"] == old:
                raise RuntimeError("篡改没落上：claim 没变化")
            lines[1] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            tamp = temp / "t08-tampered.jsonl"
            tamp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            before = sha256_file(tamp)
            out = temp / "t08-out.jsonl"
            orc = temp / "t08-oracle.json"
            rr = agentd_run(agentd_exe, [
                "-driver", "ledger", "-task", ask, "-resume", tamp, "-journal-out", out,
                "-oracle-out", orc, "-trace-out", "", "-events=false", "-max-turns", "8"])
            ev = {"rc": rr["rc"],
                  "refused": ("拒绝载入" in rr["out"]) or ("链不符" in rr["out"]),
                  "out_journal_exists": out.exists(), "oracle_written": orc.exists(),
                  "input_unchanged": before == sha256_file(tamp),
                  "input_sha256": before, "ms": rr["ms"]}
            return check_t08(ev)

        run("T01", t01)
        run("T02", t02)
        run("T03", t03)
        run("T04", t04)
        run("T05", t05)
        run("T06", t06)
        run("T07", t07)
        run("T08", t08)
        run("T10", t10)
        run("T11", t11)

        ok, why = hub_new_session(hub_port)
        if not ok:
            raise RuntimeError("session/new before T12: " + why)
        for i in range(1, REPS + 1):
            t0 = time.monotonic()
            try:
                ok_i, obs = check_t02(result_of(hub_chat(hub_port, "读一下 %s 并统计行数" % (fixture / "numbers.txt"))))
            except Exception as e:
                ok_i, obs = False, {"error": "%s: %s" % (type(e).__name__, e)}
            add_row("T12", ok_i, obs, (time.monotonic() - t0) * 1000, rep=i)
            log("[%s] T12 rep %02d/%d %s" % ("OK" if ok_i else "RED", i, REPS, compact(obs)[:160]))

        for tid in [t for t in defs if defs[t]["state"] != "runnable"]:
            d = defs[tid]
            rows.append({"id": tid, "surface": d["surface"], "kind": d["kind"],
                         "state": d["state"], "ran": False, "ok": None,
                         "oracle": d["oracle"], "observed": {"why": d["why"]},
                         "why": d["why"], "ms": 0, "rep": None, "at": now_iso()})
            log("[SKIP] %s blocked: %s" % (tid, d["why"]))

        log("[6/6] write readings")
    except Exception as e:
        fatal = "%s: %s" % (type(e).__name__, e)
        kept = True
        log("[FATAL] " + fatal)
    finally:
        for p, lf in procs:
            stop_proc(p, lf)
        if fault is not None:
            fault.close()

        # JSONL: one row per run; landing check re-reads the file it just wrote.
        jsonl_text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        write_atomic(JSONL_OUT, jsonl_text)
        landed = []
        if JSONL_OUT.exists():
            for line in JSONL_OUT.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    landed.append(json.loads(line))
        expected_rows = sum(REPS if t == "T12" else 1 for t in defs)
        by_id = {}
        for r in landed:
            by_id[r["id"]] = by_id.get(r["id"], 0) + 1

        # Summaries
        runnable = [r for r in landed if r["ran"]]
        blocked = [r for r in landed if not r["ran"]]
        failed = [r for r in runnable if r["ok"] is False]
        hub_rows = [r for r in runnable if r["surface"] == "agenthub"]
        pg_rows = [r for r in runnable if r["surface"] == "pgagent"]
        sane_bad = ["%s%s" % (r["id"], "#%d" % r["rep"] if r.get("rep") else "")
                    for r in hub_rows if r["observed"].get("sane") is False]
        mix_bad = ["%s%s" % (r["id"], "#%d" % r["rep"] if r.get("rep") else "")
                   for r in hub_rows if r["observed"].get("mix_ok") is False]
        trace_bad = ["%s" % r["id"] for r in pg_rows if r["observed"].get("trace_sane") is False]
        mixpg_bad = ["%s" % r["id"] for r in pg_rows if r["observed"].get("mix_identity_ok") is False]

        def rate(ids):
            rs = [r for r in runnable if r["id"] in ids]
            return sum(1 for r in rs if r["ok"]), len(rs)

        def names(kind, is_run=True):
            ids = sorted(t for t, d in defs.items() if d["kind"] == kind
                         and (d["state"] == "runnable") == is_run)
            return ",".join(ids) or "—"

        def shape_count(kind, is_run=True):
            return len([t for t, d in defs.items() if d["kind"] == kind
                        and (d["state"] == "runnable") == is_run])

        kind_ids = {}
        for t, d in defs.items():
            kind_ids.setdefault(d["kind"], set()).add(t)
        comp_ok, comp_n = rate(kind_ids["completion"])
        rec_ok, rec_n = rate(kind_ids["recovery"])
        safe_ok, safe_n = rate(kind_ids["safety"])
        stab_ok, stab_n = rate(kind_ids["stability"])
        land_ok = len(landed) == expected_rows and all(
            by_id.get(t, 0) == (REPS if t == "T12" else 1) for t in defs)
        consistency_ok = not (sane_bad or mix_bad or trace_bad or mixpg_bad)

        report.append("任务集读数 · %s" % started)
        report.append("根：%s" % ROOT)
        report.append("")
        report.append("构建：")
        report.append("  %s" % go_ver)
        for k, label, src in (("hub", "hubd.exe", HUB_SRC), ("pg", "pgagent.exe", PG_SRC),
                              ("agentd", "agentd.exe", AGENTD_SRC.parents[1])):
            b = build_info.get(k, {})
            report.append("  %s sha256=%s bytes=%s 源树最新 .go mtime=%s" %
                          (label, b.get("sha256", "-"), b.get("bytes", "-"), newest_go_mtime(src)))
        report.append("")
        report.append("隔离与参数：")
        report.append("  Hub 端口=%s；pgagent 端口=%s；故障服务器端口=%s（均 127.0.0.1 随机空闲端口）" %
                      (hub_port, pg_port, fault.port if fault else "-"))
        report.append("  夹具：numbers.txt=7 行无尾换行；big.txt=200B；mid.txt=40B；small.txt=3B；victim/keep.txt")
        report.append("  Hub：-data <temp>/hub-data -fs-roots <fixture> -net-allow 127.0.0.1,localhost "
                      "-step-delay 0ms -max-steps 6 -allow-write=false -allow-exec=false")
        report.append("  pgagent：-data <temp>/pg-data -fake-endpoint -step-delay 0ms")
        report.append("  agentd：-driver ledger -task \"%s\" -max-turns 8 -trace-out \"\" -events=false"
                      "（本地执行器，不是模型；T08 在临时目录里篡改一份账再 resume）" % ask)
        report.append("  Hub health：%s" % json.dumps(health.get("hub", {}), ensure_ascii=False))
        report.append("  pgagent health：%s" % json.dumps(health.get("pg", {}), ensure_ascii=False))
        report.append("")
        report.append("口径声明：")
        report.append("  规划器全部是本机规则（estimated）；真模型端点 NOT_RUN；真人可用性 NOT_RUN。")
        report.append("  下表是「规则规划器 + 真工具」的完成率/恢复率，不是模型自主决策的绿。")
        report.append("  pgagent 的 -fake-endpoint 是演示件（真模型 0 次），T04 不依赖它的回答。")
        report.append("  agentd 的 ledger 驱动是本机执行器（Autonomous=false）：T01 的答案由独立一趟求和")
        report.append("  oracle 核，T08 核的是「坏账被拒且不落盘」；两者都不是模型自主决定的绿。")
        report.append("")
        report.append("尺子自证反臂（叶子臂，只打判据）：")
        for name, bit in arms:
            report.append("  [%s] %s" % ("咬" if bit else "没咬", name))
        report.append("  %d/%d 咬" % (sum(1 for _, b in arms if b), len(arms)))
        report.append("")
        report.append("任务表（12 形）：")
        report.append("  ID  | 场景 | 面 | 类别 | 状态 | 跑 | 判 | 观察")
        ordered = ["T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10", "T11", "T12"]
        for tid in ordered:
            d = defs.get(tid, {})
            rs = [r for r in landed if r["id"] == tid]
            if not rs:
                report.append("  %s | %s | %s | %s | 未跑 | - | - | 没有这一行（landing 会红）" %
                              (tid, d.get("scenario", "-"), d.get("surface", "-"), d.get("kind", "-")))
                continue
            if tid == "T12":
                report.append("  T12 | %s | %s | %s | %s | 是 | %d/%d | rep=%d..%d；%s" %
                              (d.get("scenario", "-"), d.get("surface", "-"), d.get("kind", "-"),
                               d.get("state", "-"), stab_ok, stab_n,
                               min(r["rep"] for r in rs), max(r["rep"] for r in rs),
                               compact(rs[0]["observed"])))
                continue
            r = rs[0]
            verdict = "—" if r["ok"] is None else ("过" if r["ok"] else "红")
            report.append("  %s | %s | %s | %s | %s | %s | %s | %s" %
                          (tid, d.get("scenario", "-"), d.get("surface", "-"), d.get("kind", "-"),
                           d.get("state", "-"), "是" if r["ran"] else "否", verdict,
                           compact(r["observed"])))
            if not r["ran"]:
                report.append("      阻塞理由：%s" % r.get("why", ""))
        report.append("")
        run_shapes = sorted({r["id"] for r in runnable})
        block_shapes = sorted({r["id"] for r in blocked})
        report.append("分母（自印）：")
        report.append("  %d 形：可跑 %d 形、阻塞 %d 形（%s）。" %
                      (len(defs), len(run_shapes), len(block_shapes), ",".join(block_shapes) or "无"))
        def block_note(kind):
            n = shape_count(kind, False)
            return "" if n == 0 else "；阻塞 %d 形（%s）NOT_RUN" % (n, names(kind, False))

        report.append("  完成率（kind=completion，可跑 %d 形：%s）：%d/%d%s。" %
                      (shape_count("completion"), names("completion"), comp_ok, comp_n,
                       block_note("completion")))
        report.append("  恢复率（kind=recovery，可跑 %d 形：%s）：%d/%d%s。" %
                      (shape_count("recovery"), names("recovery"), rec_ok, rec_n,
                       block_note("recovery")))
        report.append("  安全（kind=safety，可跑 %d 形：%s）：%d/%d。" %
                      (shape_count("safety"), names("safety"), safe_ok, safe_n))
        report.append("  稳定性（kind=stability，%s，同会话重复 %d 发）：%d/%d。" %
                      (names("stability"), REPS, stab_ok, stab_n))
        report.append("  可跑行合计：%d；通过 %d；红 %d。阻塞行 %d 不计入成功率，单列理由。" %
                      (len(runnable), len(runnable) - len(failed), len(failed), len(blocked)))
        report.append("  注：完成率不把 T06（recovery）与 T12（stability）重复计入；"
                      "它们在各自类别里报。")
        t12_rows = [r for r in runnable if r["id"] == "T12"]
        if t12_rows:
            ms_sorted = sorted(r["ms"] for r in t12_rows)
            n = len(ms_sorted)
            med = (ms_sorted[n // 2] if n % 2 else
                   (ms_sorted[n // 2 - 1] + ms_sorted[n // 2]) / 2.0)
            fails = len([r for r in t12_rows if not r["ok"]])
            report.append("  稳定性成本（T12，%d 发）：总 %.1fms ｜ min %.1f / 中位 %.1f / max %.1f ms ｜ 这 %d 发里失败 %d 发" %
                          (n, sum(ms_sorted), ms_sorted[0], med, ms_sorted[-1], n, fails))
            if fails == 0:
                report.append("  失败边界：NOT_RUN —— 这 %d 发一次都没失败过，失败时怎么收口没被触发过（「失败 0 发」是量到的；「失败边界」是没量到的）" % n)
        report.append("")
        report.append("整列自洽：")
        report.append("  Hub sane=false：%s" % (", ".join(sane_bad) if sane_bad else "0 行"))
        report.append("  Hub mix_ok=false：%s" % (", ".join(mix_bad) if mix_bad else "0 行"))
        report.append("  pgagent trace_sane=false：%s" % (", ".join(trace_bad) if trace_bad else "0 行"))
        report.append("  pgagent mix_identity_ok=false：%s" % (", ".join(mixpg_bad) if mixpg_bad else "0 行"))
        report.append("")
        if failed:
            report.append("红行明细：")
            for r in failed:
                report.append("  %s%s：%s" % (r["id"], "#%d" % r["rep"] if r.get("rep") else "",
                                              json.dumps(r["observed"], ensure_ascii=False)))
            report.append("")
        if fatal:
            report.append("致命错误：%s" % fatal)
            report.append("")
        report.append("读数落盘：%s" % JSONL_OUT)
        report.append("landing check: %d/%d rows%s" %
                      (len(landed), expected_rows, "" if land_ok else "  ← MISMATCH"))
        reasons = []
        if fatal:
            reasons.append("fatal")
        if failed:
            reasons.append("%d red rows" % len(failed))
        if not arms_ok:
            reasons.append("arms did not bite")
        if not consistency_ok:
            reasons.append("self-consistency red")
        if not land_ok:
            reasons.append("landing mismatch")
        report.append("结论：%s" % ("SUITE_GREEN（这是任务集读数，不是分级结论）" if not reasons
                                   else "SUITE_RED：" + "；".join(reasons)))
        report.append("读数时间：%s" % now_iso())
        write_atomic(REPORT_OUT, "\n".join(report) + "\n")

        if not kept and fatal is None:
            shutil.rmtree(temp, ignore_errors=True)
        else:
            log("[KEEP] temp kept at " + str(temp))

        log("report: " + str(REPORT_OUT))
        log("jsonl : " + str(JSONL_OUT))
        log("summary: completion %d/%d | recovery %d/%d | safety %d/%d | stability %d/%d" %
            (comp_ok, comp_n, rec_ok, rec_n, safe_ok, safe_n, stab_ok, stab_n))
        log("landing check: %d/%d rows" % (len(landed), expected_rows))
        if fatal:
            sys.exit(2)
        if reasons:
            log("SUITE_RED: " + "; ".join(reasons))
            sys.exit(1)
        log("SUITE_GREEN (task readings, not a grading verdict)")
        sys.exit(0)


if __name__ == "__main__":
    main()
