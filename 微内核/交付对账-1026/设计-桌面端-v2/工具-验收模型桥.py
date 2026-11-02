# -*- coding: utf-8 -*-
"""模型桥验收：用本机假端点逐项验，不碰真端点、不打印口令。
产物：读数/模型桥验收.json（UTF-8），控制台只打 ASCII。
退出码：0 全过；1 有失败；2 环境/启动失败。
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable
BRIDGE = BASE / "模型桥.py"
OUT = BASE / "读数" / "模型桥验收.json"
SENTINEL_KEY = "TEST-KEY-DO-NOT-USE-0123456789"

results = []


def rec(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:600]})
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def http_json(url, method="GET", body=None, headers=None, timeout=8):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            obj = {"raw": raw.decode("utf-8", "replace")[:300]}
        return e.code, obj


GOOD_DIGEST = {
    "deliveries": [
        {
            "id": "D-1",
            "title": "样例交付",
            "agent": "本地 Agent",
            "verdict": "NOT-ACCEPTED-MISMATCH",
            "counts": {"MATCH": 1, "MISMATCH": 1, "ABSENT": 0},
            "claims": [
                {"id": "D1-C1", "text": "测试通过", "verdict": "MISMATCH", "basis": "disk", "why": "13 步里没有测试步"},
                {"id": "D1-C2", "text": "没有执行代码", "verdict": "MATCH", "basis": "disk", "why": "code_executed=false"},
            ],
        }
    ],
    "not_same_run": ["样例，非同发"],
}


class FakeUpstream(BaseHTTPRequestHandler):
    mode = "ok"
    last = {}
    sleep_s = 0.0

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        FakeUpstream.last = {
            "path": self.path,
            "auth": self.headers.get("Authorization") or "",
            "body": raw.decode("utf-8", "replace"),
        }
        if FakeUpstream.sleep_s:
            time.sleep(FakeUpstream.sleep_s)
        if FakeUpstream.mode == "500":
            body = b'{"error":"boom","key":"' + SENTINEL_KEY.encode() + b'"}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if FakeUpstream.mode == "empty":
            payload = {"choices": []}
        elif FakeUpstream.mode == "text":
            payload = {"choices": [{"message": {"content": "D1-C1 不符：13 步里没有测试步。"}}], "usage": {"total_tokens": 12}}
        else:
            content = json.dumps({"title": "模型转述", "text": "D1-C1 不符：13 步里没有测试步。", "refs": ["D1-C1", "D9-C9"]}, ensure_ascii=False)
            payload = {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_fake():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def start_bridge(env_extra):
    env = os.environ.copy()
    env.pop("WEIHETAI_MODEL_BASE_URL", None)
    env.pop("WEIHETAI_MODEL", None)
    env.pop("WEIHETAI_MODEL_KEY", None)
    env.update(env_extra)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.Popen([PY, str(BRIDGE), "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(BASE))
    url = None
    deadline = time.time() + 10
    while time.time() < deadline:
        line = p.stdout.readline().decode("utf-8", "replace").strip()
        if line.startswith("MODEL_BRIDGE "):
            url = line.split(" ", 1)[1]
            break
    if not url:
        err = p.stderr.read(2000).decode("utf-8", "replace")
        p.kill()
        raise RuntimeError("bridge did not start: " + err)
    for _ in range(3):
        try:
            st, obj = http_json(url + "health", timeout=3)
            if st == 200:
                return p, url, obj
        except Exception:
            pass
        time.sleep(0.2)
    p.kill()
    raise RuntimeError("bridge health not ready")


def stop(p):
    try:
        p.terminate()
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def explain(url, question="测试过了吗？", digest=None, header=True):
    h = {"X-Weihetai-Bridge": "1"} if header else {}
    return http_json(url + "explain", "POST", {"question": question, "digest": digest or GOOD_DIGEST}, headers=h, timeout=15)


def main():
    fake = start_fake()
    fake_url = f"http://127.0.0.1:{fake.server_address[1]}/v1"
    procs = []
    try:
        # 1) 未配置：明确答未配置，且不计调用
        p, url, st = start_bridge({})
        procs.append(p)
        rec("unconfigured state", st.get("state") == "unconfigured", st.get("state"))
        code, obj = explain(url)
        rec("unconfigured explain 503", code == 503 and obj.get("error") == "NO_ENDPOINT", (code, obj))
        rec("unconfigured no call", obj.get("call_made") is False and obj.get("calls") == 0, obj)
        rec("health has no key value", SENTINEL_KEY not in json.dumps(st), "sentinel check")
        stop(p)
        procs.remove(p)

        # 2) 已配置：正常一发
        FakeUpstream.mode = "ok"
        FakeUpstream.sleep_s = 0
        p, url, st = start_bridge({
            "WEIHETAI_MODEL_BASE_URL": fake_url,
            "WEIHETAI_MODEL": "fake-model-1",
            "WEIHETAI_MODEL_KEY": SENTINEL_KEY,
            "WEIHETAI_MODEL_TIMEOUT": "5",
        })
        procs.append(p)
        rec("ready state", st.get("state") == "ready" and st.get("model") == "fake-model-1", st)
        rec("key present flag only", st.get("key_present") is True and SENTINEL_KEY not in json.dumps(st), st)
        rec("base_host hides path", st.get("base_host") == f"http://127.0.0.1:{fake.server_address[1]}", st.get("base_host"))
        code, obj = explain(url)
        rec("ok explain 200", code == 200 and obj.get("ok") is True, (code, obj))
        rec("tier is not model-chosen", "tier" not in obj, obj.keys())
        rec("valid refs only", [r.get("id") for r in obj.get("refs", [])] == ["D1-C1"], obj.get("refs"))
        rec("usage kept", obj.get("usage", {}).get("total_tokens") == 120, obj.get("usage"))
        rec("upstream auth header", FakeUpstream.last.get("auth") == "Bearer " + SENTINEL_KEY, "auth header mismatch")
        rec("upstream path appended", FakeUpstream.last.get("path") == "/v1/chat/completions", FakeUpstream.last.get("path"))
        sent = FakeUpstream.last.get("body") or ""
        rec("upstream body no memory key", '"memory"' not in sent and '"operator"' not in sent, "forbidden key in body")
        rec("upstream body no local path", "C:\\\\" not in sent and "/Users/" not in sent, "path in body")
        rec("upstream body has question", "测试过了吗" in sent, "question missing")
        code, h2 = http_json(url + "health")
        rec("calls counted", h2.get("calls") == 1, h2.get("calls"))

        # 3) 请求头 / Origin
        code, obj = explain(url, header=False)
        rec("missing bridge header 403", code == 403 and obj.get("error") == "BRIDGE_HEADER_REQUIRED", (code, obj))
        code, obj = http_json(url + "explain", "POST", {"question": "x", "digest": GOOD_DIGEST}, headers={"X-Weihetai-Bridge": "1", "Origin": "http://evil.example"})
        rec("origin rejected", code == 403 and obj.get("error") == "ORIGIN_REJECTED", (code, obj))

        # 4) 摘要白名单
        bad1 = json.loads(json.dumps(GOOD_DIGEST))
        bad1["memory"] = {"owner": "x"}
        code, obj = explain(url, digest=bad1)
        rec("digest memory key 400", code == 400 and obj.get("error") == "BAD_DIGEST", (code, obj))
        bad2 = json.loads(json.dumps(GOOD_DIGEST))
        bad2["deliveries"][0]["claims"][0]["why"] = "证据在 C:\\Users\\Admin\\secret.json"
        code, obj = explain(url, digest=bad2)
        rec("digest local path 400", code == 400 and obj.get("error") == "BAD_DIGEST", (code, obj))
        bad3 = json.loads(json.dumps(GOOD_DIGEST))
        bad3["deliveries"][0]["claims"][0]["sha256"] = "abc"
        code, obj = explain(url, digest=bad3)
        rec("digest hash key 400", code == 400 and obj.get("error") == "BAD_DIGEST", (code, obj))
        bad4 = json.loads(json.dumps(GOOD_DIGEST))
        bad4["deliveries"][0]["claims"][0]["why"] = "账上 " + "a1b2c3d4" * 8
        code, obj = explain(url, digest=bad4)
        rec("digest literal hash 400", code == 400 and obj.get("error") == "BAD_DIGEST", (code, obj))
        good_word = json.loads(json.dumps(GOOD_DIGEST))
        good_word["deliveries"][0]["claims"][0]["why"] = "逐条重算 payload_sha256，49/49 相符。"
        code, obj = explain(url, digest=good_word)
        rec("algorithm word sha256 allowed", code == 200 and obj.get("ok") is True, (code, obj))
        code, obj = explain(url, question="x" * 501)
        rec("question too long 400", code == 400 and obj.get("error") == "BAD_QUESTION", (code, obj))

        # 5) 上游 500：错误映射 + 正文不含口令
        FakeUpstream.mode = "500"
        code, obj = explain(url)
        rec("upstream 500 mapped", code == 502 and obj.get("error") == "UPSTREAM_500", (code, obj))
        rec("upstream error redacts key", SENTINEL_KEY not in json.dumps(obj), obj.get("why"))
        rec("upstream failure call_made", obj.get("call_made") is True, obj)

        # 6) 空 choices
        FakeUpstream.mode = "empty"
        code, obj = explain(url)
        rec("bad response mapped", code == 502 and obj.get("error") == "BAD_RESPONSE", (code, obj))

        # 7) 非 JSON 模型输出：降级成纯文本，不失败
        FakeUpstream.mode = "text"
        code, obj = explain(url)
        refs = obj.get("refs") or []
        rec("plain text accepted", code == 200 and bool(obj.get("text")) and [r.get("id") for r in refs] == ["D1-C1"], obj)

        # 8) 超时
        stop(p)
        procs.remove(p)
        FakeUpstream.mode = "ok"
        FakeUpstream.sleep_s = 3.0
        p, url, st = start_bridge({
            "WEIHETAI_MODEL_BASE_URL": fake_url,
            "WEIHETAI_MODEL": "fake-model-1",
            "WEIHETAI_MODEL_KEY": SENTINEL_KEY,
            "WEIHETAI_MODEL_TIMEOUT": "1",
        })
        procs.append(p)
        t0 = time.time()
        code, obj = explain(url)
        dt = time.time() - t0
        rec("timeout mapped 504", code == 504 and obj.get("error") == "TIMEOUT", (code, obj, round(dt, 1)))
        rec("timeout honored ~1s", 0.8 <= dt <= 6, round(dt, 2))
        rec("timeout call_made", obj.get("call_made") is True, obj)

        # 9) 日志不落问题正文 / 口令
        log_file = BASE / "读数" / "模型桥-日志.jsonl"
        log_text = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        rec("log has no key", SENTINEL_KEY not in log_text, "sentinel in log")
        rec("log has no question text", "测试过了吗" not in log_text, "question in log")
        rec("log has calls", '"event": "explain"' in log_text or '"event":"explain"' in log_text, "no explain event")
    finally:
        for p in procs:
            stop(p)
        fake.shutdown()
        fake.server_close()

    fails = [r for r in results if not r["ok"]]
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bridge": str(BRIDGE),
        "bridge_sha256": __import__("hashlib").sha256(BRIDGE.read_bytes()).hexdigest(),
        "fake_upstream": "127.0.0.1 random port",
        "key_source": "env only; sentinel not real; not printed",
        "checks": results,
        "counts": {"total": len(results), "pass": len(results) - len(fails), "fail": len(fails)},
        "verdict": "PASS" if not fails else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.part")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"RESULT {out['verdict']} {out['counts']['pass']}/{out['counts']['total']}")
    print("READOUT " + str(OUT))
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("FATAL " + type(e).__name__ + ": " + str(e)[:300])
        sys.exit(2)
