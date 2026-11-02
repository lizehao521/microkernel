"""起当前 build 的 pgagent（真端点），用 Edge 无头打开页面跑一发并举证截图。"""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
EXE = HERE / "pgagent-real.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = "4323"
PNG = HERE / "读数" / "截图-pgagent-真端点-1023.png"


def main():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    base = next(x for x in lines if x.startswith("http")).rsplit("/chat/completions", 1)[0]
    key = next(x for x in lines if x.startswith("sk-"))
    env = dict(os.environ)
    env.update({"PGAGENT_BASE_URL": base, "PGAGENT_MODEL": "MiniMax-M2.5", "PGAGENT_KEY": key})
    data = Path(tempfile.mkdtemp(prefix="ak-real-pg-ui-"))
    log = open(HERE / "读数" / "pgagent-ui-server.log", "wb")
    proc = subprocess.Popen([str(EXE), "-port", PORT, "-data", str(data), "-gateway-timeout", "60s"],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%s/api/health" % PORT, timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        profile = Path(tempfile.mkdtemp(prefix="ak-edge-pg-"))
        r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--window-size=1440,900",
                            "--user-data-dir=" + str(profile), "--virtual-time-budget=60000",
                            "--screenshot=" + str(PNG),
                            "http://127.0.0.1:%s/?run=1" % PORT],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        print("edge rc =", r.returncode)
        print("png exists =", PNG.exists(), "bytes =", PNG.stat().st_size if PNG.exists() else 0)
        meta = {
            "surface": "pgagent-ui",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "url": "http://127.0.0.1:%s/?run=1" % PORT,
            "exe_sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
            "png": str(PNG),
            "png_bytes": PNG.stat().st_size if PNG.exists() else 0,
            "edge_rc": r.returncode,
            "note": "无头截图只证「这一版 build 的页面看得见」；交互与真端点读数以 读数/pgagent-真端点.json 为准",
        }
        (HERE / "读数" / "探针-pgagent-真端点-1023.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(meta, ensure_ascii=False))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
