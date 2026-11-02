"""真端点 1023 · AgentHub 跨步实测（同一发里第 2 步的历史形状）。
口令只走环境变量，产物不含口令原文；任务与步数上限走 env，产物名分开，不覆盖单步那份。"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
EXE = HERE / "hubd-real.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
PORT = os.environ.get("REAL_HUB_PORT", "4324")
MODEL = os.environ.get("REAL_MODEL", "MiniMax-M2.5")
TASK = os.environ.get("REAL_HUB_TASK", "先列出当前目录里的文件，再统计其中最大那个文件有多少字节")
MAX_STEPS = os.environ.get("REAL_HUB_MAX_STEPS", "6")
OUT = os.environ.get("REAL_HUB_OUT", "agenthub-真端点-多步.json")


def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    return url, key


def main():
    url, key = load_secret()
    tmp = Path(tempfile.mkdtemp(prefix="ak-real-hub-multi-"))
    fs = tmp / "fs"
    fs.mkdir()
    (fs / "alpha.txt").write_text("alpha\n" * 3, encoding="utf-8")
    (fs / "beta.txt").write_text("beta\n", encoding="utf-8")
    data = tmp / "data"
    data.mkdir()
    env = dict(os.environ)
    env["HUBD_MODEL_KEY"] = key
    log = open(HERE / "读数" / "agenthub-server-多步.log", "wb")
    proc = subprocess.Popen([str(EXE),
                             "-port", PORT, "-data", str(data),
                             "-tools-dir", str(ROOT / "AgentHub-1021" / "src" / "hubd" / "tools"),
                             "-fs-roots", str(fs),
                             "-model-endpoint", url,
                             "-model-name", MODEL,
                             "-model-key-env", "HUBD_MODEL_KEY",
                             "-model-timeout-ms", "60000",
                             "-max-steps", MAX_STEPS],
                            env=env, stdout=log, stderr=subprocess.STDOUT, cwd=str(fs))
    try:
        base = "http://127.0.0.1:%s" % PORT
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                    health = json.loads(r.read().decode("utf-8"))
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("FAIL health never came up")
            return 2
        print("task =", TASK)
        print("health.tools =", health.get("tools"))
        body = json.dumps({"text": TASK}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(base + "/api/chat", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        events, result = [], None
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=240) as r:
            ev = None
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: "):
                    payload = line[6:]
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if ev == "result":
                        result = obj
                    else:
                        events.append({"event": ev, "data": obj})
        elapsed = (time.time() - t0) * 1000
        out = {
            "surface": "agenthub",
            "shape": "multi-step",
            "task": TASK,
            "max_steps": int(MAX_STEPS),
            "endpoint": url,
            "model": MODEL,
            "key_masked": key[:6] + "..." + key[-4:],
            "exe_sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
            "elapsed_ms": round(elapsed),
            "health": health,
            "events": events,
            "result": result,
        }
        (HERE / "读数" / OUT).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("elapsed_ms", round(elapsed))
        kinds = {}
        for e in events:
            kinds[e["event"]] = kinds.get(e["event"], 0) + 1
        print("event_kinds", kinds)
        r0 = result or {}
        for s in r0.get("steps") or []:
            print("step", s.get("step"), s.get("tool"), s.get("class"),
                  "prov=", s.get("provenance"), "ev=", s.get("evidence"),
                  "args=", json.dumps(s.get("args"), ensure_ascii=False)[:100],
                  "|", (s.get("text") or "")[:120].replace("\n", " "))
        print("stop =", r0.get("stop"), "|", (r0.get("stop_why") or "")[:220])
        print("plan_names =", r0.get("plan"))
        print("fallbacks =", r0.get("fallbacks"))
        text = json.dumps(out, ensure_ascii=False)
        print("masked_key_still_present =", key in text)
        print("answer_head =", (r0.get("answer") or "")[:220])
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
