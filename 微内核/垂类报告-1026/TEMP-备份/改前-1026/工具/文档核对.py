#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档核对：本族的尺子。只读，不改任何东西，不写 HTML。

十四道：K1–K12 + D1（引用指针双向无孤儿）+ D3（普查标记）。
算法一律走 工具/模型.py —— 与 出表.py 同一个实现，所以「核对通过」不是两件各算一遍碰巧相等。

退出码契约（沿用 交付对账-1026/README.md 的档位含义）：
    0 全过
    2 成品与 JSON 真值源不符（渲染漂移 / 赢家不符 / 章名不符 / 页脚不符 / 引用孤儿）
    3 判不了（格子非法 / unknown 冒充数字 / 缺凭据 / 凭据核不了 / 全 unknown 维带权重 /
             撞车差异不可证伪 / 普查标记缺失 / 引用登记件不存在）
    1 本件自己错（读不到文件、解析炸了、一道检查都没跑起来）

用法（工作目录 垂类报告-1026）：
    C:/Users/Admin/sdk/py314/python.exe 工具/文档核对.py
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 模型  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
MD = os.path.join(ROOT, "方法与分母-1026.md")
# 缺席陈述的词表与档位定义在 工具/模型.py（渲染件与核对件同一份）——附录 A 是脚本渲染的，
# 两边各写一套就会各数一套。「0 条」「0/」要的是零读数而不是任何以 0 结尾的数（200 条、10/20 不算），
# 「有没有 X」是在问不是在报缺席，所以那两个位置分别用 (?<!\\d) 与 (?<!有) 挡掉。
SCAN_WORDS = 模型.SCAN_WORDS
SCAN_KINDS = 模型.SCAN_KINDS
TERM_FORBIDS = 模型.TERM_FORBIDS
TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9_.:-]*)([^>]*)>", re.S)
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col",
             "embed", "source", "track", "wbr", "path", "circle", "rect", "line",
             "polyline", "polygon", "use", "stop", "ellipse"}
SENT_BREAK = "。！？；｜\n"
# 句子在「块级元素边界」处断开（一格一句、一段一句），行内标记（span/code/strong）保持透明。
# 这样句子单位只跟结构有关，不跟源码换行有关——重新排版一行不会改分母。
BLOCK_TAGS = {"p", "li", "td", "th", "tr", "div", "h1", "h2", "h3", "h4", "h5", "h6",
              "figcaption", "figure", "table", "tbody", "thead", "tfoot", "ul", "ol",
              "section", "article", "blockquote", "pre", "dt", "dd", "br", "hr",
              "caption", "text", "svg"}


# ---------------------------------------------------------------- 小工具

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def src_files():
    if not os.path.isdir(SRC):
        return []
    return sorted(os.path.join(SRC, x) for x in os.listdir(SRC) if x.endswith(".html"))


def strip_tags(s):
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def element_text(html, tag_pat):
    m = re.search(tag_pat, html, flags=re.S)
    return strip_tags(m.group(1)) if m else None


# ---------------------------------------------------------------- 各道检查
# 每道返回 (findings, notes)；findings 是 [(rc, 文本)]。

def k1(score, ctx):
    w = sum(float(d.get("weight", 0)) for d in score.get("dimensions", []))
    if abs(w - 1.0) > 1e-9:
        return [(3, "权重合计 %.4f ≠ 1" % w)], "sum=%.4f" % w
    return [], "sum=%.2f" % w


def k2(score, ctx):
    ids = [d.get("id") for d in score.get("dimensions", [])]
    bad = []
    if len(score.get("verticals", [])) != 4:
        bad.append((3, "垂类数 %d ≠ 4" % len(score.get("verticals", []))))
    if len(ids) != 5:
        bad.append((3, "计分维数 %d ≠ 5" % len(ids)))
    for v in score.get("verticals", []):
        cells = v.get("cells", {})
        miss = [i for i in ids if i not in cells]
        extra = [i for i in cells if i not in ids]
        if miss:
            bad.append((3, "%s 缺格 %s" % (v.get("id"), ",".join(miss))))
        if extra:
            bad.append((3, "%s 多余格 %s" % (v.get("id"), ",".join(extra))))
    return bad, "%d 垂类 × %d 维" % (len(score.get("verticals", [])), len(ids))


