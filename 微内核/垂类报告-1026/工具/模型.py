#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型：评分表与引用登记的**唯一**计算与渲染实现。只读，不写盘，不判对错。

为什么单独一件：`出表.py`（写）与 `文档核对.py`（查）必须用同一个算法，否则
「渲染出来的总分」与「重算出来的总分」相等就只是巧合。教训来自 1024——
交叉等式有一边只有「写的那件」知道时，先把两边搬进同一个只读件。

打分口径（写死在这里，两个入口共用）：
  · 每维原始分 0–5；`low_is_good` 维在合成总时**先反转**（max−v），所以「加权好度」越大越好。
  · `unknown` 既不进分子也不进分母 ⇒ 按「已知维的权重和」归一，缺依据不罚分也不加分。
  · 同分先比 D2 再比 D5；仍同分 ⇒ 不造赢家（返回 winner=None，由调用方判 rc=3）。
  · **胜出资格线**（`win_rule.min_known_dims`）：归一化会把「这一维没证据」抬成高分——躲开了
    「没证据所以打低分」的罚。所以原始名次照印，但只有达到资格线的垂类能被冠「胜出」。
    这条不是修饰：本轮第一次算的时候，只有 3/5 维有依据的候选排到了第一。

用法（工作目录 垂类报告-1026）：两件都 `import 模型`，本件不作为入口。
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE = os.path.dirname(ROOT)
SCORE_PATH = os.path.join(ROOT, "数据", "评分表.json")
CLOSED_PATH = os.path.join(ROOT, "数据", "已关闭方向登记.json")
REFS_PATH = os.path.join(ROOT, "数据", "引用登记-1026.json")

GEN_START = "<!-- GEN:%s START ｜ 本块由 工具/出表.py 生成，手改会被 工具/文档核对.py 判红 -->"
GEN_END = "<!-- GEN:%s END -->"

STATUSES = ("核", "片", "未", "反")
CHIP_ORDER = ("disk", "public", "estimate", "relayed", "未")
PUBLIC_OK = "核"
CRED_KINDS = ("disk", "public", "estimate", "relayed")

# 「0 是哪一种 0」的词表与档位：口径件 §三 写的是同一套，渲染件与核对件共用这一份定义。
# 两个精度例外都是「尺子变准」：数字位前的 0 不算缺席；「有没有 X」是在问不是在报缺席。
SCAN_WORDS = re.compile(r"(未找到|没有取到|(?<!有)没有|(?<!\d)0 条|(?<!\d)0\s*/|不存在)")
SCAN_KINDS = ("census", "targeted", "not_run", "term")
# term 档的牙：摘掉「…」引号与 <code> 片段之后，不许还剩读数——还剩就说明它是真读数，挂 term 是绕档。
TERM_FORBIDS = re.compile(r"(\d+\s*/\s\d|(?<!\d)0\s*条|NOT_RUN)")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all():
    """返回 (score, closed, refs)。refs 允许还不存在（波 1 未起），此时为 None。"""
    score = load_json(SCORE_PATH)
    closed = load_json(CLOSED_PATH)
    refs = load_json(REFS_PATH) if os.path.isfile(REFS_PATH) else None
    return score, closed, refs


# ---------------------------------------------------------------- 校验

def norm(s):
    return re.sub(r"\s+", "", s or "")


def cell_value(cell):
    """格子的 v 字段 → ("num", int) / ("unknown", reason) / ("illegal", 说明)。"""
    if not isinstance(cell, dict):
        return "illegal", "格子不是对象"
    v = cell.get("v", "__missing__")
    if v == "__missing__":
        return "illegal", "缺 v 字段"
    if isinstance(v, bool):
        return "illegal", "v 是布尔（true/false 不是分数）"
    if v == "unknown":
        r = (cell.get("unknown_reason") or "").strip()
        if not r:
            return "illegal", "unknown 没有 unknown_reason"
        return "unknown", r
    if isinstance(v, int):
        return "num", v
    return "illegal", "v 既不是整数也不是字符串 unknown：%r" % (v,)


