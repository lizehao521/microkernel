#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the existing browser stop probe against a fresh hubd build.

ASCII stdout only; the probe's JSON stays UTF-8 on disk.
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

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HUB_SRC = ROOT / "AgentHub-1021" / "src" / "hubd"
EXE = ROOT / "AgentHub-1021" / "构建-hubd" / "hubd-停止-1023.exe"
PROBE = ROOT / "AgentHub-1021" / "工具" / "浏览器-停止探针-1023.js"
OUT = ROOT / "AgentHub-1021" / "读数" / "浏览器-停止-1023.json"
PNG = ROOT / "AgentHub-1021" / "读数" / "截图" / "hubd-停止-1023.png"


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


class SilentServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class Fault:
    def __init__(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/slow"):
                    time.sleep(4.5)
                body = b"slow-ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

        self.httpd = SilentServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def wait_health(port, timeout=20):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
                j = json.loads(r.read().decode("utf-8"))
                if j.get("ok"):
                    return True, j
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
        time.sleep(0.1)
    return False, {"err": last}


def main():
    temp = Path(tempfile.mkdtemp(prefix="hubd-stop-probe-"))
    data = temp / "data"
    data.mkdir()
    fault = Fault()
    hub_port = free_port()
    log = open(temp / "hubd.log", "wb")
    proc = None
    rc = 1
    try:
        proc = subprocess.Popen([
            str(EXE), "-port", str(hub_port), "-data", str(data),
            "-step-delay", "120ms",
            "-net-allow", "127.0.0.1,localhost", "-max-steps", "6",
            "-allow-write=false", "-allow-exec=false",
        ], cwd=str(HUB_SRC), stdout=log, stderr=subprocess.STDOUT)
        ok, health = wait_health(hub_port)
        print(json.dumps({"health_ok": ok, "health": health,
                          "hub_port": hub_port, "fault_port": fault.port}, ensure_ascii=True))
        if not ok:
            return 2
        args = ["node", str(PROBE),
                "http://127.0.0.1:%d/" % hub_port,
                "http://127.0.0.1:%d/slow" % fault.port,
                str(OUT), str(PNG)]
        r = subprocess.run(args, cwd=str(ROOT / "AgentHub-1021"), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
        print("probe_rc=%s" % r.returncode)
        print("probe_out=" + (r.stdout or "").strip()[:1200])
        print("probe_err=" + (r.stderr or "").strip()[:1200])
        rc = r.returncode
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        try:
            log.close()
        except Exception:
            pass
        fault.close()
    if OUT.exists():
        j = json.loads(OUT.read_text(encoding="utf-8"))
        print(json.dumps({"reading": str(OUT), "bytes": OUT.stat().st_size,
                          "pass": j.get("过"), "exe_sha256": j.get("exe_sha256"),
                          "served_app_equals_disk": j.get("served_app_js_equals_disk"),
                          "served_index_equals_disk": j.get("served_index_equals_disk"),
                          "probes": j.get("探针")}, ensure_ascii=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
