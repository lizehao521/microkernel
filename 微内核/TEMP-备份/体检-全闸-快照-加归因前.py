#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全闸一件跑（本工作区的四道闸 + 证据件那几把尺子 + 八条针 + 臂读数体检）。

**它自己不判任何东西**：每道闸的判据仍归各自的主人（kcheck / go test / 臂检-全部族 /
锚点核对 / 证据模型核对 / 验收-事件层）。这件只负责「按顺序都跑一遍、把每道的 rc 与尾巴印出来、
最后给一个合取结论」—— 免得有人只跑了两道就报「全绿」（这在本现场真发生过）。

顺手核三件事，别处没核：
1. **臂读数是不是比树新** —— `读数/臂检-全部族.jsonl` 的 mtime 早于 `cmd/agentd` 里任一 .go
   ⇒ 那份「82/82 全咬」只作参考，不许当刚跑过。（过期只 WARN，因为不是判据坏，是读数旧。）
2. **臂读数是不是真说了话** —— 行数 0，或里面有 BLIND / BROKEN / NOT-WIRED / CONTROL-NOT-GREEN
   ⇒ 红，并点名是哪一桶在响。理由是一个现场抓到的洞：`臂检-全部族.py` 一开跑就用 "w" 截断
   jsonl，中途被打断会留下「mtime 最新但 0 行」的文件，只看新鲜度就把空读数判成绿。
3. **红的那一道能不能自证为什么** —— rc≠0 时把 stdout 里的 `--- FAIL: TestXxx` 点名进行数、
   把全量输出落进 `读数/红-全量-*.txt`、末行的 conclusion 点名是哪几道。起因是 02:0x 那趟：
   go test 那一行 rc=1 而末两行只有包名，单独重跑又 rc=0 ⇒ 这次红既复现不了也归不了因。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 体检-全闸-1023.py <go.exe> <树根> [--skip-arms]
退出码：0 全过；3 有任一道不绿 / 臂读数为空或含坏档（读数比树旧只警告不红）。
"""
import io
import json
import os
import re
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


def fail_names(out):
    """从 go test 的输出里点出「红在哪一支」。

    为什么要这一条：本件原先只留 stdout 的最后两行，而 go test 的末两行是
    `FAIL\\tagentkernel/cmd/agentd 27.6s` + `FAIL` —— 包名不是罪名。02:0x 那趟复合跑就是
    这样红的（单独重跑 rc=0），现场连「哪一支 Test」都答不出来，等于红了的读数不自证为什么。
    """
    return re.findall(r"^--- FAIL: (\S+)", out, re.M)


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
    extra = ""
    if r.returncode != 0:
        fn = fail_names(out)
        if fn:
            tail = "红在 %s ｜ %s" % (",".join(fn[:5]), tail)
        else:
            tail = "红但点不出 Test 名（不是 --- FAIL 那形）｜ " + tail
        # 红的那一道把**全量输出**留在读数/：光有罪名没有现场，下一个人只能重跑碰运气
        full = os.path.join(HERE, "读数", "红-全量-%s.txt" % re.sub(r"[^\w.-]", "_", label))
        io.open(full, "w", encoding="utf-8", newline="\n").write(out + "\n")
        extra = " ｜ 全量=%s" % os.path.basename(full)
    # 产物留原文（UTF-8 句柄），**只有上屏那一遍**转 ASCII —— 转义过的报告文件等于没留凭据。
    print("%-22s rc=%d %5.0fs | %s" % (label, r.returncode, time.time() - t0,
                                        ascii_safe(tail + extra)[:180]))
    return r.returncode, "%-22s rc=%d %5.0fs | tail<-%s | %s%s" % (
        label, r.returncode, time.time() - t0, src_of_tail, tail[:400], extra)


def arm_freshness():
    """臂读数两维体检 —— 返回 (state, info, n)。
    state：FRESH / STALE（旧但真说过话 ⇒ 只 WARN）/ EMPTY / BAD / MISSING（这三态 ⇒ 红）。
    先看「有没有真说话」再看「新不新」：一份 0 行的读数即使 mtime 最新也不算数，
    否则臂跑一半被打断（截断式写盘留下的现场）会被这行报成绿。
    """
    if not os.path.isfile(ARMS):
        return "MISSING", "读不到 %s ⇒ 先跑 臂检-全部族.py" % ARMS, 0
    d = os.path.join(SRC, "cmd", "agentd")
    newest = max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".go"))
    verdicts, n = {}, 0
    for l in io.open(ARMS, encoding="utf-8"):
        if l.strip():
            v = str(json.loads(l).get("verdict", ""))
            # 分档不许压平：BIT(进程崩，症状可见) 是臂特意分出来的一档，合并成 BIT 就把症状丢了。
            # 键名保持 ASCII（GBK 控制台会把中文打崩，崩掉的 rc 会冒充闸红）。
            key = "BIT-CRASH" if v.startswith("BIT(") else v
            verdicts[key] = verdicts.get(key, 0) + 1
            n += 1
    count = "rows=%d verdicts=%s" % (n, json.dumps(verdicts, sort_keys=True))
    if n == 0:
        return "EMPTY", count + " ｜ 一条臂都没说话 ⇒ 这一趟臂检被打断或没跑，新鲜度不作数", 0
    # 咬住的档位只有 BIT 与 BIT-CRASH；其余（BLIND/BROKEN/NOT-WIRED/CONTROL-NOT-GREEN/空档）都得点名。
    silent = sorted(k for k in verdicts if k not in ("BIT", "BIT-CRASH"))
    if silent:
        return "BAD", count + " ｜ 点名不绿的档：%s" % ",".join(silent), n
    fresh = os.path.getmtime(ARMS) >= newest
    return ("FRESH" if fresh else "STALE"), count, n


def main():
    lines, bad, warn, bad_labels = [], 0, [], []

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
            bad_labels.append(label)
    if SKIP_ARMS:
        keep("臂检 跳过（--skip-arms）⇒ 这一趟没重跑变异，只核下面那行新鲜度")
    else:
        rc, line = gate("臂检-全部族（变异自证）",
                        [PY, os.path.join(HERE, "臂检-全部族.py"), GO, SRC], HERE,
                        os.path.join(HERE, "臂检-全部族-读数.md"), started)
        keep(line)
        if rc != 0:
            bad += 1
            bad_labels.append("臂检-全部族（变异自证）")
    state, info, n = arm_freshness()
    keep("arm-reading %s | %s" % (state, ascii_safe(info)))
    if state in ("MISSING", "EMPTY", "BAD"):
        bad += 1
        bad_labels.append("arm-reading=%s" % state)
    if state == "STALE":
        warn.append("臂读数比树旧 ⇒ 上面引它的地方只作参考（不是判据坏，是读数旧）")
    for w in warn:
        keep("WARN " + ascii_safe(w))
    keep("conclusion=%s" % ("ALL-GATES-GREEN" if bad == 0
                           else "%d 道不绿：%s" % (bad, "、".join(bad_labels))))
    io.open(REPORT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