def resolve_disk(cred):
    """disk 凭据：文件在不在、行号越不越界、引文对不对得上那一行。返回 (ok, 说明)。"""
    p = (cred.get("path") or "").strip()
    if not p:
        return False, "disk 凭据没写 path"
    cands = []
    if os.path.isabs(p):
        cands.append(p.replace("\\", "/"))
    else:
        cands.append(os.path.join(ROOT, p).replace("\\", "/"))
        cands.append(os.path.join(BASE, p).replace("\\", "/"))
    ap = next((c for c in cands if os.path.isfile(c)), None)
    if ap is None:
        return False, "文件不存在：%s（试过 %s）" % (p, " ｜ ".join(cands))
    try:
        lines = open(ap, encoding="utf-8").read().splitlines()
    except Exception as e:  # noqa: BLE001
        return False, "读不到：%s（%s）" % (p, e)
    n = cred.get("line")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > len(lines):
        return False, "行号越界：%s:%r（该文件 %d 行）" % (p, n, len(lines))
    q = norm(cred.get("quote"))
    if not q:
        return False, "disk 凭据没带引文（无法证明那一行写了什么）"
    tgt = norm(lines[n - 1])
    nxt = norm(lines[n]) if n < len(lines) else ""
    if q not in tgt and q not in (tgt + nxt):
        return False, "引文对不上 %s:%d —— 那一行是「%s」" % (p, n, lines[n - 1].strip()[:60])
    return True, "OK"


def check_credential(cred, refs):
    """单条凭据能不能给这个数字当依据。返回 (ok, 罪名)。"""
    if not isinstance(cred, dict):
        return False, "凭据不是对象"
    kind = cred.get("kind")
    if kind not in CRED_KINDS:
        return False, "凭据 kind 不认识：%r（允许 %s）" % (kind, "/".join(CRED_KINDS))
    if kind == "disk":
        return resolve_disk(cred)
    if kind == "public":
        if refs is None:
            return False, "引用登记件还不存在（波 1 未起），public 凭据无从核对"
        idx = {r.get("id"): r for r in refs.get("entries", [])}
        rid = cred.get("cite")
        r = idx.get(rid)
        if r is None:
            return False, "public 凭据指向不存在的引用号 %r" % (rid,)
        st = r.get("status")
        if st != PUBLIC_OK:
            return False, ("引用号 %s 的状态是「%s」；只有「核」级外部件能给数字当凭据"
                           "（快照级数字不许进正文，这条同样管打分）" % (rid, st))
        for f in ("url", "quote", "checked_at"):
            if not (r.get(f) or "").strip():
                return False, "引用号 %s 标了「核」但缺 %s（无法复跑）" % (rid, f)
        return True, "OK"
    if kind == "estimate":
        for f in ("assumption", "falsifier"):
            if not (cred.get(f) or "").strip():
                return False, "estimate 凭据缺 %s（C 级假设必须能把自己证伪）" % f
        return True, "OK"
    return True, "OK"


def cell_problems(vid, did, cell, refs, scale):
    """一个格子的全部罪名（空 = 干净）。"""
    out = []
    kindv, info = cell_value(cell)
    if kindv == "illegal":
        return ["%s·%s 格子本身非法：%s" % (vid, did, info)]
    cred = cell.get("cred") or []
    if kindv == "num":
        lo, hi = scale.get("min", 0), scale.get("max", 5)
        if not (lo <= info <= hi):
            out.append("%s·%s 分数 %d 越出量表 [%s,%s]" % (vid, did, info, lo, hi))
        if not cred:
            out.append("%s·%s 是数字但一条凭据都没有" % (vid, did))
        for c in cred:
            ok, why = check_credential(c, refs)
            if not ok:
                out.append("%s·%s 凭据无效：%s" % (vid, did, why))
    elif cred:
        out.append("%s·%s 标了 unknown 却挂着凭据（要么给数，要么老实空着）" % (vid, did))
    if not (cell.get("rationale") or "").strip():
        out.append("%s·%s 没写 rationale（读者无法知道这个数为什么是这个数）" % (vid, did))
    return out


