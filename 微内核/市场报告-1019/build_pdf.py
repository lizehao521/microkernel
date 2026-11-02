#!/usr/bin/env python3
"""Build the market-entry report PDF and backfill TOC page numbers."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PARTS = [
    "00-head.html",
    "01-cover-toc.html",
    "02-exec.html",
    "03-ch1-2.html",
    "04-ch3-5.html",
    "05-ch6-8.html",
    "06-ch9-13.html",
    "07-appendix.html",
]
TMP_HTML = Path("C:/Users/Admin/agentkernel-market-1019.html")
TMP_PDF = Path("C:/Users/Admin/agentkernel-market-1019.pdf")
FINAL_HTML = ROOT / "报告.html"
FINAL_PDF = ROOT / "agentkernel-市场进入研究-1019.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
NODE_SCRIPT = ROOT / "print_cdp.js"
NODE_CANDIDATES = [
    os.environ.get("NODE_EXE", ""),
    r"C:\Users\Admin\AppData\Local\Programs\Qoder CN\Qoder CN.exe",
    "node",
]

KEY_TEXT = {
    "exec": "00摘要与建议",
    "ch1": "01研究对象与问题",
    "s1-1": "为什么是agentkernel，不是26策略引擎",
    "s1-2": "产品是什么、不是什么",
    "s1-3": "两种失效：说法漂白与事后拿不出",
    "ch2": "02市场定义与规模",
    "s2-2": "三路自上而下",
    "s2-3": "自下而上：账户数",
    "s2-4": "三角校验与SOM",
    "ch3": "03需求驱动",
    "ch4": "04竞争格局",
    "s4-1": "五类玩家",
    "s4-2": "价格锚：为什么不能按",
    "ch5": "05客户细分与购买旅程",
    "ch6": "06产品与证据现状",
    "s6-1": "能说的：A/B级证据",
    "s6-2": "不能说的：X级缺口",
    "ch7": "07市场进入方式：五个选项",
    "s7-1": "选项A：开源/开放核心",
    "s7-2": "选项B：企业私有化许可",
    "s7-3": "选项C：托管按次证据服务",
    "s7-4": "选项D：研究出版/标准",
    "s7-5": "选项E：竞赛/生态",
    "ch8": "08推荐路线与四道闸",
    "s8-2": "三个阶段与交付物",
    "s8-3": "四道闸：Go/No-Go",
    "ch9": "09定价与单位经济",
    "ch10": "10风险登记与热图",
    "ch11": "11实施路线图（26周）",
    "ch12": "12财务情景与继续/冻结判据",
    "ch13": "13结论",
    "appA": "方法与证据分级",
    "appB": "B数据表",
    "appC": "C参考文献",
    "appD": "D术语表",
    "appE": "E对外材料草稿",
    "fig1": "图1·市场层级",
    "fig2": "图2·三路自上而下",
    "fig3": "图3·账户数",
    "fig4": "图4·竞争定位",
    "fig5": "图5·五力",
    "fig6": "图6·证据阶梯",
    "fig7": "图7·进入方式矩阵",
    "fig8": "图8·决策树",
    "fig9": "图9·风险热图",
    "fig10": "图10·26周路线",
    "fig11": "图11·三情景收入",
    "tab1": "表1·研究对象对比",
    "tab2": "表2·市场边界",
    "tab3": "表3·三路自上而下",
    "tab4": "表4·自下而上假设",
    "tab5": "表5·合规映射",
    "tab6": "表6·五类玩家",
    "tab7": "表7·公开价格锚",
    "tab8": "表8·客户细分",
    "tab9": "表9·能说的",
    "tab10": "表10·不能说的",
    "tab11": "表11·进入方式对比",
    "tab12": "表12·四道闸",
    "tab13": "表13·单位经济",
    "tab14": "表14·风险登记",
    "tab15": "表15·财务情景",
}


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def assemble(pages: dict) -> str:
    html = "".join((SRC / name).read_text(encoding="utf-8") for name in PARTS)
    pattern = re.compile(r'<td class="pg" data-key="([^"]+)">\s*</td>')

    def repl(match):
        key = match.group(1)
        return '<td class="pg" data-key="%s">%s</td>' % (key, pages.get(key, ""))

    return pattern.sub(repl, html)


def render(html: str) -> None:
    TMP_HTML.write_text(html, encoding="utf-8")
    if TMP_PDF.exists():
        TMP_PDF.unlink()
    env = os.environ.copy()
    last_error = None
    for node in NODE_CANDIDATES:
        if not node:
            continue
        if node != "node" and not Path(node).exists():
            continue
        env["ELECTRON_RUN_AS_NODE"] = "1"
        proc = subprocess.run(
            [node, str(NODE_SCRIPT), str(TMP_HTML), str(TMP_PDF)],
            capture_output=True,
            timeout=180,
            env=env,
        )
        if proc.returncode == 0:
            break
        last_error = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        print("NODE_PRINT_RC", proc.returncode, last_error)
    else:
        raise SystemExit("CDP_PRINT_FAILED")
    last = -1
    stable = 0
    for _ in range(120):
        if TMP_PDF.exists():
            size = TMP_PDF.stat().st_size
            if size == last and size > 10000:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
            last = size
        time.sleep(0.5)
    raise SystemExit("PDF_NOT_STABLE")


def extract_pages() -> list:
    proc = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(TMP_PDF), "-"],
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        print(proc.stderr.decode("utf-8", errors="replace"))
        raise SystemExit("PDFTOTEXT_FAILED")
    text = proc.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    if pages and pages[-1].strip() == "":
        pages.pop()
    return pages


def build_map(pages: list) -> tuple:
    normalized = [norm(p) for p in pages]
    start = None
    for i, text in enumerate(normalized):
        if "图表读法" in text:
            start = i + 1
            break
    if start is None:
        raise SystemExit("INDEX_END_NOT_FOUND")
    result = {}
    missing = []
    for key, needle in KEY_TEXT.items():
        target = norm(needle)
        found = None
        for i in range(start, len(normalized)):
            if target in normalized[i]:
                found = i + 1
                break
        if found is None:
            missing.append(key)
        else:
            result[key] = str(found)
    return result, missing, start + 1


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not EDGE.exists():
        raise SystemExit("EDGE_NOT_FOUND")
    keys = set(re.findall(r'data-key="([^"]+)"', (SRC / "01-cover-toc.html").read_text(encoding="utf-8")))
    unknown = keys - set(KEY_TEXT)
    if unknown:
        print("NO_SEARCH_TEXT_FOR:", ",".join(sorted(unknown)))
        return 1

    pages_map = {}
    missing = []
    page_count = 0
    body_start = 0
    for iteration in range(1, 6):
        html = assemble(pages_map)
        render(html)
        pages = extract_pages()
        page_count = len(pages)
        new_map, missing, body_start = build_map(pages)
        print("PASS", iteration, "pages", page_count, "filled", len(new_map), "missing", len(missing))
        if new_map == pages_map:
            break
        pages_map = new_map
    else:
        print("MAP_NOT_STABLE")
        return 1

    if missing:
        print("MISSING_KEYS:", ",".join(missing))
        return 1

    empty_left = len(re.findall(r'<td class="pg" data-key="[^"]+">\s*</td>', assemble(pages_map)))
    if empty_left:
        print("EMPTY_KEYS_LEFT:", empty_left)
        return 1

    final_html = assemble(pages_map)
    FINAL_HTML.write_text(final_html, encoding="utf-8")

    extract = "\n".join(pages)
    if re.search(r"sk-[A-Za-z0-9]{16,}", extract):
        print("SECRET_PATTERN_FOUND")
        return 1

    FINAL_PDF.write_bytes(TMP_PDF.read_bytes())
    pdf_bytes = FINAL_PDF.stat().st_size
    html_bytes = FINAL_HTML.stat().st_size
    cjk = len(re.findall(r"[\u4e00-\u9fff]", extract))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    manifest = []
    manifest.append("REPORT MANIFEST")
    manifest.append("built_at=%s" % stamp)
    manifest.append("html=%s" % FINAL_HTML.name)
    manifest.append("pdf=%s" % FINAL_PDF.name)
    manifest.append("pdf_pages=%d" % page_count)
    manifest.append("pdf_bytes=%d" % pdf_bytes)
    manifest.append("html_bytes=%d" % html_bytes)
    manifest.append("pdf_sha256=%s" % sha256(FINAL_PDF))
    manifest.append("html_sha256=%s" % sha256(FINAL_HTML))
    manifest.append("cjk_chars_extracted=%d" % cjk)
    manifest.append("toc_keys_expected=%d" % len(keys))
    manifest.append("toc_keys_filled=%d" % len(pages_map))
    manifest.append("body_start_page=%d" % body_start)
    manifest.append("edge=%s" % EDGE)
    manifest.append("render=Microsoft Edge headless via CDP Page.printToPDF, custom footer, no URL")
    manifest.append("extract=pdftotext -enc UTF-8")
    manifest.append("missing_keys=0")
    manifest.append("secret_pattern=0")
    (ROOT / "MANIFEST.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    print("PDF_ONLY_BYTES", pdf_bytes)
    print("PAGES", page_count)
    print("CJK", cjk)
    print("KEYS", len(pages_map))
    print("SHA256", sha256(FINAL_PDF))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
