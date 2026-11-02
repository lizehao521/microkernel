# -*- coding: utf-8 -*-
"""Merge 原型-源/{style.css,body.html,app.js} into one self-contained HTML.

Reads/writes UTF-8 with LF endings; stdout stays ASCII (GBK console safe).
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "原型-源")
OUT = os.path.join(HERE, "收货台-原型.html")


def read(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return f.read()


def main():
    css = read("style.css")
    body = read("body.html")
    js = read("app.js")

    if body.count("/*__STYLE__*/") != 1 or body.count("/*__SCRIPT__*/") != 1:
        print("FAIL: placeholder count != 1")
        return 1

    html = body.replace("/*__STYLE__*/", css).replace("/*__SCRIPT__*/", js)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    raw = open(OUT, encoding="utf-8").read()
    checks = [
        ("placeholders_left", raw.count("/*__STYLE__*/") + raw.count("/*__SCRIPT__*/"), 0),
        ("style_tags", raw.count("<style>"), 1),
        ("script_tags", raw.count("<script>"), 1),
        ("external_src", raw.count('src="http') + raw.count('href="http') + raw.count("@import"), 0),
        ("cdn_mentions", raw.count("cdn.") + raw.count("unpkg") + raw.count("jsdelivr"), 0),
        ("queue_rows", raw.count('id="queueRows"'), 1),
        ("claim_rows", raw.count('id="claimRows"'), 1),
        ("status_banner", raw.count('id="statusBanner"'), 1),
        ("drawer", raw.count('id="drawer"'), 1),
        ("cellgrid_css", raw.count(".cellgrid"), 1),
        ("verdict_unk", raw.count(".verdict.unk {") + raw.count(".verdict.unk .dot"), 2),
        ("tok_style", raw.count("--paper:"), 1),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += 0 if ok else 1
        print("%-18s %s got=%d want=%d" % (name, "ok" if ok else "FAIL", got, want))

    data = raw.encode("utf-8")
    print("bytes=%d lines=%d sha256=%s" % (len(data), raw.count("\n"), hashlib.sha256(data).hexdigest()))
    print("BALANCED style:%d/%d script:%d/%d braces:%d/%d"
          % (raw.count("<style"), raw.count("</style>"),
             raw.count("<script"), raw.count("</script>"),
             raw.count("{"), raw.count("}")))
    print("RESULT " + ("PASS" if bad == 0 else "FAIL %d" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
