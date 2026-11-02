#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""结算判据新补的六条牙（F 族）的变异自证：每条判据一支，摘平它就必须红。

对照先跑（必须绿），变异后必须红；编译崩不算红。
用法：C:/Users/Admin/sdk/py314/python.exe 臂检-F族-结算牙.py <go.exe> <树根>
"""
import json, os, shutil, subprocess, sys, tempfile

GO = sys.argv[1] if len(sys.argv) > 1 else ""
SRC = sys.argv[2] if len(sys.argv) > 2 else ""
if not os.path.isdir(SRC) or not os.path.isfile(GO):
    print("usage: python 臂检-F族-结算牙.py <go.exe> <tree-root>")
    sys.exit(4)

PAT = "^TestSettlementJudgeCatchesEachBadShape$"
MUTS = [
    ("F1 半结算不判（回到 continue）",
     'return fmt.Errorf("第 %d 发有 %d 条事件却没有结算 —— 半结算：循环进去了没收口", t, len(group))',
     'continue'),
    ("F2 相位名散写不判", 'if !inPhaseTable(s.Settle.Phase) {', 'if false {'),
    ("F3 结算不带 why 不判", 'if s.Settle.Why == "" {', 'if false {'),
    ("F4 done_before 大于发号不判", 'if s.Settle.DoneBefore < 0 || s.Settle.DoneBefore > t {', 'if false {'),
    ("F5 同趟计数倒退不判", 'if prev, has := prevDone[runKey]; has && s.Settle.DoneBefore < prev {', 'if prev, has := prevDone[runKey]; has && false {'),
    ("F6 counts 逐名比整条摘掉（只剩加总）",
     'if s.Settle.Counts[st] != want[st] {', 'if false {'),
    ("F7 reached 里表外相名不判（回到 continue）",
     'return fmt.Errorf("第 %d 发 reached 里的 %q 不在相位表里 —— 补一个表外的相就当走过了", t, p)',
     'continue'),
]

work = os.path.join(tempfile.gettempdir(), "F族臂检-" + str(os.getpid()))
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
fp = os.path.join(work, "cmd", "agentd", "events.go")
base = open(fp, encoding="utf-8").read()
out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "臂检-F族.jsonl"), "w", encoding="utf-8", newline="\n")

def run():
    r = subprocess.run([GO, "test", "./cmd/agentd/", "-count=1", "-run", PAT],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    broken = any(k in out for k in ("[build failed]", "cannot use", "undefined:", "declared and not used"))
    return r.returncode, out, broken

blind, ctrl = [], []
print("arm | control_rc | mutant_rc | verdict")
for name, old, new in MUTS:
    if base.count(old) != 1:
        print("%s | snippet hit %d —— 变异没接上" % (name.split()[0], base.count(old)))
        blind.append(name)
        continue
    rc0, _, b0 = run()
    open(fp, "w", encoding="utf-8", newline="\n").write(base.replace(old, new))
    rc1, tail, b1 = run()
    open(fp, "w", encoding="utf-8", newline="\n").write(base)
    if rc0 != 0 or b0:
        v = "CONTROL-NOT-GREEN"; ctrl.append(name)
    elif b1:
        v = "BROKEN(崩不算红)"
    elif rc1 == 0:
        v = "BLIND"
    else:
        v = "BIT"
    if v in ("BLIND", "BROKEN(崩不算红)"):
        blind.append(name)
    log.write(json.dumps({"arm": name, "file": "cmd/agentd/events.go", "test": PAT, "control_rc": rc0,
                          "mutant_rc": rc1, "mutant_build_broken": b1, "verdict": v,
                          "note": "" if v == "BIT" else tail.strip().splitlines()[-1][:140]}, ensure_ascii=False) + "\n")
    print("%s | %d | %d | %s" % (name.split()[0], rc0, rc1, v))
log.close()
shutil.rmtree(work, ignore_errors=True)
print("total %d | bit %d | blind %d | control-red %d" % (len(MUTS), len(MUTS) - len(blind), len(blind), len(ctrl)))
sys.exit(2 if blind else 0)