def validate(score, closed, refs):
    """结构判据。返回 (罪名列表, compute 结果)。罪名非空即不许出分。"""
    bad = []
    dims = score.get("dimensions", [])
    verts = score.get("verticals", [])
    scale = score.get("scale", {"min": 0, "max": 5})
    ids = [d.get("id") for d in dims]

    if not score.get("decided_at"):
        bad.append("评分表缺 decided_at（页脚日期要与之对账）")
    if len(verts) != 4:
        bad.append("垂类数应为 4，现 %d（少了不许偷偷出，多了不许偷偷加）" % len(verts))
    if len(ids) != 5:
        bad.append("计分维数应为 5，现 %d" % len(ids))
    if len(ids) != len(set(ids)):
        bad.append("维度 id 有重复")

    wsum = sum(float(d.get("weight", 0)) for d in dims)
    if abs(wsum - 1.0) > 1e-9:
        bad.append("权重合计 %.4f ≠ 1 ⇒ 判不了（总分不可解释）" % wsum)
    for d in dims:
        if not (d.get("name") or "").strip():
            bad.append("维度 %s 没有名字" % d.get("id"))
        if not (d.get("ask") or "").strip():
            bad.append("维度 %s 没写「这一维在问什么」" % d.get("id"))
        if not isinstance(d.get("low_is_good"), bool):
            bad.append("维度 %s 的 low_is_good 不是布尔（反向维必须显式声明）" % d.get("id"))

    if not (score.get("shared_gate") or {}).get("status"):
        bad.append("shared_gate 没有 status（接入门实测是 NOT_RUN 也要显式写出来）")

    cids = {e.get("id") for e in closed.get("entries", [])}
    for v in verts:
        vid = v.get("id", "?")
        cells = v.get("cells", {})
        miss = [i for i in ids if i not in cells]
        extra = [i for i in cells if i not in ids]
        if miss:
            bad.append("%s 缺格：%s" % (vid, ",".join(miss)))
        if extra:
            bad.append("%s 有多余格：%s" % (vid, ",".join(extra)))
        for i in ids:
            if i in cells:
                bad += cell_problems(vid, i, cells[i], refs, scale)
        cc = v.get("closed_collision")
        note = (v.get("collision_note") or "").strip()
        if not cc:
            bad.append("%s 没有 closed_collision（每个垂类必须自报撞了哪条已关闭方向）" % vid)
        elif cc not in cids:
            bad.append("%s 的 closed_collision=%r 在关闭方向登记里不存在" % (vid, cc))
        if not note:
            bad.append("%s 的 collision_note 为空" % vid)
        elif not (("若" in note and "则" in note) or "证伪" in note):
            bad.append("%s 的 collision_note 里没有可证伪条件（要写成「若 X 则本差异不成立」）" % vid)

    for i in ids:
        vals = [cell_value(v["cells"][i])[0] for v in verts if i in v.get("cells", {})]
        if vals and all(x == "unknown" for x in vals):
            w = [float(d.get("weight", 0)) for d in dims if d.get("id") == i]
            if w and w[0] > 0:
                bad.append("维度 %s 四个垂类全是 unknown 却带权重 %.2f ⇒ 判不了"
                           "（要么撤该维权重，要么给出依据）" % (i, w[0]))

    res = compute(score)
    if res.get("error"):
        bad.append("总分算不出来：%s" % res["error"])
    elif res.get("tie"):
        bad.append("%s 两两同分且 D2/D5 也同 ⇒ 不造赢家（rc=3）" % "、".join(res["tie"]))
    elif res.get("winner") is None and res.get("blocked"):
        bad.append("没有任何垂类达到胜出资格线（min_known_dims=%d）⇒ 判不了，不造赢家；"
                   "被挡住的：%s" % (res["min_known"],
                                    "、".join("%s(%d/%d 维)" % (b["id"], b["n_known"], len(dims))
                                              for b in res["blocked"])))
    else:
        stated = score.get("winner")
        if stated and stated != res["winner"]:
            bad.append("winner=%r 与脚本重算的 %r 不符（不许手写赢家）" % (stated, res["winner"]))
    return bad, res


# ---------------------------------------------------------------- 计算

def _goodness(d, v, hi):
    """把原始分转成「好度」∈[0,1]；low_is_good 维先反转。"""
    t = (hi - v) if d.get("low_is_good") else v
    return float(t) / float(hi) if hi else 0.0