def k3(score, ctx):
    bad = []
    for v in score.get("verticals", []):
        for did, cell in (v.get("cells") or {}).items():
            kindv, info = 模型.cell_value(cell)
            if kindv == "illegal":
                bad.append((3, "%s·%s 非法：%s" % (v.get("id"), did, info)))
    return bad, "格子值全为整数或字符串 unknown" if not bad else "%d 格非法" % len(bad)


def k4(score, ctx):
    bad = []
    for v in score.get("verticals", []):
        for did, cell in (v.get("cells") or {}).items():
            if isinstance(cell, dict) and cell.get("v") == "unknown":
                if not (cell.get("unknown_reason") or "").strip():
                    bad.append((3, "%s·%s unknown 没写 unknown_reason" % (v.get("id"), did)))
                if cell.get("cred"):
                    bad.append((3, "%s·%s unknown 却挂着凭据" % (v.get("id"), did)))
    return bad, "未判定格 %d 个，全部带理由" % ctx["n_unknown"]


def k5(score, ctx):
    bad = []
    for v in score.get("verticals", []):
        for did, cell in (v.get("cells") or {}).items():
            kindv, _ = 模型.cell_value(cell)
            if kindv == "num" and not (cell.get("cred") or []):
                bad.append((3, "%s·%s 是数字 %s 但零凭据" % (v.get("id"), did, cell.get("v"))))
            if not (cell.get("rationale") or "").strip():
                bad.append((3, "%s·%s 没写 rationale" % (v.get("id"), did)))
    return bad, "数字格均有凭据" if not bad else "%d 格缺凭据/缺理由" % len(bad)


def k6(score, ctx):
    bad = []
    refs = ctx["refs"]
    for v in score.get("verticals", []):
        for did, cell in (v.get("cells") or {}).items():
            kindv, _ = 模型.cell_value(cell)
            if kindv != "num":
                continue
            for c in cell.get("cred") or []:
                ok, why = 模型.check_credential(c, refs)
                if not ok:
                    bad.append((3, "%s·%s 凭据（%s）核不了：%s"
                                % (v.get("id"), did, c.get("kind"), why)))
    kinds = ctx["cred_kinds"]
    return bad, "凭据 %d 条（%s）" % (sum(kinds.values()),
                                     " ".join("%s=%d" % (k, n) for k, n in sorted(kinds.items())))


def k7(score, ctx):
    bad = []
    ids = [d.get("id") for d in score.get("dimensions", [])]
    for i in ids:
        vals = []
        for v in score.get("verticals", []):
            cell = (v.get("cells") or {}).get(i)
            if cell is None:
                continue
            vals.append(模型.cell_value(cell)[0])
        w = [float(d.get("weight", 0)) for d in score.get("dimensions", []) if d.get("id") == i]
        if vals and all(x == "unknown" for x in vals) and w and w[0] > 0:
            bad.append((3, "维度 %s 全为 unknown 却带权重 %.2f ⇒ 这一维的权重在骗人" % (i, w[0])))
    return bad, "无「全 unknown 带权重」维"


def k8(score, closed, ctx):
    bad = []
    idx = {e.get("id"): e for e in closed.get("entries", [])}
    for v in score.get("verticals", []):
        cc = v.get("closed_collision")
        note = (v.get("collision_note") or "").strip()
        if not cc:
            bad.append((3, "%s 未自报撞车（closed_collision 缺）" % v.get("id")))
            continue
        if cc not in idx:
            bad.append((3, "%s 的 closed_collision=%s 不在关闭方向登记里" % (v.get("id"), cc)))
            continue
        if not note:
            bad.append((3, "%s 撞了 %s 却没写差异说明" % (v.get("id"), cc)))
        elif not (("若" in note and "则" in note) or "证伪" in note):
            bad.append((3, "%s 的差异说明里没有可证伪条件（要「若…则本差异不成立」）" % v.get("id")))
    used = {v.get("closed_collision") for v in score.get("verticals", [])}
    notes = ["%s→%s" % (v.get("id"), v.get("closed_collision")) for v in score.get("verticals", [])]
    return bad, "登记 %d 条 / 被点名 %d 条 ｜ %s" % (
        len(idx), len([u for u in used if u]), " ".join(notes))


