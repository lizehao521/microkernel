#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点核对：把 evidence.md 表里每一个 `path:line` 回到盘上验一遍。

为什么要它：evidence.md 是「当前态」那张图的凭据面，它写的是行号。行号会随代码漂，
漂了不会自己喊 —— 下一个读它的人只能选择信我。所以把「引用还对不对」做成可复跑的一把尺子：
  1) 文件在不在；
  2) 行号有没有越界；
  3) 那一行（含上下各 2 行）里能不能找到该行声称的符号（从「节点」列里抽 `...` 反引号词）；
  4) 命中数自己印，不手抄。

它还会**自己注一发假锚点**（臂）：把一条已命中的行号改成 99999，尺子必须报未命中。
臂不红就是恒绿装饰，本件的结论也就不能写「核过」。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 锚点核对.py
退出码：0 全命中；3 有未命中/缺文件；4 evidence.md 读不到或表里一条锚点都没解析出来。
产物用 UTF-8 句柄写，print 里不放 ✓ / ⇒（GBK 控制台会崩，崩掉的是退出码契约）。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)                      # C:\Users\Admin\Desktop\微内核
KERNEL = os.path.join(WS, "微内核", "微内核")    # 内核 Go 树
EVID = os.path.join(HERE, "evidence.md")
OUT = os.path.join(HERE, "读数-锚点核对.txt")

# 锚点里裸文件名按这个顺序解析（打印解析到的全路径，可审计，不靠搜索顺序猜）
SEARCH_DIRS = [os.path.join(KERNEL, "cmd", "agentd"), KERNEL, WS, HERE]

RE_ANCHOR = re.compile(r"`([A-Za-z0-9_./\\-]+\.(?:go|md|js|json|py))((?::\d+)(?:-\d+)?)?`")
RE_TOKEN = re.compile(r"`([A-Za-z0-9_.]{3,})`")


def resolve(rel):
    rel = rel.replace("\\", "/")
    base = os.path.basename(rel)
    cands = []
    if rel.startswith("cmd/agentd/") or rel.startswith("报告/") or rel.startswith("README"):
        cands.append(os.path.join(KERNEL, rel.replace("/", os.sep)))
    for d in SEARCH_DIRS:
        cands.append(os.path.join(d, base))
    seen = set()
    for c in cands:
        c = os.path.normpath(c)
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return None


def rows_with_anchors(text):
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        anchors = RE_ANCHOR.findall(line)
        if anchors:
            out.append((ln, cells, anchors))
    return out


def token_cands(t):
    """`r.say` / `run.loop()` / `kernel.check_call` 都要能对上盘上那一行：
    整串算一个候选，末段（去括号）再算一个候选。只比整串会把接收者写法判成未命中——那是假红。"""
    out = {t}
    tail = t.rstrip("()").split(".")[-1]
    if tail:
        out.add(tail)
    return out


def check_row(rowline, anchors):
    """返回 (verdict, detail)。verdict in {hit, miss, nofile, range}
    符号从**整行**抽（这个表的符号写在「出处」列，不在「节点」列 —— 只扫第一列会让 13/14 行
    退化成存在性检查，行号写错但仍在文件内时抓不到，那是没牙的尺子）。"""
    raw = [t for t in RE_TOKEN.findall(rowline) if not t.endswith((".go", ".md", ".json", ".py"))]
    tokens = sorted({c for t in raw for c in token_cands(t)})
    resolved = []
    for rel, rng in anchors:
        p = resolve(rel)
        if not p:
            return "nofile", f"文件没找到：{rel}"
        if not rng:
            resolved.append((p, None))
            continue
        nums = [int(x) for x in re.findall(r"\d+", rng)]
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        start, end = nums[0], (nums[1] if len(nums) > 1 else nums[0])
        if start > len(lines):
            return "range", f"{os.path.basename(p)} 只有 {len(lines)} 行，却引到 {start}"
        window = "\n".join(lines[max(0, start - 3):min(len(lines), end + 2)])
        resolved.append((p, window))
    if not tokens:
        return "hit", "；".join(os.path.normpath(p) for p, _ in resolved) + " ｜（该行没给可核符号，只验存在与行界）"
    for p, window in resolved:
        if window is None:
            continue
        if any(t in window for t in tokens):
            return "hit", f"{os.path.normpath(p)} 内找到 {"、".join(tokens)}"
    return "miss", f"{os.path.basename(resolved[0][0])} 那一行的上下 2 行里找不到 {"、".join(tokens)}"


