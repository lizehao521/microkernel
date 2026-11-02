#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付对账-1026 验收：三份样例 + HTML 结构 + 只读性 + 臂检。控制台只印 ASCII。"""
import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PRODUCT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(PRODUCT, "工具", "对账单.py")
ARM_TOOL = os.path.join(PRODUCT, "工具", "臂检-对账单.py")
OUTDIR = os.path.join(PRODUCT, "读数")

SAMPLES = [
    {
        "key": "good",
        "name": "对账单-示例-好交付",
        "spec": os.path.join(PRODUCT, "示例-编程", "交付声明.json"),
        "rc": 0,
        "status": "ACCEPTED",
        "claims": 8,
        "disk": 8,
        "self": 0,
        "verdicts": {"C%d" % i: "MATCH" for i in range(1, 9)},
        "sources": {},
        "checks": {},
    },
    {
        "key": "bad",
        "name": "对账单-示例-谎报",
        "spec": os.path.join(PRODUCT, "示例-编程-谎报", "交付声明.json"),
        "rc": 2,
        "status": "NOT-ACCEPTED-MISMATCH",
        "claims": 8,
        "disk": 8,
        "self": 0,
        "verdicts": dict([("C%d" % i, "MISMATCH") for i in range(1, 6)]
                         + [("C%d" % i, "MATCH") for i in range(6, 9)]),
        "sources": {},
        "checks": {},
    },
    {
        "key": "real",
        "name": "对账单-真端点",
        "spec": os.path.join(PRODUCT, "样例", "交付声明-真端点.json"),
        "rc": 3,
        "status": "NOT-ACCEPTED-UNVERIFIED",
        "claims": 9,
        "disk": 1,
        "self": 8,
        "verdicts": dict([("D1", "MATCH"), ("D2", "MATCH"), ("D3", "ABSENT"),
                          ("D4", "MATCH"), ("D5", "MATCH"), ("D6", "MATCH"),
                          ("D7", "MATCH"), ("D8", "MATCH"), ("D9", "MATCH")]),
        "sources": {"pgagent": "ABSENT", "agentd": "GREEN", "journal": "GREEN"},
        "checks": {
            "pgagent": {"P0": "GREEN", "P1": "GREEN", "P2": "GREEN", "P3": "GREEN",
                        "P4": "GREEN", "P5": "GREEN", "P6": "GREEN", "P7": "GREEN",
                        "P8": "GREEN", "P9": "GREEN", "P10": "ABSENT"},
            "agentd": {"E1": "GREEN", "E2": "GREEN", "E3": "GREEN", "E4": "GREEN",
                       "E5": "VACUOUS", "E6": "VACUOUS", "E7": "GREEN"},
            "journal": {"J1": "GREEN", "J2": "GREEN", "J3": "GREEN", "J4": "GREEN",
                        "J5": "GREEN", "J6": "GREEN", "J7": "GREEN", "J8": "GREEN"},
        },
        "relayed": {
            "pgagent": {"trace_sane": True, "chain_sane": True,
                        "kpi_ledger_decided": 4, "mix_identity_ok": True},
        },
    },
]

TAGS = ["html", "head", "body", "table", "tr", "td", "th", "div", "ul", "li",
        "span", "h1", "h2", "h3", "p"]
BANNED_IMPORTS = ["socket", "ssl", "http", "urllib", "ftplib", "smtplib",
                  "telnetlib", "xmlrpc", "requests", "httpx", "openai", "anthropic"]
ALLOWED_IMPORTS = {
    "对账单.py": {"argparse", "base64", "datetime", "hashlib", "html", "json",
                "os", "re", "sys"},
    "臂检-对账单.py": {"argparse", "datetime", "hashlib", "json", "os", "shutil",
                     "subprocess", "sys", "tempfile"},
}


