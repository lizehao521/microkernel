#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E3 补丁族（路 A 的 P0 + 针4 空载那一族）的变异自证：E 族。

【已被取代 · M5 工具债 #113-1（2026-10 本轮执行）】本件 5 根臂（含 E1 多站点 pairs 与 panic 单列）
已原样并入 臂检-全部族.py（E 族）。旧件先留盘勿删、别再当闸跑，等作者核完对照读数再删。

一条规矩不变：先跑未变异对照（必须绿），再落变异（必须红）；编译崩不算红，
进程崩单列一栏（症状可见但要写明是崩，不是判据在管）。
E1 是多站点变异：counts 的键要写侧与读侧**一起**退回「只按 turn」那一形，才是路 A 那条 P0。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂检-E族-E3补丁.py <go.exe> <树根>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

GO = sys.argv[1] if len(sys.argv) > 1 else ""
SRC = sys.argv[2] if len(sys.argv) > 2 else ""
if not os.path.isdir(SRC) or not os.path.isfile(GO):
    print("usage: python 臂检-E族-E3补丁.py <go.exe> <tree-root>")
    sys.exit(4)

K = "b.states[blockOf(e)]"
MUTS = [
    ("E1 counts 键抹掉 run+session 轴（路 A 的 P0 复发）", "events.go",
     [(K, "b.states[blockOf(Event{Turn: e.Turn})]", 6),
      ("blockOf(Event{Session: session, Run: b.run, Turn: turn})", "blockOf(Event{Turn: turn})", 1)],
     "^TestCrossRunCountsArePerRun$"),
    ("E2 打断时 KPI 清零（计划 E3 点名的反臂）", "loop.go",
     [("DoneBefore: r.shot, KPI: r.kpi},", "DoneBefore: r.shot, KPI: 0},", 1)],
     "^TestInterruptSettlesWithinSecond$"),
    ("E3 打断时 DoneBefore 归零", "loop.go",
     [("DoneBefore: r.shot, KPI: r.kpi},", "DoneBefore: 0, KPI: r.kpi},", 1)],
     "^TestInterruptSettlesWithinSecond$"),
    ("E4 打断负载退回空载（针4 变 0==0）", "events_settle_test.go",
     [('if !waitForKind(path, "turn_accepted", 2, 6*time.Second) {',
       'if !waitForEvent(path, "turn_accepted", 3*time.Second) {', 2)],
     "^TestInterruptSettlesWithinSecond$"),
    ("E5 叫停不查「关过没有」", "loop.go",
     [("if r.abort == nil || r.abortClosed {", "if r.abort == nil || false {", 1)],
     "^TestConcurrentStopClosesAbortExactlyOnce$"),
]

work = os.path.join(tempfile.gettempdir(), "E族臂检-" + str(os.getpid()))
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
files = {}
for _, fname, _, _ in MUTS:
    if fname not in files:
        files[fname] = open(os.path.join(work, "cmd", "agentd", fname), encoding="utf-8").read()

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "臂检-E族.jsonl"), "w", encoding="utf-8", newline="\n")


def run(pat):
    r = subprocess.run([GO, "test", "./cmd/agentd/", "-count=1", "-run", pat],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    broken = any(k in out for k in ("[build failed]", "cannot use", "undefined:", "declared and not used"))
    return r.returncode, out, broken, ("panic:" in out)


blind, ctrl_red = [], []
print("arm | file | control_rc | mutant_rc | verdict")
for name, fname, pairs, pat in MUTS:
    base = files[fname]
    cpath = os.path.join(work, "cmd", "agentd", fname)
    wired = True
    for old, _new, want in pairs:
        if base.count(old) != want:
            print("%s | %s | snippet hit %d (want %d) —— 变异没接上" % (name.split()[0], fname, base.count(old), want))
            wired = False
    if not wired:
        blind.append(name)
        continue
    rc0, _, b0, _ = run(pat)
    mut = base
    for old, new, _want in pairs:
        mut = mut.replace(old, new)
    open(cpath, "w", encoding="utf-8", newline="\n").write(mut)
    rc1, tail, b1, cr1 = run(pat)
    open(cpath, "w", encoding="utf-8", newline="\n").write(base)
    if rc0 != 0 or b0:
        v = "CONTROL-NOT-GREEN"
        ctrl_red.append(name)
    elif b1:
        v = "BROKEN(崩不算红)"
    elif rc1 == 0:
        v = "BLIND"
    elif cr1:
        v = "BIT(进程崩，症状可见)"
    else:
        v = "BIT"
    if v in ("BLIND", "BROKEN(崩不算红)"):
        blind.append(name)
    log.write(json.dumps({"arm": name, "file": "cmd/agentd/" + fname, "test": pat, "control_rc": rc0,
                          "mutant_rc": rc1, "mutant_build_broken": b1, "mutant_panicked": cr1,
                          "verdict": v,
                          "note": "" if v.startswith("BIT") else tail.strip().splitlines()[-1][:140]},
                         ensure_ascii=False) + "\n")
    print("%s | cmd/agentd/%s | %d | %d | %s" % (name.split()[0], fname, rc0, rc1, v))
log.close()
shutil.rmtree(work, ignore_errors=True)
print("total %d | bit %d | blind %d | control-red %d" % (len(MUTS), len(MUTS) - len(blind), len(blind), len(ctrl_red)))
sys.exit(2 if blind else 0)
