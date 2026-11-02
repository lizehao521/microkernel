#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全闸一件跑（本工作区四道闸 + 两把尺子 + 八条针 + 臂读数新鲜度）。

**它自己不判任何东西**：每道闸的判据仍归各自的主人（kcheck / go test / 臂检-全部族 /
锚点核对 / 证据模型核对 / 验收-事件层）。这件只负责「按顺序都跑一遍、把每道的 rc 与尾巴印出来、
最后给一个合取结论」—— 免得有人只跑了两道就报「全绿」（这在本现场真发生过）。

顺手核一件事，别处没核：**臂读数是不是比树新**。
`读数/臂检-全部族.jsonl` 的 mtime 早于 `cmd/agentd` 里任一 .go ⇒ 那份「82/82 全咬」只作参考，不许当刚跑过。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 体检-全闸-1023.py <go.exe> <树根> [--skip-arms]
退出码：0 全过；3 有任一道不绿 / 臂读数过期（过期只警告不红，因为它不是判据坏，是读数旧）。
"""
import io
import json
import os
import subprocess
import sys
import time

GO = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/Admin/sdk/go/bin/go.exe"
SRC = sys.argv[2] if len(sys.argv) > 2 else r"C:/Users/Admin/Desktop/微内核/微内核/微内核"
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ARMS = os.path.join(HERE, "读数", "臂检-全部族.jsonl")
REPORT = os.path.join(HERE, "报告-全闸.txt")
SKIP_ARMS = "--skip-arms" in sys.argv[1:]   # 臂那一道一趟要十几分钟，可选


def ascii_safe(s):
    # GBK 控制台上中文/勾号会崩 print —— 崩掉的 rc 会冒充「闸红」。产物走 UTF-8 句柄，控制台只走 ASCII。
    return s.encode("ascii", "backslashreplace").decode("ascii")


def gate(label, args, cwd, reading=None, t_start=None):
    t0 = time.time()
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    tail = " / ".join(out.splitlines()[-2:]) if out else ""
    # 有的闸（验收-事件层）为了 GBK 控制台安全，把上屏那份转成了 ASCII 转义。
    # 转义过的文本进本件报告 = 凭据半损坏（中文变 \u771f）。所以：闸门自己写了 UTF-8 读数，
    # 就从**那份读数**取尾巴；只有读数不在/不比这一趟新，才退回 stdout。
    src_of_tail = "stdout"
    if reading:
        try:
            fresh = os.path.isfile(reading) and os.path.getmtime(reading) >= max(t0, t_start or t0)
        except OSError:
            fresh = False
        if fresh:
            txt = io.open(reading, encoding="utf-8", errors="replace").read().strip()
            if txt:
                tail = " / ".join(txt.splitlines()[-2:])
                src_of_tail = "reading"
        else:
            src_of_tail = "stdout(读数缺或比本趟旧⇒不引它)"
    # 产物留原文（UTF-8 句柄），**只有上屏那一遍**转 ASCII —— 转义过的报告文件等于没留凭据。
    print("%-22s rc=%d %5.0fs | %s" % (label, r.returncode, time.time() - t0,
                                        ascii_safe(tail)[:180]))
    return r.returncode, "%-22s rc=%d %5.0fs | tail<-%s | %s" % (
        label, r.returncode, time.time() - t0, src_of_tail, tail[:400])


def arm_freshness():
    if not os.path.isfile(ARMS):
        return False, "读不到 %s" % ARMS, 0
    d = os.path.join(SRC, "cmd", "agentd")
    newest = max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".go"))
    verdicts, n = {}, 0
    for l in io.open(ARMS, encoding="utf-8"):
        if l.strip():
            v = str(json.loads(l).get("verdict", ""))
            key = "BIT" if v.startswith("BIT") else v
            verdicts[key] = verdicts.get(key, 0) + 1
            n += 1
    fresh = os.path.getmtime(ARMS) >= newest
    return fresh, "rows=%d verdicts=%s" % (n, json.dumps(verdicts, sort_keys=True)), n


def main():
    lines, bad, warn = [], 0, []

    def keep(line):
        lines.append(line)

    keep("tree=%s" % SRC)
    started = time.time()
    for label, args, cwd, reading in [
        ("go vet ./cmd/agentd", [GO, "vet", "./cmd/agentd/"], SRC, None),
        ("go test -count=1", [GO, "test", "./cmd/agentd/", "-count=1"], SRC, None),
        ("kcheck（内核快闸）", [GO, "run", "./cmd/kcheck"], SRC, None),
        ("锚点核对（尺子一）", [PY, os.path.join(HERE, "锚点核对.py")], HERE,
         os.path.join(HERE, "读数-锚点核对.txt")),
        ("证据模型核对（尺子二）", [PY, os.path.join(HERE, "证据模型核对.py")], HERE,
         os.path.join(HERE, "读数-证据模型核对.txt")),
        ("尺子自证（旧病复现）", [PY, os.path.join(HERE, "尺子自证-旧病复现-1023.py")], HERE,
         os.path.join(HERE, "读数", "尺子自证-旧病复现-1023.txt")),
        ("验收-事件层（八条针）", [PY, os.path.join(HERE, "验收-事件层-1022.py"), GO, SRC], HERE,
         os.path.join(HERE, "报告-验收.txt")),
    ]:
        rc, line = gate(label, args, cwd, reading, started)
        keep(line)
        if rc != 0:
            bad += 1
    if SKIP_ARMS:
        keep("臂检 跳过（--skip-arms）⇒ 这一趟没重跑变异，只核下面那行新鲜度")
    else:
        rc, line = gate("臂检-全部族（变异自证）",
                        [PY, os.path.join(HERE, "臂检-全部族.py"), GO, SRC], HERE,
                        os.path.join(HERE, "臂检-全部族-读数.md"), started)
        keep(line)
        if rc != 0:
            bad += 1
    fresh, info, n = arm_freshness()
    keep("arm-reading %s | %s" % ("FRESH" if fresh else "STALE", ascii_safe(info)))
    if not fresh:
        warn.append("臂读数比树旧 ⇒ 上面引它的地方只作参考（不是判据坏，是读数旧）")
    for w in warn:
        keep("WARN " + ascii_safe(w))
    keep("conclusion=%s" % ("ALL-GATES-GREEN" if bad == 0 else "%d 道不绿（见上面点名的哪一行）" % bad))
    io.open(REPORT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
