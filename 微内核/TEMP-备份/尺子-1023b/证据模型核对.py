#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""证据模型核对：把 event-layer.evidence.json 的每条 sourceRefs、每个边端点、每条状态口径回盘验。

与 锚点核对.py 的分工：那把尺子管 evidence.md 里的 `path:line` 有没有漂；
这把管**机器可读模型**是不是自洽 —— 因为插件契约要求「节点/边有稳定 ID、可 diff、能回到代码」，
而 JSON 一旦手改就会出现：边指向不存在的节点、target 节点被写成 current、sourceRef 拼错路径。
这三种都不会喊，只会让下一个读图的人信错东西。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 证据模型核对.py
退出码：0 全过；3 有问题；4 模型读不到。
臂（每条都必须红，否则本尺子没牙）：
    A1 塞一条盘上不存在的 sourceRef
    A2 塞一条 from 指向不存在节点的边
    A3 把一个 target 节点改标成 current（它没有代码证据）
    A4 把一条「符号可核」的 ref 改成界内错行（M2 路 B 实测：只有存在性检查时这一族无针）
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
MODEL = os.path.join(HERE, "event-layer.evidence.json")
OUT = os.path.join(HERE, "读数-证据模型核对.txt")
RE_REF = re.compile(r"^(?P<path>.+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$")


def ref_ok(ref):
    """返回 (对不对, 说明)。ref 形如 微内核/微内核/cmd/agentd/loop.go:85"""
    m = RE_REF.match(ref)
    if not m:
        return False, "形状不认识"
    p = os.path.normpath(os.path.join(WS, m.group("path").replace("/", os.sep)))
    if not os.path.isfile(p):
        return False, f"文件不在盘上：{m.group('path')}"
    a, b = m.group("a"), m.group("b")
    if not a:
        return True, os.path.basename(p) + "（无行号，只验存在）"
    n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
    hi = int(b or a)
    if hi > n:
        return False, f"{m.group('path')} 只有 {n} 行，引到 {hi}"
    return True, f"{os.path.basename(p)}:{a}{'-' + b if b else ''}（文件 {n} 行内）"