def compute(score):
    dims = {d["id"]: d for d in score.get("dimensions", [])}
    hi = float(score.get("scale", {}).get("max", 5))
    out = []
    for v in score.get("verticals", []):
        num = den = 0.0
        unk = []
        cells = v.get("cells", {})
        for did, d in dims.items():
            cell = cells.get(did)
            if cell is None:
                return {"error": "%s 缺格 %s" % (v.get("id"), did)}
            kindv, info = cell_value(cell)
            if kindv == "illegal":
                return {"error": "%s·%s：%s" % (v.get("id"), did, info)}
            if kindv == "unknown":
                unk.append(did)
                continue
            w = float(d.get("weight", 0))
            num += w * _goodness(d, info, hi)
            den += w
        if den <= 0:
            return {"error": "%s 没有任何已知维（全 unknown 的垂类不参与排名）" % v.get("id")}
        out.append({
            "id": v["id"], "name": v["name"],
            "total": num / den, "raw": num, "weight_known": den,
            "n_known": len(dims) - len(unk), "unknown": unk,
            "cells": {did: (cell_value(c)[1] if cell_value(c)[0] == "num" else "unknown")
                      for did, c in cells.items()},
        })

    def key(r):
        return (-r["total"], -_tb(dims, r, "D2", hi), -_tb(dims, r, "D5", hi), r["id"])

    out.sort(key=key)
    tie = []
    if len(out) > 1 and abs(out[0]["total"] - out[1]["total"]) < 1e-9:
        if (out[0]["cells"].get("D2") == out[1]["cells"].get("D2")
                and out[0]["cells"].get("D5") == out[1]["cells"].get("D5")):
            tie = [out[0]["id"], out[1]["id"]]
    # 胜出资格线：unknown 既不进分子也不进分母 ⇒ 缺依据会被归一化**抬高**总分，
    # 于是「在打分最难的二维上没证据」反而排到前面。这是归一化的已知病理，不是垂类的优点。
    # 处理：raw 名次照原样印（不藏），但达到 min_known_dims 才有资格冠「胜出」。
    rule = score.get("win_rule") or {}
    min_known = int(rule.get("min_known_dims", 0) or 0)
    blocked = [{"id": r["id"], "n_known": r["n_known"], "missing": r["unknown"]}
               for r in out if r["n_known"] < min_known]
    eligible = [r for r in out if r["n_known"] >= min_known]
    winner = None if tie else (eligible[0]["id"] if eligible else None)
    return {"error": None, "rows": out, "hi": hi,
            "winner": winner, "tie": tie,
            "ranking": [r["id"] for r in out],
            "eligible": [r["id"] for r in eligible], "blocked": blocked,
            "min_known": min_known,
            "raw_top": out[0]["id"] if out else None}


def _tb(dims, r, did, hi):
    v = r["cells"].get(did)
    if not isinstance(v, int):
        return 0.0
    return _goodness(dims.get(did, {}), v, hi)


def sensitivity(score):
    """逐维 ±X% 扰动（扰动后整体归一），看赢家会不会翻。"""
    pct = float(score.get("sensitivity_pct", 0.2))
    base = compute(score)
    if base.get("error"):
        return {"error": base["error"], "rows": [], "flips": [], "pct": pct, "base_winner": None}
    rows, flips = [], []
    for d in score.get("dimensions", []):
        for sign in (1, -1):
            s2 = json.loads(json.dumps(score))
            for dd in s2["dimensions"]:
                if dd["id"] == d["id"]:
                    dd["weight"] = float(dd["weight"]) * (1 + sign * pct)
            tot = sum(float(x["weight"]) for x in s2["dimensions"])
            if tot <= 0:
                continue
            for x in s2["dimensions"]:
                x["weight"] = float(x["weight"]) / tot
            r2 = compute(s2)
            if r2.get("error"):
                rows.append({"dim": d["id"], "dir": "+" if sign > 0 else "-",
                             "winner": "算不出", "stable": False})
                flips.append("%s%s%%→算不出" % (d["id"], "+" if sign > 0 else "-"))
                continue
            w2 = r2["winner"] or "并列"
            same = (w2 == (base["winner"] or "并列"))
            rows.append({"dim": d["id"], "dir": "+" if sign > 0 else "-",
                         "winner": w2, "stable": same})
            if not same:
                flips.append("%s%s%%→%s" % (d["id"], "+" if sign > 0 else "-", w2))
    return {"error": None, "base_winner": base["winner"], "rows": rows,
            "flips": flips, "pct": pct}


