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
                         "first": a[0] if a else -1, "rest": a[1:],
                         "max": max(a) if a else -1, "over": sum(1 for x in a if x > BUDGET),
                         "rc100": rc, "reds": reds})
        all_acks += a
        say("run %2d rc=%d busy=%d 发=%d max_ack=%dms 超%d=%d  check-log@100 rc=%d 红的支=%s" %
            (i, r.returncode, busy, len(a), max(a) if a else -1, BUDGET,
             sum(1 for x in a if x > BUDGET), rc, ",".join(reds) or "-"))

    s = sorted(all_acks)
    firsts = sorted(p["first"] for p in per_run if p["first"] >= 0)
    rest = sorted(x for p in per_run for x in p["rest"])
    over = sum(1 for x in s if x > BUDGET)
    over_first = sum(1 for x in firsts if x > BUDGET)
    runs_bad = sum(1 for p in per_run if p["rc"] != 0)
    runs_red = sum(1 for p in per_run if p["rc100"] != 0)
    busy_max = max(p["busy"] for p in per_run)
    say("")
    say("SAMPLES 发=%d 趟=%d (每趟一行，行数即趟数) 自证: sum(每趟发数)=%d == 总发数=%d -> %s" %
        (len(s), len(per_run), sum(p["acks"] for p in per_run), len(s),
         "OK" if sum(p["acks"] for p in per_run) == len(s) else "MISMATCH"))
    # 两个口径分开数，别拿全样本的中位数冒充「宿主有多快」：
    # 每趟只有**第一发**要走 runtime 启动 + 连内核，后面几发的入口->回执不到 1ms，整数毫秒就是 0。
    # 0 是量到的 0，不是没量 —— 但它让 p50 变成 0，所以按发位分层报。
    say("DIST-第一发 n=%d min=%d p50=%d p90=%d max=%d | 超%d 的发=%d (%.1f%%)" %
        (len(firsts), firsts[0] if firsts else -1, pct(firsts, .5), pct(firsts, .9),
         firsts[-1] if firsts else -1, BUDGET, over_first, 100.0 * over_first / len(firsts) if firsts else -1))
    say("DIST-后续发  n=%d min=%d max=%d 其中 ack_ms=0 的发=%d" %
        (len(rest), rest[0] if rest else -1, rest[-1] if rest else -1,
         sum(1 for x in rest if x == 0)))
    say("DIST-全样本 n=%d min=%d p50=%d p90=%d max=%d | 超%d 的发=%d (%.1f%%)" %
        (len(s), s[0] if s else -1, pct(s, .5), pct(s, .9), s[-1] if s else -1, BUDGET, over,
         100.0 * over / len(s) if s else -1))
    say("PER-RUN 趟级 rc!=0 的趟=%d / -check-log@100 红的趟=%d / 观测到的最忙 busy=%d" %
        (runs_bad, runs_red, busy_max))
    say("BREAK   超预算的那几发（发位=每趟第一发）= %s" %
        (",".join("run%d=%dms" % (p["run"], p["first"]) for p in per_run if p["first"] > BUDGET) or "无"))
    say("SWEEP 第一发口径，若预算改成这些数则超的发数 = %s" %
        " ".join("%d:%d" % (t, sum(1 for x in firsts if x > t)) for t in (20, 50, 100, 150, 200, 300, 500)))

    # 两条叶子臂：尺子必须会红，否则上面那行「超预算的发=0」没牙。
    # 臂的红不只看 rc，还要看**它红在哪一句**：预算 0 时那句必须报出一个 >0 的毫秒数，
    # 否则「红了」可能只是 ack_ms 缺失或 0>0 这种空转。
    m00 = os.path.join(work, "m00.events.jsonl")
    rc0, reds0, why0 = check_log(exe, m00, 0)
    mm = re.search(r"距入口 (\d+)ms", why0)
    teeth = rc0 == 4 and len(reds0) > 0 and mm is not None and int(mm.group(1)) > 0
    say("ARM-TEETH 预算=0 在正常日志上 rc=%d 红的支=%s 读数=%s 那句里的ack=%s -> %s" %
        (rc0, ",".join(reds0) or "-", why0[:80], mm.group(1) if mm else "没报毫秒数",
         "有牙" if teeth else "没牙(不作数)"))
    rcw, redsw, _ = check_log(exe, m00, 60000)
    wide_ok = rcw == 0 and not redsw
    say("ARM-WIDE  预算=60000 rc=%d 红的支=%s -> %s" %
        (rcw, ",".join(redsw) or "-", "绿" if wide_ok else "仍红(那这本账有别的问题)"))
    # 阈值穿越配对（臂要让两个读数真打架）：拿**第一发最慢的那本日志**，设它的 ack=F，
    # 同一份文件判两次：预算 F-1 必须红、预算 F 必须绿（Go 侧判的是 `ack > limit`，等于不算超）。
    # 这一对钉的是「VERDICT 里那个破/守的数确实是 Go 判据在读这个旗标」——两档同色就说明
    # 旗标没接上线，或这一支压根没走。穿越点 F 与契约预算 100 的相对位置一起印出来。
    worst = max(per_run, key=lambda p: p["first"]) if firsts else None
    cross_state = "NOT_MEASURABLE"
    if worst and worst["first"] >= 1:
        f_val = worst["first"]
        wlog = os.path.join(work, "m%02d.events.jsonl" % worst["run"])
        rca, reda, whya = check_log(exe, wlog, f_val - 1)
        rcb, redb, _ = check_log(exe, wlog, f_val)
        rcc, redc, _ = check_log(exe, wlog, BUDGET)
        crossed = (rcb == 0 and not redb) and (rca == 4 and len(reda) > 0)
        cross_state = "穿越点F=%d 与契约100的关系=%s" % (
            f_val, "100 在穿越点之内(这一发守住)" if f_val <= BUDGET
            else "100 已越过(这一发破)")
        say("ARM-CROSS 最慢那本 run%d F=%dms: 预算%d rc=%d 红的支=%s | 预算%d rc=%d 红的支=%s | 预算%d rc=%d 红的支=%s -> %s" %
            (worst["run"], f_val, f_val - 1, rca, ",".join(reda) or "-", f_val, rcb,
             ",".join(redb) or "-", BUDGET, rcc, ",".join(redc) or "-",
             "两档真打架" if crossed else "没打架(旗标没接上线，臂不成立)")
            )
        say("ARM-CROSS-READ 预算%d 那句=%s" % (f_val - 1, whya[:100]))
        if not crossed:
            cross_ok = False
        else:
            cross_ok = True
    else:
        cross_ok = True  # 第一发全 0 时构造不出穿越点：这一格如实留 NOT_MEASURABLE，别算成有牙
        say("ARM-CROSS %s（第一发没量到非零 ack，造不出穿越点）" % cross_state)

    if not firsts:
        verdict = "没量到：一趟第一发都没落下来 —— 本件红，别写成守住"
    elif not teeth:
        verdict = "尺子没牙（预算 0 不报出非零 ack 或不红）—— 上面所有 ack 结论作废"
    elif not wide_ok:
        verdict = "宽预算 60000 下仍红 —— 这本账有别的问题，ack 那一支的绿不能单独归因"
    elif not cross_ok:
        verdict = "预算 F-1 / F 两档没打架 —— -ack-limit-ms 这个旗标没接上判据，结论不作数"
    elif runs_bad > 0:
        verdict = "有趟没跑完（rc!=0 的趟=%d）—— 分布不作数" % runs_bad
    elif over_first == 0:
        verdict = ("守住：这台机器、无并发编译（busy 最大=%d）、%d 趟 %d 个第一发里没有一发 ack_ms 超 %d"
                   "（max=%dms，p50=%dms）") % (busy_max, len(per_run), len(firsts), BUDGET,
                                               firsts[-1], pct(firsts, .5))
    else:
        verdict = ("偶发破：同一无并发条件下 %d 趟第一发里 %d 趟超 %dms（破的那几发见 BREAK；"
                   "其余第一发 max=%dms、p50=%dms）—— 预算是**发现**不是本件的闸，"
                   "所以这不算测量失败，算『100ms 这台机器守得住但不是每次』") % (
            len(firsts), over_first, BUDGET,
            max([x for x in firsts if x <= BUDGET] or [0]), pct(firsts, .5))
    say("VERDICT " + verdict)
    say("CAVEAT 只测了 happy 脚本、max-turns=20、单进程；真模型端点 NOT_RUN、真人 NOT_RUN —— 换负载这一分布得重测")
    say("三态 分布=量出来的 / 破预算=发现（不改本件 rc）/ 本件 rc 只答『这趟量可不可信』：臂不成立或趟没跑完才红")

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
    bad = ((not firsts) or (not teeth) or (not wide_ok) or (not cross_ok)
           or runs_bad > 0 or not land_ok)
    print("rc 归因: 没量到=%s 没牙=%s 宽预算仍红=%s 臂没打架=%s 有趟没跑完=%s 落盘不配平=%s" %
          (not firsts, not teeth, not wide_ok, not cross_ok, runs_bad > 0, not land_ok))
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
