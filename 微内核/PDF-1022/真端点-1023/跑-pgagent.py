"""真端点 1023 · pgagent 一发实测。

口令只在进程内从本地文件读入环境变量；本脚本与任何产物都不写口令原文。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
EXE = HERE / "pgagent-real.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
PORT = os.environ.get("REAL_PORT", "4321")
MODEL = os.environ.get("REAL_MODEL", "MiniMax-M2.5")


def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    return url.rsplit("/chat/completions", 1)[0], key


def main():
    base, key = load_secret()
    data = Path(tempfile.mkdtemp(prefix="ak-real-pgagent-"))
    env = dict(os.environ)
    env.update({"PGAGENT_BASE_URL": base, "PGAGENT_MODEL": MODEL, "PGAGENT_KEY": key})
    log = open(HERE / "读数" / "pgagent-server.log", "wb")
    proc = subprocess.Popen([str(EXE), "-port", PORT, "-data", str(data),
                             "-gateway-timeout", os.environ.get("REAL_GW_TIMEOUT", "60s")],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        health = "http://127.0.0.1:%s/api/health" % PORT
        for _ in range(80):
            try:
                with urllib.request.urlopen(health, timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        else:
            print("FAIL health never came up")
            return 2
        body = {
            "code": "def add_all(xs):\n    total = 0\n    for i in range(1, len(xs)):\n        total += xs[i]\n    return total\n",
            "question": "这段代码有什么问题？请指出具体行并给一句修法。",
            "lang": "python",
            "session": "real-pgagent-1",
        }
        req = urllib.request.Request("http://127.0.0.1:%s/api/turn" % PORT,
                                     data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        steps, result = [], None
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
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
                    if ev == "step":
                        steps.append(obj)
                    elif ev == "result":
                        result = obj
        elapsed = (time.time() - t0) * 1000
        out = {
            "surface": "pgagent",
            "endpoint": base,
            "model": MODEL,
            "key_masked": key[:6] + "..." + key[-4:],
            "exe_sha256": __import__("hashlib").sha256(EXE.read_bytes()).hexdigest(),
            "elapsed_ms": round(elapsed),
            "steps": steps,
            "result": result,
        }
        (HERE / "读数" / "pgagent-真端点.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        text = json.dumps(result, ensure_ascii=False) if result else ""
        masked = text.replace(key, "***")
        # 汇总：只印能复核的结构，不印口令
        print("elapsed_ms", round(elapsed))
        for s in steps:
            print("step", s.get("no"), s.get("name"), "|", s.get("basis"), "|", (s.get("summary") or "")[:110])
        print("result_keys", sorted((result or {}).keys()))
        for k in ("KPI", "Decisions", "StopReason", "ChainSane", "ChainWhy", "Gateway"):
            if result and k in result:
                print(k, "=", json.dumps(result[k], ensure_ascii=False)[:300])
        if "pipe" in (result or {}):
            print("pipe =", json.dumps(result["pipe"], ensure_ascii=False)[:500])
        print("answer_head =", ((result or {}).get("Answer") or "")[:300])
        print("masked_key_still_present =", key in text)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()


if __name__ == "__main__":
    sys.exit(main())
