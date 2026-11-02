#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 端到端冒烟：跑**建出来的 exe**，不跑 go run（go run 会把非零退出码塌成 1，六态读不出来）。

要证的八件事，一件一条读数：
  S1 stdout 正文不受事件层影响（开/关两趟，掩掉数字宽度与自身路径后逐字比）
  S2 append-only 跨进程是真的：第二趟在第一趟后面追加，序号不重来
  S3 撞车守卫：事件落点压在 --journal-out 上时，账本还是文件、还能写，事件不落
  S4 横幅三态：落了 / 没落点 / 没开 —— 各印各的，不塌成一态
  S5 六态退出码没被改动（real 驱动仍 2、额度到仍 3、账满仍 5、跑完仍 0）
  S6 收口那一条：state=settled、stop=六态整句、done/total/limit 三格都在
  S7 回执（E2）：每一发第一条恒为 turn_accepted，ack_ms 真量出来、上限 100ms 内、载荷给全
  S8 结算（E3）：一发恰好一条结算、not_reached 里不许出现对应事件、run 级 stop 是 token

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 冒烟-事件层-1022.py <go.exe> <内核树根>
退出码 0 = 六条全过；2 = 有没过的一条（点名是哪一条）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

GO = sys.argv[1]
SRC = sys.argv[2]
if not os.path.isdir(SRC):
    print("usage: python 冒烟-事件层-1022.py <go.exe> <sandbox-root>")
    sys.exit(4)

