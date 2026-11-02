"""真端点 1023 · agentd 一发实测。

口令只在子进程环境里；本脚本与任何产物都不写口令原文。
agentd 只做文本口径的算术 oracle（不是执行器复算），读数里会写明。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
EXE = HERE / "agentd-real.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
READ = HERE / "读数"
MODEL = os.environ.get("REAL_MODEL", "MiniMax-M2.5")
TASK = os.environ.get("REAL_AGENTD_TASK", "把 27、15、8、34 加起来")

def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    return url, key

def main():
    url, key = load_secret()
    tmp = Path(tempfile.mkdtemp(prefix="ak-real-agentd-"))
    data = tmp / "data"
    data.mkdir()
    env = dict(os.environ)
    env.update({
        "AGENTNES_BASE_URL": url,
        "AGENTNES_KEY": key,
        "AGENTNES_MODEL": MODEL,
        "AGENTNES_TIMEOUT_MS": "60000",
    })
    cmd = [str(EXE),
           "-driver", "real",
           "-task", TASK,
           "-max-turns", "1",
           "-oracle-out", str(READ / "agentd-真端点-oracle.json"),
           "-journal-out", str(READ / "agentd-真端点.ckpt.json"),
           "-events-out", str(READ / "agentd-真端点.events.jsonl"),
           "-trace-out", str(READ / "agentd-真端点-轨迹.html")]
    with open(READ / "agentd-真端点.stdout.txt", "wb") as out, \
         open(READ / "agentd-真端点.stderr.txt", "wb") as err:
        proc = subprocess.run(cmd, env=env, cwd=str(tmp), stdout=out, stderr=err, timeout=180)
    if proc.returncode not in (0, 3):
        print("FAIL rc", proc.returncode)
        return proc.returncode
    oracle = json.loads((READ / "agentd-真端点-oracle.json").read_text(encoding="utf-8"))
    print("exe_sha256 =", hashlib.sha256(EXE.read_bytes()).hexdigest())
    print("rc =", proc.returncode, "（3 = 轮次额度到，这一发的正常收口）")
    print("oracle =", json.dumps(oracle, ensure_ascii=False))
    print("key_masked =", key[:6] + "..." + key[-4:])
    text = "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in READ.glob("agentd-真端点*") if p.is_file())
    print("key_still_present_in_readings =", key in text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