class Report:
    def __init__(self):
        self.lines = []
        self.passed = 0
        self.failed = 0

    def add(self, ok, name, detail=""):
        tag = "PASS" if ok else "FAIL"
        self.lines.append("[%s] %s%s" % (tag, name, ("  -- " + detail) if detail else ""))
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        print("%s %s" % (tag, name))
        return ok

    def section(self, title):
        self.lines.append("")
        self.lines.append("== " + title + " ==")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_tool(spec, out_json, out_html):
    p = subprocess.run([sys.executable, TOOL, spec, "-o", out_json, "--html", out_html],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {
        "rc": p.returncode,
        "out": p.stdout.decode("utf-8", "replace"),
        "err": p.stderr.decode("utf-8", "replace"),
    }


def snapshot_inputs():
    files = []
    for rel in ("示例-编程", "示例-编程-谎报", "样例"):
        for root, dirs, names in os.walk(os.path.join(PRODUCT, rel)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                files.append(os.path.join(root, n))
    for s in SAMPLES:
        if not os.path.isfile(s["spec"]):
            continue
        spec = json.loads(open(s["spec"], encoding="utf-8").read())
        base = os.path.dirname(s["spec"])
        for c in spec.get("claims", []):
            if "path" in c:
                p = os.path.normpath(os.path.join(base, c["path"]))
                if os.path.isfile(p):
                    files.append(p)
        for cfg in (spec.get("evidence") or {}).values():
            for key in ("path", "source_file"):
                if key in cfg:
                    p = os.path.normpath(os.path.join(base, cfg[key]))
                    if os.path.isfile(p):
                        files.append(p)
    uniq = sorted(set(files))
    return {p: sha256_file(p) for p in uniq}


def tag_balance(page):
    bad = []
    for tag in TAGS:
        opens = len(re.findall(r"<%s(?=[\s>])" % tag, page))
        closes = len(re.findall(r"</%s>" % tag, page))
        if opens != closes:
            bad.append("%s open=%d close=%d" % (tag, opens, closes))
    return bad


def check_html(rep, label, receipt, page, expect):
    n = len(receipt.get("claims", []))
    rep.add(page.count('data-claim="') == n,
            "%s html data-claim rows == %d" % (label, n),
            "found %d" % page.count('data-claim="'))
    rep.add(page.count('class="claim"') == n,
            "%s html claim row class == %d" % (label, n),
            "found %d" % page.count('class="claim"'))
    m = re.search(r"landing check: (\d+)/(\d+) rows OK", page)
    rep.add(bool(m) and int(m.group(1)) == n and int(m.group(2)) == n,
            "%s html landing check n/n OK" % label,
            m.group(0) if m else "missing")
    rep.add("\ufffd" not in page, "%s html no U+FFFD" % label)
    bad = tag_balance(page)
    rep.add(not bad, "%s html tag balance" % label, ", ".join(bad) if bad else "ok")
    row_map = {}
    for rm in re.finditer(r'<tr class="claim" data-claim="([^"]+)">(.*?)</tr>', page, re.S):
        vm = re.search(r'<td class="(?:ok|bad|warn|info)">([A-Z]+)</td>', rm.group(2))
        row_map[rm.group(1)] = vm.group(1) if vm else "?"
    json_map = {c["id"]: c["verdict"] for c in receipt.get("claims", [])}
    rep.add(row_map == json_map, "%s html rows match json verdicts" % label,
            "html=%s json=%s" % (row_map, json_map) if row_map != json_map else "%d rows" % len(row_map))
    rep.add(page.count("证据源：") == len(receipt.get("evidence") or {}),
            "%s html evidence sections == %d" % (label, len(receipt.get("evidence") or {})),
            "found %d" % page.count("证据源："))
    bm = re.search(r'<div class="banner (\w+)">([^<]*)<small>', page)
    cls_ok = {0: "ok", 2: "bad", 3: "warn"}.get(expect["rc"])
    rep.add(bool(bm) and bm.group(1) == cls_ok,
            "%s html banner class %s" % (label, cls_ok),
            bm.group(1) if bm else "missing")
    rep.add(bool(bm) and bm.group(2).strip() == expect["status"],
            "%s html banner status %s" % (label, expect["status"]),
            bm.group(2).strip() if bm else "missing")
    st = receipt.get("status")
    rep.add(st == expect["status"], "%s receipt status %s" % (label, expect["status"]), st)
    s = receipt.get("summary") or {}
    rep.add(s.get("claims") == expect["claims"], "%s summary claims == %d" % (label, expect["claims"]),
            str(s.get("claims")))
    rep.add(s.get("disk") == expect["disk"], "%s summary disk == %d" % (label, expect["disk"]),
            str(s.get("disk")))
    rep.add(s.get("self") == expect["self"], "%s summary self == %d" % (label, expect["self"]),
            str(s.get("self")))
    got_v = {c["id"]: c["verdict"] for c in receipt.get("claims", [])}
    bad_v = {k: (v, got_v.get(k)) for k, v in expect["verdicts"].items() if got_v.get(k) != v}
    rep.add(not bad_v, "%s claim verdicts" % label,
            "mismatched %s" % bad_v if bad_v else "%d checked" % len(expect["verdicts"]))
    got_s = {k: v.get("verdict") for k, v in (receipt.get("evidence") or {}).items()}
    rep.add(got_s == expect["sources"], "%s source verdicts" % label,
            "%s != %s" % (got_s, expect["sources"]) if got_s != expect["sources"] else "ok")
    for src, want in expect["checks"].items():
        got = {x["id"]: x["verdict"] for x in (receipt.get("evidence") or {}).get(src, {}).get("checks", [])}
        bad_c = {k: (v, got.get(k)) for k, v in want.items() if got.get(k) != v}
        rep.add(not bad_c, "%s %s checks" % (label, src),
                "mismatched %s" % bad_c if bad_c else "%d checked" % len(want))
    for src, want in (expect.get("relayed") or {}).items():
        got = {x["key"]: x["value"] for x in (receipt.get("evidence") or {}).get(src, {}).get("relayed", [])}
        bad_r = {k: (v, got.get(k)) for k, v in want.items() if got.get(k) != v}
        rep.add(not bad_r, "%s %s relayed (self-reported, not recomputed)" % (label, src),
                "mismatched %s" % bad_r if bad_r else "%d checked" % len(want))
    rep.add(receipt.get("tool", {}).get("sha256") == sha256_file(TOOL),
            "%s receipt tool sha matches current build" % label)
    rep.add(receipt.get("spec", {}).get("sha256") == sha256_file(expect["spec"]),
            "%s receipt spec sha matches input" % label)
    landing = receipt.get("landing") or {}
    rep.add(landing.get("ok") is True,
            "%s receipt landing.ok" % label, str(landing.get("ok")))


def check_imports(rep):
    aliases = {"对账单.py": "receipt tool", "臂检-对账单.py": "arm harness"}
    for fname, allowed in ALLOWED_IMPORTS.items():
        path = os.path.join(PRODUCT, "工具", fname)
        tree = ast.parse(open(path, encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        banned = sorted(m for m in mods if m.split(".")[0] in BANNED_IMPORTS)
        label = aliases.get(fname, fname)
        rep.add(not banned, "%s imports no network/model client" % label,
                ",".join(banned) if banned else ",".join(sorted(mods)))
        extra = sorted(m for m in mods if m.split(".")[0] not in allowed)
        rep.add(not extra, "%s imports stay in declared stdlib set" % label,
                ",".join(extra) if extra else "ok")


def check_arms(rep):
    p = subprocess.run([sys.executable, ARM_TOOL],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    m = re.search(r"summary: arms=(\d+) pass=(\d+) fail=(\d+) neg_control_biting=(\w+)", out)
    if not m:
        rep.add(False, "arms summary line present", (out + err)[-300:])
        return
    arms, passed, failed, neg = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    rep.add(arms >= 24, "arms denominator >= 24 (floor, not a reading)", str(arms))
    rep.add(passed == arms and failed == 0, "arms all bite", "pass=%d fail=%d" % (passed, failed))
    rep.add(neg == "True", "arms negative control bites", neg)
    rep.add(p.returncode == 0, "arms rc 0", str(p.returncode))
    rep.add("conclusion: ALL-ARMS-BITE" in out, "arms conclusion ALL-ARMS-BITE")
    report = os.path.join(OUTDIR, "臂检-对账单.txt")
    ok_report = os.path.isfile(report)
    rep.add(ok_report, "arms report on disk")
    if ok_report:
        text = open(report, encoding="utf-8").read()
        rep.add("neg_control_biting=True" in text and "ALL-ARMS-BITE" in text,
                "arms report content")


def parse_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(PRODUCT, "报告-验收.txt"))
    args = ap.parse_args(argv)

    rep = Report()
    rep.lines.append("交付对账-1026 验收 · %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    rep.lines.append("产品根 %s" % PRODUCT)
    rep.lines.append("工具 %s" % TOOL)

    backup_root = tempfile.mkdtemp(prefix="duizhang-receipts-")
    backups = {}
    before = {}
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR, exist_ok=True)

        before = snapshot_inputs()
        rep.lines.append("输入文件 %d 个（跑前已取 sha256）" % len(before))

        for s in SAMPLES:
            for ext in (".json", ".html"):
                src = os.path.join(OUTDIR, s["name"] + ext)
                if os.path.isfile(src):
                    dst = os.path.join(backup_root, os.path.basename(src))
                    shutil.copy2(src, dst)
                    backups[src] = dst

        rep.section("样例回放")
        for s in SAMPLES:
            out_json = os.path.join(OUTDIR, s["name"] + ".json")
            out_html = os.path.join(OUTDIR, s["name"] + ".html")
            for p in (out_json, out_html):
                if os.path.exists(p):
                    os.remove(p)
            started = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            r = run_tool(s["spec"], out_json, out_html)
            rep.add(r["rc"] == s["rc"], "%s rc == %d" % (s["key"], s["rc"]),
                    "got %d" % r["rc"])
            if not os.path.isfile(out_json) or not os.path.isfile(out_html):
                rep.add(False, "%s receipts written" % s["key"], (r["err"] or r["out"])[-200:])
                continue
            receipt = json.loads(open(out_json, encoding="utf-8").read())
            page = open(out_html, encoding="utf-8").read()
            try:
                stamp = parse_utc(receipt.get("generated_at", ""))
                fresh = stamp >= started
            except (TypeError, ValueError):
                stamp, fresh = None, False
            rep.add(fresh, "%s receipt generated_at not older than this run" % s["key"],
                    "generated_at=%s run_start=%s" % (receipt.get("generated_at"),
                                                      started.strftime("%Y-%m-%dT%H:%M:%SZ")))
            check_html(rep, s["key"], receipt, page, s)
            printed = re.search(r"landing check: (\d+)/(\d+) rows OK", r["out"])
            rep.add(bool(printed), "%s tool printed landing check OK" % s["key"])

        rep.section("HTML 交叉核对（盘上重读）")
        for s in SAMPLES:
            jp = os.path.join(OUTDIR, s["name"] + ".json")
            hp = os.path.join(OUTDIR, s["name"] + ".html")
            if not (os.path.isfile(jp) and os.path.isfile(hp)):
                continue
            rec = json.loads(open(jp, encoding="utf-8").read())
            page = open(hp, encoding="utf-8").read()
            n = len(rec["claims"])
            rep.add(page.count('data-claim="') == n == (rec.get("landing") or {}).get("claims_json"),
                    "%s json/html row counts agree" % s["key"],
                    "html=%d json=%d landing=%s" % (page.count('data-claim="'), n,
                                                     (rec.get("landing") or {}).get("claims_json")))

        rep.section("只读性")
        after = snapshot_inputs()
        changed = sorted(p for p in before if after.get(p) != before[p])
        missing = sorted(p for p in before if p not in after)
        added = sorted(p for p in after if p not in before)
        rep.add(not changed, "inputs unchanged", ",".join(changed[:3]) if changed else "0 changed")
        rep.add(not missing, "inputs not removed", ",".join(missing[:3]) if missing else "0 missing")
        rep.add(not added, "no stray input files added", ",".join(added[:3]) if added else "0 added")
        rep.add(len(after) == len(before), "input file count stable",
                "%d -> %d" % (len(before), len(after)))

        rep.section("静态边界")
        check_imports(rep)

        rep.section("臂检")
        check_arms(rep)
    except Exception as e:
        rep.add(False, "harness exception", "%s: %s" % (type(e).__name__, e))
    finally:
        if rep.failed:
            restored = 0
            for dst, src in backups.items():
                shutil.copy2(src, dst)
                restored += 1
            rep.lines.append("")
            rep.lines.append("失败收尾：已把 %d 份上一趟读数还原，避免半新半旧" % restored)
        shutil.rmtree(backup_root, ignore_errors=True)

        rep.lines.append("")
        rep.lines.append("checks: %d pass=%d fail=%d" % (rep.passed + rep.failed, rep.passed, rep.failed))
        rep.lines.append("conclusion: %s" % ("ALL-GREEN" if rep.failed == 0 else "NOT-GREEN"))
        print("checks: %d pass=%d fail=%d" % (rep.passed + rep.failed, rep.passed, rep.failed))
        print("conclusion: %s" % ("ALL-GREEN" if rep.failed == 0 else "NOT-GREEN"))

        with open(args.report, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(rep.lines) + "\n")
        print("wrote: acceptance report")
    return 0 if rep.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