here = os.path.dirname(os.path.abspath(__file__))
out_dir = os.path.join(here, "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "冒烟-事件层.jsonl"), "w", encoding="utf-8", newline="\n")
base = os.path.join(tempfile.gettempdir(), "E1-冒烟-" + str(os.getpid()))
os.makedirs(base, exist_ok=True)


def emit(name, ok, **kw):
    rec = {"step": name, "ok": ok}
    rec.update(kw)
    log.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("%s %s | %s" % ("PASS" if ok else "FAIL", name,
                          " ".join("%s=%s" % (k, v) for k, v in kw.items())))
    return bool(ok)


results = []
exe = os.path.join(base, "agentd-e1.exe")
b = subprocess.run([GO, "build", "-o", exe, "./cmd/agentd"], cwd=SRC,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
digest = hashlib.sha256(open(exe, "rb").read()).hexdigest()[:12] if b.returncode == 0 else "-"
print("build rc=%d exe=%s sha256=%s" % (b.returncode, exe, digest))
results.append(emit("S0 跑的是哪一份 build", b.returncode == 0 and digest != "-",
                    exe=os.path.basename(exe), sha256_12=digest, build_rc=b.returncode))
if b.returncode != 0:
    print(b.stdout + b.stderr)
    sys.exit(2)


def go(*args):
    r = subprocess.run([exe] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


NUM = re.compile(r"[0-9]+ 字节")


def norm(s, *paths):
    s = NUM.sub("N 字节", s)
    for p in paths:
        if p:
            s = s.replace(p, "<PATH>")
    return s


def read_events(p):
    if not os.path.isfile(p):
        return []
    return [json.loads(ln) for ln in open(p, encoding="utf-8").read().splitlines() if ln.strip()]


j1 = os.path.join(base, "s1-on.jsonl")
j2 = os.path.join(base, "s1-off.jsonl")
e1 = os.path.join(base, "s1-on.events.jsonl")
rc_on, so_on, se_on = go("-script", "happy", "-max-turns", "20", "-journal-out", j1, "-events-out", e1)
rc_off, so_off, se_off = go("-script", "happy", "-max-turns", "20", "-journal-out", j2, "-events=false")
same = norm(so_on, j1) == norm(so_off, j2)
results.append(emit("S1 stdout 不受事件层影响", same and rc_on == 0 and rc_off == 0,
                    rc_on=rc_on, rc_off=rc_off, stdout_equal=same,
                    on_bytes=len(so_on), off_bytes=len(so_off),
                    events_in_stdout=("事件层" in so_on)))

# S2：同一对路径跑第二趟，日志必须变长且序号不重来
n1 = len(read_events(e1))
rc2, _, _ = go("-script", "happy", "-max-turns", "20", "-journal-out", j1, "-events-out", e1)
evs = read_events(e1)
n2 = len(evs)
last, seq_bad = {}, []
for e in evs:
    t = e.get("turn", 0)
    if t in last and e["seq"] <= last[t]:
        seq_bad.append((t, last[t], e["seq"]))
    last[t] = e["seq"]
started = sum(1 for e in evs if e["kind"] == "run_started")
results.append(emit("S2 append-only 跨进程", n2 > n1 and not seq_bad and started >= 2,
                    first_run=n1, after_second=n2, seq_regressions=len(seq_bad), run_started=started))

# S3：撞车 —— 事件落点压在账本路径上
j3 = os.path.join(base, "s3.jsonl")
rc3, so3, se3 = go("-script", "happy", "-max-turns", "20", "-journal-out", j3,
                   "-events-out", os.path.join(j3, "nested.events.jsonl"))
journal_is_file = os.path.isfile(j3)
nested = os.path.join(j3, "nested.events.jsonl")
results.append(emit("S3 撞车守卫保住账本",
                    journal_is_file and "撞车" in se3 and not os.path.exists(nested) and rc3 == 0
                    and os.path.getsize(j3) > 0,
                    journal_is_file=journal_is_file, journal_bytes=os.path.getsize(j3) if journal_is_file else 0,
                    rc=rc3, stderr_has_collision_note=("撞车" in se3), nested_events_written=os.path.exists(nested)))

# S4：横幅三态
_, _, se_mem = go("-script", "happy", "-max-turns", "20", "-journal-out", "", "-events-out", "")
_, _, se_off = go("-script", "happy", "-max-turns", "20", "-journal-out", j2, "-events=false")
_, _, se_file = go("-script", "happy", "-max-turns", "20", "-journal-out",
                   os.path.join(base, "s4.jsonl"), "-events-out", os.path.join(base, "s4.events.jsonl"))
three = ("没有落点" in se_mem, "没开" in se_off, "→" in se_file)
results.append(emit("S4 横幅三态各说各的", all(three), 内存态=three[0], 没开态=three[1], 落盘态=three[2],
                    file_line=[ln for ln in se_file.splitlines() if "事件层" in ln][:1]))

# S5：六态退出码没动
j5 = os.path.join(base, "s5.jsonl")
codes = {
    "real": go("-driver", "real", "-journal-out", j5)[0],
    "turns": go("-script", "happy", "-max-turns", "2", "-journal-out", j5)[0],
    "capped": go("-script", "full", "-entry-cap", "200", "-journal-out", j5)[0],
    "script": go("-script", "happy", "-max-turns", "20", "-journal-out", j5)[0],
    "bad_resume": go("-resume", os.path.join(base, "不存在.jsonl"), "-journal-out", j5)[0],
}
want = {"real": 2, "turns": 3, "capped": 5, "script": 0, "bad_resume": 2}
results.append(emit("S5 六态退出码未改", all(codes[k] == want[k] for k in codes), **codes))

# S6：收口那一条的形状
evs6 = read_events(os.path.join(base, "s4.events.jsonl"))
settle = [e for e in evs6 if e["kind"] == "run_settled"][-1] if evs6 else {}
prog = settle.get("progress", {})
# stop 是 token、整句话在 stop_why —— 原来这支拿「stop 含『跑完』」判，
# 那是「判据里的字符串匹配要盯那一步的那句话」的反面教材（中文散文当分支键）。
ok6 = (settle.get("state") == "settled" and settle.get("stop") == "script"
       and "跑完" in settle.get("stop_why", "")
       and prog.get("done") == prog.get("total") and prog.get("limit") == 20
       and "step" not in settle and settle.get("turn") == 0)
results.append(emit("S6 收口事件形状", ok6, state=settle.get("state"), stop=settle.get("stop"), stop_why=settle.get("stop_why"),
                    progress=prog, evidence=settle.get("evidence"),
                    turn=settle.get("turn"), step_field=settle.get("step", "absent")))
# S7：回执（E2）+ S8：结算（E3）—— 口径与 Go 判据对齐：分组键是 (session,run,turn)
# 早先 S7 自己按 turn 数「最小 seq 那条」，恰好对跨趟追加那本日志免疫（M2 两路都点到：
# 三方读数互不覆盖）。现在与 run 轴一起判，并且把「没走到的步骤」也数出来。
def key(e):
    return (e.get("session", ""), e.get("run", ""), e.get("turn", 0))

by_turn = {}
for e in evs6:
    k = key(e)
    if k[2] == 0:
        continue
    if k not in by_turn or e.get("seq", 0) < by_turn[k].get("seq", 0):
        by_turn[k] = e
acks = [(k, (e.get("accept") or {}).get("ack_ms")) for k, e in sorted(by_turn.items())]
bad_first = {k: e["kind"] for k, e in by_turn.items() if e["kind"] != "turn_accepted"}
payload_bad = [k for k, e in by_turn.items()
               if not (e.get("accept") or {}).get("stop_via") or (e.get("accept") or {}).get("turn_limit") != 20
               or "resumable" not in (e.get("accept") or {})
               or ((e.get("accept") or {}).get("resumable") is False and not e.get("why"))]
over = [(k, a) for k, a in acks if isinstance(a, int) and a > 100]
results.append(emit("S7 回执先于干活", bool(by_turn) and not bad_first and not over and not payload_bad,
                    有回执的发=len(by_turn), 趟身份=len({k[1] for k in by_turn}),
                    最大ack_ms=max([a for _, a in acks if isinstance(a, int)] or [-1]),
                    第一条不是回执=bad_first, 超上限=over, 载荷缺项=payload_bad))

settles = {}
for e in evs6:
    if e["kind"] in ("turn_settled", "turn_interrupted"):
        settles.setdefault(key(e), []).append(e)
dup = [k for k, v in settles.items() if len(v) > 1]
missing = [k for k in by_turn if k not in settles]
kinds = {s[0]["settle"]["kind"] for s in settles.values()}
notreached = {k: len(s[0]["settle"]["not_reached"]) for k, s in settles.items()}
PHASES = {"accept": "turn_accepted", "work": "shot_started", "check_call": "precheck", "record_call": "recorded"}
fabricated = []
for k, v in settles.items():
    st = v[0]["settle"]
    mine = [e["kind"] for e in evs6 if key(e) == k]
    for ph in st["not_reached"]:
        if PHASES[ph] in mine:
            fabricated.append((k, ph))
    for ph in st["reached"]:
        if PHASES[ph] not in mine:
            fabricated.append((k, "虚报" + ph))
    if sum(st["counts"].values()) != len([e for e in evs6 if key(e) == k and not e["kind"].startswith("turn_settled") and not e["kind"].startswith("turn_interrupted")]):
        fabricated.append((k, "counts"))
rs = [e for e in evs6 if e["kind"] == "run_settled"]
run_ok = bool(rs) and rs[-1].get("stop") in ("script", "turns", "policy", "driver", "capped", "abort") and rs[-1].get("stop_why")
ok8 = bool(settles) and not dup and not missing and not fabricated and run_ok
results.append(emit("S8 结算与相位（E3）", ok8, 结算的发=len(settles), 重复=dup, 没结算=missing,
                    补步或虚报=fabricated[:4], 结算类别=sorted(kinds),
                    有未走到步骤的份数=sum(1 for v in notreached.values() if v),
                    run_stop=rs[-1].get("stop") if rs else None, run_why=bool(rs and rs[-1].get("stop_why"))))
# 真实流里五档/why 的用量：只用一档这件事要能被数出来（不藏）
tiers, whys = {}, sum(1 for e in evs6 if e.get("why"))
for e in evs6:
    tiers[e.get("evidence", "?")] = tiers.get(e.get("evidence", "?"), 0) + 1
print("INFO 真实流出处档分布 %s；带 why 的 %d/%d" % (tiers, whys, len(evs6)))

log.close()
print("")
print("steps %d, passed %d" % (len(results), sum(1 for r in results if r)))
print("readings: %s" % os.path.join(out_dir, "冒烟-事件层.jsonl"))
sys.exit(0 if all(results) else 2)