def k9(score, ctx):
    res = ctx["res"]
    if res.get("error"):
        return [(3, "总分算不出来：%s" % res["error"])], "重算失败"
    if res.get("tie"):
        return [(3, "%s 同分且 D2/D5 也同 ⇒ 不造赢家" % "、".join(res["tie"]))], "并列"
    stated = score.get("winner")
    if stated and stated != res["winner"]:
        return [(2, "winner=%s 与脚本重算 %s 不符（不许手写赢家）" % (stated, res["winner"]))], "不符"
    return [], "重算赢家 %s，名次 %s" % (res["winner"], "→".join(res["ranking"]))


def k10(ctx):
    """渲染漂移：把 GEN 块内容与「用同一算法重新渲染的结果」逐字比对。"""
    bad = []
    want = ctx["blocks"]
    on = ctx["html_blocks"]
    for name in ("SCORE", "REFS"):
        if name not in want:
            continue
        if name not in on:
            bad.append((2, "%s 块在 HTML 里不存在（GEN 标记丢了或整块被删）" % name))
            continue
        if 模型.norm(want[name]) != 模型.norm(on[name]):
            # 点名差在哪一段，否则只说「不一样」等于没查
            a, b = want[name], on[name]
            i = 0
            while i < min(len(a), len(b)) and a[i] == b[i]:
                i += 1
            bad.append((2, "%s 块与真值源不符：盘上第 %d 字起不同（盘上「%s」/ 应为「%s」）"
                        % (name, i, b[i:i + 26].replace("\n", "⏎"),
                           a[i:i + 26].replace("\n", "⏎"))))
    return bad, "比对 %s" % ("、".join(want.keys()) or "无块")


def k11(score, ctx):
    """第 7 章章名必须等于脚本重算出来的赢家——赢家变了，这一章必须重写。"""
    res = ctx["res"]
    if res.get("error") or not res.get("winner"):
        return [(3, "赢家未定，第 7 章章名无从核对")], "赢家未定"
    path = os.path.join(SRC, "05-vertical.html")
    if not os.path.isfile(path):
        return [(1, "读不到 src/05-vertical.html")], "缺文件"
    title = element_text(read(path), r'<h1 id="ch7"[^>]*>(.*?)</h1>')
    if title is None:
        return [(2, "src/05-vertical.html 里没有 <h1 id=\"ch7\">（章名核对无从下手）")], "无章名"
    names = {v["id"]: v["name"] for v in score.get("verticals", [])}
    win = res["winner"]
    bad = []
    if names[win][:6] not in title:
        bad.append((2, "第 7 章章名不含赢家 %s 的名称「%s」；章名是：%s" % (win, names[win][:6], title[:40])))
    for vid, nm in names.items():
        if vid != win and nm[:6] in title:
            bad.append((2, "第 7 章章名里出现了非赢家 %s 的名称「%s」" % (vid, nm[:6])))
    return bad, "章名：%s ｜ 赢家：%s" % (title[:30], win)


def k12(score, ctx):
    da = (score.get("decided_at") or "").strip()
    if not da:
        return [(3, "评分表没有 decided_at，页脚日期无从对账")], "缺 decided_at"
    bad = []
    seen = []
    for p in ctx["html_paths"]:
        t = read(p)
        for m in re.finditer(r'data-date="([^"]+)"', t):
            seen.append((os.path.basename(p), m.group(1)))
            if m.group(1) != da:
                bad.append((2, "%s 的 data-date=%s 与 decided_at=%s 不符"
                            % (os.path.basename(p), m.group(1), da)))
    if not seen:
        bad.append((3, "全族没有任何 data-date 标记（页脚日期核对是空的，等于没这道闸）"))
    return bad, "页脚日期 %d 处，均为 %s" % (len(seen), da) if not bad else "%d 处不符" % len(bad)


CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def md_section_guard(srcs):
    """正文里写成「口径件 §N」的指针，落点进行的那一节必须真是 §N。
    只管指向 方法与分母-1026.md 的那几条；行号非空但节号走错，正是改一次口径件就会出现的静默错位。"""
    if not os.path.isfile(MD):
        return []
    lines = read(MD).splitlines()
    heads = []
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^## +([一二三四五六七八九十]+)、", ln)
        if m:
            heads.append((i, CN_NUM.get(m.group(1), -1), m.group(1)))
    bad = []
    for f, pl, disp in srcs:
        if not pl.startswith("方法与分母-1026.md"):
            continue
        mm = re.search(r"§\s*([一二三四五六七八九十]+)", disp)
        if not mm:
            continue
        claim = CN_NUM.get(mm.group(1), -1)
        line_no = int(re.match(r".+?:(\d+)", pl).group(1))
        here = [h for h in heads if h[0] <= line_no]
        if not here:
            bad.append((2, "%s 的 data-src=%s 指到 §%s，但那一行之前没有任何 ## 节标题"
                        % (f, pl, mm.group(1))))
            continue
        if here[-1][1] != claim:
            bad.append((2, "%s 的 data-src=%s 写的是「§%s」，可那一行现在落在 §%s（第 %d 行起）里——"
                        "口径件改过，正文行号没跟着搬"
                        % (f, pl, mm.group(1), here[-1][2], here[-1][0])))
    return bad


def d1(score, closed, ctx):
    """引用双向无孤儿：HTML 里每个 data-cite 都要有号；登记里每条都要被引或显式标未用。
    另：data-src 与口径件里的 file:line 指针必须解析得到、且那一行不空。"""
    bad = []
    refs = ctx["refs"]
    cite_ids = set()
    srcs = []
    for p in ctx["html_paths"]:
        t = read(p)
        cite_ids |= set(re.findall(r'data-cite="([^"]+)"', t))
        srcs += [(os.path.basename(p), m.group(1),
                  t[m.end():m.end() + 120].split("<")[0]) for m in
                 re.finditer(r'data-src="([^"]+:\d+(?:-\d+)?)"', t)]
    if refs is None:
        bad.append((3, "引用登记件不存在 ⇒ data-cite %d 个号无从核对（波 1 未起）" % len(cite_ids)))
    else:
        idx = {r.get("id") for r in refs.get("entries", [])}
        orphan = sorted(cite_ids - idx)
        if orphan:
            bad.append((2, "悬空引用号（HTML 引了登记里没有的）：%s" % ",".join(orphan)))
        unused = []
        for r in refs.get("entries", []):
            if r.get("id") in cite_ids:
                continue
            if r.get("used") is False:
                if not (r.get("unused_reason") or "").strip():
                    bad.append((2, "引用号 %s 标了未用但没写 unused_reason" % r.get("id")))
                continue
            unused.append(r.get("id"))
        if unused:
            bad.append((2, "无主引用（登记里有、正文没引、也没标未用）：%s" % ",".join(sorted(unused))))
        cnt = 模型.status_counts(refs)
        for r in refs.get("entries", []):
            if r.get("status") == "核" and not (r.get("url") or "").strip():
                bad.append((3, "引用号 %s 标「核」却无 url" % r.get("id")))
            if r.get("status") not in 模型.STATUSES:
                bad.append((3, "引用号 %s 的状态词「%s」不在 核/片/未/反 四档内"
                            % (r.get("id"), r.get("status"))))
            # 附录 A 是脚本渲染的：登记件里那半句上了屏，就得自带档位，否则 D3 抓的是生成块，改不动
            sc = r.get("scan")
            if sc is not None and sc not in 模型.SCAN_KINDS:
                bad.append((3, "引用号 %s 的 scan 档「%s」不在 census/targeted/not_run/term 之内"
                            % (r.get("id"), sc)))
            elif sc and 模型.TERM_FORBIDS.search(
                    模型.ref_row_text(r).replace("「", "").replace("」", "")):
                bad.append((3, "引用号 %s 挂了 term，可上屏那行摘掉引号后仍带读数" % r.get("id")))
            elif 模型.SCAN_WORDS.search(模型.ref_row_text(r)) and not sc:
                bad.append((3, "引用号 %s 上屏那一行含缺席陈述词却没写 scan 档" % r.get("id")))
        ctx["refs_status"] = cnt
    # path:line 指针解析（HTML 侧）
    for f, pl, disp in srcs:
        ok, why = resolve_pair(pl)
        if not ok:
            bad.append((2, "%s 的 data-src=%s 解析不了：%s" % (f, pl, why)))
    # 口径件指针的「节号跟不跟得上行号」：改一次口径件，正文里写的 §五 与指过去的行号会各走各的
    # （1026 实测踩过两次：给 §三 补一档，后面每一节都往下挪，指针指到别节却照样非空）
    bad += md_section_guard(srcs)
    # 口径件侧的 file:line 文本指针（允许带目录；裸文件名撞名时判不了，不静默取第一个）
    if os.path.isfile(MD):
        md = read(MD)
        for m in re.finditer(
                r"((?:[\w.\-一-鿿]+/)*[\w.\-一-鿿]+\.(?:md|py|html|json|txt|js)):(\d+)", md):
            fn, ln = m.group(1), int(m.group(2))
            if "/" in fn:
                ok, why = resolve_pair("%s:%d" % (fn, ln))
                if not ok:
                    bad.append((2, "方法与分母里指向 %s:%s，解析不了：%s" % (fn, ln, why)))
                else:
                    ctx["md_pointers"] += 1
                continue
            cands = find_all_named(fn)
            if not cands:
                bad.append((2, "方法与分母里指向 %s:%s，但按文件名找不到这个文件" % (fn, ln)))
                continue
            if len(cands) > 1:
                bad.append((3, "方法与分母里裸文件名 %s 撞名 %d 个，指针不知道指谁（要点名候选，别按列举序取第一个）：%s"
                            % (fn, len(cands), " ".join(c.replace("\\", "/") for c in cands[:6]))))
                continue
            ls = open(cands[0], encoding="utf-8").read().splitlines()
            if not (1 <= ln <= len(ls)) or not ls[ln - 1].strip():
                bad.append((2, "方法与分母里指向 %s:%s，那一行不在或为空（该文件 %d 行）"
                            % (fn, ln, len(ls))))
            else:
                ctx["md_pointers"] += 1
    ctx["cite_n"] = len(cite_ids)
    ctx["src_n"] = len(srcs)
    return bad, "data-cite %d ｜ data-src %d ｜ 口径件指针 %d" % (
        ctx["cite_n"], ctx["src_n"], ctx.get("md_pointers", 0))


