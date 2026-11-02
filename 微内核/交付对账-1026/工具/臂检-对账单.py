#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""臂检：每根臂只改一处，断言「改后与干净对照的差集」恰好等于清单。

叶子纪律：每根臂都在一份全新拷贝上只做一处改动；差集多一条少一条都算这根臂没咬准。
控制：每份样例先跑一次干净对照（CTL-good / CTL-real）作为零差集基线；
A-neg 故意写错期望，比较器必须判它 FAIL（否则比较器没牙）。
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "对账单.py")
GOOD_SPEC = os.path.join(PRODUCT, "示例-编程", "交付声明.json")
REAL_SPEC = os.path.join(PRODUCT, "样例", "交付声明-真端点.json")


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_set(obj, path, value):
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur[p]
    cur[parts[-1]] = value


def load_journal(path):
    headers, records = [], []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if not s.lstrip().startswith("{"):
                headers.append(s)
            else:
                records.append(json.loads(s))
    return headers, records


def write_journal(path, headers, records):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for h in headers:
            f.write(h + "\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def stage_spec(spec_path, workdir):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    base = os.path.dirname(os.path.abspath(spec_path))
    mapping = {}
    counter = [0]

    def stage_path(rel):
        src = os.path.normpath(os.path.join(base, rel))
        if src in mapping:
            return mapping[src]
        counter[0] += 1
        dst = os.path.join(workdir, "files", "%02d-%s" % (counter[0], os.path.basename(src)))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        mapping[src] = dst
        return dst

    for c in spec.get("claims", []):
        if "path" in c:
            c["path"] = stage_path(c["path"])
    for cfg in (spec.get("evidence") or {}).values():
        if "path" in cfg:
            cfg["path"] = stage_path(cfg["path"])
        if "source_file" in cfg:
            cfg["source_file"] = stage_path(cfg["source_file"])
    return spec, base, mapping


def apply_mutation(spec, base, mapping, mut):
    """返回被改动的盘上路径（没改动就 None）。"""
    if not mut:
        return None
    if mut["kind"] == "claim_add":
        return None
    if mut["kind"] == "spec_text":
        return None
    if mut["kind"] == "spec_set":
        spec[mut["key"]] = mut["value"]
        return None
    if mut["kind"] in ("claim_set", "claim_del_key"):
        for c in spec.get("claims", []):
            if c.get("id") == mut["claim"]:
                if mut["kind"] == "claim_set":
                    c[mut["key"]] = mut["value"]
                else:
                    c.pop(mut["key"], None)
                return None
        raise SystemExit("arm mutation: claim id not found: %s" % mut["claim"])
    if mut["kind"] == "evidence_add":
        spec.setdefault("evidence", {})[mut["key"]] = mut["cfg"]
        return None
    if mut["kind"] == "pin":
        spec["evidence"][mut["source"]]["sha256"] = mut["value"]
        return None
    src = os.path.normpath(os.path.join(base, mut["path"]))
    path = mapping[src]
    kind = mut["kind"]
    if kind == "append":
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(mut["text"])
    elif kind == "replace":
        with open(path, "rb") as f:
            raw = f.read()
        old, new = mut["old"].encode("utf-8"), mut["new"].encode("utf-8")
        n = raw.count(old)
        if n != 1:
            raise SystemExit("arm mutation: replace expected exactly 1 hit, got %d" % n)
        with open(path, "wb") as f:
            f.write(raw.replace(old, new))
    elif kind == "write":
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(mut["text"])
    elif kind == "delete":
        os.remove(path)
    elif kind == "json_set":
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        walk_set(doc, mut["json_path"], mut["value"])
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
    elif kind == "jsonl_append":
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(mut["event"], ensure_ascii=False) + "\n")
    elif kind in ("jsonl_set", "jsonl_delete"):
        headers, records = load_journal(path)
        i = mut["index"]
        if kind == "jsonl_set":
            records[i][mut["key"]] = mut["value"]
        else:
            del records[i]
        write_journal(path, headers, records)
    else:
        raise SystemExit("unknown mutation kind: %s" % kind)
    return path


def repin(spec, path):
    if not path or not os.path.isfile(path):
        return
    sha = sha256_file(path)
    for cfg in (spec.get("evidence") or {}).values():
        if os.path.normpath(cfg.get("path", "")) == os.path.normpath(path) and cfg.get("sha256"):
            cfg["sha256"] = sha


def run_tool(spec_path, out_json, out_html):
    cmd = [sys.executable, TOOL, spec_path, "-o", out_json, "--html", out_html]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    receipt = None
    if os.path.isfile(out_json):
        try:
            with open(out_json, "r", encoding="utf-8") as f:
                receipt = json.load(f)
        except json.JSONDecodeError:
            receipt = None
    return p.returncode, receipt, p.stdout, p.stderr


