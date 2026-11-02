#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""臂读数空档自证（一条命令，不碰真树、不跑 go）。

被检的是合取件 `体检-全闸-1023.py` 里 `arm_freshness()` 那一行判据。它原来只看 mtime，
所以「0 行的臂读数 + 最新的 mtime」会被报成 FRESH，整件结论仍是 ALL-GATES-GREEN ——
这不是假想：`臂检-全部族.py` 一开跑就用 "w" 截断 `读数/臂检-全部族.jsonl`，
中途被打断留下的正是这样一份文件（10-23 现场抓到过一次 0 字节）。

四形各喂两遍：
  修后件（现盘上的 `体检-全闸-1023.py`）⇒ 空档/坏档必须红，新鲜全绿必须绿，比树旧必须只 WARN。
  修前件（`TEMP-备份/文档-1023/体检-改前2-1023.py`）⇒ 同一份编造读数必须全报成「不红」，
     这一头的用处是证明这条牙是新长的，不是本来就有。

读数里假臂文件与假树都建在 %TEMP% 的独立目录；真 `读数/` 与 `cmd/agentd` 全程只读，不碰。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂读数空档自证-1023.py
退出码：0 四形判定与预期全对；3 任一条不过（尺子没牙也算不过）。
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "体检-全闸-1023.py")
OLD = os.path.join(r"C:/Users/Admin/Desktop/微内核", "TEMP-备份", "文档-1023", "体检-改前2-1023.py")
OUT_TXT = os.path.join(HERE, "读数", "臂读数空档自证-1023.txt")
OUT_JSON = os.path.join(HERE, "读数", "臂读数空档自证-1023.json")
RED = ("MISSING", "EMPTY", "BAD")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mk_fake_tree(work):
    tree = os.path.join(work, "tree")
    d = os.path.join(tree, "cmd", "agentd")
    os.makedirs(d)
    io.open(os.path.join(d, "a.go"), "w", encoding="utf-8", newline="\n").write("package agentd\n")
    return tree


def rows(n_bit, extra=None):
    out = []
    for i in range(n_bit):
        out.append(json.dumps({"arm": "T%d" % i, "verdict": "BIT"}))
    for v in (extra or []):
        out.append(json.dumps({"arm": "X", "verdict": v}))
    return "\n".join(out) + ("\n" if out else "")


def probe(mod, tree, content, age_seconds=0):
    """把一份编造读数喂给 mod，返回它自报的 state（修前件只有 bool，翻成同名的态）。
    content=None ⇒ 读数根本不在盘上（MISSING 那一形）。"""
    jsonl = os.path.join(tree, "读数.jsonl")
    if content is None:
        if os.path.isfile(jsonl):
            os.remove(jsonl)
    else:
        io.open(jsonl, "w", encoding="utf-8", newline="\n").write(content)
        if age_seconds:
            t = os.path.getmtime(os.path.join(tree, "cmd", "agentd", "a.go")) - age_seconds
            os.utime(jsonl, (t, t))
    mod.ARMS = jsonl
    mod.SRC = tree
    r = mod.arm_freshness()
    if isinstance(r[0], bool):          # 修前件：(fresh, info, n)
        return ("FRESH" if r[0] else "STALE"), r[1], r[2]
    return r[0], r[1], r[2]


def main():
    for p, what in ((LIVE, "被检件"), (OLD, "修前对照原件")):
        if not os.path.isfile(p):
            sys.stderr.write("%s missing: %s\n" % (what, p))
            return 4
    work = tempfile.mkdtemp(prefix="armempty-")
    try:
        tree = mk_fake_tree(work)
        live = load(LIVE, "live_tijian")
        old = load(OLD, "old_tijian")
        cases = [
            ("empty-fresh", rows(0), 0, "EMPTY", True),
            ("blind-row", rows(2, ["BLIND"]), 0, "BAD", True),
            ("not-wired-row", rows(2, ["NOT-WIRED"]), 0, "BAD", True),
            ("all-bit-fresh", rows(2), 0, "FRESH", False),
            ("all-bit-stale", rows(2), 900, "STALE", False),
            ("no-file", None, 0, "MISSING", True),
        ]
        lines, fails = [], []
        for name, content, age, expect, should_red in cases:
            st, info, n = probe(live, tree, content, age)
            st_old, info_old, n_old = probe(old, tree, content, age)
            ok_state = (st == expect)
            # 修前件必须对每一形都「报不出来」：既说 FRESH/STALE，也够不到红档名。
            ok_old = (st_old not in RED) and (("EMPTY" not in info_old) and ("点名" not in info_old))
            # 三态不许塌：红档要真能把合取件推向 rc=3，绿/旧档不许被算进 bad。
            counted_red = st in RED
            ok_red = (counted_red == should_red)
            mark = "PASS" if (ok_state and ok_old and ok_red) else "FAIL"
            lines.append("%s %-15s live=%-6s old=%-6s rows=%d red=%s | %s" % (
                mark, name, st, st_old, n, "Y" if counted_red else "n", info[:150]))
            if mark == "FAIL":
                fails.append(name)
        bad = len(fails)
        head = ("# 臂读数空档自证（臂读数空档自证-1023.py 现跑，勿手抄）\n\n"
                "- 被检件：%s\n- 修前对照：%s\n- 形 %d 个（假树与假读数全在 %s，真读数没被碰）\n\n"
                % (LIVE, OLD, len(cases), work))
        io.open(OUT_TXT, "w", encoding="utf-8", newline="\n").write(
            head + "\n".join(lines) + "\n\n结论：%d 条自证不过。%s\n" % (
                bad, "空读数与坏档现在都能把合取件逼红，而同一份读数喂修前件一条都报不出来 ⇒ 这条牙是新长的。"
                if bad == 0 else "不过的是：" + ",".join(fails)))
        io.open(OUT_JSON, "w", encoding="utf-8", newline="\n").write(json.dumps({
            "tool": "臂读数空档自证-1023.py", "cases": len(cases), "fails": fails,
            "rc": 0 if bad == 0 else 3}, ensure_ascii=False) + "\n")
        for i, l in enumerate(lines):
            sys.stdout.write("CHECK %d/%d %s\n" % (i + 1, len(cases),
                             l.encode("ascii", "backslashreplace").decode("ascii")))
        sys.stdout.write("FAIL %d\n" % bad)
        sys.stdout.write("readings: %s\n" % OUT_TXT.encode("ascii", "backslashreplace").decode("ascii"))
        return 0 if bad == 0 else 3
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
