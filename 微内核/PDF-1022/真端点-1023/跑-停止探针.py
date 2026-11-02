"""重跑 AgentHub 浏览器停止探针：起慢端点 + 起当前 build 的 hubd + 跑 node 探针。"""
import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HUB = ROOT / "AgentHub-1021"
EXE = HUB / "构建-hubd" / "hubd-停止-1023.exe"
PROBE = HUB / "工具" / "浏览器-停止探针-1023.js"


class Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(300)

    def log_message(self, *a):
        pass


def main():
    slow = ThreadingHTTPServer(("127.0.0.1", 55377), Slow)
    threading.Thread(target=slow.serve_forever, daemon=True).start()
    data = ROOT / "TEMP-备份" / "真端点-1023" / "hub-stop-data"
    data.mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "PDF-1022" / "真端点-1023" / "读数" / "hubd-停止-server.log", "wb")
    proc = subprocess.Popen([str(EXE), "-port", "55378", "-data", str(data),
                             "-fs-roots", str(data)],
                            stdout=log, stderr=subprocess.STDOUT,
                            cwd=str(ROOT / "AgentHub-1021"))
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:55378/api/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(["node", str(PROBE), "http://127.0.0.1:55378/",
                            "http://127.0.0.1:55377/slow"],
                           cwd=str(HUB), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        print("node rc =", r.returncode)
        print("stdout:", (r.stdout or "").strip()[:400])
        print("stderr:", (r.stderr or "").strip()[:400])
        reading = json.loads((HUB / "读数" / "浏览器-停止-1023.json").read_text(encoding="utf-8"))
        print("时刻 =", reading.get("时刻"))
        print("probes =", [(p.get("how"), p.get("ms"), p.get("steps"), p.get("dirty")) for p in reading.get("探针", [])])
        print("判据 =", reading.get("判据"))
        print("过 =", reading.get("过"))
        print("exe_sha256 =", reading.get("exe_sha256"))
        return 0 if reading.get("过") else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        slow.shutdown()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
