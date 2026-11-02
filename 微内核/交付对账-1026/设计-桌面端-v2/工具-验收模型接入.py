# -*- coding: utf-8 -*-
"""模型组件接主服务的端到端验收：假上游 -> 模型桥 -> 微核台本地服务 -> 对话 API。

只打 127.0.0.1；假上游与测试口令均在本进程临时生成，不碰真端点。
控制台只打印 ASCII；证据写 读数/模型接入验收.json（UTF-8）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable
SERVICE = BASE / "工具-本地服务.py"
BRIDGE = BASE / "模型桥.py"
HTML = BASE / "微核台.html"
READOUT = BASE / "读数" / "模型接入验收.json"
BRIDGE_LOG = BASE / "读数" / "模型桥-日志.jsonl"
MEMORY = BASE / "记忆" / "记忆.json"
KEY = "TEST-KEY-MODEL-INTEGRATION-7f3a9c"
QUESTION_MODEL = "接入验收：D-1026-01 哪几条声明与盘上不符？"
QUESTION_LOCAL = "测试过了吗？"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:500]})
    print(("PASS " if ok else "FAIL ") + name)


def sha_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read(500000).decode("utf-8"))


def post_json(url, obj, timeout=50):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(500000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read(500000).decode("utf-8"))


def wait_health(url, timeout=10):
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        try:
            st, obj = get_json(url + "/health" if not url.endswith("/") else url + "health", timeout=1)
            if st == 200:
                return obj
        except Exception as e:
            last = str(e)
        time.sleep(0.15)
    raise RuntimeError("health timeout: " + last)


def start_proc(cmd, env, cwd, marker):
    p = subprocess.Popen(
        [PY] + cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    url = ""
    lines = []
    end = time.time() + 20
    while time.time() < end:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        line = line.strip()
        lines.append(line)
        if line.startswith(marker):
            url = line.split(marker, 1)[1].strip()
            break
    if not url:
        tail = "\n".join(lines[-8:])
        p.terminate()
        raise RuntimeError("no " + marker + " from " + " ".join(cmd) + " output=" + tail)
    return p, url, lines


def stop_proc(p):
    if p is None:
        return
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


class Upstream:
    def __init__(self):
        self.mode = "ok"
        self.requests = []
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            server_version = "StubUpstream/1.0"

            def log_message(self, fmt, *args):
                pass

            def _send(self, code, obj, raw=None):
                body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                with outer.lock:
                    outer.requests.append({
                        "path": self.path,
                        "headers": dict(self.headers),
                        "raw": raw,
                        "mode": outer.mode,
                    })
                    mode = outer.mode
                if mode == "error500":
                    return self._send(500, {"error": "stub upstream rejected key " + KEY})
                if mode == "bad":
                    return self._send(200, None, raw=b"not-json-at-all")
                content = json.dumps({
                    "title": "摘要复核",
                    "text": "D1-C4 不符；D9-C9 不在摘要里，核不了。",
                    "refs": ["D1-C4", "D9-C9"],
                }, ensure_ascii=False)
                return self._send(200, {
                    "id": "stub-1",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
                })

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def base_env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WEIHETAI_MODEL_")}
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def main():
    if not HTML.exists():
        print("RESULT FAIL missing build")
        return 2
    if not BRIDGE.exists() or not SERVICE.exists():
        print("RESULT FAIL missing component")
        return 2
    page = HTML.read_bytes()
    page_sha = hashlib.sha256(page).hexdigest()
    log_size = BRIDGE_LOG.stat().st_size if BRIDGE_LOG.exists() else 0
    up = Upstream()
    bridge = core = core_off = bridge_unc = core_unc = None
    try:
        # ---- 1. configured bridge + core ----
        bridge, burl, _ = start_proc(
            ["模型桥.py", "--port", "0"],
            base_env({
                "WEIHETAI_MODEL_BASE_URL": f"http://127.0.0.1:{up.port}/v1",
                "WEIHETAI_MODEL": "stub-model-1",
                "WEIHETAI_MODEL_KEY": KEY,
                "WEIHETAI_MODEL_TIMEOUT": "3",
            }),
            BASE, "MODEL_BRIDGE ",
        )
        bh = wait_health(burl)
        check("bridge ready", bh.get("state") == "ready" and bh.get("model") == "stub-model-1", bh.get("state"))
        check("bridge key is flag only", bh.get("key_present") is True and KEY not in json.dumps(bh), bh.get("key_present"))

        core, curl, _ = start_proc(
            ["工具-本地服务.py", "--port", "0", "--no-open", "--no-kernel"],
            base_env({"WEIHETAI_MODEL_BRIDGE": burl}),
            BASE, "READY ",
        )
        st, state = get_json(curl + "api/state")
        check("state 200 with model", st == 200 and state.get("ok") is True, st)
        m = state.get("model") or {}
        check("state model ready", m.get("state") == "ready" and m.get("model") == "stub-model-1", m.get("state"))
        check("state model boundary present", "不发记忆" in (m.get("boundary") or ""), m.get("boundary"))
        check("state has no key", KEY not in json.dumps(state, ensure_ascii=False))
        st, mo = get_json(curl + "api/model")
        check("api model ready", st == 200 and (mo.get("model") or {}).get("state") == "ready", st)
        with urllib.request.urlopen(curl, timeout=5) as r:
            served = r.read()
        check("served bytes match build", served == page, f"got={len(served)} file={len(page)}")
        check("served sha match build", hashlib.sha256(served).hexdigest() == page_sha)
        post_json(curl + "api/memory/clear", {"confirm": "CLEAR"})

        # ---- 2. local rules stay 0 calls ----
        st, r = post_json(curl + "api/dialogue", {"q": QUESTION_LOCAL})
        a = r.get("answer") or {}
        check("local answer measured", st == 200 and a.get("tier") == "measured", a.get("tier"))
        check("local answer source local_rules", a.get("source") == "local_rules" and a.get("model_calls") == 0, a.get("source"))
        check("local answer made no upstream call", len(up.requests) == 0, len(up.requests))

        st, r = post_json(curl + "api/dialogue", {"q": QUESTION_LOCAL, "use_model": "true"})
        a = r.get("answer") or {}
        check("string use_model stays local", st == 200 and a.get("source") == "local_rules" and len(up.requests) == 0, a.get("source"))

        # ---- 3. model_says path ----
        st, r = post_json(curl + "api/dialogue", {"q": QUESTION_MODEL, "use_model": True})
        a = r.get("answer") or {}
        check("model answer 200", st == 200, st)
        check("model answer tier model_says", a.get("tier") == "model_says", a.get("tier"))
        check("model answer source model", a.get("source") == "model" and a.get("model_calls") == 1, a.get("source"))
        check("model answer title from upstream", a.get("title") == "摘要复核", a.get("title"))
        check("model answer text from upstream", "D1-C4 不符" in (a.get("text") or ""), a.get("text"))
        refs = [x.get("claim") for x in (a.get("refs") or [])]
        check("model refs only valid ids", refs == ["D1-C4"], refs)
        check("model answer no key", KEY not in json.dumps(r, ensure_ascii=False))
        check("one upstream call", len(up.requests) == 1, len(up.requests))

        req = up.requests[-1]
        check("upstream path v1/chat/completions", req["path"] == "/v1/chat/completions", req["path"])
        auth = req["headers"].get("Authorization") or req["headers"].get("authorization") or ""
        check("upstream bearer key", auth == "Bearer " + KEY, auth[:24])
        raw_text = req["raw"].decode("utf-8", "replace")
        check("upstream body has no key", KEY not in raw_text)
        body = json.loads(raw_text)
        check("upstream model name", body.get("model") == "stub-model-1", body.get("model"))
        check("upstream temperature 0", body.get("temperature") == 0, body.get("temperature"))
        user = json.loads(body["messages"][1]["content"])
        ev = user.get("evidence") or {}
        check("digest top keys whitelist", set(ev) <= {"deliveries", "not_same_run"}, sorted(ev))
        check("digest 3 deliveries / 16 claims", len(ev.get("deliveries") or []) == 3 and sum(len(d.get("claims") or []) for d in ev["deliveries"]) == 16, len(ev.get("deliveries") or []))
        claim_keys = {k for d in ev["deliveries"] for c in d["claims"] for k in c}
        check("digest claim keys whitelist", claim_keys == {"id", "text", "verdict", "basis", "why"}, sorted(claim_keys))
        leaky = [x for x in ("本机操作者", "记忆/", "回执/", "receipt-", "api_key") if x in raw_text]
        hash_like = re.search(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40,64}(?![0-9a-fA-F])", raw_text)
        drive_like = re.search(r"[A-Za-z]:\\\\", raw_text)
        check("digest has no memory/operator/path", not leaky and not hash_like and not drive_like, {"leaky": leaky, "hash": bool(hash_like), "drive": bool(drive_like)})
        check("question sent with digest", user.get("question") == QUESTION_MODEL, user.get("question"))

        # ---- 4. upstream 500 -> absent, key redacted ----
        up.mode = "error500"
        st, r = post_json(curl + "api/dialogue", {"q": QUESTION_MODEL, "use_model": True})
        a = r.get("answer") or {}
        check("upstream 500 maps absent", st == 200 and a.get("tier") == "absent", a.get("tier"))
        check("upstream 500 title", a.get("title") == "模型没有答上来", a.get("title"))
        check("upstream 500 call counted", a.get("model_calls") == 1 and len(up.requests) == 2, a.get("model_calls"))
        check("upstream 500 says call happened", "发生了" in (a.get("text") or ""), a.get("text"))
        check("upstream 500 no key in answer", KEY not in json.dumps(r, ensure_ascii=False))

        # ---- 5. malformed upstream -> absent ----
        up.mode = "bad"
        st, r = post_json(curl + "api/dialogue", {"q": QUESTION_MODEL, "use_model": True})
        a = r.get("answer") or {}
        check("bad response maps absent", st == 200 and a.get("tier") == "absent" and a.get("model_error") == "BAD_RESPONSE", a.get("model_error"))
        check("bad response call counted", a.get("model_calls") == 1 and len(up.requests) == 3, a.get("model_calls"))

        # ---- 6. persisted row keeps source and no key ----
        st, mem = get_json(curl + "api/memory")
        rows = (mem.get("memory") or {}).get("dialogue") or []
        model_rows = [x for x in rows if x.get("q") == QUESTION_MODEL and x.get("source") == "model"]
        check("memory has model rows", len(model_rows) >= 1, len(rows))
        check("memory model row has calls/model", model_rows and model_rows[0].get("model_calls") == 1 and model_rows[0].get("model") == "stub-model-1", model_rows and model_rows[0].get("model"))
        check("memory file no key", MEMORY.exists() and KEY not in MEMORY.read_text(encoding="utf-8"))
        new_log = ""
        if BRIDGE_LOG.exists():
            with BRIDGE_LOG.open("rb") as f:
                f.seek(log_size)
                new_log = f.read().decode("utf-8", "replace")
        check("bridge log no key", KEY not in new_log)
        check("bridge log no question", QUESTION_MODEL not in new_log and QUESTION_LOCAL not in new_log)
        check("bridge log has explain events", '"event": "explain"' in new_log, len(new_log))

        # ---- 7. no bridge: off, use_model absent 0 calls ----
        core_off, curl_off, _ = start_proc(
            ["工具-本地服务.py", "--port", "0", "--no-open", "--no-kernel"],
            base_env(), BASE, "READY ",
        )
        st, state = get_json(curl_off + "api/state")
        check("no bridge state off", (state.get("model") or {}).get("state") == "off", (state.get("model") or {}).get("state"))
        st, r = post_json(curl_off + "api/dialogue", {"q": QUESTION_MODEL, "use_model": True})
        a = r.get("answer") or {}
        check("no bridge answer absent", a.get("tier") == "absent" and a.get("title") == "模型未接入", a.get("title"))
        check("no bridge 0 calls", a.get("model_calls") == 0 and a.get("source") == "model", a.get("model_calls"))
        st, r2 = post_json(curl_off + "api/dialogue", {"q": QUESTION_LOCAL})
        check("no bridge local still works", (r2.get("answer") or {}).get("tier") == "measured", (r2.get("answer") or {}).get("tier"))

        # ---- 8. unconfigured bridge: absent, 0 calls ----
        bridge_unc, burl_unc, _ = start_proc(
            ["模型桥.py", "--port", "0"], base_env(), BASE, "MODEL_BRIDGE ",
        )
        bh = wait_health(burl_unc)
        check("unconfigured bridge state", bh.get("state") == "unconfigured", bh.get("state"))
        core_unc, curl_unc, _ = start_proc(
            ["工具-本地服务.py", "--port", "0", "--no-open", "--no-kernel"],
            base_env({"WEIHETAI_MODEL_BRIDGE": burl_unc}), BASE, "READY ",
        )
        st, state = get_json(curl_unc + "api/state")
        check("core sees unconfigured", (state.get("model") or {}).get("state") == "unconfigured", (state.get("model") or {}).get("state"))
        st, r = post_json(curl_unc + "api/dialogue", {"q": QUESTION_MODEL, "use_model": True})
        a = r.get("answer") or {}
        check("unconfigured answer absent", a.get("tier") == "absent" and a.get("title") == "模型桥不可用", a.get("title"))
        check("unconfigured 0 calls", a.get("model_calls") == 0, a.get("model_calls"))

        # ---- 9. clean up test dialogue ----
        post_json(curl + "api/memory/clear", {"confirm": "CLEAR"})
        st, mem = get_json(curl + "api/memory")
        check("test dialogue cleared", not (mem.get("memory") or {}).get("dialogue"), len((mem.get("memory") or {}).get("dialogue") or []))

        bad = [x for x in RESULTS if not x["ok"]]
        out = {
            "result": "PASS" if not bad else "FAIL",
            "checks": len(RESULTS) - len(bad),
            "total": len(RESULTS),
            "build": {"file": HTML.name, "bytes": len(page), "sha256": page_sha},
            "model": {"base_host": "http://127.0.0.1:" + str(up.port), "model": "stub-model-1"},
            "upstream_requests": len(up.requests),
            "checks_detail": RESULTS,
        }
        READOUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("RESULT " + out["result"] + " checks=%d/%d" % (out["checks"], out["total"]))
        print("READOUT 读数/模型接入验收.json")
        return 0 if not bad else 1
    except Exception as e:
        out = {
            "result": "ERROR", "error": repr(e),
            "checks": len([x for x in RESULTS if x["ok"]]), "total": len(RESULTS),
            "checks_detail": RESULTS,
        }
        READOUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("RESULT ERROR " + repr(e)[:300])
        return 2
    finally:
        stop_proc(core_unc)
        stop_proc(bridge_unc)
        stop_proc(core_off)
        stop_proc(core)
        stop_proc(bridge)
        up.stop()


if __name__ == "__main__":
    sys.exit(main())