def refresher_spec():
    """从 锚点刷新.py 里把「哪些 ref 是按符号反推的」读出来 —— 用 ast 读，不 import（那件会读 argv）。

    这一层是给 M2 路 B 的 P2-8 还债：`ref_ok` 只验「文件在 + 行界内」，
    它把 ev.accept 三条改成界内错行仍然 rc=0、报表照写「82 条全部回盘可解析」。
    现在把 ref 分成两档：**符号可核**（这件自己回盘反推行号再比）与**仅存在性**，两档分开印。
    """
    import ast
    src = os.path.join(HERE, "锚点刷新.py")
    if not os.path.isfile(src):
        return {}, {}
    tree = ast.parse(io.open(src, encoding="utf-8").read())

    consts = {}

    def lit(node):
        """把 TREE + "x.go" 这种拼接算成字符串；算不出来返回 None（宁可少一档，不猜）。

        上一版漏了 Name 那一支：TREE 存进 dict 却从没被查，于是 SPEC 解出空表、
        「符号可核 0 条」—— A4 那条臂当场把它报成失效（臂在做它该做的事）。
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = lit(node.left), lit(node.right)
            return (a + b) if (a is not None and b is not None) else None
        return None

    spec, rng = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TREE":
            consts["TREE"] = lit(node.value)
    # TREE 在后面才被引用，先扫两遍
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        tgt = node.targets[0]
        name = getattr(tgt, "id", "")
        # 追加式赋值（SPEC["ev.sse"] = [...]）以前看不见 ⇒ 那几件的引用被降成「仅存在性」，
        # 符号档的条数就少报 —— 尺子哑在那儿，臂还不响（A4 抓的是「改错行」，抓不到「根本没进档」）。
        key = None
        if name == "SPEC" and isinstance(node.value, ast.Dict):
            key = None  # 字面量整体：下面按 k.value 收
        elif isinstance(tgt, ast.Subscript) and getattr(tgt.value, "id", "") in ("SPEC", "RANGE"):
            name = tgt.value.id
            key = tgt.slice.value if isinstance(tgt.slice, ast.Constant) else None
        if name == "SPEC" and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                pairs = []
                for elt in v.elts:
                    rel, pat = lit(elt.elts[0]), lit(elt.elts[1])
                    if rel and pat:
                        pairs.append((rel, pat))
                spec[k.value] = pairs
            if key is not None:
                pairs = []
                for elt in node.value.elts:
                    rel, pat = lit(elt.elts[0]), lit(elt.elts[1])
                    if rel and pat:
                        pairs.append((rel, pat))
                if pairs:
                    spec[key] = pairs
        if name == "RANGE" and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                parts = [lit(x) for x in v.elts]
                if all(parts):
                    rng[k.value] = tuple(parts)
        elif name == "RANGE" and key is not None:
            parts = [lit(x) for x in node.value.elts] if isinstance(node.value, ast.Tuple) else []
            if parts and all(parts):
                rng[key] = tuple(parts)
    return spec, rng


def symbol_mismatches(model):
    """返回 (符号可核条数, 不指到行的清单)。改漂一行必须落进第二条里。"""
    spec, rng = refresher_spec()
    if not spec:
        return 0, ["锚点刷新.py 的 SPEC 读不出来 —— 符号档为空"]
    byid = {n["id"]: n for n in model["nodes"] if "id" in n}
    checked, bad = 0, []
    lines = {}
    def file_lines(rel):
        if rel not in lines:
            f = os.path.normpath(os.path.join(WS, rel.replace("/", os.sep)))
            lines[rel] = io.open(f, encoding="utf-8", errors="replace").read().splitlines() if os.path.isfile(f) else []
        return lines[rel]
    import re as _re
    for nid, pairs in spec.items():
        refs = byid.get(nid, {}).get("sourceRefs", [])
        for i, (rel, pat) in enumerate(pairs):
            if i >= len(refs):
                bad.append("%s 第 %d 条 ref 缺失（SPEC 有 %d 条）" % (nid, i + 1, len(pairs)))
                continue
            checked += 1
            want = [n for n, ln in enumerate(file_lines(rel), 1) if _re.search(pat, ln)]
            m = RE_REF.match(refs[i])
            got = int(m.group("a")) if m and m.group("a") else -1
            if want and got not in want:
                bad.append("%s 的 %s 不指到 `%s` 所在行（盘上是 %s）" % (nid, refs[i], pat[:34], want[:3]))
    for nid, (rel, p1, p2) in rng.items():
        refs = byid.get(nid, {}).get("sourceRefs", [])
        if not refs:
            continue
        checked += 1
        a = [n for n, ln in enumerate(file_lines(rel), 1) if _re.search(p1, ln)]
        b = [n for n, ln in enumerate(file_lines(rel), 1) if _re.search(p2, ln)]
        m = RE_REF.match(refs[-1])
        if not (a and b and m and m.group("a") == str(a[0]) and (m.group("b") or m.group("a")) == str(b[0])):
            bad.append("%s 的区间 %s 与盘上 %s 的 [%s..%s] 不符" % (nid, refs[-1], rel, a[:1], b[:1]))
    return checked, bad


def audit(model, extra=None):
    """跑一遍全量检查；extra 可以往 nodes/edges 里临时塞坏件（给臂用）。"""
    nodes = list(model["nodes"])
    edges = list(model["edges"])
    if extra:
        nodes += extra.get("nodes", [])
        edges += extra.get("edges", [])
    ids = [n["id"] for n in nodes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    problems = []
    if dup:
        problems.append("节点 id 重复：" + "、".join(dup))
    idset = set(ids)
    dangling = [e["id"] for e in edges if e["from"] not in idset or e["to"] not in idset]
    for e in edges:
        if e["from"] not in idset or e["to"] not in idset:
            problems.append(f"边 {e['id']} 端点悬空：from={e['from']} to={e['to']}")
    refcount = bad = 0
    badrefs = []
    for n in nodes:
        for r in n.get("sourceRefs", []):
            refcount += 1
            ok, why = ref_ok(r)
            if not ok:
                bad += 1
                badrefs.append(f"节点 {n['id']} 的 {r}：{why}")
    for e in edges:
        for r in e.get("sourceRefs", []):
            refcount += 1
            ok, why = ref_ok(r)
            if not ok:
                bad += 1
                badrefs.append(f"边 {e['id']} 的 {r}：{why}")
    # 状态与置信度口径：current 必须有证据且不得 low/unknown；target 不得 high
    mis = []
    for n in nodes:
        st, cf, refs = n.get("state"), n.get("confidence"), n.get("sourceRefs", [])
        if st == "current" and (not refs or cf in ("low", "unknown")):
            mis.append(f"current 节点 {n['id']} 证据不足（confidence={cf}，refs={len(refs)}）")
        if st == "current" and cf not in ("high", "medium"):
            mis.append(f"current 节点 {n['id']} 置信度不合规：{cf}")
        if st == "target" and cf == "high":
            mis.append(f"target 节点 {n['id']} 不许写 high（它没有代码证据）")
        if st not in ("current", "target"):
            mis.append(f"节点 {n['id']} 状态不在口径内：{st}")
    for e in edges:
        if e.get("state", "current") == "current" and not e.get("sourceRefs"):
            mis.append(f"current 边 {e['id']} 没有 sourceRefs")
    # problems 只装 id 重复那一类，返回时没人读它 —— 那行加法是空写，删掉免得下次又有人以为它在管
    sym_checked, sym_bad = symbol_mismatches({"nodes": nodes, "edges": edges})
    # 上一版把符号档的坏点加进 problems（那变量在返回时根本没用），于是报表印了坏点、rc 仍然 0 ——
    # 这就是我自己最恨的那族「印了但不判」。坏点必须进 mis 才算闸。
    mis_pre = sym_bad
    return {
        "nodes": len(nodes), "edges": len(edges), "refs": refcount, "badrefs": bad,
        "sym_checked": sym_checked, "sym_bad": sym_bad,
        "mis": mis + mis_pre,
        "badref_list": badrefs, "dangling": dangling, "dup": dup, "mis": mis,
    }


def main():
    if not os.path.isfile(MODEL):
        print(f"证据模型核对: 读不到 {MODEL}")
        return 4
    model = json.load(open(MODEL, encoding="utf-8"))
    lines = []
    def w(f, *a): lines.append(f % a if a else f)

    base = audit(model)
    w("证据模型核对 · event-layer.evidence.json（回盘可解析）")
    w("节点 %d ｜ 边 %d ｜ sourceRefs %d ｜ 解析失败 %d ｜ 悬空边 %d ｜ id 重复 %d",
      base["nodes"], base["edges"], base["refs"], base["badrefs"], len(base["dangling"]), len(base["dup"]))
    w("分档：符号可核 %d 条（本件自己回盘反推行号来比） ｜ 仅存在性 %d 条（只验文件在、行界内）",
      base["sym_checked"], base["refs"] - base["sym_checked"])
    for b in base["sym_bad"]:
        w("  [符号对不上] %s", b)
    for b in base["badref_list"]:
        w("  [引用坏] %s", b)
    for m in base["mis"]:
        w("  [口径坏] %s", m)

    cur = sum(1 for n in model["nodes"] if n["state"] == "current")
    tgt = sum(1 for n in model["nodes"] if n["state"] == "target")
    w("状态分布：current %d ｜ target %d（target 允许无代码证据，但必须标 target 且 confidence ≤ low）", cur, tgt)

    # 三条臂：在内存里塞坏件，尺子必须点名（不改盘上的模型件）
    arms = []
    a1 = audit(model, extra={"nodes": [{"id": "arm.badref", "label": "臂", "type": "module", "state": "target",
                                       "confidence": "low", "sourceRefs": ["cmd/agentd/根本不存在.go:1"]}], "edges": []})
    arms.append(("A1 塞一条不存在的 sourceRef", a1["badrefs"] > base["badrefs"]))
    a2 = audit(model, extra={"nodes": [], "edges": [
        {"id": "arm.dangling", "from": "arm.没这个节点", "to": "host.loop", "type": "calls",
         "state": "target", "sourceRefs": ["微内核/微内核/cmd/agentd/loop.go:117"]}]})
    arms.append(("A2 塞一条端点悬空的边", len(a2["dangling"]) > len(base["dangling"])))
    import copy
    m3 = copy.deepcopy(model)
    for n in m3["nodes"]:
        if n["state"] == "target":
            n["state"] = "current"
            break
    a3 = audit(m3)
    arms.append(("A3 把一个 target 节点改标成 current", len(a3["mis"]) > len(base["mis"])))
    import copy as _c
    m4 = _c.deepcopy(model)
    moved = False
    for n in m4["nodes"]:
        if n["id"] in refresher_spec()[0]:
            for r in n["sourceRefs"]:
                mm = RE_REF.match(r)
                if mm and mm.group("a") and (mm.group("b") or mm.group("a")):
                    n["sourceRefs"] = [("%s:%d" % (mm.group("path"), 2)) if x == r else x for x in n["sourceRefs"]]
                    moved = True
                    break
        if moved:
            break
    a4 = audit(m4) if moved else None
    arms.append(("A4 把一条符号档 ref 改成界内错行（路 B 的 P2-8）",
                 bool(a4) and len(a4["sym_bad"]) > len(base["sym_bad"])))
    if not moved:
        w("臂：A4 没处下手（SPEC 里没有任何带行号的 ref）—— 不算有效")
    w("")
    dead = 0
    for name, ok in arms:
        w("臂：%s → %s", name, "有效（抓到了）" if ok else "失效（这条检查没在管）")
        dead += 0 if ok else 1
    w("")
    if dead:
        w("结论：%d 条臂没红 —— 上面的通过数不算核对过。", dead)
        rc = 3
    elif base["badrefs"] or base["dangling"] or base["dup"] or base["mis"]:
        w("结论：模型有坏件，按上面点名的行改模型（别改尺子迁就它）。")
        rc = 3
    else:
        w("结论：sourceRefs %d 条回盘（符号可核 %d 条全指到行，仅存在性 %d 条未验符号），端点闭合，状态口径合规，四臂能红。"
          % (base["refs"], base["sym_checked"], base["refs"] - base["sym_checked"]))
        rc = 0
    out = "\n".join(lines) + "\n"
    open(OUT, "w", encoding="utf-8").write(out)
    sys.stdout.buffer.write(out.encode("utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
