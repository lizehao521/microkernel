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
    "03-ch1-3.html",
    "04-ch4-6.html",
    "05-ch7-8.html",
    "06-ch9-12.html",
    "07-appendix.html",
]
TMP_HTML = Path("C:/Users/Admin/agentkernel-market-1020.html")
TMP_PDF = Path("C:/Users/Admin/agentkernel-market-1020.pdf")
FINAL_HTML = ROOT / "报告.html"
FINAL_PDF = ROOT / "agentkernel-市场进入重评-1020.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
NODE_SCRIPT = ROOT / "print_cdp.js"
NODE_CANDIDATES = [
    os.environ.get("NODE_EXE", ""),
    r"C:\Users\Admin\AppData\Local\Programs\Qoder CN\Qoder CN.exe",
    "node",
]

KEY_TEXT = {
    "exec": "00重评摘要与建议",
    "ch1": "01为什么要重评",
    "s1-1": "1.1v1的结论与它的前提",
    "s1-2": "1.2变了什么：从账本到证据包",
    "s1-3": "1.3重评问题与判据",
    "ch2": "02市场与定位",
    "s2-1": "2.1市场边界：记账层不是可观测性",
    "s2-2": "2.2规模重算：为什么下调SAM",
    "s2-3": "2.3买家与预算科目",
    "ch3": "03需求与反需求",
    "ch4": "04竞争格局：功能，还是平台",
    "ch5": "05产品证据现状",
    "ch6": "06五条进入方式重评",
    "s6-a": "选项A：开源证据适配层",
    "s6-b": "选项B：企业私有化",
    "s6-c": "选项C：托管按次",
    "s6-d": "选项D：研究出版/标准",
    "s6-e": "选项E：竞赛/生态",
    "ch7": "07推荐路线与五道闸",
    "s7-2": "7.3五道闸：Go/No-Go",
    "ch8": "08定价与单位经济",
    "ch9": "09风险登记与红队",
    "ch10": "10实施路线图（26周）",
    "ch11": "11财务情景",
    "ch12": "12结论",
    "appA": "A方法与证据分级",
    "appB": "B数据表",
    "appC": "C参考文献",
    "appD": "D术语与对外材料草稿",
    "fig1": "图1修订后的市场层级",
    "fig2": "图2证据层在价值链中的位置",
    "fig3": "图3竞争定位",
    "fig4": "图4证据阶梯",
    "fig5": "图5五条进入方式矩阵",
    "fig6": "图6决策树",
    "fig7": "图7风险热图",
    "fig8": "图826周路线",
    "fig9": "图9三情景收入",
    "tab1": "表1v1与v2的差异",
    "tab2": "表2市场边界",
    "tab3": "表3规模三路交叉",
    "tab4": "表4买家、触发与预算科目",
    "tab5": "表5五类玩家",
    "tab6": "表6能说/不能说",
    "tab7": "表7五条进入方式对比",
    "tab8": "表8五道闸",
    "tab9": "表9价格梯子",
    "tab10": "表10风险登记",
    "tab11": "表11三情景财务",
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
