#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""§7.3 那一发单独的量：契约预算 ack_limit_ms=100 在这台机器上**守不守得住**。

为什么单开一件：E4 真负载那件一次要 go build + 起 SSE + 连跑三趟，量到的 452ms 是「机器正在忙」时的数，
拿它下结论就是把并发编译的抖动算到了宿主头上。这一件只干一件事 ——
**建一次 exe，然后不打架地连跑 N 趟**，把每一发 turn_accepted 的 ack_ms 攒成分布。

三态口径写死在这儿：
  · 分布（min/p50/p90/max + 超预算的发数）是**量出来的**；
  · 「守得住 / 守不住」只在 N 与超预算数都自印之后才说；
  · 判据会不会红由两条叶子臂当场证（预算 0 必红、预算 60000 必绿），臂不红则本件的绿不作数。

用法：C:/Users/Admin/sdk/py314/python.exe 测量-回执预算-1023.py [趟数，默认 15]
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GO = r"C:/Users/Admin/sdk/go/bin/go.exe"
ROOT = os.environ.get("AGENTD_TREE") or r"C:/Users/Admin/Desktop/微内核/微内核/微内核"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "读数", "测量-回执预算-1023.txt")
BUDGET = 100
RE_PROC = re.compile(r"\b(go|go-build|compile|link|agentd)\.exe\b", re.I)

log_lines = []


def say(s):
    log_lines.append(s)
    print(s)


def acks_of(path):
    out = []
    for l in open(path, encoding="utf-8"):
        if not l.strip():
            continue
        e = json.loads(l)
        if e.get("kind") == "turn_accepted":
            a = (e.get("accept") or {}).get("ack_ms")
            out.append(a)
    return out


def go_procs():
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
    except Exception:
        return -1
    return len([l for l in r.stdout.splitlines() if RE_PROC.search(l)])


