#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""话术闸：扫研究报告/市场报告里的四类越界话术 + 一条分级配对判据。

来历：2026-10-22 我第一版用 120 字窗口找「[High] 附近有没有凭据词」，报了 3 处假红 ——
`[High]` 在句首、凭据（L40/L41/L42 原文）落在 200 字外。按现场规矩，红了先怀疑判据，
不改成品的样子迁就它。所以这一版把窗口换成**段落配对**（空行分段），并给每条判据配臂。

五类判据：
  1 合规声称      ：「符合/遵从/满足/compliant」+ EU AI Act / NIST / ISO / SOC 出现在同一段
  2 夸大词        ：显著 / 大幅 / 必然 / 一定 / 彻底解决 / 行业标配 / 大幅降低
  3 惯例冒充      ：业界都 / 标准都 / 行业普遍要求 / 各家都 / 按惯例必须
  4 计划冒充实现  ：已实现 / 已落地 / 已完成开发 / 上线了 / 已支持
  5 分级配对      ：每个 [High] 所在段落必须含凭据词（核｜原文｜实跑｜RC=0｜官网｜定价页｜报告-验收｜SHA｜规范）

用法（工作目录 研究-1022）：
    C:/Users/Admin/sdk/py314/python.exe 话术闸.py 文件.md [另一个.md ...]