# ---------------------------------------------------------------- 渲染（无时间戳，可复现）

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ramp(t, low_is_good):
    """颜色深浅一律表示「这个垂类在这一维上好不好」：深绿＝好，红＝差。"""
    g = (1.0 - t) if low_is_good else t
    if g < 0.34:
        return "#f3c3c3"
    if g < 0.5:
        return "#f2e2b8"
    if g < 0.75:
        return "#bfe3cd"
    return "#8fd0ae"


def heat_svg(score):
    dims = score.get("dimensions", [])
    verts = score.get("verticals", [])
    hi = int(score.get("scale", {}).get("max", 5))
    x0, y0, cw, ch, gap = 168, 44, 60, 32, 4
    width = x0 + len(dims) * (cw + gap) + 148
    height = y0 + len(verts) * (ch + gap) + 66
    res = compute(score)
    b = io.StringIO()
    b.write('<svg viewBox="0 0 %d %d" width="100%%" role="img" '
            'aria-label="四个候选垂直在五个计分维上的热矩阵，灰格为未判定">\n' % (width, height))
    b.write('<g font-family="system-ui,Microsoft YaHei" font-size="10.5" fill="#0b1f33">\n')
    for j, d in enumerate(dims):
        x = x0 + j * (cw + gap)
        b.write('<text x="%d" y="%d" text-anchor="middle" font-weight="700">%s%s</text>\n'
                % (x + cw / 2, y0 - 22, esc(d["id"]), "↓" if d.get("low_is_good") else ""))
        b.write('<text x="%d" y="%d" text-anchor="middle" font-size="9">%s</text>\n'
                % (x + cw / 2, y0 - 9, esc(d["name"][:10])))
    for i, v in enumerate(verts):
        y = y0 + i * (ch + gap)
        b.write('<text x="%d" y="%d" text-anchor="end">%s %s</text>\n'
                % (x0 - 8, y + ch / 2 + 4, esc(v.get("id", "")), esc(v.get("name", "")[:11])))
        for j, d in enumerate(dims):
            x = x0 + j * (cw + gap)
            cell = (v.get("cells") or {}).get(d["id"], {})
            kindv, info = cell_value(cell)
            if kindv == "num":
                fill, txt, tw = _ramp(info / float(hi), d.get("low_is_good")), str(info), 700
            elif kindv == "unknown":
                fill, txt, tw = "#e2e8f0", "未", 400
            else:
                fill, txt, tw = "#7f1d1d", "非法", 700
            b.write('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#c7d3df"/>\n'
                    % (x, y, cw, ch, fill))
            col = "#0b1f33" if txt != "非法" else "#fff"
            b.write('<text x="%d" y="%d" text-anchor="middle" font-weight="%d" fill="%s">%s</text>\n'
                    % (x + cw / 2, y + ch / 2 + 4, tw, col, esc(txt)))
        nk = sum(1 for d in dims if cell_value((v.get("cells") or {}).get(d["id"], {}))[0] == "num")
        b.write('<text x="%d" y="%d" font-size="9.5" fill="#5b6b7f">%d/%d 维有依据</text>\n'
                % (x0 + len(dims) * (cw + gap) + 8, y + ch / 2 + 4, nk, len(dims)))
    yl = y0 + len(verts) * (ch + gap) + 14
    b.write('<text x="%d" y="%d" font-size="9" fill="#5b6b7f">色深＝这一维上占优（原始分 0–%d；'
            '带↓的维反向）；灰格「未」＝未判定，不进总分也不当 0。</text>\n' % (x0, yl, hi))
    if not res.get("error"):
        b.write('<text x="%d" y="%d" font-size="9.5" font-weight="700" fill="#0b6b34">'
                '脚本重算赢家：%s</text>\n' % (x0, yl + 18, esc(res["winner"] or "并列，不造赢家")))
    b.write('</g>\n</svg>\n')
    return b.getvalue()


