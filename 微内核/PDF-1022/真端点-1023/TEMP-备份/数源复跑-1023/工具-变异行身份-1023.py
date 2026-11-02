"""变异：把「行身份」退回旧的 (题号, 趟)，只改 rows_seen 这一处 ⇒ 复现 19:00 的跨窗吞发，不波及其他代码路径。
变异件写在正式件同目录（要 import 同目录聚合件），跑完删；正式件只读不改。"""
import io
import json
import os
import subprocess
from pathlib import Path

HERE = Path(r"C:/Users/Admin/Desktop/微内核/PDF-1022/真端点-1023")
SRC = HERE / "分析-答案数源-1023.py"
PY = r"C:/Users/Admin/sdk/py314/python.exe"
OUT = HERE / "TEMP-备份/数源复跑-1023/变异-身份退回.json"
NAME = "变异-行身份退回旧键-数源.py"

NEEDLE = "rows_seen[k].add(row_key(r))"
REPL = 'rows_seen[k].add((r.get("id"), r.get("pass")))'

raw = SRC.read_text(encoding="utf-8")
assert raw.count(NEEDLE) == 1, "needle count %d" % raw.count(NEEDLE)
p = HERE / NAME
io.open(p, "w", encoding="utf-8").write(raw.replace(NEEDLE, REPL))
env = dict(os.environ, PYTHONIOENCODING="utf-8")
r = subprocess.run([PY, str(p), "--selftest"], capture_output=True, text=True,
                   encoding="utf-8", env=env, cwd=str(HERE))
lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("{")]
tail = json.loads(lines[-1]) if lines else {}
bad = [json.loads(ln) for ln in lines if '"ok": false' in ln]
summary = {"mutant": NAME, "rc": r.returncode, "arms": tail.get("arms"),
           "selftest_fails": tail.get("selftest_fails"), "failed": tail.get("failed"),
           "failing_arm_names": [b["arm"] for b in bad],
           "stderr_tail": (r.stderr or "")[-200:],
           "source_untouched_bytes": SRC.stat().st_size}
p.unlink()
summary["leftover"] = sorted(f.name for f in HERE.glob("变异-*数源.py"))
io.open(OUT, "w", encoding="utf-8").write(json.dumps(summary, ensure_ascii=True, indent=1))
print(json.dumps(summary, ensure_ascii=True))