def scan_regions(t):
    """所有带 data-scan 的元素的源码跨度 [(start, end, kind)]，含标签本身。
    配对靠栈；不配平时把残留深度报给调用方（区间数不清 ⇒ 这道闸在这份件里没有判据）。"""
    regions = []
    stack = []
    i = 0
    n = len(t)
    while i < n:
        if t.startswith("<!--", i):
            j = t.find("-->", i)
            i = n if j < 0 else j + 3
            continue
        m = TAG_RE.match(t, i)
        if not m:
            i += 1
            continue
        i = m.end()
        name = m.group(2).lower()
        attrs = m.group(3)
        if m.group(1) == "/":
            k = None
            for j2 in range(len(stack) - 1, -1, -1):
                if stack[j2][0] == name:
                    k = j2
                    break
            if k is None:
                continue
            while len(stack) - 1 > k:
                o_name, o_scan, o_start = stack.pop()
                if o_scan:
                    regions.append((o_start, i, o_scan))
            o_name, o_scan, o_start = stack.pop()
            if o_scan:
                regions.append((o_start, i, o_scan))
            continue
        if attrs.rstrip().endswith("/") or name in VOID_TAGS:
            continue
        sm = re.search(r'data-scan="([^"]+)"', attrs)
        stack.append((name, sm.group(1) if sm and sm.group(1) in SCAN_KINDS else None, m.start()))
    unbalanced = len(stack)
    while stack:
        o_name, o_scan, o_start = stack.pop()
        if o_scan:
            regions.append((o_start, n, o_scan))
    return regions, unbalanced


def visible_text(t):
    """剥标签与注释，但每个字符保留它的源码下标：块级标签与注释换成 \\n（=句子分隔符），
    行内标签换成空（同句内的加粗/代码/分句 span 不切断句子）。
    于是「句子」= 一段里的一句、一格里的一段话，与源码怎么折行无关。"""
    chars = []
    src = []
    i = 0
    n = len(t)
    while i < n:
        if t.startswith("<!--", i):
            j = t.find("-->", i)
            j = n if j < 0 else j + 3
            chars.append("\n")
            src.append(min(j, max(n - 1, 0)))
            i = j
            continue
        m = TAG_RE.match(t, i)
        if m:
            name = m.group(2).lower()
            if m.group(1) == "/":
                if name == "code":
                    chars.append("\x02")
                    src.append(min(m.end(), max(n - 1, 0)))
            elif name == "code":
                chars.append("\x01")
                src.append(min(m.end(), max(n - 1, 0)))
            if name in BLOCK_TAGS:
                chars.append("\n")
                src.append(min(m.end(), max(n - 1, 0)))
            i = m.end()
            continue
        c = t[i]
        # 源码折行不是句子边界（重新排版一行不该改分母）——只有块级边界与标点才是。
        chars.append(" " if c == "\n" else c)
        src.append(i)
        i += 1
    return "".join(chars), src


