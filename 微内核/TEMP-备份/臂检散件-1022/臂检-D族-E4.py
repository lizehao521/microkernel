#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4（SSE 投送 + Last-Event-ID 重放）的变异自证：D 族。

【已被取代 · M5 工具债 #113-1（2026-10 本轮执行）】本件 10 根臂已并入 臂检-全部族.py（D 族）。
旧件先留盘勿删、别再当闸跑，等作者核完对照读数再删。

规矩与 A/B/C 族同一条：先跑未变异对照（必须绿），再落变异（必须红），
且**编译崩不算红**（mutant_build_broken 单独一列），臂必须指到**走得到那条分支的负载**上。
本件在 E4 沙箱里写；合入 臂检-事件层-1022.py 之后删掉，别留两份闸。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂检-D族-E4.py <go.exe> <树根>
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
    print("usage: python 臂检-D族-E4.py <go.exe> <tree-root>")
    sys.exit(4)

MUTS = [
    # D1 游标退回三元组（把 E1 加的 run 轴丢了）：跨趟日志上两个 turn=1 就会指到同一条。
    ("D1 游标丢 run 轴（退回 session:turn:seq）", "sse.go",
     'return fmt.Sprintf("%s%s%s%s%d%s%d", e.Session, sseCursorSep, e.Run, sseCursorSep, e.Turn, sseCursorSep, e.Seq)',
     'return fmt.Sprintf("%s%s%d%s%d", e.Session, sseCursorSep, e.Turn, sseCursorSep, e.Seq)',
     "^TestReplayTwiceGivesSameSequence$|^TestCursorCarriesRunAxis$"),
    # D2 投送层不过判据（坏游标被当首连，整本重播）。
    ("D2 坏游标当首连（跳过续传判断）", "sse.go",
     "if err := ValidateReplay(log, c); err != nil {",
     "if err := ValidateReplay(log, \"\"); err != nil {",
     "^TestBadCursorIsNotTreatedAsHead$|^TestReplayJudgeAndHandlerAgreeOnBadCursor$"),
    # D3 重放把游标那条也播一遍（off-by-one）：界面会看到已经看过的一步。
    ("D3 游标那条被重播（log[idx:]）", "sse.go",
     "\treturn log[idx+1:]",
     "\treturn log[idx:]",
     "^TestReplayTwiceGivesSameSequence$"),
    # D4 resumable 退回「恒 false 的约定」：E4 兑现了能力还写不能续，是把能续的那一半藏了。
    ("D4 resumable 恒 false（约定冒充度量）", "events.go",
     '\treturn true, "断开可续：游标就是日志里的身份四元组，投送层按日志行序取游标之后的尾部"',
     '\treturn false, "断开不能续：写死的约定，没看落点"',
     "^TestReceiptPayloadIsHonest$|^TestResumableIsMeasuredNotAssumed$"),
    # D5 内存模式也写可续：盘上没有可读回的账，重放必然接不上，那是谎。
    ("D5 内存模式冒充可续", "events.go",
     '\t\treturn false, "断开不能续：没有落点，这一趟只在内存数序"',
     '\t\treturn true, "断开可续：内存里也数得着"',
     "^TestResumableIsMeasuredNotAssumed$"),
    # D6 「声称能续却续不上」那一支摘平：针6 的红线就没牙了。
    ("D6 resumable=true 却接不上不判", "sse.go",
     "\tif *acc.Accept.Resumable {",
     "\tif false {",
     "^TestReplayArmsCatchEachBadShape$"),
    # D7 身份撞车不判：两条一模一样时重放指不准是哪条，判据必须点名而不是换个理由红。
    ("D7 同身份多条不判（hits>2）", "sse.go",
     "\tif hits > 1 {",
     "\tif hits > 2 {",
     "^TestReplayArmsCatchEachBadShape$"),
    # D8 帧不带 id：Last-Event-ID 无从递回来，重放整条路是装饰。
    ("D8 帧不写 id 行", "sse.go",
     'fmt.Fprintf(w, "id: %s\\ndata: %s\\n\\n", formatCursor(e), b)',
     'fmt.Fprintf(w, "data: %s\\n\\n", b)',
     "^TestServedFramesAreLogRows$|^TestReplayTwiceGivesSameSequence$"),
    # D9 路由摘掉：任何路径都播事件，等于没有路由。
    ("D9 不分路径都播事件（mux 摘掉）", "sse.go",
     "srv := &http.Server{Handler: eventsMux(sseHandler(path)), ReadHeaderTimeout: 5 * time.Second}",
     "srv := &http.Server{Handler: sseHandler(path), ReadHeaderTimeout: 5 * time.Second}",
     "^TestOtherPathGives404$"),
    # D10 尾部退回按 seq 定序：seq 是发内的，跨趟日志会把第二趟的 turn=1 插到第一趟的高 turn 前面。
    ("D10 尾部按 seq 定序（旧写法）", "sse.go",
     "\treturn log[idx+1:]",
     "\tout := []Event{}\n\tfor _, e := range log {\n\t\tif e.Seq > log[idx].Seq {\n\t\t\tout = append(out, e)\n\t\t}\n\t}\n\treturn out",
     "^TestCrossRunReplayKeepsLogOrder$"),
]

work = os.path.join(tempfile.gettempdir(), "D族臂检-" + str(os.getpid()))
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
keep = {}
for f in ("events.go", "sse.go"):
    keep[f] = open(os.path.join(work, "cmd", "agentd", f), encoding="utf-8").read()

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
log = open(os.path.join(out_dir, "臂检-D族.jsonl"), "w", encoding="utf-8", newline="\n")


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
