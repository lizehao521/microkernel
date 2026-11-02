#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""事件层反臂自证：每一根针都要能红，还要能绿（A 族 = E1，B 族 = E2，随故事增长）。

判据本体一改就红 = 这根针接在被改的那个绑定上（不是恒绿的装饰）。
两头都跑：同一支测试在**未变异**的副本上必须 rc=0（否则「红了」不作数 —— 恒红的尺子也没牙）。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂检-事件层-1022.py <go.exe> <内核树根>
退出码：0 = 全部变异都红且对照全绿；2 = 有变异没咬（盲区）；3 = 对照不绿（现场问题）。
产物：读数/臂检-事件层.jsonl（每发一行结构化读数）+ 臂检-事件层-读数.md。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

GO = sys.argv[1] if len(sys.argv) > 1 else "go"
SRC = sys.argv[2] if len(sys.argv) > 2 else ""
if not SRC or not os.path.isdir(SRC):
    print("用法: python 臂检-事件层-1022.py <go.exe> <内核树根>")
    sys.exit(4)

# (编号, 文件, 原片段, 变异片段, 该红的测试)
MUTS = [
    ("A1 append 改回截断", "events.go",
     "os.O_CREATE|os.O_WRONLY|os.O_APPEND", "os.O_CREATE|os.O_WRONLY|os.O_TRUNC",
     "^TestEventLogAppendsAcrossRuns$"),
    ("A2 序号判据恒过", "events.go",
     "func ValidateLog(evs []Event) error {\n\tlast := map[int]int{}",
     "func ValidateLog(evs []Event) error {\n\treturn nil\n}\n\nfunc ValidateLogX(evs []Event) error {\n\tlast := map[int]int{}",
     "^TestValidateLogArmRejectsDuplicateAndRegress$"),
    ("A3 state 白名单拆掉", "events.go",
     "\tcase !eventStates[e.State]:", "\tcase false:",
     "^TestAbsentWithoutWhyIsRefusedAndNotWritten$"),
    ("A4 计数先于落盘", "events.go",
     "\tif b.f != nil {\n\t\t// 先落盘（含 Sync）再算落了",
     "\tif false {\n\t\t// 先落盘（含 Sync）再算落了",
     "^TestEventSeqMonotonicWithinEachTurn$"),
    ("A5 已关闭的守卫拆掉", "events.go",
     "\tif b.closed {\n\t\treturn fmt.Errorf", "\tif false {\n\t\treturn fmt.Errorf",
     "^TestClosedBusRefusesNewEvents$"),
    ("A6 拒收改回写 stdout", "events.go",
     'r.errf("    事件层拒了', 'r.say("    事件层拒了',
     "^TestEmitFailureIsLoudOnStderr$"),
    # 变异要能编译：原来这条把整个条件换成 false，`j :=` 就变成「声明未用」——
    # rc 非 0 是编译崩，不是判据红（BROKEN 检测上线后才发现它一直在冒充「咬住」）。
    ("A7 撞车守卫拆掉", "main.go",
     "if clean == j || filepath.Dir(clean) == j {", "if j == \"\" {",
     "^TestEventLogPathDerivationAndCollision$"),
    ("A8 total 一律取额度", "loop.go",
     "\t\ttotal = done", "\t\ttotal = r.maxTurns",
     "^TestEventSeqMonotonicWithinEachTurn$"),
    ("A9 账满那一形与继续那一形混成一条", "loop.go",
     'refusedWhy += " ｜ 容量栏挡下 "', 'refusedWhy += " ｜ "',
     "^TestRefusedEventsCarryTheirWhy$"),
    ("A10 收口塞回发级坐标", "loop.go",
     'settle := Event{Kind: "run_settled", State: "settled", Evidence: "measured"}',
     'settle := r.stepEv("run_settled", "settled", "measured", "", "closeOut", r.shot)',
     "^TestEventSeqMonotonicWithinEachTurn$"),
    # ---- E2（回执）----
    ("B1 回执挂点摘掉", "loop.go",
     "\t\tr.emit(r.acceptedEv())\n", "",
     "^TestTurnAcceptedLeadsEveryTurn$"),
    ("B2 ack 写成恒 0", "events.go",
     "ms := time.Since(ne.enteredAt).Milliseconds()", "ms := int64(0)",
     "^TestLateReceiptGoesRed$"),
    ("B3 上限调到永远够", "events.go",
     "const ackLimitMS = 100", "const ackLimitMS = 1 << 40",
     "^TestLateReceiptGoesRed$"),
    ("B4 否定式豁免拆掉", "events.go",
     "regexp.MustCompile(`(^|[^不])可续`)", "regexp.MustCompile(`可续`)",
     "^TestAcceptArmsCatchEachBadShape$"),
    ("B5 resumable 不落盘", "events.go",
     'json:"resumable"', 'json:"-"',
     "^TestResumableFieldSurvivesFalse$"),
    ("B6 入口时刻门禁拆掉", "events.go",
     "case e.Accept != nil && e.enteredAt.IsZero():", "case false:",
     "^TestReceiptWithoutEntryInstantIsRefused$"),
    # 判据被摘平（恒过）时，红的是**接坏值那支臂**，不是走绿路径那支 —— 目标要选对，
    # 否则就是「变异没咬」的假盲区（这一条本脚本自己刚踩过）。
    ("B7 回执判据恒过", "events.go",
     "func ValidateAccepts(evs []Event) error {",
     "func ValidateAccepts(evs []Event) error {\n\treturn nil\n}\n\nfunc ValidateAcceptsX(evs []Event) error {",
     "^TestAcceptArmsCatchEachBadShape$"),
]