def sentence_bounds(text, i):
    a = i
    while a > 0 and text[a - 1] not in SENT_BREAK:
        a -= 1
    b = i
    n = len(text)
    while b < n:
        if text[b] in SENT_BREAK:
            b += 1
            break
        b += 1
    return a, b


def unquoted(seg):
    """摘掉被引号「」或 <code> 包住的片段：那是在引用一个词，不是本件报出的读数。"""
    s = re.sub(r"\x01[^\x02]*\x02?", " ", seg)
    return re.sub(r"「[^」]*」", " ", s)


def d3(ctx):
    """普查标记：凡正文出现「没有 / 未找到 / 0 条 / 不存在」这类缺席陈述，必须自报是哪一种 0。
    判定口径 = 这句话的源码区间整个落在某个带合法 data-scan 的元素区间里，落不进就是漏标。
    标记可打在任意层（块、figure、tr、分句 span 都算），祖先的标记盖得住里面的后代；
    第四档 term 只给「引用这个词本身」用，它一旦带了读数就判红。"""
    bad = []
    hits = 0
    marks = 0
    by_kind = dict((k, 0) for k in SCAN_KINDS)
    for p in ctx["html_paths"]:
        base = os.path.basename(p)
        if base in ("00-head.html",):
            continue
        t = read(p)
        for mm in re.finditer(r'data-scan="([^"]*)"', t):
            if mm.group(1) not in SCAN_KINDS:
                bad.append((3, "%s 的 data-scan=%r 不在 census/targeted/not_run/term 四档内"
                            % (base, mm.group(1))))
        regions, unbalanced = scan_regions(t)
        if unbalanced:
            bad.append((3, "%s 有 %d 个标签到件尾还没闭合 ⇒ 标记区间数不清，这份件里这道闸没有判据"
                        % (base, unbalanced)))
        text, src = visible_text(t)
        seen = set()
        for m in SCAN_WORDS.finditer(text):
            a, b = sentence_bounds(text, m.start())
            if (a, b) in seen:
                continue
            seen.add((a, b))
            hits += 1
            # 区间比较只看句子正文的首尾字符：尾标点可能来自后面的块边界标签，不算这句话的内容。
            ia, ib = a, b - 1
            while ia < b and (text[ia] in SENT_BREAK or text[ia] in " \t"):
                ia += 1
            while ib > ia and (text[ib] in SENT_BREAK or text[ib] in " \t"):
                ib -= 1
            sa, sb = src[ia], src[ib]
            enc = [r for r in regions if r[0] <= sa and sb <= r[1]]
            raw = text[a:b]
            seg = re.sub(r"[\x01\x02]", "", re.sub(r"\s+", " ", raw)).strip()
            if not enc:
                bad.append((3, "%s:%d 有一句缺席陈述没标 data-scan：%s"
                            % (base, t.count("\n", 0, sa) + 1, seg[:56])))
                continue
            kind = min(enc, key=lambda r: r[1] - r[0])[2]
            marks += 1
            by_kind[kind] += 1
            if kind == "term":
                fm = TERM_FORBIDS.search(unquoted(raw))
                if fm:
                    bad.append((3, "%s:%d 把缺席陈述标成了 term（词引用），可摘掉引号后这句仍带读数「%s」：%s"
                                % (base, t.count("\n", 0, sa) + 1,
                                   re.sub(r"\s+", " ", fm.group(0)), seg[:56])))
    if hits and marks == 0:
        bad.append((3, "有 %d 句缺席陈述，一处标记都没有 ⇒ 这道闸是空的" % hits))
    return bad, "缺席陈述 %d 句，已标 %d 句（census %d / targeted %d / not_run %d / term %d）" % (
        hits, marks, by_kind["census"], by_kind["targeted"], by_kind["not_run"], by_kind["term"])