def shape(receipt):
    claims = {c["id"]: c["verdict"] for c in receipt["claims"]}
    bases = {c["id"]: c["basis"] for c in receipt["claims"]}
    sources = {k: v["verdict"] for k, v in receipt["evidence"].items()}
    checks = {k: {c["id"]: c["verdict"] for c in v["checks"]} for k, v in receipt["evidence"].items()}
    return {"claims": claims, "bases": bases, "sources": sources,
            "checks": checks, "status": receipt["status"]}


def delta(control, got):
    d = {"claims": {}, "bases": {}, "sources": {}, "checks": {}}
    for cid, v in got["claims"].items():
        if control["claims"].get(cid) != v:
            d["claims"][cid] = v
    for cid in control["claims"]:
        if cid not in got["claims"]:
            d["claims"][cid] = "GONE"
    for cid, v in got["bases"].items():
        if control["bases"].get(cid) != v:
            d["bases"][cid] = v
    for k, v in got["sources"].items():
        if control["sources"].get(k) != v:
            d["sources"][k] = v
    for k in control["sources"]:
        if k not in got["sources"]:
            d["sources"][k] = "GONE"
    for k, cm in got["checks"].items():
        cm0 = control["checks"].get(k, {})
        for cid, v in cm.items():
            if cm0.get(cid) != v:
                d["checks"].setdefault(k, {})[cid] = v
    for k, cm0 in control["checks"].items():
        cm = got["checks"].get(k, {})
        for cid in cm0:
            if cid not in cm:
                d["checks"].setdefault(k, {})[cid] = "GONE"
    return d


