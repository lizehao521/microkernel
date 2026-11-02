"""One-shot probe of the real model endpoint. Prints status/exception class only -- never the key.
Why: hubd fell back to local answers in ~70ms/run; before discarding a window I need
independent evidence about the upstream, not evidence filtered through the surface under test."""
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
lines = [x.strip() for x in SRC.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
url = next(x for x in lines if x.startswith("http"))
key = next(x for x in lines if x.startswith("sk-"))
host = url.split("//", 1)[1].split("/", 1)[0]
print(json.dumps({"url": url, "key_masked": key[:6] + "..." + key[-4:]}))

t0 = time.monotonic()
try:
    s = socket.create_connection((host.split(":")[0], int(host.split(":")[1])), timeout=5)
    s.close()
    print(json.dumps({"tcp": "open", "ms": round((time.monotonic() - t0) * 1000, 1)}))
except Exception as e:
    print(json.dumps({"tcp": "FAIL", "exc": type(e).__name__, "args": str(e)[:160],
                      "ms": round((time.monotonic() - t0) * 1000, 1)}))

body = json.dumps({"model": "MiniMax-M2.5", "messages": [{"role": "user", "content": "say OK"}],
                   "max_tokens": 8}).encode("utf-8")
req = urllib.request.Request(url, data=body, method="POST", headers={
    "Content-Type": "application/json", "Authorization": "Bearer " + key})
t0 = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.dumps({"http": r.status, "ms": round((time.monotonic() - t0) * 1000, 1),
                          "body_head": r.read(200).decode("utf-8", "replace")}))
except urllib.error.HTTPError as e:
    print(json.dumps({"http": e.code, "ms": round((time.monotonic() - t0) * 1000, 1),
                      "body_head": (e.read(200) or b"").decode("utf-8", "replace")}))
except Exception as e:
    print(json.dumps({"http": "FAIL", "exc": type(e).__name__, "args": str(e)[:200],
                      "ms": round((time.monotonic() - t0) * 1000, 1)}))