def resolve_pair(pl):
    """解析 `path:line` 或 `path:a-b`。"""
    m = re.match(r"^(.+?):(\d+)(?:-(\d+))?$", pl)
    if not m:
        return False, "形状不是 path:line"
    p, a, b = m.group(1), int(m.group(2)), m.group(3)
    ap = p if os.path.isabs(p) else None
    if ap is None:
        for base in (ROOT, 模型.BASE):
            c = os.path.join(base, p).replace("\\", "/")
            if os.path.isfile(c):
                ap = c
                break
    if ap is None or not os.path.isfile(ap):
        return False, "文件不存在"
    ls = open(ap, encoding="utf-8").read().splitlines()
    for n in ([a] if b is None else [a, int(b)]):
        if not (1 <= n <= len(ls)) or not ls[n - 1].strip():
            return False, "第 %d 行越界或为空（该文件 %d 行）" % (n, len(ls))
    return True, "OK"


def find_all_named(fn):
    """按文件名在 ROOT 与 BASE 两棵树里找齐所有同名件。
    返回排序后的绝对路径列表——撞名时调用方必须点名，不许按列举序取第一个。"""
    if os.path.isabs(fn):
        return [fn] if os.path.isfile(fn) else []
    hits = set()
    for base in (ROOT, 模型.BASE):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in ("TEMP-备份", "node_modules", "__pycache__", ".git")]
            if fn in filenames:
                hits.add(os.path.normcase(os.path.join(dirpath, fn)))
    return sorted(hits)


# ---------------------------------------------------------------- 主流程