ARMS = [
    {
        "id": "A1", "sample": "good", "desc": "给 calc.py 末尾追加一行注释",
        "mut": {"kind": "append", "path": "工作区/calc.py", "text": "\n# note\n"},
        "expect_rc": 2,
        "expect": {"claims": {"C1": "MISMATCH", "C6": "MISMATCH", "C7": "MISMATCH"},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A2", "sample": "good", "desc": "把第 2 行 if not xs: 换成同长度的 if not ys:",
        "mut": {"kind": "replace", "path": "工作区/calc.py", "old": "if not xs:", "new": "if not ys:"},
        "expect_rc": 2,
        "expect": {"claims": {"C1": "MISMATCH", "C2": "MISMATCH"}, "sources": {}, "checks": {}},
    },
    {
        "id": "A3", "sample": "good", "desc": "删掉测试日志",
        "mut": {"kind": "delete", "path": "证据/修复后-测试.log"},
        "expect_rc": 3,
        "expect": {"claims": {"C3": "ABSENT", "C4": "ABSENT", "C8": "ABSENT"},
                   "bases": {"C3": "absent", "C4": "absent", "C8": "absent"},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A4", "sample": "good", "desc": "把日志末行 exit_code=0 改成 exit_code=2",
        "mut": {"kind": "replace", "path": "证据/修复后-测试.log", "old": "exit_code=0", "new": "exit_code=2"},
        "expect_rc": 2,
        "expect": {"claims": {"C3": "MISMATCH"}, "sources": {}, "checks": {}},
    },
    {
        "id": "A5", "sample": "good", "desc": "把声称已删的临时文件放回去",
        "mut": {"kind": "write", "path": "工作区/tmp_debug.txt", "text": "debug\n"},
        "expect_rc": 2,
        "expect": {"claims": {"C5": "MISMATCH"}, "sources": {}, "checks": {}},
    },
    {
        "id": "A6", "sample": "good", "desc": "声明里加一条本件不认识的核对类型",
        "mut": {"kind": "claim_add", "claim": {"id": "C9", "kind": "magic_check", "path": "工作区/calc.py",
                                               "value": "whatever", "evidence_class": "disk"}},
        "expect_rc": 3,
        "expect": {"claims": {"C9": "ABSENT"}, "bases": {"C9": "absent"},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A7", "sample": "real", "desc": "把 pgagent 自报的 trace_sane 改成 false",
        "mut": {"kind": "json_set", "path": "../../PDF-1022/真端点-1023/读数/pgagent-真端点.json",
                "json_path": "result.trace_sane", "value": False},
        "expect_rc": 2,
        "expect": {"claims": {"D7": "MISMATCH"}, "sources": {"pgagent": "RED"},
                   "checks": {"pgagent": {"R-trace_sane": "RED"}}},
    },
    {
        "id": "A8", "sample": "real", "desc": "事件层：给已收口的那一发补一条不带理由的拒绝",
        "mut": {"kind": "jsonl_append", "path": "../../PDF-1022/真端点-1023/读数/agentd-真端点.events.jsonl",
                "event": {"v": 1, "session": "real-agentd-1", "run": "r28960-1792729790298584000",
                          "turn": 1, "seq": 6, "ts": "2026-10-26T00:00:00Z", "kind": "precheck",
                          "state": "refused", "evidence": "measured"}},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"agentd": "RED"},
                   "checks": {"agentd": {"E5": "RED"}}},
    },
    {
        "id": "A9", "sample": "real", "desc": "账本第 2 条改一个字的 claim（seal 应该对不上）",
        "mut": {"kind": "jsonl_set", "path": "../../构建-1017/客服靶场/导出/账本-全量-1018.jsonl",
                "index": 1, "key": "claim", "value": "tampered"},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"journal": "RED"},
                   "checks": {"journal": {"J4": "RED"}}},
    },
    {
        "id": "A10", "sample": "real", "desc": "账本第 2 条改 prev_hash（seal 与链接都该断）",
        "mut": {"kind": "jsonl_set", "path": "../../构建-1017/客服靶场/导出/账本-全量-1018.jsonl",
                "index": 1, "key": "prev_hash", "value": "0" * 64},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"journal": "RED"},
                   "checks": {"journal": {"J4": "RED", "J5": "RED"}}},
    },
    {
        "id": "A11", "sample": "real", "desc": "账本第 2 条 seq 重号（seal 与序号都该断）",
        "mut": {"kind": "jsonl_set", "path": "../../构建-1017/客服靶场/导出/账本-全量-1018.jsonl",
                "index": 1, "key": "seq", "value": 1},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"journal": "RED"},
                   "checks": {"journal": {"J4": "RED", "J6": "RED"}}},
    },
    {
        "id": "A12", "sample": "real", "desc": "账本删掉第 3 条（条数、链接、序号、49 格分组都该断）",
        "mut": {"kind": "jsonl_delete", "path": "../../构建-1017/客服靶场/导出/账本-全量-1018.jsonl",
                "index": 2},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"journal": "RED"},
                   "checks": {"journal": {"J2": "RED", "J5": "RED", "J6": "RED", "J8": "RED"}}},
    },
    {
        "id": "A13", "sample": "real", "desc": "把钉住的证据指纹改错一位",
        "mut": {"kind": "pin", "source": "pgagent", "value": "0" * 64},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"pgagent": "RED"},
                   "checks": {"pgagent": {"P0": "RED"}}},
    },
    {
        "id": "A14", "sample": "good", "desc": "把声明清空（没有可核的东西不能算过）",
        "mut": {"kind": "spec_set", "key": "claims", "value": []},
        "expect_rc": 3, "expect_status": "NOT-ACCEPTED-UNVERIFIED",
        "expect": {"claims": {"C%d" % i: "GONE" for i in range(1, 9)},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A15", "sample": "good", "desc": "C1 删掉 evidence_class（缺省按自报）",
        "mut": {"kind": "claim_del_key", "claim": "C1", "key": "evidence_class"},
        "expect_rc": 3, "expect_status": "NOT-ACCEPTED-UNVERIFIED",
        "expect": {"claims": {}, "bases": {"C1": "relayed"}, "sources": {}, "checks": {}},
    },
    {
        "id": "A16", "sample": "good", "desc": "C2 的 value 改成空串（空串会恒真）",
        "mut": {"kind": "claim_set", "claim": "C2", "key": "value", "value": ""},
        "expect_rc": 3,
        "expect": {"claims": {"C2": "ABSENT"}, "bases": {"C2": "absent"},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A17", "sample": "good", "desc": "声明里加一个本件不认识的证据源",
        "mut": {"kind": "evidence_add", "key": "pgagentx", "cfg": {"path": "nowhere.json"}},
        "expect_rc": 3, "expect_status": "NOT-ACCEPTED-UNVERIFIED",
        "expect": {"claims": {}, "sources": {"pgagentx": "ABSENT"},
                   "checks": {"pgagentx": {"S0": "ABSENT"}}},
    },
    {
        "id": "A18", "sample": "good", "desc": "日志 exit_code=0 之后追一段崩溃栈",
        "mut": {"kind": "append", "path": "证据/修复后-测试.log",
                "text": "\nTraceback (most recent call last):\nZeroDivisionError: boom\n"},
        "expect_rc": 3,
        "expect": {"claims": {"C3": "ABSENT"}, "bases": {"C3": "absent"},
                   "sources": {}, "checks": {}},
    },
    {
        "id": "A19", "sample": "real", "desc": "agentd 事件文件清空（0 条事件不是绿）",
        "mut": {"kind": "write", "path": "../../PDF-1022/真端点-1023/读数/agentd-真端点.events.jsonl",
                "text": ""},
        "expect_rc": 3,
        "expect": {"claims": {}, "sources": {"agentd": "ABSENT"},
                   "checks": {"agentd": {"E8": "ABSENT", "E2": "GONE", "E3": "GONE",
                                         "E4": "GONE", "E5": "GONE", "E6": "GONE", "E7": "GONE"}}},
    },
    {
        "id": "A20", "sample": "real", "desc": "内核账本清空（0 条账不是绿）",
        "mut": {"kind": "write", "path": "../../构建-1017/客服靶场/导出/账本-全量-1018.jsonl",
                "text": ""},
        "expect_rc": 3,
        "expect": {"claims": {}, "sources": {"journal": "ABSENT"},
                   "checks": {"journal": {"J9": "ABSENT", "J2": "GONE", "J3": "GONE",
                                          "J4": "GONE", "J5": "GONE", "J6": "GONE",
                                          "J7": "GONE", "J8": "GONE"}}},
    },
    {
        "id": "A21", "sample": "good", "desc": "声明不是合法 JSON（本件自己报错 rc=1）",
        "mut": {"kind": "spec_text", "text": "{not json"},
        "expect_rc": 1, "expect": {"claims": {}, "sources": {}, "checks": {}},
    },
    {
        "id": "A22", "sample": "good", "desc": "两条声明同号（编号有歧义，rc=1）",
        "mut": {"kind": "claim_add", "claim": {"id": "C1", "kind": "file_exists",
                                               "path": "工作区/calc.py",
                                               "evidence_class": "disk", "why": "重复编号"}},
        "expect_rc": 1, "expect": {"claims": {}, "sources": {}, "checks": {}},
    },
    {
        "id": "A23", "sample": "real", "desc": "把 agentd 钉住的指纹改错",
        "mut": {"kind": "pin", "source": "agentd", "value": "0" * 64},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"agentd": "RED"},
                   "checks": {"agentd": {"E0": "RED"}}},
    },
    {
        "id": "A24", "sample": "real", "desc": "把内核账本钉住的指纹改错",
        "mut": {"kind": "pin", "source": "journal", "value": "0" * 64},
        "expect_rc": 2,
        "expect": {"claims": {}, "sources": {"journal": "RED"},
                   "checks": {"journal": {"J0": "RED"}}},
    },
    {
        "id": "A-neg", "sample": "good", "desc": "假期望对照：干净的树却期望 C1 红",
        "mut": None, "expect_rc": 0, "neg": True,
        "expect": {"claims": {"C1": "MISMATCH"}, "sources": {}, "checks": {}},
    },
]


