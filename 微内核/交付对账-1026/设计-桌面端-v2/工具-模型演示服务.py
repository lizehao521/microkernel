# -*- coding: utf-8 -*-
"""模型组件演示栈：假上游 + 模型桥 + 微核台本地服务，全部只监听 127.0.0.1。

只用于本机界面验收；假上游用测试口令，不连真端点。
启动后打印 UI_READY <url>，Ctrl+C 或终止进程时收掉三个子进程。
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable
KEY = "TEST-KEY-MODEL-DEMO-2c8f5a"
MODEL = "stub-model-1"


class FakeUpstream:
    def __init__(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            server_version = "StubUpstream/1.0"

            def log_message(self, fmt, *args):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
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
                self.rfile.read(n)
                content = json.dumps({
                    "title": "摘要复核",
                    "text": "D1-C4 不符：13 步里没有测试步；D1-C5 也不符。其余声明以摘要为准，核不了的不写成通过。",
                    "refs": ["D1-C4", "D1-C5"],
                }, ensure_ascii=False)
                return self._send(200, {
                    "id": "stub-1",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 36, "total_tokens": 156},
                })

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def start(cmd, env, marker):
    p = subprocess.Popen(
        [PY] + cmd, cwd=str(BASE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    url = ""
    lines = []
    end = time.time() + 30
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
        p.terminate()
        raise RuntimeError("no " + marker + ": " + "\n".join(lines[-8:]))
    return p, url


def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def env_for(extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WEIHETAI_MODEL_")}
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-kernel", action="store_true")
    args = ap.parse_args()
    up = FakeUpstream()
    bridge = core = None
    try:
        bridge, burl = start(
            ["模型桥.py", "--port", "0"],
            env_for({
                "WEIHETAI_MODEL_BASE_URL": f"http://127.0.0.1:{up.port}/v1",
                "WEIHETAI_MODEL": MODEL,
                "WEIHETAI_MODEL_KEY": KEY,
                "WEIHETAI_MODEL_TIMEOUT": "10",
            }),
            "MODEL_BRIDGE ",
        )
        print("BRIDGE_READY " + burl, flush=True)
        cmd = ["工具-本地服务.py", "--port", "0", "--no-open"]
        if args.no_kernel:
            cmd.append("--no-kernel")
        core, curl = start(cmd, env_for({"WEIHETAI_MODEL_BRIDGE": burl}), "READY ")
        print("UI_READY " + curl, flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop(core)
        stop(bridge)
        up.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