work = os.path.join(tempfile.gettempdir(), "E1-臂检-" + str(os.getpid()))
# mcpsrv 必须一起拷：cmd/agentd 的 rpc.go 直接 import 它（漏了就是「对照不绿」的假红）。
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
keep = {}
for f in ("events.go", "loop.go", "main.go"):
    p = os.path.join(work, "cmd", "agentd", f)
    keep[f] = open(p, encoding="utf-8").read()

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "臂检-事件层.jsonl"), "w", encoding="utf-8", newline="\n")


def run(pat):
    r = subprocess.run([GO, "test", "./cmd/agentd/", "-count=1", "-run", pat],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    # 编译不过 ≠ 判据红：内核那条老规矩（崩不算红）在这里同样适用 ——
    # 变异写坏了语法会让 rc 非 0，冒充「咬住」。
    broken = ("[build failed]" in out) or ("cannot use" in out) or ("undefined:" in out) or ("expected" in out)
    return r.returncode, out, broken


blind, ctrl_red = [], []
rows = []
# 控制台只用 ASCII：GBK 下中文表头会变砖（读不到就等于没读数）。中文进 jsonl 与 md。
print("arm | file | test | control_rc | mutant_rc | verdict")
for name, fname, old, new, pat in MUTS:
    src = keep[fname]
    if src.count(old) != 1:
        print("%s | %s | snippet hit %d times, mutation not wired" % (name.split()[0], fname, src.count(old)))
        blind.append(name + "(片段不唯一)")
        continue
    cpath = os.path.join(work, "cmd", "agentd", fname)
    # 先跑对照（未变异必须绿），再落变异跑第二遍 —— 顺序反了就是拿变异自己当对照，
    # 两个数会长成一样，"盲区"全是假的（这一条本脚本自己刚踩过）。
    rc0, _, broken0 = run(pat)
    open(cpath, "w", encoding="utf-8", newline="\n").write(src.replace(old, new))
    rc1, tail, broken1 = run(pat)
    open(cpath, "w", encoding="utf-8", newline="\n").write(src)
    verdict = "BIT"
    if rc0 != 0 or broken0:
        ctrl_red.append(name)
        verdict = "CONTROL-NOT-GREEN"
    elif broken1:
        verdict = "BROKEN(崩不算红)"
    elif rc1 == 0:
        verdict = "BLIND"
    if verdict != "BIT":
        blind.append(name)
    ok = verdict == "BIT"
    reason = "" if ok else tail.strip().splitlines()[-1][:120]
    log.write(json.dumps({"arm": name, "file": "cmd/agentd/" + fname, "test": pat,
                          "control_rc": rc0, "mutant_rc": rc1, "mutant_build_broken": broken1,
                          "bit": ok, "verdict": verdict, "note": reason}, ensure_ascii=False) + "\n")
    rows.append({"arm": name, "file": "cmd/agentd/" + fname, "test": pat.strip("^$"),
                 "control_rc": rc0, "mutant_rc": rc1, "verdict": verdict})
    print("%s | cmd/agentd/%s | %s | %d | %d | %s" %
          (name.split()[0], fname, pat.strip("^$"), rc0, rc1, verdict))
log.close()
shutil.rmtree(work, ignore_errors=True)

md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "臂检-事件层-读数.md")
with open(md, "w", encoding="utf-8", newline="\n") as f:
    f.write("# 事件层反臂自证读数（臂检-事件层-1022.py 现跑，勿手抄）\n\n")
    f.write("- 树根：%s\n- 臂 %d 根：咬住 %d，盲区 %d；对照不绿 %d\n\n" %
            (SRC, len(MUTS), len(MUTS) - len(blind), len(blind), len(ctrl_red)))
    f.write("| 编号 | 变异（把修好的那一处改回坏法） | 文件 | 该红的测试 | 对照 rc | 变异 rc | 判定 |\n")
    f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
    for row in rows:
        f.write("| %s | %s | %s | %s | %d | %d | %s |\n" % (
            row["arm"].split()[0], row["arm"].split(" ", 1)[1], row["file"], row["test"],
            row["control_rc"], row["mutant_rc"], row["verdict"]))
print("markdown: %s" % md)
print("total %d | bit %d | blind %d | control-red %d" %
      (len(MUTS), len(MUTS) - len(blind), len(blind), len(ctrl_red)))
print("readings: %s" % os.path.join(out_dir, "臂检-事件层.jsonl"))
if blind:
    print("blind: %s" % ", ".join(b.split()[0] for b in blind))
    sys.exit(2)
if ctrl_red:
    print("control not green (scene problem): %s" % ", ".join(c.split()[0] for c in ctrl_red))
    sys.exit(3)
print("conclusion: every new pin bites, and all controls are green")
sys.exit(0)
