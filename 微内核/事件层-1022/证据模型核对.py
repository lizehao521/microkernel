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
    A4b 同一条坏点必须进「判 rc」的清单（10-23 发现：返回字典里 "mis" 写了两个键，
        后者覆盖前者 ⇒ 符号档坏点只印不判，报表挂着「[符号对不上]」而 rc 照样 0）
    A5 改一条只由追加式赋值（SPEC["x"] = […]）给出的 ref（10-23 发现：上一版 refresher_spec
        只认 `SPEC = {…}` 字面量，那 7 槽被整体降成「仅存在性」，符号档少报 21 条）
这两条病不是猜的，是 尺子自证-旧病复现-1023.py 把旧代码注回内存副本后各点一条臂红出来的。
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
    shape = {"literal_keys": [], "appended_keys": [], "unparsed": []}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TREE":
            consts["TREE"] = lit(node.value)

    def slot(node):
        """这条赋值是在给 SPEC/RANGE 的哪个槽位写东西？给不出就 None。

        上一版只认 `SPEC = {…}` 那种字面量，于是 `SPEC["ev.sse"] = […]`（值是 List 不是 Dict）
        全被丢掉：E4/E5/E7/E8 那几件明明有带行号的引用，却被降成「仅存在性」，
        符号档少报 21 条而 rc 仍然 0 —— A4 只测「已进档的 ref 改错行」，测不到「根本没进档」。
        """
        tgt = node.targets[0]
        if isinstance(tgt, ast.Subscript):
            base = getattr(tgt.value, "id", "")
            if base in ("SPEC", "RANGE") and isinstance(tgt.slice, ast.Constant):
                return base, tgt.slice.value
            return None
        name = getattr(tgt, "id", "")
        if name in ("SPEC", "RANGE"):
            return name, None
        return None

    def entries(name, key, value):
        """把两种形状摊平成一串 (槽位, 值节点)：字面量按 key 摊，追加就一条。"""
        if key is not None:
            if isinstance(value, (ast.List, ast.Tuple)):
                return [(key, value)]
            shape["unparsed"].append("%s[%r] 的值不是列表" % (name, key))
            return []
        if isinstance(value, ast.Dict):
            got, miss = [], []
            for k, v in zip(value.keys, value.values):
                if isinstance(k, ast.Constant):
                    got.append((k.value, v))
                else:
                    miss.append(k)
            if miss:
                shape["unparsed"].append("%s 字面量里 %d 个键不是常量" % (name, len(miss)))
            return got
        shape["unparsed"].append("%s = 的值不是字典" % name)
        return []

    # TREE 在后面才被引用，先扫两遍
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        st = slot(node)
        if st is None:
            continue
        name, key = st
        for k, v in entries(name, key, node.value):
            if name == "SPEC":
                pairs = []
                for elt in getattr(v, "elts", []):
                    try:
                        rel, pat = lit(elt.elts[0]), lit(elt.elts[1])
                    except Exception:
                        rel = pat = None
                    if rel and pat:
                        pairs.append((rel, pat))
                if not pairs:
                    shape["unparsed"].append("SPEC[%r] 一条符号也没解出来" % (k,))
                spec[k] = pairs
                shape["literal_keys" if key is None else "appended_keys"].append(k)
            else:
                parts = [lit(x) for x in getattr(v, "elts", [])]
                if parts and all(parts):
                    rng[k] = tuple(parts)
    return spec, rng, shape


def symbol_mismatches(model):
    """返回 (符号可核条数, 不指到行的清单)。改漂一条必须落进第二条里。"""
    spec, rng, _ = refresher_spec()
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
    judged = mis + mis_pre
    return {
        "nodes": len(nodes), "edges": len(edges), "refs": refcount, "badrefs": bad,
        "sym_checked": sym_checked, "sym_bad": sym_bad,
        # 上一版这里写了两个 "mis" 键：`"mis": mis` 在后面把 `"mis": mis + mis_pre` 覆盖了。
        # 后果是符号档的坏点只印不判 —— 报表里挂着「[符号对不上]」，rc 照样 0。
        # 现在只留一个键，且 A4 臂判的就是这个键，谁再把它拆回两个就当场红。
        "mis": judged,
        "badref_list": badrefs, "dangling": dangling, "dup": dup,
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

    # 臂：在内存里塞坏件，尺子必须点名（不改盘上的模型件）。道数由 arms 自己数，别在文案里写死。
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

    def move_ref(mod, ids):
        """把 ids 里第一件、第一条形如 path:a-b 的符号档 ref 改成同一文件的 :2 —— 越出符号所在行就算坏。"""
        spec, _, _ = refresher_spec()
        want = [n for n in mod["nodes"] if n.get("id") in ids]
        for n in want:
            for r in n.get("sourceRefs", []):
                mm = RE_REF.match(r)
                if mm and mm.group("a") and (mm.group("b") or mm.group("a")):
                    n["sourceRefs"] = [("%s:2" % mm.group("path")) if x == r else x for x in n["sourceRefs"]]
                    return n["id"], r
        return None, None

    spec_ids, _, shp = refresher_spec()
    lit_keys, app_keys = set(shp["literal_keys"]), set(shp["appended_keys"])
    w("符号档形状：SPEC 槽 %d（字面量 %d ＋ 追加 %d，其中只有追加给的 %d）｜ 解不出来的 %d",
      len(spec_ids), len(lit_keys), len(app_keys), len(app_keys - lit_keys), len(shp["unparsed"]))
    for u in shp["unparsed"]:
        w("  [符号档漏读] %s", u)

    m4 = _c.deepcopy(model)
    id4, from4 = move_ref(m4, spec_ids)
    a4 = audit(m4) if id4 else None
    arms.append(("A4 把一条符号档 ref 改成界内错行（路 B 的 P2-8）",
                 bool(a4) and len(a4["sym_bad"]) > len(base["sym_bad"])))
    if id4:
        # 只让 sym_bad 变大不算闸：判 rc 的是 mis。上一版 mis 被重复键覆盖，坏点只印不判。
        arms.append(("A4b 同一条坏点必须进「判 rc」那份清单（不是只印出来）",
                     len(a4["mis"]) > len(base["mis"])))
    else:
        w("臂：A4 没处下手（SPEC 里没有任何带行号的 ref）—— 不算有效")

    m5 = _c.deepcopy(model)
    id5, from5 = move_ref(m5, app_keys - lit_keys)
    arms.append(("A5 改一条「追加式 SPEC（SPEC[\"x\"] = […]）」推出的 ref（尺子上一版根本读不到这类形状）",
                 bool(id5) and len(audit(m5)["sym_bad"]) > len(base["sym_bad"])))
    if not id5:
        w("臂：A5 没处下手（%d 个只由追加给出的槽里，没有一个落到带行号的 ref 上）—— 不算有效",
          len(app_keys - lit_keys))
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
        # 「四臂能红」是写死的道数：臂加到 6 条它就会说谎。道数由上面的清单自己数。
        w("结论：sourceRefs %d 条回盘（符号可核 %d 条全指到行，仅存在性 %d 条未验符号），端点闭合，状态口径合规，%d 臂能红。"
          % (base["refs"], base["sym_checked"], base["refs"] - base["sym_checked"], len(arms)))
        rc = 0
    out = "\n".join(lines) + "\n"
    open(OUT, "w", encoding="utf-8").write(out)
    sys.stdout.buffer.write(out.encode("utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
