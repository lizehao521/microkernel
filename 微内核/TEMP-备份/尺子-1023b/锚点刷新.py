#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 event-layer.evidence.json 的 sourceRefs 按**盘上现数**刷新一遍。

为什么要有这件：行号是抄下来的，抄一次就冻一次 —— 代码一改就悄悄漂（这一发现场已经为这个红过一轮）。
这件不做「校验」（那是 证据模型核对.py 的活），它只做「重新指到行」，找不到就点名并退出 2。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 锚点刷新.py [内核树根]
退出码 0 = 全部指到；2 = 有符号在盘上找不到（宁可红，不许留旧行号）。
"""
import io
import json
import os
import re
import sys

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = _args[0] if _args else r"C:/Users/Admin/Desktop/微内核/微内核/微内核"
# --dry：只报告不写盘。反臂要用它 —— 拿推广前那份旧代码跑一遍，符号找不到必须红，
# 但不能把已经指对的 json 改坏（不 dry 就是拿自证当破坏性实验）。
# 旗标必须先认出来再取树根：早先写成 `sys.argv[1]`，把 `--dry` 当根路径，
# 结果是「所有符号都找不到」而退出码 2 —— 看着像代码坏了，其实是命令行读错。
DRY = "--dry" in sys.argv[1:]
TREE = "微内核/微内核/cmd/agentd/"  # 工作区根往下看到的相对路径（与 json 里既有写法一致）
ABS = os.path.join(ROOT, "cmd", "agentd")

# node -> [(文件, 必须出现在同一行/窗口内的正则), ...]
SPEC = {
    "ev.bus": [(TREE + "events.go", r"func \(r \*run\) emit\("),
               (TREE + "events.go", r"func \(b \*eventBus\) Emit\("),
               (TREE + "loop.go", r'r\.emit\(Event\{Kind: "run_started"')],
    "ev.log": [(TREE + "events.go", r"func newEventBus\("),
               (TREE + "events.go", r"func ValidateLog\("),
               (TREE + "events.go", r"func \(b \*eventBus\) Emit\(")],
    "host.hooks": [(TREE + "loop.go", r'r\.emit\(Event\{Kind: "run_started"'),
                   (TREE + "loop.go", r'stepEv\("shot_started"'),
                   (TREE + "loop.go", r'stepEv\("precheck", "refused"'),
                   (TREE + "loop.go", r'stepEv\("precheck", "ok"'),
                   (TREE + "loop.go", r'stepEv\("recorded", "refused"'),
                   (TREE + "loop.go", r'stepEv\("recorded", "ok"'),
                   (TREE + "loop.go", r"r\.emit\(settle\)")],
    "host.eventTests": [(TREE + "events_test.go", r"func TestEventSeqMonotonicWithinEachTurn\("),
                        (TREE + "events_test.go", r"func TestValidateLogArmRejectsDuplicateAndRegress\("),
                        (TREE + "events_test.go", r"func TestEventLogAppendsAcrossRuns\("),
                        (TREE + "events_test.go", r"func TestEmitFailureIsLoudOnStderr\("),
                        (TREE + "events_test.go", r"func TestRefusedEventsCarryTheirWhy\("),
                        (TREE + "events_test.go", r"func TestEventLogPathDerivationAndCollision\(")],
    "host.eventFlags": [(TREE + "main.go", r'eventsOn\s+= flag\.Bool'),
                        (TREE + "main.go", r'eventsPath\s+= flag\.String'),
                        (TREE + "main.go", r"func eventLogPath\("),
                        (TREE + "main.go", r"func printEventBanner\(")],
    "ev.settle": [(TREE + "loop.go", r"func \(r \*run\) settleTurn\("),
                   (TREE + "events.go", r"func ValidateSettlement\("),
                   (TREE + "events.go", r"var stopTokens = ")],
    "ev.identity": [(TREE + "events.go", r"func blockOf\("),
                     (TREE + "events.go", r"run: fmt.Sprintf")],
    "host.stopentry": [(TREE + "loop.go", r"func \(r \*run\) Stop\(")],
    "ev.accept": [(TREE + "events.go", r"func \(r \*run\) acceptedEv\("),
                  (TREE + "events.go", r"func ValidateAcceptsWithin\("),
                  (TREE + "loop.go", r"r\.emit\(r\.acceptedEv\(\)\)")],
}
SPEC["ev.sse"] = [(TREE + "sse.go", r"func formatCursor\("),
                    (TREE + "sse.go", r"func parseCursor\("),
                    (TREE + "sse.go", r"func ValidateReplay\("),
                    (TREE + "sse.go", r"func sseHandler\("),
                    (TREE + "sse.go", r"func serveEvents\("),
                    (TREE + "main.go", r"eventsServe\s+= flag\.Bool")]
SPEC["ev.resumeAxis"] = [(TREE + "loop.go", r"func \(r \*run\) turnNo\("),
                          (TREE + "loop.go", r"r\.turnFloor = shots")]
SPEC["ev.phaseTables"] = [(TREE + "events.go", r"func ValidatePhaseTables\("),
                          (TREE + "events.go", r"func inPhaseTable\(")]
SPEC["ev.checklog"] = [(TREE + "checklog.go", r"func checkLogAgainst\("),
                       (TREE + "main.go", r"checkLog\s+= flag\.String")]
# E5 / E7 / E8 落码后这三件也要尺子印引用（不然「模型说已建、盘上没有」又回来了）
SPEC["ev.watchdog"] = [(TREE + "loop.go", r"func \(r \*run\) startTick\("),
                       (TREE + "events.go", r"func \(b \*eventBus\) idleView\("),
                       (TREE + "main.go", r"tickIdle\s+= flag\.Duration")]
SPEC["ev.ui"] = [(TREE + "web.go", r"const threeLinePage = "),
                 (TREE + "web.go", r"func pageHandler\("),
                 (TREE + "sse.go", r'mux\.Handle\("/", pageHandler\(\)\)')]
SPEC["host.trace"] = [(TREE + "trace.go", r"func \(r \*run\) traceLedger\("),
                      (TREE + "trace.go", r"func \(r \*run\) writeTrace\("),
                      (TREE + "events.go", r"func \(b \*eventBus\) runID\(")]
RANGE = {}  # 原先这条按「区间」推 ev.sse；E4 落地后 ev.sse/ev.checklog 都改由 SPEC 的符号推，区间规则没有使用者了

P = "event-layer.evidence.json"
d = json.load(io.open(P, encoding="utf-8"))
idx = {n["id"]: n for n in d["nodes"] if "id" in n}
missing, changed = [], 0


def line_of(rel, pat):
    # json 里的引用按工作区根写（微内核/微内核/cmd/agentd/…），ROOT 已经是那棵树，
    # 所以把前缀换成 cmd/agentd —— 直接拼会得到三层微内核那种不存在的路径（假红）。
    parts = rel.split("/")
    if rel.startswith(TREE):
        f = os.path.join(ROOT, "cmd", "agentd", parts[-1])
    else:
        f = os.path.join(ROOT, *parts)
    if not os.path.isfile(f):
        return None
    rx = re.compile(pat)
    for i, ln in enumerate(io.open(f, encoding="utf-8").read().splitlines(), 1):
        if rx.search(ln):
            return i
    return None


for nid, pairs in SPEC.items():
    refs = []
    for rel, pat in pairs:
        n = line_of(rel, pat)
        if n is None:
            missing.append("%s: %s" % (nid, pat))
            continue
        refs.append("%s:%d" % (rel, n))
    if refs and idx[nid].get("sourceRefs") != refs:
        changed += 1
    idx[nid]["sourceRefs"] = refs

for nid, (rel, p1, p2) in RANGE.items():
    a, b = line_of(rel, p1), line_of(rel, p2)
    if a is None or b is None:
        missing.append("%s: range %s" % (nid, rel))
        continue
    idx[nid]["sourceRefs"] = ["研究-协同工作-1022.md", "%s:%d-%d" % (rel, a, b)]

if missing:
    print("MISSING（盘上找不到，宁可红不留旧行号，也不写盘）：")
    for m in missing:
        print("  " + m)
    sys.exit(2)
if not DRY:
    io.open(P, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("dry=%s refreshed=%d" % (DRY, changed))
print("nodes refreshed=%d, refs total=%d" %
      (changed, sum(len(v.get("sourceRefs", [])) for k, v in idx.items() if k in SPEC or k in RANGE)))
for nid in list(SPEC) + list(RANGE):
    print("  %s -> %s" % (nid, " | ".join(idx[nid]["sourceRefs"])))

# ---------------- evidence.md 的行号也归这件印 ----------------
# 它是 #117 那笔债的正解：以前表格里的 path:line 是**手抄**的，代码一改就漂
# （本轮漂过两次，每次都要我临时写一遍重推脚本 —— 那就是第二个 owner）。
# 现在：每行用它自己写的记号回盘找行号；--dry 只报漂移并以 3 退出（反臂要用），不 dry 就写回。
DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence.md")
WS = os.path.normpath(os.path.join(ROOT, "..", ".."))
RE_ANCH = re.compile(r"`([A-Za-z0-9_./\\-]+\.(?:go|md|js|json|py))((?::\d+)(?:-\d+)?)?`")
RE_TOK = re.compile(r"`([A-Za-z0-9_.]{3,})`")


def doc_abs(rel):
    cand = os.path.normpath(os.path.join(WS, rel.replace("/", os.sep)))
    if os.path.isfile(cand):
        return cand
    import glob as _g
    g = _g.glob(os.path.join(ABS, os.path.basename(rel))) or \
        _g.glob(os.path.join(WS, "**", os.path.basename(rel)), recursive=True)
    return g[0] if g else None


doc_drift, doc_bad = [], []
if os.path.isfile(DOC):
    doc_lines = io.open(DOC, encoding="utf-8", newline="").read().split("\n")
    cache = {}
    for i, row in enumerate(doc_lines):
        refs = [(m.group(1), m.group(2)) for m in RE_ANCH.finditer(row) if m.group(2)]
        if not refs:
            continue
        toks = [t for t in RE_TOK.findall(row) if not re.search(r"\.(go|md|json|py|js)$", t)]
        if not toks:
            continue
        new = row
        for rel, ln in refs:
            f = doc_abs(rel)
            if not f:
                doc_bad.append("行 %d：%s 不在盘上" % (i + 1, rel))
                continue
            if f not in cache:
                cache[f] = io.open(f, encoding="utf-8", errors="replace").read().split("\n")
            body = cache[f]
            old = int(ln[1:].split("-")[0])
            hit = None
            for t in toks:
                cands = [k + 1 for k, l in enumerate(body) if t in l]
                if cands:
                    hit = min(cands, key=lambda h: abs(h - old))
                    break
            if hit is None:
                doc_bad.append("行 %d：%s 的记号 %s 在盘上找不到" % (i + 1, rel, toks[0]))
                continue
            if hit != old:
                doc_drift.append("行 %d %s:%d -> :%d" % (i + 1, rel, old, hit))
                new = new.replace("`" + rel + ln + "`", "`%s:%d`" % (rel, hit), 1)
        if new != row:
            doc_lines[i] = new
    if doc_bad:
        print("EVIDENCE-DOC 找不到（宁可红，不猜行号、不写盘）：")
        for m in doc_bad:
            print("  " + m)
        sys.exit(2)
    if doc_drift and not DRY:
        io.open(DOC, "w", encoding="utf-8", newline="\n").write("\n".join(doc_lines))
    print("evidence.md 行号：漂移 %d 处%s" % (len(doc_drift), "（--dry 未写盘）" if DRY and doc_drift else ""))
    for m in doc_drift:
        print("  " + m)
    if DRY and doc_drift:
        sys.exit(3)
sys.exit(0)
