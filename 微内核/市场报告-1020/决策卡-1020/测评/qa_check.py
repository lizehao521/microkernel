#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策卡机械测评：单页、自包含、禁用宣称、必备声明、对比度、证据状态。
主卡应全绿；反臂（故意夸大版）应至少让禁用宣称/必备声明/证据状态三项转红。
"""
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
CARD_HTML = ROOT / "decision-card.html"
CARD_PDF = ROOT / "decision-card.pdf"
ANTI_HTML = EVAL / "anti-arm.html"
ANTI_PDF = EVAL / "anti-arm.pdf"
MEASURE_JS = ROOT / "measure_card.js"
NODE = r"C:\Users\Admin\AppData\Local\Programs\Qoder CN\Qoder CN.exe"
OUT_JSON = EVAL / "qa-results.json"
OUT_MD = EVAL / "机械测评结果.md"

VOID = {"br", "meta", "link", "img", "hr", "input", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.all_parts = []
        self.positive_parts = []
        self.cant_depth = 0
        self.in_style = 0
        self.in_script = 0

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self.in_style += 1
            return
        if tag == "script":
            self.in_script += 1
            return
        if self.cant_depth:
            if tag not in VOID:
                self.cant_depth += 1
            return
        if tag == "div" and "cant" in (dict(attrs).get("class") or "").split():
            self.cant_depth = 1
            return
        if tag == "br":
            self.all_parts.append(" ")
            self.positive_parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "style" and self.in_style:
            self.in_style -= 1
            return
        if tag == "script" and self.in_script:
            self.in_script -= 1
            return
        if self.cant_depth and tag not in VOID:
            self.cant_depth -= 1

    def handle_data(self, data):
        if self.in_style or self.in_script:
            return
        self.all_parts.append(data)
        if not self.cant_depth:
            self.positive_parts.append(data)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def extract_texts(html_text):
    p = TextExtractor()
    p.feed(html_text)
    return norm("".join(p.all_parts)), norm("".join(p.positive_parts))


def pdf_pages(pdf_path):
    if not pdf_path.exists():
        return None, "文件不存在"
    p = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
                       capture_output=True, timeout=120)
    if p.returncode != 0:
        return None, "pdftotext rc=%d" % p.returncode
    text = p.stdout.decode("utf-8", "replace")
    return text.count("\f"), "form-feed count"


def measure_layout(html_path):
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        p = subprocess.run([NODE, str(MEASURE_JS), str(html_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=150, env=env)
    except Exception as e:
        return None, "measure 调用失败: %s" % e
    if p.returncode != 0:
        return None, "measure rc=%d: %s" % (p.returncode, (p.stderr or "").strip()[:300])
    try:
        return json.loads(p.stdout), "CDP"
    except Exception as e:
        return None, "measure 输出非 JSON: %s" % e


def hex_lum(c):
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def lin(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg, bg):
    a, b = hex_lum(fg), hex_lum(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def rule_block(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else None


def resolve_color(raw, css):
    raw = (raw or "").strip()
    m = re.match(r"var\(\s*(--[\w-]+)\s*\)", raw)
    if m:
        vm = re.search(re.escape(m.group(1)) + r"\s*:\s*(#[0-9a-fA-F]{3,6})", css)
        return vm.group(1) if vm else None
    return raw if re.fullmatch(r"#[0-9a-fA-F]{3,6}", raw) else None


# selector, background, 用途
CONTRAST_PAIRS = [
    (".foot .fine", "#ffffff", "页脚免责小字"),
    (".foot .src", "#ffffff", "页脚来源"),
    (".foot .legend", "#ffffff", "证据分级图例"),
    (".sec-h .note", "#ffffff", "章节右侧说明"),
    (".decide .head .t", "#ecfdf5", "00 决策带标题"),
    (".decide .head .n", "#ecfdf5", "00 决策带说明"),
    (".decide .ask .n", "#ecfdf5", "00 决策序号"),
    (".decide .ask .why", "#ecfdf5", "00 决策理由"),
    (".gap-list li", "#ffffff", "01 缺口列表"),
    (".card .detail", "#fbfefd", "02 证据卡正文"),
    (".badge.x", "#fef2f2", "X 徽标"),
    (".badge.a", "#ecfdf5", "A 徽标"),
    (".poc .col li", "#ecfdf5", "04 试点三列"),
    (".poc .fine", "#ecfdf5", "04 试点小字"),
    (".who .trig", "#f6f8fa", "01 触发条件"),
]

FORBIDDEN = [
    ("闭环已通", r"闭环已通"),
    ("30 分钟接入", r"30\s*分钟接入"),
    ("内容可信", r"内容可信"),
    ("攻击已被挡住", r"攻击已被挡住"),
    ("挡住提示注入", r"挡住(?:提示注入|攻击)"),
    ("自动改进已有效", r"自动改进已有效"),
    ("符合 EU AI Act", r"符合\s*EU\s*AI\s*Act"),
    ("审计层就是防线", r"审计层(?:就是|是)防线"),
    ("托管按次", r"托管按次"),
    ("成熟平台（非否定）", r"(?<!不是)成熟平台"),
    ("所有项均", r"所有项均"),
    ("R/N 双臂 +N", r"R/N\s*双臂\s*\+\s*\d"),
    ("已通过合规认证", r"已通过合规认证"),
    ("保证做出", r"保证做出"),
    ("已服务多家", r"已服务多家"),
]

REQUIRED = [
    ("NOT_RUN 标记", "NOT_RUN"),
    ("不构成合规认证", "不构成合规认证"),
    ("审计层不是防线", "审计层不是防线"),
    ("不能证明", "不能证明"),
    ("当前缺口", "当前缺口"),
    ("未验证", "未验证"),
    ("不接你的模型调用", "不接你的模型调用"),
    ("做不出不收尾款", "做不出可复核证据包，不收尾款"),
    ("不是成熟平台", "不是成熟平台"),
    ("不塌成 0", "不塌成 0"),
    ("A 级读数", "2,940 / 2,940"),
]


def evaluate(name, html_path, pdf_path):
    checks = []
    html_text = html_path.read_text(encoding="utf-8")
    all_text, positive_text = extract_texts(html_text)
    css_match = re.search(r"<style[^>]*>(.*?)</style>", html_text, re.S)
    css = css_match.group(1) if css_match else ""

    pages, pages_ev = pdf_pages(pdf_path)
    if pages is None:
        checks.append({"id": "P1", "name": "PDF 单页", "status": "NOT_RUN", "evidence": pages_ev})
    else:
        checks.append({"id": "P1", "name": "PDF 单页", "status": "PASS" if pages == 1 else "FAIL",
                       "evidence": "pages=%d（%s）" % (pages, pages_ev)})

    layout, layout_ev = measure_layout(html_path)
    if layout is None:
        checks.append({"id": "P2", "name": "A4 无纵向溢出", "status": "NOT_RUN", "evidence": layout_ev})
        checks.append({"id": "P3", "name": "页脚在纸面内", "status": "NOT_RUN", "evidence": layout_ev})
    else:
        body_ok = layout["bodyScroll"] <= layout["bodyClient"] + 1
        checks.append({"id": "P2", "name": "A4 无纵向溢出", "status": "PASS" if body_ok else "FAIL",
                       "evidence": "bodyScroll=%s bodyClient=%s" % (layout["bodyScroll"], layout["bodyClient"])})
        foot = layout.get("foot") or {}
        sheet = layout.get("sheet") or {}
        foot_ok = bool(foot) and bool(sheet) and foot.get("bottom", 1e9) <= sheet.get("bottom", -1e9) + 1
        checks.append({"id": "P3", "name": "页脚在纸面内", "status": "PASS" if foot_ok else "FAIL",
                       "evidence": "foot.bottom=%s sheet.bottom=%s" % (foot.get("bottom"), sheet.get("bottom"))})

    ext = re.findall(r'(?:src|href)\s*=\s*["\']\s*https?://', html_text, re.I)
    imports = re.findall(r"@import", html_text, re.I)
    urls = re.findall(r"url\(\s*[\"']?\s*https?://", html_text, re.I)
    checks.append({"id": "P4", "name": "无外部资源", "status": "PASS" if not (ext or imports or urls) else "FAIL",
                   "evidence": "src/href=%d @import=%d url(http)=%d" % (len(ext), len(imports), len(urls))})

    hits = []
    for label, pat in FORBIDDEN:
        found = sorted(set(re.findall(pat, positive_text)))
        if found:
            hits.append({"label": label, "pattern": pat, "samples": found[:3]})
    # 证明负面清单块确实被剔除：同一禁用短语出现在全文、但不在正面文本里
    neg_isolated = [label for label, pat in FORBIDDEN
                    if re.search(pat, all_text) and not re.search(pat, positive_text)]
    if hits:
        p5_status, p5_ev = "FAIL", "命中 %d 类：%s；负面块隔离 %d 类" % (
            len(hits), "、".join(h["label"] for h in hits), len(neg_isolated))
    elif len(neg_isolated) < 3:
        p5_status, p5_ev = "FAIL", "正面 0 类，但负面块只隔离 %d 类，剔除逻辑未被验证" % len(neg_isolated)
    else:
        p5_status, p5_ev = "PASS", "正面 0 类；负面清单块内隔离 %d 类，剔除逻辑已执行" % len(neg_isolated)
    checks.append({"id": "P5", "name": "禁用宣称（正面文本）", "status": p5_status, "evidence": p5_ev})

    missing = [label for label, needle in REQUIRED if needle not in all_text]
    checks.append({"id": "P6", "name": "必备声明齐全", "status": "PASS" if not missing else "FAIL",
                   "evidence": "缺失 %d 项：%s" % (len(missing), "、".join(missing)) if missing else "11/11 齐全"})

    not_run_count = all_text.count("NOT_RUN")
    x_badges = len(re.findall(r'class="badge x"', html_text))
    ev_ok = not_run_count >= 2 and x_badges >= 2 and "2,940 / 2,940" in all_text
    checks.append({"id": "P7", "name": "证据状态不塌", "status": "PASS" if ev_ok else "FAIL",
                   "evidence": "NOT_RUN=%d X徽标=%d A读数=%s" % (not_run_count, x_badges, "有" if "2,940 / 2,940" in all_text else "无")})

    ratios = []
    for selector, bg, label in CONTRAST_PAIRS:
        block = rule_block(css, selector)
        if block is None:
            ratios.append({"selector": selector, "label": label, "status": "NOT_RUN", "ratio": None, "fg": None, "bg": bg})
            continue
        m = re.search(r"(?<!-)color:\s*([^;}]+)", block)
        fg = resolve_color(m.group(1), css) if m else None
        if not fg:
            ratios.append({"selector": selector, "label": label, "status": "FAIL", "ratio": None, "fg": None, "bg": bg})
            continue
        r = contrast(fg, bg)
        ratios.append({"selector": selector, "label": label, "status": "PASS" if r >= 4.5 else "FAIL",
                       "ratio": r, "fg": fg, "bg": bg})
    bad_ratios = [x for x in ratios if x["status"] == "FAIL"]
    n_ratio_pass = len([x for x in ratios if x["status"] == "PASS"])
    n_ratio_na = len([x for x in ratios if x["status"] == "NOT_RUN"])
    min_ratio = min((x["ratio"] for x in ratios if x["ratio"] is not None), default=None)
    p8_ev = "%d/%d 对达标，最小 %.2f" % (n_ratio_pass, len(ratios), min_ratio or 0)
    if n_ratio_na:
        p8_ev += "；%d 项选择器不适用" % n_ratio_na
    checks.append({"id": "P8", "name": "正文对比度 ≥4.5", "status": "PASS" if not bad_ratios else "FAIL",
                   "evidence": p8_ev})

    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)pt", css)]
    min_pt = min(sizes) if sizes else None
    checks.append({"id": "P9", "name": "最小字号 ≥6pt", "status": "PASS" if min_pt is not None and min_pt >= 6.0 else "FAIL",
                   "evidence": "min=%spt，共 %d 处" % (min_pt, len(sizes))})

    decide = (layout or {}).get("decide")
    if layout is None:
        checks.append({"id": "P10", "name": "三个决定在页面上半部", "status": "NOT_RUN", "evidence": layout_ev})
    elif not decide:
        checks.append({"id": "P10", "name": "三个决定在页面上半部", "status": "NOT_RUN",
                       "evidence": "未找到 .decide（反臂不适用）"})
    else:
        mid = (layout.get("sheet") or {}).get("top", 0) + (layout.get("sheet") or {}).get("height", 0) / 2
        decide_ok = decide.get("bottom", 1e9) <= mid + 1
        style_ok = ".decide .head .t" in css and ".decide .ask .why" in css
        checks.append({"id": "P10", "name": "三个决定在页面上半部", "status": "PASS" if decide_ok and style_ok else "FAIL",
                       "evidence": "decide.bottom=%.1f mid=%.1f；样式%s" % (
                           decide.get("bottom", 0), mid, "在" if style_ok else "缺失")})

    summary = {"pass": 0, "fail": 0, "not_run": 0}
    for c in checks:
        summary[c["status"].lower()] += 1
    return {
        "name": name,
        "html": str(html_path),
        "pdf": str(pdf_path),
        "checks": checks,
        "summary": summary,
        "forbidden_hits": hits,
        "missing_markers": missing,
        "contrast": ratios,
        "min_font_pt": min_pt,
        "layout": layout,
        "visible_chars": len(all_text),
        "positive_chars": len(positive_text),
        "pdf_pages": pages,
    }


def table(rows):
    out = ["| 检查 | 结果 | 读数 |", "| --- | --- | --- |"]
    for c in rows:
        icon = {"PASS": "PASS", "FAIL": "FAIL", "NOT_RUN": "NOT_RUN"}[c["status"]]
        out.append("| %s %s | %s | %s |" % (c["id"], c["name"], icon, c["evidence"]))
    return "\n".join(out)


def main():
    for p in (CARD_HTML, CARD_PDF, ANTI_HTML, ANTI_PDF, MEASURE_JS):
        if not p.exists():
            print("MISSING " + str(p))
            return 1

    card = evaluate("主卡", CARD_HTML, CARD_PDF)
    anti = evaluate("反臂（故意夸大）", ANTI_HTML, ANTI_PDF)

    card_red = {c["id"] for c in card["checks"] if c["status"] == "FAIL"}
    anti_red = {c["id"] for c in anti["checks"] if c["status"] == "FAIL"}
    sensitivity_ids = ["P5", "P6", "P7"]
    sensitivity = {
        "ruler_turns_red": all(i in anti_red for i in sensitivity_ids),
        "card_green_on_same": all(i not in card_red for i in sensitivity_ids),
        "anti_red": sorted(anti_red),
        "card_red": sorted(card_red),
    }

    result = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "method": "机械检查：pdftotext 页数 + Edge CDP 布局测量 + HTML 文本/ CSS 静态解析；不含真人",
        "card": card,
        "anti_arm": anti,
        "sensitivity": sensitivity,
        "human_status": "NOT_RUN",
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md = []
    md.append("# 决策卡机械测评结果")
    md.append("")
    md.append("- **生成时间**：%s" % result["generated_at"])
    md.append("- **方法**：%s" % result["method"])
    md.append("- **真人可用性测试**：NOT_RUN（本机无目标读者，未伪造通过率）")
    md.append("")
    md.append("## 主卡 `decision-card.html / .pdf`")
    md.append("")
    md.append(table(card["checks"]))
    md.append("")
    md.append("汇总：PASS %d / FAIL %d / NOT_RUN %d；PDF %s 页；可见文本 %d 字；正面文本 %d 字。" %
              (card["summary"]["pass"], card["summary"]["fail"], card["summary"]["not_run"],
               card["pdf_pages"], card["visible_chars"], card["positive_chars"]))
    md.append("")
    md.append("## 反臂 `测评/anti-arm.html / .pdf`（故意夸大，用作阴性对照）")
    md.append("")
    md.append(table(anti["checks"]))
    md.append("")
    md.append("汇总：PASS %d / FAIL %d / NOT_RUN %d。" %
              (anti["summary"]["pass"], anti["summary"]["fail"], anti["summary"]["not_run"]))
    md.append("")
    md.append("## 灵敏度：尺子会不会红")
    md.append("")
    md.append("- 反臂转红项：%s" % ("、".join(sorted(anti_red)) if anti_red else "无"))
    md.append("- 主卡转红项：%s" % ("、".join(sorted(card_red)) if card_red else "无"))
    md.append("- 判定：禁用宣称 / 必备声明 / 证据状态三项，主卡绿、反臂红 → **%s**" %
              ("尺子可红" if sensitivity["ruler_turns_red"] and sensitivity["card_green_on_same"] else "灵敏度未成立"))
    md.append("")
    if anti["forbidden_hits"]:
        md.append("反臂命中的禁用宣称：")
        for h in anti["forbidden_hits"]:
            md.append("- **%s**：`%s` → %s" % (h["label"], h["pattern"], "、".join(h["samples"])))
        md.append("")
    if anti["missing_markers"]:
        md.append("反臂缺失的必备声明：%s" % "、".join(anti["missing_markers"]))
        md.append("")
    md.append("## 对比度明细（主卡）")
    md.append("")
    md.append("| 选择器 | 用途 | 前景 / 背景 | 比值 | 结果 |")
    md.append("| --- | --- | --- | --- | --- |")
    for r in card["contrast"]:
        md.append("| `%s` | %s | %s / %s | %s | %s |" %
                  (r["selector"], r["label"], r["fg"], r["bg"], r["ratio"], r["status"]))
    md.append("")
    md.append("最小字号：%s pt（阈值 6 pt）。" % card["min_font_pt"])
    md.append("")
    md.append("## 边界")
    md.append("")
    md.append("- 机械项通过只说明「单页、自包含、措辞未越界、对比度达标」，**不等于**目标读者能读懂、会相信、愿意见面。")
    md.append("- 反臂只用于证明尺子会红，不是可比稿，也不对外。")
    md.append("- 真人 5 秒 / 理解 / 信任 / POC 意向测试：NOT_RUN。方案见 `测评方案.md`。")
    md.append("- AI 模拟读者结论另册记录，标注「非真人、不计入通过率」。")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print("CARD PASS=%d FAIL=%d NOTRUN=%d pages=%s" %
          (card["summary"]["pass"], card["summary"]["fail"], card["summary"]["not_run"], card["pdf_pages"]))
    print("ANTI PASS=%d FAIL=%d NOTRUN=%d red=%s" %
          (anti["summary"]["pass"], anti["summary"]["fail"], anti["summary"]["not_run"], ",".join(sorted(anti_red))))
    print("SENSITIVITY=%s" % ("OK" if sensitivity["ruler_turns_red"] and sensitivity["card_green_on_same"] else "FAILED"))
    print("OUT=%s" % OUT_MD)
    return 0 if not card_red and sensitivity["ruler_turns_red"] and sensitivity["card_green_on_same"] else 2


if __name__ == "__main__":
    sys.exit(main())