def check_log(exe, log, limit):
    r = subprocess.run([exe, "-check-log", log, "-ack-limit-ms", str(limit)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    rows = [l.split("\t") for l in r.stdout.splitlines() if l.startswith("check-log")]
    reds = [x for x in rows if len(x) >= 4 and x[3] == "RED"]
    return r.returncode, [x[1] for x in reds], (" ".join(x[4] for x in reds if len(x) > 4)[:160] or "-")


def pct(sorted_vals, q):
    if not sorted_vals:
        return -1
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    work = tempfile.mkdtemp(prefix="ack预算-")
    exe = os.path.join(work, "agentd.exe")
    t0 = time.time()
    b = subprocess.run([GO, "build", "-o", exe, "./cmd/agentd"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if b.returncode != 0:
        say("BUILD-FAIL " + (b.stderr or b.stdout)[:400])
        return 4
    eb = open(exe, "rb").read()
    say("exe built once: sha256_12=%s bytes=%d build_s=%.1f" %
        (hashlib.sha256(eb).hexdigest()[:12], len(eb), time.time() - t0))
    time.sleep(3.0)  # 让编译进程真的退干净，别拿编译尾巴当"无并发"
    say("idle check before loop: go/compile/agentd procs=%d" % go_procs())

    per_run, all_acks = [], []
    for i in range(n):
        log = os.path.join(work, "m%02d.events.jsonl" % i)
        jrn = os.path.join(work, "m%02d.jsonl" % i)
        busy = go_procs()
        t1 = time.time()
        r = subprocess.run([exe, "-script", "happy", "-max-turns", "20",
                            "-journal-out", jrn, "-events-out", log, "-trace-out", ""],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        a = [x for x in acks_of(log) if isinstance(x, int)]
        rc, reds, why = check_log(exe, log, BUDGET)
        per_run.append({"run": i, "rc": r.returncode, "busy": busy, "acks": len(a),
                        "max": max(a) if a else -1, "over": sum(1 for x in a if x > BUDGET),
                        "rc100": rc, "reds": reds})
        all_acks += a
        say("run %2d rc=%d busy=%d 发=%d max_ack=%dms 超%d=%d  check-log@100 rc=%d 红的支=%s" %
            (i, r.returncode, busy, len(a), max(a) if a else -1, BUDGET,
             sum(1 for x in a if x > BUDGET), rc, ",".join(reds) or "-"))

    s = sorted(all_acks)
    over = sum(1 for x in s if x > BUDGET)
    runs_bad = sum(1 for p in per_run if p["rc"] != 0)
    runs_red = sum(1 for p in per_run if p["rc100"] != 0)
    busy_max = max(p["busy"] for p in per_run)
    say("")
    say("SAMPLES 发=%d 趟=%d (每趟一行，行数即趟数) 自证: sum(每趟发数)=%d == 总发数=%d -> %s" %
        (len(s), len(per_run), sum(p["acks"] for p in per_run), len(s),
         "OK" if sum(p["acks"] for p in per_run) == len(s) else "MISMATCH"))
    say("DIST ack_ms min=%d p50=%d p90=%d max=%d | 预算=%d 超预算的发=%d (%.1f%%)" %
        (s[0] if s else -1, pct(s, .5), pct(s, .9), s[-1] if s else -1, BUDGET, over,
         100.0 * over / len(s) if s else -1))
    say("PER-RUN 趟级 rc!=0 的趟=%d / -check-log@100 红的趟=%d / 观测到的最忙 busy=%d" %
        (runs_bad, runs_red, busy_max))
    say("SWEEP 若预算改成这些数，超预算的发数 = %s" %
        " ".join("%d:%d" % (t, sum(1 for x in s if x > t)) for t in (50, 100, 150, 200, 300, 500, 1000)))

    # 两条叶子臂：尺子必须会红，否则上面那行「超预算的发=0」没牙。
    rc0, reds0, why0 = check_log(exe, os.path.join(work, "m00.events.jsonl"), 0)
    teeth = rc0 == 4 and len(reds0) > 0 and s and s[0] > 0
    say("ARM-TEETH 预算=0 在正常日志上 rc=%d 红的支=%s 读数=%s 最小ack=%d -> %s" %
        (rc0, ",".join(reds0) or "-", why0[:80], s[0] if s else -1, "有牙" if teeth else "没牙(不作数)"))
    rcw, redsw, _ = check_log(exe, os.path.join(work, "m00.events.jsonl"), 60000)
    say("ARM-WIDE  预算=60000 rc=%d 红的支=%s -> %s" %
        (rcw, ",".join(redsw) or "-", "绿" if rcw == 0 and not redsw else "仍红(那这本账有别的问题)"))

    verdict = None
    if not s:
        verdict = "没量到：一趟 turn_accepted 都没落下来 —— 本件红，别写成守住"
    elif not teeth:
        verdict = "尺子没牙（预算 0 不红）—— 上面所有 ack 结论作废"
    elif runs_bad > 0:
        verdict = "有趟没跑完（rc!=0 的趟=%d）—— 分布不作数" % runs_bad
    elif over == 0:
        verdict = "守住：这台机器、无并发编译、%d 趟 %d 发里没有一发 ack_ms 超 %d（max=%d，p50=%d）" % (
            len(per_run), len(s), BUDGET, s[-1], pct(s, .5))
    elif pct(s, .5) <= BUDGET:
        verdict = "没全守住：中位数 %d 在预算内，但有 %d/%d 发超 %d（max=%d）—— 预算是硬门的话这一形会红" % (
            pct(s, .5), over, len(s), BUDGET, s[-1])
    else:
        verdict = "守不住：中位数 %d 已超预算 %d（超预算 %d/%d，max=%d）" % (
            pct(s, .5), BUDGET, over, len(s), s[-1])
    say("VERDICT " + verdict)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    part = OUT + ".part"
    with open(part, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(log_lines) + "\n")
    os.replace(part, OUT)
    # 上面那句 landing 不能再走 say()：走了 say 就进了 log_lines，而文件已经写完了 ——
    # 上屏的数和盘上的数又不同源了（E4 那件本轮刚栽过）。
    with open(OUT, encoding="utf-8") as f:
        on_disk = f.read().splitlines()
    land_ok = len(on_disk) == len(log_lines)
    print("landing: %s %d lines %d bytes" % (OUT, len(on_disk), os.path.getsize(OUT)))
    print("landing check: %s (%d/%d lines)" % ("OK" if land_ok else "MISMATCH", len(on_disk), len(log_lines)))
    bad = (not s) or (not teeth) or runs_bad > 0 or not land_ok
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