def main():
    o = io.StringIO()

    def w(f, *a):
        o.write((f % a if a else f) + "\n")

    try:
        score, closed, refs = 模型.load_all()
    except FileNotFoundError as e:
        sys.stderr.write("文档核对：输入件缺失 %s\n" % e)
        print("E1 INPUT_MISSING")
        return 1
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("文档核对：输入件解析失败 %r\n" % (e,))
        print("E1 PARSE_FAIL")
        return 1

    html_paths = src_files()
    if not html_paths:
        sys.stderr.write("文档核对：src/ 下一份 HTML 都没有\n")
        print("E1 NO_SRC")
        return 1
    joined = "\n".join(read(p) for p in html_paths)
    res = 模型.compute(score)
    sens = 模型.sensitivity(score)

    n_unknown = sum(len(r["unknown"]) for r in res.get("rows", [])) if not res.get("error") else 0
    kinds = {}
    for v in score.get("verticals", []):
        for cell in (v.get("cells") or {}).values():
            for c in (cell.get("cred") or []) if isinstance(cell, dict) else []:
                kinds[c.get("kind", "?")] = kinds.get(c.get("kind", "?"), 0) + 1

    want = {}
    if not res.get("error"):
        want["SCORE"] = 模型.gen_score_html(score, res, sens).split(
            模型.GEN_START % "SCORE", 1)[-1].split(模型.GEN_END % "SCORE")[0].strip()
    if refs is not None:
        want["REFS"] = 模型.gen_refs_html(refs).split(
            模型.GEN_START % "REFS", 1)[-1].split(模型.GEN_END % "REFS")[0].strip()

    ctx = {"res": res, "sens": sens, "refs": refs, "refs_status": None,
           "n_unknown": n_unknown, "cred_kinds": kinds,
           "html_paths": html_paths, "html_blocks": 模型.rendered_blocks(joined),
           "blocks": want, "md_pointers": 0, "cite_n": 0, "src_n": 0}

    w("文档核对 · 垂类选择与产品化 v1 ｜ 只读，不改任何东西")
    w("输入：评分表 schema=%s ｜ 关闭方向 %d 条 ｜ 引用登记 %s",
      score.get("schema"), len(closed.get("entries", [])),
      "%d 条" % len(refs.get("entries", [])) if refs is not None else "不存在")
    w("正文：%d 份 HTML 段（src/）" % len(html_paths))
    w("")

    checks = [
        ("K1  权重合计=1", lambda: k1(score, ctx)),
        ("K2  结构齐（4×5）", lambda: k2(score, ctx)),
        ("K3  格子值合法", lambda: k3(score, ctx)),
        ("K4  unknown 带理由且不挂凭据", lambda: k4(score, ctx)),
        ("K5  数字格有凭据与 rationale", lambda: k5(score, ctx)),
        ("K6  凭据可核（盘上行号/核级/证伪阈值）", lambda: k6(score, ctx)),
        ("K7  无全 unknown 带权重维", lambda: k7(score, ctx)),
        ("K8  撞车核对可证伪", lambda: k8(score, closed, ctx)),
        ("K9  赢家由重算得出", lambda: k9(score, ctx)),
        ("K10 生成块无渲染漂移", lambda: k10(ctx)),
        ("K11 第7章章名=赢家", lambda: k11(score, ctx)),
        ("K12 页脚日期=decided_at", lambda: k12(score, ctx)),
        ("D1  引用双向无孤儿 + 指针解析", lambda: d1(score, closed, ctx)),
        ("D3  普查标记（哪一种 0）", lambda: d3(ctx)),
    ]

    findings = []
    own_err = 0
    for name, fn in checks:
        try:
            bad, note = fn()
        except Exception as e:  # noqa: BLE001
            own_err += 1
            bad, note = [(1, "本件在这道上炸了：%r" % (e,))], "EXCEPTION"
        findings += [(name, rc, x) for rc, x in bad]
        w("%-38s %s ｜ %s", name, "PASS" if not bad else "RED(%d)" % len(bad), note)
        for rc, x in bad:
            w("    [%d] %s", rc, x)

    chips = re.findall(r'data-chip="([^"]+)"', joined)
    tri = re.findall(r'data-state="([^"]+)"', joined)
    bad_chip = [c for c in chips if c not in 模型.CHIP_ORDER]
    bad_tri = [t for t in tri if t not in ("有据", "相背", "取不到")]

    w("")
    w("chip 词表（disk/public/estimate/relayed/未）：%d 处，越表 %d 处", len(chips), len(bad_chip))
    w("三态（有据/相背/取不到）：%d 处，越档 %d 处", len(tri), len(bad_tri))
    if chips and bad_chip:
        findings.append(("chip 词表", 3, "chip 用了词表外的值：%s" % ",".join(sorted(set(bad_chip)))))
    if tri and bad_tri:
        findings.append(("三态档", 3, "三态用了档位外的值：%s" % ",".join(sorted(set(bad_tri)))))
    if chips and not tri:
        findings.append(("chip/三态配对", 3, "有 chip 但没有一处三态标注：只分了级，没分「有据/相背/取不到」"))

    filled = sum(r["n_known"] for r in res.get("rows", [])) if not res.get("error") else 0
    cells_n = len(score.get("verticals", [])) * len(score.get("dimensions", []))
    rs = ctx["refs_status"]
    w("")
    w("checks_run=%d/%d ｜ checks_red=%d ｜ own_error=%d", len(checks), len(checks),
      len([x for x in findings if x[1] != 1]), own_err)
    w("score_cells_filled=%d/%d ｜ score_verticals=%d ｜ score_winner=%s ｜ score_flips=%d",
      filled, cells_n, len(score.get("verticals", [])),
      res.get("winner") or ("TIE" if res.get("tie") else "NONE"), len(sens.get("flips", [])))
    if rs is not None:
        w("refs_rows=%d ｜ refs_status=核%d|片%d|未%d|反%d",
          len(refs.get("entries", [])), rs["核"], rs["片"], rs["未"], rs["反"])
    else:
        w("refs_rows=0 ｜ refs_status=登记件不存在（判不了，不许当成 0 条）")
    w("tier-labelled assertions = %d/%d", len(chips) - len(bad_chip), len(chips))
    w("pointers_resolved: data-src=%d data-cite=%d 口径件=%d",
      ctx["src_n"], ctx["cite_n"], ctx["md_pointers"])

    if own_err:
        rc = 1
        verdict = "本件错（rc=1）：有检查没能跑起来，上面任何 PASS 都不作数"
    elif any(x[1] == 3 for x in findings):
        rc = 3
        verdict = "判不了（rc=3）：%d 处。不许改成品的样子迁就尺子——先看是不是数据本身没依据。" % \
                  len([x for x in findings if x[1] == 3])
    elif any(x[1] == 2 for x in findings):
        rc = 2
        verdict = "成品与真值源不符（rc=2）：%d 处，多半是手改了生成区或章名没跟着赢家改。跑 工具/出表.py 重出。" % \
                  len([x for x in findings if x[1] == 2])
    else:
        rc = 0
        verdict = "全过（rc=0）。注意：这只说十四道都红不起来，不说结论对——臂有没有牙看 工具/臂检-文档.py。"
    w("")
    w("结论：%s", verdict)

    text = o.getvalue()
    out = os.path.join(ROOT, "读数")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "文档核对.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
