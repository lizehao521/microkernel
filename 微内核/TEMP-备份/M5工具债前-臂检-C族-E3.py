#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E3（停止入口 + 结算）的变异自证：C 族。

规矩与 A/B 族同一条：先跑未变异对照（必须绿），再落变异（必须红），
且**编译崩不算红**（mutant_build_broken 单独一列）。
本件是 E3 在沙箱里写的；合入 臂检-事件层-1022.py 之后删掉，别留两份闸。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂检-C族-E3.py <go.exe> <树根>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

GO = sys.argv[1]
SRC = sys.argv[2]
if not os.path.isdir(SRC):
    print("usage: python 臂检-C族-E3.py <go.exe> <tree-root>")
    sys.exit(4)

MUTS = [
    # C1/C2 原本指向「全跑完」那支测试 —— 假盲区：那种负载每一发都走到最后一相，
    # not_reached 天然是空的，判据改坏了也看不见。臂必须指到**走得到那条分支的负载**上。
    ("C1 not_reached 恒空（没走到的步骤不交）", "loop.go",
     "\t\t\tnot = append(not, p)", "\t\t\t_ = p",
     "^TestInterruptDoesNotFabricateSteps$"),
    ("C2 补步：所有相都算走过", "loop.go",
     "\t\tif i <= at {", "\t\tif i <= at || i >= 0 {",
     "^TestInterruptSettlesWithinSecond$"),
    ("C3 counts 不现数（人手打空表）", "loop.go",
     "Counts: r.events.countsFor(r.session, r.turns)", "Counts: map[string]int{}",
     "^TestEveryTurnSettlesExactlyOnce$"),
    ("C4 幂等守卫拆掉（一发可结多次）", "loop.go",
     "if r.events == nil || r.settled || r.turns == 0 {", "if r.events == nil || r.turns == 0 {",
     "^TestSettleTurnIsIdempotent$"),
    ("C5 打断不结算", "loop.go",
     'r.settleTurn("interrupted", "等待端点回话时被叫停（-shot-delay 期间）")', "r.settled = true",
     "^TestInterruptSettlesWithinSecond$"),
    ("C6 叫停原因被后发的覆盖", "loop.go",
     "if r.stopWhy == \"\" {", "if true {",
     "^TestStopEntryIsSingleAndIdempotent$"),
    ("C7 run 级 stop 写回散文", "loop.go",
     "\tsettle.Stop = r.stop.Token()", "\tsettle.Stop = string(r.stop)",
     "^TestEventSeqMonotonicWithinEachTurn$"),
    ("C8 结算类别散写没门禁", "events.go",
     'case "completed", "refused", "failed", "interrupted":', 'case "completed", "refused", "failed", "interrupted", "done":',
     "^TestSettlementArmsCatchEachBadShape$"),
    ("C9 被打断也标成 completed", "loop.go",
     '\tif kind == "interrupted" {\n\t\te.Kind = "turn_interrupted"\n\t\te.State = "interrupted"\n\t}',
     "\tif false {\n\t\te.Kind = \"turn_interrupted\"\n\t\te.State = \"interrupted\"\n\t}",
     "^TestInterruptDoesNotFabricateSteps$"),
]

work = os.path.join(tempfile.gettempdir(), "C族臂检-" + str(os.getpid()))
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
keep = {}
for f in ("events.go", "loop.go"):
    keep[f] = open(os.path.join(work, "cmd", "agentd", f), encoding="utf-8").read()

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "臂检-C族.jsonl"), "w", encoding="utf-8", newline="\n")


def run(pat):
    r = subprocess.run([GO, "test", "./cmd/agentd/", "-count=1", "-run", pat],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    broken = ("[build failed]" in out) or ("cannot use" in out) or ("undefined:" in out) or ("declared and not used" in out)
    return r.returncode, out, broken


blind, ctrl_red = [], []
print("arm | file | test | control_rc | mutant_rc | verdict")
for name, fname, old, new, pat in MUTS:
    src = keep[fname]
    if src.count(old) != 1:
        print("%s | %s | snippet hit %d times (mutation not wired)" % (name.split()[0], fname, src.count(old)))
        blind.append(name)
        continue
    cpath = os.path.join(work, "cmd", "agentd", fname)
    rc0, _, b0 = run(pat)
    open(cpath, "w", encoding="utf-8", newline="\n").write(src.replace(old, new))
    rc1, tail, b1 = run(pat)
    open(cpath, "w", encoding="utf-8", newline="\n").write(src)
    if rc0 != 0 or b0:
        v = "CONTROL-NOT-GREEN"
        ctrl_red.append(name)
    elif b1:
        v = "BROKEN(崩不算红)"
    elif rc1 == 0:
        v = "BLIND"
    else:
        v = "BIT"
    if v != "BIT":
        blind.append(name)
    log.write(json.dumps({"arm": name, "file": "cmd/agentd/" + fname, "test": pat, "control_rc": rc0,
                          "mutant_rc": rc1, "mutant_build_broken": b1, "verdict": v,
                          "note": "" if v == "BIT" else tail.strip().splitlines()[-1][:120]}, ensure_ascii=False) + "\n")
    print("%s | cmd/agentd/%s | %s | %d | %d | %s" % (name.split()[0], fname, pat.strip("^$"), rc0, rc1, v))
log.close()
shutil.rmtree(work, ignore_errors=True)
print("total %d | bit %d | blind %d | control-red %d" %
      (len(MUTS), len(MUTS) - len(blind), len(blind), len(ctrl_red)))
if blind:
    print("blind: %s" % ", ".join(b.split()[0] for b in blind))
    sys.exit(2)
sys.exit(0)