不给参数时扫本目录的 DEEP_RESEARCH_*.md。
退出码：0 干净；3 命中；4 文件读不到或一段都没解析出来。
臂（五条，每条都必须红，否则本闸没牙）：每类各注入一句坏话术到内存副本。
"""
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

RULES = [
    # 「符合 X」只有在 X 是具名框架时才是危险话术；而且必须**相邻**（16 字之内）。
    # 教训：编号列表项之间没有空行，整列表会被当成一段，于是「来自符合 RFC 6962 日志的 SCT」
    # 会和另一条里的「NIST」凑成一句假合规声称 ⇒ 段落级共现不能用，改成行级 + 相邻。
    ("合规声称", [r"(符合|遵从|满足|compliant\w*)[^。；\n]{0,16}(EU\s*AI\s*Act|AI Act|NIST|ISO\s*/?\s*IEC\s*42001|ISO\s*42001|SOC\s*2)"]),
    ("夸大词", [r"(显著|大幅|必然|一定|彻底解决|行业标配|完美)"]),
    ("惯例冒充", [r"(业界都|标准都|行业普遍要求|各家都|按惯例必须|所有主流实现都)"]),
    ("计划冒充实现", [r"(已实现|已落地|已完成开发|上线了|已支持)"]),
]
EVID = r"(核（|已读|原文|实跑|RC=0|官网|定价页|报告-验收|SHA|规范原文|本件自印|脚本数出来|可复跑)"
BAD_SAMPLES = {
    "合规声称": "本件符合 EU AI Act 第 12 条的记录义务。",
    "夸大词": "接入后核验成本显著下降。",
    "惯例冒充": "受理回执是业界都有的做法，标准都要求它。",
    "计划冒充实现": "事件层已实现并上线了结算载荷。",
}


def units(text):
    """行级单元：每条列表项/表格行/标题各自成单元（段落级会把多条并列成一条，制造假红）。"""
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        if line.strip():
            out.append((ln, line))
    return out


NEG = re.compile(r"(不得|禁止|不许|不要|别|不可|不应|勿)")


def scan(text):
    us = units(text)
    hits = []
    for ln, line in us:
        for name, pats in RULES:
            got = [re.search(x, line) for x in pats]
            if all(got):
                m0 = got[0]
                # 否定语境豁免对**四类短语判据**统一生效：「不得说『业界都要求…』」这类引用禁句的行
                # 是红线本身。上一版只豁免了「合规声称」，结果附录 D 因为抄了禁句被自己的闸抓了两次。
                if NEG.search(line[: m0.start()]):
                    continue
                toks = " ｜ ".join(m.group(0) for m in got if m)
                hits.append((name, ln, "%s ｜ 行：%s" % (toks, line.strip()[:100])))
        if re.search(r"\*\*\[High\]\*\*", line) and not re.search(EVID, line):
            hits.append(("分级无凭据", ln, line.strip()[:120]))
    return us, hits


def main(argv):
    targets = argv[1:] or sorted(glob.glob(os.path.join(HERE, "DEEP_RESEARCH_*.md")))
    if not targets:
        print("话术闸: 没有可扫的文件")
        return 4
    out = io.StringIO()
    def w(f, *a): out.write((f % a if a else f) + "\n")

    total_hits = 0
    for t in targets:
        if not os.path.isfile(t):
            w("读不到：%s", t)
            return 4
        text = open(t, encoding="utf-8").read()
        us, hits = scan(text)
        if not us:
            print(out.getvalue())
            return 4
        w("话术闸 · %s ｜ 行单元 %d ｜ 评级标签 %d ｜ 命中 %d",
          os.path.basename(t), len(us), text.count("**[High]**"), len(hits))
        for name, ln, ctx in hits:
            w("  [%s] 行 %d：%s", name, ln, ctx)
        total_hits += len(hits)

    # 臂：每类注入一句，闸必须点名
    w("")
    dead = []
    for name, sentence in BAD_SAMPLES.items():
        probe = "这是一段用来验闸的正文。\n\n" + sentence
        _, hh = scan(probe)
        caught = any(h[0] == name for h in hh)
        w("臂（注入一句「%s」的话术）：%s", name, "抓到" if caught else "**没抓到 —— 这条判据没牙**")
        if not caught:
            dead.append(name)
    probe2 = "这是一段正文。\n\n**[High]** 这条结论什么凭据都没写。"
    _, hh2 = scan(probe2)
    caught2 = any(h[0] == "分级无凭据" for h in hh2)
    w("臂（注入一句没有凭据词的 `**[High]**`）：%s", "抓到" if caught2 else "**没抓到 —— 分级配对没牙**")
    if not caught2:
        dead.append("分级无凭据")
    # 反臂的反臂：正文里**提及**这个词（不加粗、当术语用）不该被判红，否则标题都写不了
    probe3 = "这是一段正文。\n\n## 说明\n每条 `**评级**` 的写法是 [High]、[Medium] 两种。"
    _, hh3 = scan(probe3)
    false_red = any(h[0] == "分级无凭据" for h in hh3)
    w("过度匹配检查（在标题里提及 [High] 这个术语）：%s", "不误伤" if not false_red else "**误伤 —— 这条判据会把术语提及当评级**")
    # 否定语境豁免的对照两臂：红线句不该响，越界句必须响（对四类短语判据都要成对验）
    neg_probe = "对外红线：\n\n不得说「符合 EU AI Act 第 12 条」。\n不得说「业界都要求受理回执」。\n不得说「用了更准 / 显著降低风险」。"
    _, hneg = scan(neg_probe)
    neg_ok = not hneg
    pos_ok = True
    for s in ("本件符合 EU AI Act 第 12 条。", "受理回执是业界都有的做法。", "接入后核验成本显著下降。"):
        if not scan(s + "\n")[1]:
            pos_ok = False
    w("豁免对照（三句引用禁句都不响 / 三句真越界都要响）：%s ｜ %s",
      "对" if neg_ok else "**错：红线句被自己抓住了**", "对" if pos_ok else "**错：豁免把真越界也放过了**")
    if not neg_ok or not pos_ok:
        dead.append("短语判据豁免口径")

    w("")
    if dead:
        w("结论：%d 条判据的臂没红（%s）—— 上面「命中 0」不作数。" % (len(dead), "、".join(dead)))
        rc = 3
    elif total_hits:
        w("结论：%d 处越界话术，按上面点名段落改文（这是话术闸，不判对错，只判有没有说过界）。" % total_hits)
        rc = 3
    else:
        w("结论：干净，且五条臂都红过。")
        rc = 0
    text_out = out.getvalue()
    open(os.path.join(HERE, "读数-话术闸.txt"), "w", encoding="utf-8").write(text_out)
    sys.stdout.buffer.write(text_out.encode("utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