def main():
    if not os.path.isfile(EVID):
        print(f"锚点核对: 读不到 {EVID}")
        return 4
    text = open(EVID, encoding="utf-8").read()
    rows = rows_with_anchors(text)
    buf = io.StringIO()
    def w(f, *a):
        s = f % a if a else f
        buf.write(s + "\n")

    w("锚点核对 · evidence.md 逐条回盘验证（本件自印分母，不手抄）")
    w("解析到带锚点的表行：%d" % len(rows))
    if not rows:
        print(buf.getvalue())
        return 4
    tally = {"hit": 0, "miss": 0, "nofile": 0, "range": 0}
    hit_lines = []
    sym_lines = []   # 只收「这一行确实给了可核符号」的命中行，臂二必须从这里挑
    lines = text.splitlines()
    for ln, cells, anchors in rows:
        verdict, detail = check_row(lines[ln - 1], anchors)
        tally[verdict] += 1
        if verdict == "hit":
            hit_lines.append((ln, cells[0]))
            if "仅存在性检查" not in detail and "没给可核符号" not in detail:
                sym_lines.append((ln, cells[0]))
        w("[%3s] 表行 %d ｜ %s ｜ %s", {"hit": "命中", "miss": "未命中", "nofile": "缺文件", "range": "行越界"}[verdict], ln, cells[0], detail)

    # 臂一（行界）：把第一条命中的行号改成 99999，尺子必须报未命中/行越界
    # 臂二（符号）：把同一行的符号换成盘上不存在的标识符，行号仍合法 —— 只有臂二能证明
    #        符号匹配那段逻辑真的在管，而不是靠行号越界蒙红。
    arm_ok = None
    arm_sym = None
    if hit_lines:
        ln, label = hit_lines[0]
        line = text.splitlines()[ln - 1]
        tampered = re.sub(r":\d+", ":99999", line, count=1)
        anchors2 = RE_ANCHOR.findall(tampered)
        v2, d2 = check_row(tampered, anchors2)
        arm_ok = v2 in ("miss", "range")
        w("")
        w("臂一（把「%s」的行号改成 99999）：读数=%s ｜ %s ｜ 臂%s" % (label, v2, d2, "有效" if arm_ok else "失效 —— 本尺子没牙，上面所有「命中」都不算数"))

        # 臂二只能挑「这一行真的给了可核符号」的命中行：挑一行没符号的，
        # 换掉符号等于什么都没换，报出来的「失效」是工具的谎，不是代码的谎。
        if sym_lines:
            ln3, label3 = sym_lines[0]
            t3 = re.sub(r"`([A-Za-z_][A-Za-z0-9_.]{2,})`", "`zzynothere_sym`", lines[ln3 - 1], count=1)
            v3, d3 = check_row(t3, RE_ANCHOR.findall(t3))
            arm_sym = v3 == "miss"
            w("臂二（把「%s」那一行的符号换成 ASCII 假标识符，行号不动）：读数=%s ｜ %s ｜ 臂%s",
              label3, v3, d3, "有效" if arm_sym else "失效 —— 符号匹配没在管，命中可能只是「文件在+行没越界」")
        else:
            w("臂二：表里没有一行给出可核符号 ⇒ 这一臂**无从下手**（不算有效也不算失效），先给 evidence.md 补符号")
            arm_sym = None

    only_exist = sum(1 for ln, cells, a in rows if check_row(text.splitlines()[ln - 1], a)[1].endswith("仅存在性检查"))
    w("")
    w("覆盖面自印：符号可核 %d 行 ｜ 仅存在性 %d 行 ｜ 共 %d 行" % (len(rows) - only_exist, only_exist, len(rows)))
    w("合计：命中 %d ｜ 未命中 %d ｜ 缺文件 %d ｜ 行越界 %d ｜ 共 %d 行" % (
        tally["hit"], tally["miss"], tally["nofile"], tally["range"], len(rows)))
    if arm_ok is False or arm_sym is not True:
        w("结论：不写「已核对」—— 臂没红或无从下手（臂一=%s，臂二=%s），命中数不算数。" % (
            {"True": "有效", "False": "失效"}.get(str(arm_ok), "无从下手"),
            {"True": "有效", "False": "失效"}.get(str(arm_sym), "无从下手")))
        rc = 3
    elif tally["miss"] or tally["nofile"] or tally["range"]:
        w("结论：有锚点漂了，按上面点名那几行改 evidence.md（别改尺子迁就它，先确认是代码漂还是引用写错）。")
        rc = 3
    else:
        w("结论：evidence.md 的 %d 条锚点全部回盘命中，且臂能红。" % len(rows))
        rc = 0
    out = buf.getvalue()
    open(OUT, "w", encoding="utf-8").write(out)
    sys.stdout.buffer.write(out.encode("utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