def totals_table(score, res, tid=None):
    dims = score.get("dimensions", [])
    cap = ('<caption>图 3 的数据层：每格原始分（<b>未</b>＝未判定）、加权好度、'
           '以及这一行的权重只由几维已知分撑起。</caption>' if tid else "")
    b = io.StringIO()
    b.write('<table class="tbl"%s>%s<tr><th>垂类</th>' % (
        (' id="%s"' % tid) if tid else "", cap))
    for d in dims:
        b.write('<th class="num">%s%s</th>' % (esc(d["id"]), "↓" if d.get("low_is_good") else ""))
    b.write('<th class="num">加权好度</th><th class="num">已知权重和</th><th>未判定维</th></tr>\n')
    for r in res["rows"]:
        b.write('<tr><td><strong>%s</strong> %s</td>' % (esc(r["id"]), esc(r["name"][:22])))
        for d in dims:
            v = r["cells"].get(d["id"])
            b.write('<td class="num">%s</td>' % ("未" if v == "unknown" else esc(v)))
        b.write('<td class="num"><strong>%.3f</strong></td><td class="num">%.2f</td>'
                '<td>%s</td></tr>\n' % (r["total"], r["weight_known"],
                                        esc("、".join(r["unknown"]) or "—")))
    b.write('</table>\n')
    return b.getvalue()


def sens_table(sens):
    if sens.get("error"):
        return '<p class="small">敏感性算不出来：%s</p>\n' % esc(sens["error"])
    b = io.StringIO()
    b.write('<table class="tbl"><tr><th>扰动</th><th>赢家</th><th>与基准一致？</th></tr>\n')
    for r in sens["rows"]:
        b.write('<tr><td>%s 权重 %s%.0f%%</td><td>%s</td><td>%s</td></tr>\n'
                % (esc(r["dim"]), r["dir"], sens["pct"] * 100, esc(r["winner"]),
                   "一致" if r["stable"] else "<strong>翻</strong>"))
    b.write('</table>\n')
    if sens["flips"]:
        b.write('<p class="small">⇒ <strong>名次会翻</strong>的扰动：%s。'
                '所以本件给的是带条件的名次，不是排序定律。</p>\n'
                % esc("、".join(sens["flips"])))
    else:
        b.write('<p class="small">⇒ 本轮所有单维 ±%.0f%% 扰动都不翻赢家。'
                '<strong>这不等于结论稳</strong>——扰动只动权重，不动格子本身；'
                '格子里的 unknown 若下一轮补上依据，名次可能整体重排。</p>\n' % (sens["pct"] * 100))
    return b.getvalue()


def ref_row_text(r):
    """附录 A 那一行真正会上屏的字（与 refs_table 的截断长度一致）——D3 数的就是它，
    所以登记件里没被排版的那半句不算进缺席陈述。"""
    return "%s %s %s" % ((r.get("title") or "")[:70],
                         (r.get("how") or "")[:70], (r.get("can_say") or "")[:80])


def refs_table(refs):
    b = io.StringIO()
    b.write('<table class="tbl"><tr><th>号</th><th>件名／出处</th><th>页上日期</th>'
            '<th>状态</th><th>本轮怎么来的</th><th>能说什么</th></tr>\n')
    for r in refs.get("entries", []):
        sc = r.get("scan")
        attr = ' data-scan="%s"' % sc if sc in SCAN_KINDS else ""
        b.write('<tr%s><td>%s</td><td>%s</td><td class="nowrap">%s</td>'
                '<td><span class="tag tag-%s">%s</span></td><td>%s</td><td>%s</td></tr>\n'
                % (attr, esc(r.get("id", "")), esc((r.get("title") or "")[:70]),
                   esc(r.get("date") or "—"), _tag_of(r.get("status", "未")),
                   esc(r.get("status") or "未"), esc((r.get("how") or "")[:70]),
                   esc((r.get("can_say") or "")[:80])))
    b.write('</table>\n')
    return b.getvalue()


