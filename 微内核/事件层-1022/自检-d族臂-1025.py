# -*- coding: utf-8 -*-
"""d 族臂的形状与锚点自检（读落盘的 kprobe.py，不读我要插的那段串）。

为什么单独一件：ast 过了不等于 edits 是 (frm,to) 二元组 ——
`('A' 'B')` 在 python 里是一个串（隐式拼接），那种臂永远命中 0 次，
kprobe 只会报 ANCHOR-BAD，而一整轮 go test 已经白跑了。

跑法：python 自检-d族臂-1025.py <树根> <kprobe.py 路径>
"""
import ast
import io
import os
import sys

WANT = ["d1-三行页没声明viewport", "d2-轨迹页没声明viewport", "d3-轨迹页没有断点",
        "d4-三行页没有断点", "d5-三行页标签不配平（配平那一半的牙）",
        "d6-样式段少一个闭括号"]
PIN = "TestEveryServedPageDeclaresViewportAndBreakpoint"


def say(s):
    sys.stdout.write((s + "\n").encode("ascii", "backslashreplace").decode("ascii"))


def main():
    src, kp = sys.argv[1], sys.argv[2]
    text = io.open(kp, encoding="utf-8", newline="").read()
    # 用 ast 把 MUT 那段**字面量**抠出来，不 exec 文件头部：
    # exec 会把 kprobe 自己的模块级代码跑一遍（它按 sys.argv 取参数），
    # 于是「自检」先撞上 IndexError —— 报的是别人的账。
    tree = ast.parse(text)
    mut = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "MUT" for t in node.targets):
            try:
                mut = ast.literal_eval(node.value)
            except Exception as e:
                say("SHAPE-BAD MUT 不是纯字面量，抠不出来：%s" % e)
                return 2
    if mut is None:
        say("SHAPE-BAD 表里没有 MUT 这个赋值")
        return 2
    d = [e for e in mut if str(e[0]).startswith("d")]
    say("表自印：MUT=%d ｜ d 族=%d" % (len(mut), len(d)))
    cache = {}
    bad = []
    for e in d:
        name, fname, edits, wants = e[0], e[1], e[2], e[3]
        if wants != [PIN]:
            bad.append("%s 点名 %r（该只有那一根针）" % (name, wants))
        if not isinstance(edits, list) or len(edits) != 1:
            bad.append("%s edits 不是 1 条（现 %r）⇒ 不是叶子" % (name, edits))
            continue
        for p in edits:
            if not isinstance(p, (tuple, list)) or len(p) != 2:
                bad.append("%s 的一条臂不是二元组：%r" % (name, p))
                continue
            frm, to = p
            if not frm or not to or frm == to:
                bad.append("%s 的臂空串或自己等于自己" % name)
                continue
            rel = fname.replace("/", os.sep)
            if rel not in cache:
                cache[rel] = io.open(os.path.join(src, rel), encoding="utf-8",
                                     newline="").read()
            n = cache[rel].count(frm)
            if n != 1:
                bad.append("%s 的锚点在 %s 命中 %d 次（该是 1）" % (name, fname, n))
                continue
            after = cache[rel].replace(frm, to, 1)
            if after == cache[rel]:
                bad.append("%s 摘了等于没摘" % name)
                continue
            lost = len(cache[rel]) - len(after)
            say("   %-30s ｜ 摘 %d 字（%s）｜ 行数 %d→%d"
                % (name, lost, fname, cache[rel].count("\n"), after.count("\n")))
    missing = [x for x in WANT if x not in [e[0] for e in d]]
    extra = [e[0] for e in d if e[0] not in WANT]
    if missing:
        bad.append("名单里缺 %r" % missing)
    if extra:
        bad.append("表里多出 %r（本趟没打算加）" % extra)
    for b in bad:
        say("SHAPE-BAD %s" % b)
    say("结论：%s（d 族 %d 根，形状/锚点/唯一性 %s）"
        % ("OK" if not bad else "不对", len(d), "全过" if not bad else "%d 处" % len(bad)))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
