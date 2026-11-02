# -*- coding: utf-8 -*-
"""把 原型-源/ 的 CSS / 结构 / 脚本合成单文件 微核台.html，并自检。
用法：python 工具-合并原型.py
控制台只打印 ASCII；产物 UTF-8。
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "原型-源"
OUT = BASE / "微核台.html"


def read(p):
    return p.read_text(encoding="utf-8")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    files = {
        "base.css": SRC / "base.css",
        "v2.css": SRC / "v2.css",
        "body.html": SRC / "body.html",
        "app.js": SRC / "app.js",
    }
    missing = [n for n, p in files.items() if not p.is_file()]
    if missing:
        print("RESULT FAIL missing source:", ",".join(missing))
        return 2
    raw = {n: read(p).encode("utf-8") for n, p in files.items()}
    css = (raw["base.css"].decode("utf-8").rstrip() + "\n\n/* ===== v2 ===== */\n\n" + raw["v2.css"].decode("utf-8").rstrip() + "\n")
    body = raw["body.html"].decode("utf-8").rstrip()
    app = raw["app.js"].decode("utf-8").rstrip()

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(("PASS " if ok else "FAIL ") + name + ((" " + detail) if detail and not ok else ""))

    check("css braces balanced", css.count("{") == css.count("}"), f"open={css.count('{')} close={css.count('}')}")
    check("no external stylesheet", "<link" not in body.lower() and "@import" not in css.lower())
    check("no external script", not re.search(r"<script[^>]+src=", body, re.I))
    check("no external url()", "url(http" not in css.lower() and "url(//" not in css.lower())
    check("no closing script in js", "</script" not in app.lower())
    check("no external anchor", not re.search(r'href="(https?:)?//', body, re.I))
    check("single inline script", body.count("<script") == 0 and app.count("<script") == 0)

    body_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', body))
    dyn_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', app))
    required = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", app)) | set(re.findall(r"\$\$\('#([A-Za-z0-9_-]+)", app))
    miss_ids = sorted(required - body_ids - dyn_ids)
    check("all script ids exist", not miss_ids, "missing=" + ",".join(miss_ids))

    defined = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    used = set()
    for m in re.findall(r'class="([^"]*)"', body):
        for tok in m.split():
            if re.fullmatch(r"[a-z][a-z0-9-]*", tok):
                used.add(tok)
    for tok in re.findall(r'class="([a-z][a-z0-9-]+)', app):
        used.add(tok)
    miss_cls = sorted(used - defined)
    check("all first classes styled", not miss_cls, "missing=" + ",".join(miss_cls))

    for anchor in ['id="kernelPill"', 'id="view-dialogue"', 'id="view-memory"', 'id="chatForm"', 'id="queueFoot"']:
        check("anchor " + anchor, anchor in body)

    node = shutil.which("node")
    if node:
        td = tempfile.mkdtemp(prefix="weihetai-check-")
        try:
            p = Path(td) / "app.js"
            p.write_bytes(raw["app.js"])
            r = subprocess.run([node, "--check", str(p)], capture_output=True)
            check("node --check app.js", r.returncode == 0, (r.stderr or b"").decode("utf-8", "replace")[-300:])
        finally:
            shutil.rmtree(td, ignore_errors=True)
    else:
        print("SKIP node --check (node not on PATH)")

    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"color-scheme\" content=\"light\">\n"
        "<title>微核台 · 本地交付取证</title>\n"
        "<style>\n" + css + "</style>\n</head>\n<body>\n"
        + body + "\n<script>\n" + app + "\n</script>\n</body>\n</html>\n"
    )
    data = html.encode("utf-8")
    tmp = OUT.with_suffix(".html.part")
    tmp.write_bytes(data)
    os.replace(tmp, OUT)

    print("SOURCE")
    for n in ("base.css", "v2.css", "body.html", "app.js"):
        b = raw[n]
        print("  " + n + " bytes=" + str(len(b)) + " sha256=" + sha(b))
    print("OUT " + OUT.name.encode("ascii", "backslashreplace").decode("ascii"))
    print("BYTES " + str(len(data)))
    print("LINES " + str(html.count("\n")))
    print("SHA256 " + sha(data))
    bad = [c for c in checks if not c[1]]
    print("CHECKS " + str(len(checks) - len(bad)) + "/" + str(len(checks)))
    print("RESULT " + ("PASS" if not bad else "FAIL"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