def _tag_of(st):
    return {"核": "a", "片": "b", "未": "x", "反": "c"}.get(st, "gray")


def status_counts(refs):
    c = {s: 0 for s in STATUSES}
    for r in refs.get("entries", []):
        s = r.get("status")
        c[s if s in c else "未"] += 1
    return c


def block(name, inner):
    return "%s\n%s\n%s" % (GEN_START % name, inner.rstrip("\n"), GEN_END % name)


def gen_score_html(score, res, sens):
    parts = [heat_svg(score), totals_table(score, res, tid="fig3"),
             ('<p class="figsrc">图 3 · 评分热矩阵。<strong>本块由 工具/出表.py 从 '
              '数据/评分表.json 生成</strong>；手改这段 HTML 会被 工具/文档核对.py 判红。'
              '灰格是「未判定」，不是 0。</p>'),
             ('<p class="small">赢家由脚本重算：同分先比 D2（语义真值来源），再比 D5'
              '（平台挤压风险，反向）；仍同分则判 rc=3，<strong>不造赢家</strong>。</p>')]
    if not res.get("error"):
        parts.append('<p class="small">重算赢家：<strong>%s</strong> ｜ 名次 %s</p>'
                     % (esc(res["winner"] or "无（并列）"),
                        esc(" → ".join(res["ranking"]))))
        if res.get("min_known"):
            line = ('<p class="small">胜出资格线：<strong>≥%d 维有依据</strong>。原因不是严谨，'
                    '是这台机器的一个病理：unknown 既不进分子也不进分母，归一化会<strong>把缺依据'
                    '抬成高分</strong>——在一维上「没证据」恰好躲开了「没证据所以分低」的罚。'
                    '所以下面这行同时给两个东西：<em>原始名次照原样印（不藏）</em>，'
                    '但只有达标者能冠「胜出」。</p>' % res["min_known"])
            parts.append(line)
            nd = len(score.get("dimensions", []))
            nk = {r["id"]: r["n_known"] for r in res.get("rows", [])}
            parts.append('<p class="small">原始排名第一：<strong>%s</strong>（%d/%d 维有依据）'
                         ' ｜ 有资格胜出者：%s ｜ <strong>不得冠「胜出」</strong>：%s</p>'
                         % (esc(res.get("raw_top") or "—"),
                            nk.get(res.get("raw_top"), 0), nd,
                            esc("、".join(res.get("eligible") or []) or "无"),
                            esc("、".join("%s（缺 %s）" % (b["id"], "、".join(b["missing"]) or "—")
                                          for b in res.get("blocked") or []) or "无")))
    parts.append(sens_table(sens))
    return block("SCORE", "\n".join(parts))


def gen_refs_html(refs):
    cnt = status_counts(refs)
    head = ('<p class="small">登记行数由脚本现数：共 <strong>%d</strong> 条 ｜ %s。'
            '只有「核」级的数字允许被排版进正文——这条不是风格：1022 那轮给「待复核」'
            '标注的快照数字仍然进了正文，结果一个判 UNSUPPORTED、一个一手根本取不到。</p>'
            % (len(refs.get("entries", [])),
               " ｜ ".join("%s %d" % (s, cnt[s]) for s in STATUSES)))
    return block("REFS", head + "\n" + refs_table(refs))


def splice(text, name, new_block):
    """替换 HTML 里的 GEN 区间；区间不存在则抛错（绝不静默追加）。"""
    s, e = GEN_START % name, GEN_END % name
    i, j = text.find(s), text.find(e)
    if i < 0 or j < 0 or j < i:
        raise RuntimeError("GEN 区间缺失或顺序错：%s（正文里要先埋好 START/END 注释）" % name)
    return text[:i] + new_block + text[j + len(e):]


def rendered_blocks(html):
    """扫 HTML，返回 {NAME: 区间内文本}，用于漂移比对。"""
    out = {}
    for name in ("SCORE", "REFS"):
        s, e = GEN_START % name, GEN_END % name
        i, j = html.find(s), html.find(e)
        if i >= 0 and j > i:
            out[name] = html[i + len(s):j].strip()
    return out
