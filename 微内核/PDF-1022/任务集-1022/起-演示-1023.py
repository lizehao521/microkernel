"""起一台真 hubd + 一个慢端点，供真浏览器量「停止」那一形。

只监听 127.0.0.1 随机空闲端口；绝不碰 8797/8799（内核研究账）。
端口与 pid 写进 读数-演示-1023.json，进程留在前台直到被杀。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HUB_SRC = ROOT / "AgentHub-1021" / "src" / "hubd"
EXE = ROOT / "AgentHub-1021" / "构建-hubd" / "hubd-停止-1023.exe"
OUT = HERE / "读数-演示-1023.json"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    assert p not in (8797, 8799)
    return p


class 慢(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(30)
        self.send_response(200)
        self.end_headers()
        try:
            self.wfile.write(b"slow done")
        except Exception:
            pass

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", free_port()), 慢)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()

hub_port = free_port()
data = Path(tempfile.mkdtemp(prefix="hubd-ui-"))
log = open(HERE / "演示-1023-hubd.log", "w", encoding="utf-8")
proc = subprocess.Popen(
    [str(EXE), "-port", str(hub_port), "-data", str(data),
     "-net-allow", "127.0.0.1,localhost", "-step-delay", "0ms", "-max-steps", "6"],
    cwd=str(HUB_SRC), stdout=log, stderr=subprocess.STDOUT,
)

for _ in range(200):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % hub_port, timeout=1) as r:
            if json.loads(r.read().decode("utf-8")).get("ok"):
                break
    except Exception:
        pass
    time.sleep(0.05)
else:
    proc.kill()
    sys.exit("hubd 没起来")

OUT.write_text(json.dumps({"hub_port": hub_port, "fault_port": srv.server_address[1],
                           "hub_pid": proc.pid, "exe": str(EXE),
                           "data": str(data)}, ensure_ascii=False, indent=2), encoding="utf-8")
print("READY hub=%d fault=%d pid=%d" % (hub_port, srv.server_address[1], proc.pid), flush=True)
try:
    proc.wait()
finally:
    srv.shutdown()