def prepare(sample, workdir):
    spec_path = GOOD_SPEC if sample == "good" else REAL_SPEC
    spec, base, mapping = stage_spec(spec_path, workdir)
    return spec, base, mapping


def run_arm(arm, root):
    workdir = os.path.join(root, arm["id"])
    os.makedirs(workdir, exist_ok=True)
    spec, base, mapping = prepare(arm["sample"], workdir)
    if arm["mut"] and arm["mut"]["kind"] == "claim_add":
        spec["claims"].append(arm["mut"]["claim"])
    mutated = apply_mutation(spec, base, mapping, arm["mut"])
    repin(spec, mutated)
    spec_path = os.path.join(workdir, "spec.json")
    with open(spec_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    if arm["mut"] and arm["mut"]["kind"] == "spec_text":
        with open(spec_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(arm["mut"]["text"])
    out_json = os.path.join(workdir, "receipt.json")
    out_html = os.path.join(workdir, "receipt.html")
    rc, receipt, out, err = run_tool(spec_path, out_json, out_html)
    if receipt is None:
        return {"ok": True, "rc": rc, "shape": None,
                "why": "no receipt (rc=%d): %s" % (rc, (err or out)[-300:])}
    return {"ok": True, "rc": rc, "shape": shape(receipt)}


def fmt_delta(d):
    parts = []
    for key in ("claims", "bases"):
        if d.get(key):
            parts.append(key + "=" + ",".join("%s:%s" % (k, v) for k, v in sorted(d[key].items())))
    if d["sources"]:
        parts.append("sources=" + ",".join("%s:%s" % (k, v) for k, v in sorted(d["sources"].items())))
    if d["checks"]:
        cs = []
        for k, m in sorted(d["checks"].items()):
            cs.append("%s{%s}" % (k, ",".join("%s:%s" % (a, b) for a, b in sorted(m.items()))))
        parts.append("checks=" + " ".join(cs))
    return "; ".join(parts) if parts else "(empty)"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(PRODUCT, "读数", "臂检-对账单.txt"))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    root = tempfile.mkdtemp(prefix="duizhang-arms-")
    lines = ["臂检-对账单 · %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "临时根目录 %s" % root,
             "工具 %s" % TOOL,
             ""]
    control = None
    results = []
    try:
        controls = {}
        for sample in ("good", "real"):
            ctl = run_arm({"id": "CTL-" + sample, "sample": sample, "mut": None, "desc": "clean"},
                          root)
            if not ctl["ok"] or ctl["shape"] is None:
                print("CONTROL BROKEN (%s): %s" % (sample, ctl.get("why", "no receipt")))
                return 1
            controls[sample] = ctl["shape"]
            lines.append("%s 干净对照：rc=%d status=%s claims=%d evidence=%s" % (
                "好交付" if sample == "good" else "真端点", ctl["rc"], ctl["shape"]["status"],
                len(ctl["shape"]["claims"]),
                ",".join("%s:%s" % (k, v) for k, v in sorted(ctl["shape"]["sources"].items())) or "—"))
        lines.append("")

        passed = failed = 0
        neg_ok = None
        for arm in ARMS:
            got = run_arm(arm, root)
            if not got["ok"]:
                lines.append("%-5s %-38s ERROR %s" % (arm["id"], arm["desc"], got["why"]))
                print("%s ERROR" % arm["id"])
                failed += 1
                continue
            if arm.get("expect_rc") == 1:
                ok = got["rc"] == 1 and got["shape"] is None
                if ok:
                    passed += 1
                    lines.append("%-5s %-38s PASS  rc=1（本件自己报错，无回执）" % (arm["id"], arm["desc"]))
                else:
                    failed += 1
                    lines.append("%-5s %-38s FAIL  rc=%d（期望 1 且无回执）"
                                 % (arm["id"], arm["desc"], got["rc"]))
                print("%s %s" % (arm["id"], "PASS" if ok else "FAIL"))
                continue
            if got["shape"] is None:
                lines.append("%-5s %-38s ERROR no receipt: %s" % (arm["id"], arm["desc"], got["why"]))
                print("%s ERROR" % arm["id"])
                failed += 1
                continue
            d = delta(controls[arm["sample"]], got["shape"])
            want = arm["expect"]
            same = all(d[k] == want.get(k, {}) for k in ("claims", "bases", "sources", "checks"))
            rc_ok = got["rc"] == arm["expect_rc"]
            status_ok = ("expect_status" not in arm) or got["shape"]["status"] == arm["expect_status"]
            ok = same and rc_ok and status_ok
            if arm.get("neg"):
                neg_ok = not ok
                tag = "FAIL-AS-EXPECTED" if neg_ok else "NOT-BITING"
                lines.append("%-5s %-38s %s" % (arm["id"], arm["desc"], tag))
                lines.append("      期望(故意写错) %s" % fmt_delta(want))
                lines.append("      实得            %s" % fmt_delta(d))
                print("%s %s" % (arm["id"], tag))
                continue
            if ok:
                passed += 1
                lines.append("%-5s %-38s PASS  rc=%d status=%s"
                             % (arm["id"], arm["desc"], got["rc"], got["shape"]["status"]))
            else:
                failed += 1
                lines.append("%-5s %-38s FAIL  rc=%d(期望 %d) status=%s"
                             % (arm["id"], arm["desc"], got["rc"], arm["expect_rc"],
                                got["shape"]["status"]))
                lines.append("      期望 %s%s" % (fmt_delta(want),
                             "" if "expect_status" not in arm else " status=" + arm["expect_status"]))
                lines.append("      实得 %s" % fmt_delta(d))
            print("%s %s" % (arm["id"], "PASS" if ok else "FAIL"))

        arm_total = sum(1 for a in ARMS if not a.get("neg"))
        lines.append("")
        lines.append("summary: arms=%d pass=%d fail=%d neg_control_biting=%s" % (
            arm_total, passed, failed, neg_ok))
        ok_all = failed == 0 and neg_ok is True
        lines.append("conclusion: %s" % ("ALL-ARMS-BITE" if ok_all else "NOT-GREEN"))
        print("summary: arms=%d pass=%d fail=%d neg_control_biting=%s" % (
            arm_total, passed, failed, neg_ok))
        print("conclusion: %s" % ("ALL-ARMS-BITE" if ok_all else "NOT-GREEN"))
        return 0 if ok_all else 1
    finally:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
