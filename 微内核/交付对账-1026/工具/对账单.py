#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付对账单：把一批交付声明逐条对到盘上证据，产出可复核的 JSON 与 HTML 单子。

只读：不执行被交付的代码，不联网，不改任何输入文件。
退出码：0 = ACCEPTED；2 = NOT-ACCEPTED-MISMATCH；3 = NOT-ACCEPTED-UNVERIFIED；1 = 本件自己出错。
"""

import argparse
import base64
import datetime
import hashlib
import html
import json
import os
import re
import sys

VERSION = "1.0"
BASIS_TIERS = ("measured", "relayed", "estimated", "model_says", "absent")
JOURNAL_BASIS = {1: "measured", 2: "relayed", 3: "estimated", 4: "model_says", 5: "absent"}
RC_BY_STATUS = {"ACCEPTED": 0, "NOT-ACCEPTED-MISMATCH": 2, "NOT-ACCEPTED-UNVERIFIED": 3}

LIMITS = [
    "本件只读盘上文件：不执行被交付的代码，不联网，不改任何输入。",
    "核对的是「声明 vs 盘上证据」是否一致，不判断代码或结论本身对不对。",
    "证据怎么产生的，本件证不了：日志与文件可能是事后补的，本件只核它们与声明是否对得上。",
    "交付方自报的读数（trace_sane / KPI / chain_sane 等）记为 relayed，本件不重算。",
    "内核账本只核 seal / 链接 / 序号 / payload / 49 格分组这些可复算的形状，不核每格内容对不对。",
    "ACCEPTED 只代表「每条声明都由盘上证据复核通过，且没有仅凭自报的项」；不代表代码正确或测试充分。",
]


# ---------- 基础 ----------

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def resolve(base, rel):
    return os.path.normpath(os.path.join(base, rel))


def clip(v, n=180):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def walk_path(obj, path):
    cur = obj
    for part in path.split("."):
        m = re.match(r"^([^\[\]]*)((?:\[\d+\])*)$", part)
        if not m or (not m.group(1) and not m.group(2)):
            raise KeyError(part)
        key, idxs = m.group(1), m.group(2)
        if key:
            if not isinstance(cur, dict) or key not in cur:
                raise KeyError(key)
            cur = cur[key]
        for idx in re.findall(r"\[(\d+)\]", idxs):
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                raise IndexError("%s[%d]" % (key, i))
            cur = cur[i]
    return cur


def same_json_value(a, b):
    if type(a) is not type(b):
        return False
    return a == b


def check(cid, desc, verdict, detail="", cls="盘上"):
    return {"id": cid, "desc": desc, "verdict": verdict, "detail": detail, "class": cls}


def count_checks(checks):
    c = {"green": 0, "red": 0, "absent": 0, "relayed": 0, "vacuous": 0}
    for x in checks:
        c[x["verdict"].lower()] += 1
    return c


def source_verdict(checks):
    if any(x["verdict"] == "RED" for x in checks):
        return "RED"
    if any(x["verdict"] == "ABSENT" for x in checks):
        return "ABSENT"
    return "GREEN"


# ---------- 声明核对 ----------

def check_claim(claim, base):
    cid = str(claim.get("id", "?"))
    kind = claim.get("kind", "")
    # 只有明写 "disk" 才算盘上证据；省略或写错一律按自报处理（自报不可能换来 ACCEPTED）
    cls = "disk" if claim.get("evidence_class") == "disk" else "self"
    out = {
        "id": cid,
        "kind": kind,
        "why": claim.get("why", ""),
        "evidence_class": cls,
        "target": claim.get("path", claim.get("json_path", "")),
        "expected": claim.get("value"),
        "actual": None,
        "verdict": "ABSENT",
        "basis": "absent",
        "detail": "",
    }

    def done(verdict, actual, detail=""):
        out["verdict"] = verdict
        out["actual"] = actual
        out["detail"] = detail
        if verdict == "ABSENT":
            out["basis"] = "absent"
        else:
            # 自报的声明即使被自家产物打脸，也仍是转述来的值，不升格成"我们量到的"
            out["basis"] = "measured" if cls == "disk" else "relayed"
        return out

    if kind in ("file_exists", "file_absent", "file_sha256", "file_bytes",
                "file_lines", "file_contains", "log_exit", "log_contains"):
        rel = claim.get("path", "")
        if not rel:
            return done("ABSENT", None, "声明没给 path，核对不了")
        path = resolve(base, rel)
        out["target"] = rel
        exists = os.path.exists(path)

        def exists_label(p):
            if os.path.isfile(p):
                return "存在（%d 字节）" % os.path.getsize(p)
            return "存在（目录）"

        if kind == "file_exists":
            return done("MATCH" if exists else "MISMATCH",
                        exists_label(path) if exists else "不存在")
        if kind == "file_absent":
            return done("MATCH" if not exists else "MISMATCH",
                        "不存在" if not exists else exists_label(path))
        if not exists:
            return done("ABSENT", None, "文件不存在，读不到内容：%s" % rel)
        if kind == "file_bytes":
            n = os.path.getsize(path)
            return done("MATCH" if n == claim.get("value") else "MISMATCH", "%d 字节" % n)
        try:
            text = read_text(path)
        except UnicodeDecodeError:
            return done("ABSENT", None, "不是 UTF-8 文本，本件不猜编码：%s" % rel)
        except OSError as e:
            return done("ABSENT", None, "读不开：%s（%s）" % (rel, e.__class__.__name__))
        if kind == "file_sha256":
            actual = sha256_file(path)
            want = str(claim.get("value", ""))
            if len(want) == 64:
                return done("MATCH" if actual == want else "MISMATCH", actual)
            if len(want) == 16:
                return done("MATCH" if actual.startswith(want) else "MISMATCH", actual,
                            "按前 16 位比对（交付方只给了 16 位）")
            return done("ABSENT", actual, "指纹长度既不是 64 也不是 16：%d 位" % len(want))
        if kind == "file_lines":
            n = len(text.splitlines())
            return done("MATCH" if n == claim.get("value") else "MISMATCH", "%d 行" % n)
        if kind == "file_contains":
            needle = claim.get("value")
            if not isinstance(needle, str) or not needle:
                return done("ABSENT", None, "声明没给非空 value；空串会恒真，本件不核")
            line_no = claim.get("line")
            if line_no is None:
                n = text.count(needle)
                return done("MATCH" if n > 0 else "MISMATCH", "出现 %d 次" % n)
            lines = text.splitlines()
            if not isinstance(line_no, int) or line_no < 1 or line_no > len(lines):
                return done("ABSENT", "文件共 %d 行" % len(lines),
                            "行号 %r 越界，无法核对" % (line_no,))
            actual_line = lines[line_no - 1]
            return done("MATCH" if needle in actual_line else "MISMATCH", clip(actual_line),
                        "第 %d 行" % line_no)
        if kind == "log_exit":
            last = ""
            for ln in text.splitlines():
                if ln.strip():
                    last = ln.strip()
            m = re.match(r"^exit_code=(\d+)$", last)
            if not m:
                return done("ABSENT", clip(last),
                            "日志最后一行不是 exit_code=N（本件的日志约定）")
            actual = int(m.group(1))
            return done("MATCH" if actual == claim.get("value") else "MISMATCH",
                        "exit_code=%d" % actual, "取最后一行非空行")
        if kind == "log_contains":
            needle = claim.get("value")
            if not isinstance(needle, str) or not needle:
                return done("ABSENT", None, "声明没给非空 value；空串会恒真，本件不核")
            n = text.count(needle)
            return done("MATCH" if n > 0 else "MISMATCH", "出现 %d 次" % n)

    if kind in ("json_value", "json_number", "json_bool", "json_string", "json_len"):
        rel = claim.get("path", "")
        jp = claim.get("json_path", "")
        if "value" not in claim:
            return done("ABSENT", None, "声明没给 value，核对不了")
        if not rel:
            return done("ABSENT", None, "声明没给 path，核对不了")
        path = resolve(base, rel)
        out["target"] = "%s#%s" % (rel, jp)
        if not os.path.isfile(path):
            return done("ABSENT", None, "文件不存在，读不到内容：%s" % rel)
        try:
            doc = json.loads(read_text(path))
        except UnicodeDecodeError:
            return done("ABSENT", None, "不是 UTF-8 文本，本件不猜编码：%s" % rel)
        except json.JSONDecodeError as e:
            return done("ABSENT", None, "JSON 解不开：%s（第 %d 行）" % (rel, e.lineno))
        try:
            actual = walk_path(doc, jp)
        except (KeyError, IndexError) as e:
            return done("ABSENT", None, "路径不存在：%s（缺 %s）" % (jp, e))
        if kind == "json_len":
            if not isinstance(actual, (list, dict, str)):
                return done("ABSENT", clip(actual), "这个值不是可计长度的类型")
            n = len(actual)
            return done("MATCH" if n == claim.get("value") else "MISMATCH", "长度 %d" % n)
        want = claim.get("value")
        ok = same_json_value(actual, want)
        return done("MATCH" if ok else "MISMATCH", clip(actual),
                    "" if ok else "类型或值不同（期望 %s，实际 %s）" % (type(want).__name__, type(actual).__name__))

    return done("ABSENT", None, "本件不认识这个核对类型：%s ⇒ 未核对（不是通过）" % (kind or "（空）"))


# ---------- 证据源：pgagent ----------

def validate_pgagent(cfg, base):
    src = {
        "name": "pgagent 轨迹",
        "relation": cfg.get("relation", "本交付的证据"),
        "note": cfg.get("note", ""),
        "path": cfg.get("path", ""),
        "resolved": "",
        "present": False,
        "sha256": None,
        "sha256_expected": cfg.get("sha256"),
        "checks": [],
        "counts": None,
        "verdict": "ABSENT",
        "relayed": [],
    }
    path = resolve(base, cfg.get("path", ""))
    src["resolved"] = path
    if not os.path.isfile(path):
        src["checks"].append(check("P1", "证据文件在盘上", "ABSENT", "文件不存在：%s" % cfg.get("path", "")))
        src["counts"] = count_checks(src["checks"])
        return src
    src["present"] = True
    src["sha256"] = sha256_file(path)
    if src["sha256_expected"]:
        pin_ok = src["sha256"] == src["sha256_expected"]
        src["checks"].append(check("P0", "指纹与钉住的一致", "GREEN" if pin_ok else "RED",
                                   "钉住 %s… 实际 %s…" % (src["sha256_expected"][:16], src["sha256"][:16])))
    try:
        doc = json.loads(read_text(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        src["checks"].append(check("P1", "JSON 可解析", "RED", "%s" % e.__class__.__name__))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src
    src["checks"].append(check("P1", "JSON 可解析", "GREEN", "顶层键 %d 个" % len(doc)))

    steps = doc.get("steps")
    if not isinstance(steps, list):
        src["checks"].append(check("P2", "轨迹是数组", "RED", "顶层 steps 不是数组"))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src
    exp = cfg.get("expect", {})
    want_steps = exp.get("steps")
    v = "GREEN" if (want_steps is None or len(steps) == want_steps) else "RED"
    if not steps:
        v = "RED"
    src["checks"].append(check("P2", "步数", v, "%d 步（期望 %s）%s" % (
        len(steps), want_steps if want_steps is not None else "不钉",
        "；轨迹 0 步，不能当交付轨迹" if not steps else "")))

    not_ran = [s.get("name", "?") if isinstance(s, dict) else "?"
               for s in steps if not (isinstance(s, dict) and s.get("ran") is True)]
    src["checks"].append(check("P3", "每步都 ran=true", "GREEN" if not not_ran else "RED",
                               "全部 %d 步" % len(steps) if not not_ran else "没跑：%s" % ", ".join(not_ran)))

    bad_basis = [s.get("name", "?") if isinstance(s, dict) else "?"
                 for s in steps if not (isinstance(s, dict) and s.get("basis") in BASIS_TIERS)]
    src["checks"].append(check("P4", "每步 basis 合法", "GREEN" if not bad_basis else "RED",
                               "全部落在五档" if not bad_basis else "越界：%s" % ", ".join(bad_basis)))

    last = steps[-1].get("name") if steps and isinstance(steps[-1], dict) else ""
    want_last = exp.get("last_step", "stop")
    src["checks"].append(check("P5", "末步是终态", "GREEN" if last == want_last else "RED",
                               "末步=%s（期望 %s）" % (last, want_last)))

    r = doc.get("result") or {}
    findings = r.get("findings") or []
    unknowns = r.get("unknowns") or []
    mix = r.get("provenance_mix") or {}
    mix_sum = sum(mix.get(k, 0) for k in BASIS_TIERS)
    want_total = len(findings) + len(unknowns)
    mix_ok = mix_sum == want_total and mix.get("total") == want_total and r.get("mix_identity_ok") is True
    src["checks"].append(check("P6", "五档恒等", "GREEN" if mix_ok else "RED",
                               "五档加总 %d，findings+unknowns %d，mix.total %s" % (mix_sum, want_total, mix.get("total"))))

    bad_f = [f.get("id", "?") for f in findings if f.get("basis") not in BASIS_TIERS]
    bad_u = [u.get("what", "?") for u in unknowns if u.get("basis") not in BASIS_TIERS]
    src["checks"].append(check("P7", "finding/unknown 的 basis 合法", "GREEN" if not (bad_f or bad_u) else "RED",
                               "findings %d 条 / unknowns %d 条" % (len(findings), len(unknowns))))

    no_why = [u.get("what", "?") for u in unknowns if not str(u.get("why_absent", "")).strip()]
    src["checks"].append(check("P8", "unknown 都带「为什么缺席」", "GREEN" if not no_why else "RED",
                               "全部 %d 条都带理由" % len(unknowns) if not no_why else "没理由：%s" % ", ".join(clip(x, 40) for x in no_why)))

    exp_f = exp.get("findings")
    exp_u = exp.get("unknowns")
    cnt_ok = (exp_f is None or len(findings) == exp_f) and (exp_u is None or len(unknowns) == exp_u)
    src["checks"].append(check("P9", "条数与钉住的一致", "GREEN" if cnt_ok else "RED",
                               "findings %d / unknowns %d（期望 %s / %s）" % (len(findings), len(unknowns), exp_f, exp_u)))

    source_file = cfg.get("source_file")
    if not findings:
        src["checks"].append(check("P10", "finding 定位能回盘", "VACUOUS", "本次交付没有 finding，这条没有现场"))
    elif not source_file:
        degenerate = [f.get("id", "?") for f in findings if not (f.get("where") or {}).get("lines") or (f.get("where") or {}).get("lines") == [0, 0]]
        src["checks"].append(check("P10", "finding 定位能回盘", "ABSENT",
                                   "%d/%d 条 finding 的 where.lines 是 [0,0]（或空）；本次交付没有把被审源码一起交出来 ⇒ 回盘核不了"
                                   % (len(degenerate), len(findings)) if degenerate else
                                   "%d 条 finding 都有行号，但本次交付没有把被审源码一起交出来 ⇒ 回盘核不了"
                                   % len(findings)))
    else:
        spath = resolve(base, source_file)
        if not os.path.isfile(spath):
            src["checks"].append(check("P10", "finding 定位能回盘", "ABSENT",
                                       "spec 指向的源码不在盘上：%s" % source_file))
        else:
            try:
                n_lines = len(read_text(spath).splitlines())
            except (UnicodeDecodeError, OSError):
                n_lines = 0
            no_loc, oob = [], []
            for f in findings:
                lines = (f.get("where") or {}).get("lines") if isinstance(f, dict) else None
                if not isinstance(lines, list) or not lines:
                    no_loc.append(f.get("id", "?") if isinstance(f, dict) else "?")
                    continue
                for ln in lines:
                    if not isinstance(ln, int) or ln < 1 or ln > n_lines:
                        oob.append(f.get("id", "?") if isinstance(f, dict) else "?")
                        break
            if oob:
                src["checks"].append(check("P10", "finding 定位能回盘", "RED",
                                           "行号越界：%s（源码共 %d 行）" % (", ".join(oob), n_lines)))
            elif no_loc:
                src["checks"].append(check("P10", "finding 定位能回盘", "ABSENT",
                                           "源码在盘上，但这些 finding 没给可用行号：%s ⇒ 回盘核不了"
                                           % ", ".join(no_loc)))
            else:
                src["checks"].append(check("P10", "finding 定位能回盘", "GREEN",
                                           "源码 %d 行，%d 条 finding 的行号全在范围内" % (n_lines, len(findings))))

    for key, label in (("trace_sane", "trace_sane"), ("chain_sane", "chain_sane"),
                       ("kpi_ledger_decided", "KPI（账本改写了结果的格数）"),
                       ("mix_identity_ok", "mix_identity_ok")):
        if key in r:
            val = r.get(key)
            if val is False:
                src["checks"].append(check("R-" + key, label + "（自报）", "RED", "交付方自己报了 false"))
            else:
                src["relayed"].append({"key": key, "label": label, "value": val,
                                       "why": "交付方自报，本件不重算"})
        elif key == "kpi_ledger_decided":
            src["relayed"].append({"key": key, "label": label, "value": None,
                                   "why": "这一版产物里没有这一格（不是 0）"})

    src["counts"] = count_checks(src["checks"])
    src["verdict"] = source_verdict(src["checks"])
    return src


# ---------- 证据源：agentd 事件 ----------

REFUSE_STATES = ("refused", "rejected", "failed", "error")


def validate_agentd(cfg, base):
    src = {
        "name": "agentd 事件层",
        "relation": cfg.get("relation", "本交付的证据"),
        "note": cfg.get("note", ""),
        "path": cfg.get("path", ""),
        "resolved": "",
        "present": False,
        "sha256": None,
        "sha256_expected": cfg.get("sha256"),
        "checks": [],
        "counts": None,
        "verdict": "ABSENT",
        "relayed": [],
        "totals": {},
    }
    path = resolve(base, cfg.get("path", ""))
    src["resolved"] = path
    if not os.path.isfile(path):
        src["checks"].append(check("E1", "证据文件在盘上", "ABSENT", "文件不存在：%s" % cfg.get("path", "")))
        src["counts"] = count_checks(src["checks"])
        return src
    src["present"] = True
    src["sha256"] = sha256_file(path)
    if src["sha256_expected"]:
        pin_ok = src["sha256"] == src["sha256_expected"]
        src["checks"].append(check("E0", "指纹与钉住的一致", "GREEN" if pin_ok else "RED",
                                   "钉住 %s… 实际 %s…" % (src["sha256_expected"][:16], src["sha256"][:16])))
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        src["checks"].append(check("E1", "是 UTF-8 文本", "RED", "不是 UTF-8"))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src
    events, bad, not_obj = [], 0, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(e, dict):
            not_obj += 1
            continue
        events.append(e)
    src["checks"].append(check("E1", "每行都可解析", "GREEN" if (bad == 0 and not_obj == 0) else "RED",
                               "%d 条事件，坏行 %d，非对象行 %d" % (len(events), bad, not_obj)))
    if not events:
        src["checks"].append(check("E8", "事件流非空", "ABSENT",
                                   "0 条事件%s；没有可核的事件流" % (("，坏行 %d" % bad) if bad else "")))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src

    need = ("v", "session", "run", "turn", "seq", "ts", "kind", "state", "evidence")
    missing = {}
    for e in events:
        for k in need:
            if k not in e:
                missing[k] = missing.get(k, 0) + 1
    src["checks"].append(check("E2", "必备字段齐", "GREEN" if not missing else "RED",
                               "全齐" if not missing else "缺：" + ", ".join("%s×%d" % (k, v) for k, v in sorted(missing.items()))))

    # 契约 §5 第 2 条与序号针：同一 (session,turn) 内 seq 严格递增、不重复、不回退；
    # 「从 1 开始」不是契约要求（重启后接着涨是合法的），所以只把起始值印出来。
    groups = {}
    for e in events:
        groups.setdefault((e.get("session"), e.get("turn")), []).append(e)
    seq_bad, starts = [], []
    for key, evs in groups.items():
        seqs = [x.get("seq") for x in evs]
        label = "%s/turn%s" % (key[0], key[1])
        starts.append("%s:%s" % (label, seqs[0] if seqs else "—"))
        if any(not isinstance(s, int) or isinstance(s, bool) for s in seqs):
            seq_bad.append("%s: seq 不是整数 %s" % (label, seqs))
            continue
        if any(seqs[i] >= seqs[i + 1] for i in range(len(seqs) - 1)):
            seq_bad.append("%s: %s" % (label, seqs))
    src["checks"].append(check("E3", "每个 (session,turn) 的 seq 严格递增", "GREEN" if not seq_bad else "RED",
                               "%d 个 (session,turn) 严格递增（起始 seq %s）"
                               % (len(groups), " / ".join(starts)) if not seq_bad
                               else "不递增或重号：%s" % "; ".join(clip(x, 80) for x in seq_bad)))

    bad_ev = [e for e in events if e.get("evidence") not in BASIS_TIERS]
    src["checks"].append(check("E4", "evidence 档合法", "GREEN" if not bad_ev else "RED",
                               "全部落在五档" if not bad_ev else "%d 条越界" % len(bad_ev)))

    refused = [e for e in events if e.get("state") in REFUSE_STATES]
    if not refused:
        src["checks"].append(check("E5", "拒绝必须带理由", "VACUOUS", "本批 0 条拒绝事件 ⇒ 这条判据没有现场"))
    else:
        no_why = [e for e in refused if not str(e.get("why", "")).strip()]
        src["checks"].append(check("E5", "拒绝必须带理由", "GREEN" if not no_why else "RED",
                                   "%d 条拒绝全带理由" % len(refused) if not no_why
                                   else "%d/%d 条拒绝没带理由" % (len(no_why), len(refused))))

    absent_ev = [e for e in events if e.get("evidence") == "absent"]
    if not absent_ev:
        src["checks"].append(check("E6", "absent 事件带理由", "VACUOUS", "本批 0 条 absent 事件"))
    else:
        no_why = [e for e in absent_ev if not str(e.get("why", "")).strip()]
        src["checks"].append(check("E6", "absent 事件带理由", "GREEN" if not no_why else "RED",
                                   "%d 条 absent 全带理由" % len(absent_ev) if not no_why
                                   else "%d/%d 条没理由" % (len(no_why), len(absent_ev))))

    run_kinds = {}
    for e in events:
        run_kinds.setdefault((e.get("session"), e.get("run")), set()).add(e.get("kind"))
    bad_runs = [k for k, v in run_kinds.items() if not {"run_started", "run_settled"} <= v]
    # turn=0 是 run 级记账（run_started/run_settled），不算一发
    turns = {(e.get("session"), e.get("turn")) for e in events if e.get("turn")}
    settled_turn = {(e.get("session"), e.get("turn")) for e in events if e.get("kind") == "turn_settled"}
    open_turns = turns - settled_turn
    src["checks"].append(check("E7", "每一发与每一程都有终态事件",
                               "GREEN" if not (open_turns or bad_runs) else "RED",
                               "%d 发 / %d 程全部 settled" % (len(turns), len(run_kinds))
                               if not (open_turns or bad_runs)
                               else "没终态：%d 发 / %d 程" % (len(open_turns), len(bad_runs))))

    src["totals"] = {
        "events": len(events),
        "runs": len(run_kinds),
        "turns": len(turns),
        "refused": len(refused),
        "absent": len(absent_ev),
    }
    src["counts"] = count_checks(src["checks"])
    src["verdict"] = source_verdict(src["checks"])
    return src


# ---------- 证据源：内核账本 ----------

def seal_of(rec):
    basis = JOURNAL_BASIS.get(rec.get("basis"))
    if basis is None:
        return None
    parts = [
        str(rec.get("seq")),
        str(rec.get("session")),
        str(rec.get("actor")),
        str(rec.get("step")),
        str(rec.get("kind")),
        str(rec.get("claim")),
        basis,
        str(rec.get("source", "")),
        str(rec.get("ts")),
        str(rec.get("payload_sha256")),
        str(rec.get("prev_hash")),
    ]
    return sha256_bytes("\n".join(parts).encode("utf-8"))


def validate_journal(cfg, base):
    src = {
        "name": "内核账本",
        "relation": cfg.get("relation", "形状样例"),
        "note": cfg.get("note", ""),
        "path": cfg.get("path", ""),
        "resolved": "",
        "present": False,
        "sha256": None,
        "sha256_expected": cfg.get("sha256"),
        "checks": [],
        "counts": None,
        "verdict": "ABSENT",
        "relayed": [],
        "totals": {},
    }
    path = resolve(base, cfg.get("path", ""))
    src["resolved"] = path
    if not os.path.isfile(path):
        src["checks"].append(check("J1", "证据文件在盘上", "ABSENT", "文件不存在：%s" % cfg.get("path", "")))
        src["counts"] = count_checks(src["checks"])
        return src
    src["present"] = True
    src["sha256"] = sha256_file(path)
    if src["sha256_expected"]:
        pin_ok = src["sha256"] == src["sha256_expected"]
        src["checks"].append(check("J0", "指纹与钉住的一致", "GREEN" if pin_ok else "RED",
                                   "钉住 %s… 实际 %s…" % (src["sha256_expected"][:16], src["sha256"][:16])))
    recs, headers, bad = [], 0, 0
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        src["checks"].append(check("J1", "是 UTF-8 文本", "RED", "不是 UTF-8"))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not s.startswith("{"):
            headers += 1
            continue
        try:
            recs.append(json.loads(s))
        except json.JSONDecodeError:
            bad += 1
    src["checks"].append(check("J1", "账行可解析", "GREEN" if bad == 0 else "RED",
                               "%d 条账 + %d 行人读表头，坏行 %d" % (len(recs), headers, bad)))
    if not recs:
        src["checks"].append(check("J9", "账本非空", "ABSENT",
                                   "0 条记账（表头 %d 行）；没有可核的账本" % headers))
        src["counts"] = count_checks(src["checks"])
        src["verdict"] = source_verdict(src["checks"])
        return src

    exp = cfg.get("expect", {})
    want_records = exp.get("records")
    src["checks"].append(check("J2", "条数", "GREEN" if (want_records is None or len(recs) == want_records) else "RED",
                               "%d 条（期望 %s）" % (len(recs), want_records if want_records is not None else "不钉")))
    want_headers = exp.get("header_lines")
    src["checks"].append(check("J3", "人读表头行", "GREEN" if (want_headers is None or headers == want_headers) else "RED",
                               "%d 行（期望 %s）" % (headers, want_headers if want_headers is not None else "不钉")))

    seal_ok = 0
    first_seal_bad = None
    for r in recs:
        if seal_of(r) == r.get("hash"):
            seal_ok += 1
        elif first_seal_bad is None:
            first_seal_bad = r.get("seq")
    src["checks"].append(check("J4", "seal 逐条复算", "GREEN" if seal_ok == len(recs) else "RED",
                               "%d/%d（首条不符 seq=%s）" % (seal_ok, len(recs), first_seal_bad)
                               if seal_ok != len(recs) else "%d/%d" % (seal_ok, len(recs))))

    link_ok = 0
    first_link_bad = None
    prev_hash = ""
    for r in recs:
        if r.get("prev_hash") == prev_hash:
            link_ok += 1
        elif first_link_bad is None:
            first_link_bad = r.get("seq")
        prev_hash = r.get("hash")
    src["checks"].append(check("J5", "prev_hash 链接", "GREEN" if link_ok == len(recs) else "RED",
                               "%d/%d（首条不符 seq=%s）" % (link_ok, len(recs), first_link_bad)
                               if link_ok != len(recs) else "%d/%d" % (link_ok, len(recs))))

    seqs = [r.get("seq") for r in recs]
    seq_ok = seqs == list(range(1, len(recs) + 1))
    src["checks"].append(check("J6", "seq 从 1 连续", "GREEN" if seq_ok else "RED",
                               "1..%d" % len(recs) if seq_ok else "断点/重号"))

    pay_ok = 0
    first_pay_bad = None
    for r in recs:
        try:
            raw = base64.b64decode(r.get("payload_b64", ""), validate=True)
            ok = sha256_bytes(raw) == r.get("payload_sha256")
        except Exception:
            ok = False
        if ok:
            pay_ok += 1
        elif first_pay_bad is None:
            first_pay_bad = r.get("seq")
    src["checks"].append(check("J7", "payload 指纹", "GREEN" if pay_ok == len(recs) else "RED",
                               "%d/%d（首条不符 seq=%s）" % (pay_ok, len(recs), first_pay_bad)
                               if pay_ok != len(recs) else "%d/%d" % (pay_ok, len(recs))))

    groups = {}
    for r in recs:
        groups.setdefault((r.get("session"), r.get("step")), []).append(r)
    size_dist = {}
    for evs in groups.values():
        size_dist[len(evs)] = size_dist.get(len(evs), 0) + 1
    want_cells = exp.get("cells_per_group")
    want_groups = exp.get("groups")
    io_bad = []
    for key, evs in groups.items():
        n_in = sum(1 for x in evs if str(x.get("kind", "")).startswith("model_input"))
        n_out = sum(1 for x in evs if str(x.get("kind", "")).startswith("model_output"))
        if n_in != 20 or n_out != 29:
            io_bad.append("%s: %d/%d" % ("/".join(str(x) for x in key), n_in, n_out))
    group_ok = all(k == want_cells for k in size_dist) if want_cells is not None else True
    group_ok = group_ok and (want_groups is None or len(groups) == want_groups) and not io_bad
    src["checks"].append(check("J8", "49 格分组（20 入 + 29 出）", "GREEN" if group_ok else "RED",
                               "%d 组，尺寸分布 %s，入/出 20/29" % (len(groups), json.dumps(size_dist, sort_keys=True))
                               if group_ok else
                               "%d 组，尺寸分布 %s，入/出不符组 %d 个" % (len(groups), json.dumps(size_dist, sort_keys=True), len(io_bad))))

    src["totals"] = {
        "records": len(recs),
        "header_lines": headers,
        "groups": len(groups),
        "size_dist": size_dist,
        "seal_ok": seal_ok,
        "link_ok": link_ok,
        "payload_ok": pay_ok,
        "sessions": len({r.get("session") for r in recs}),
    }
    src["counts"] = count_checks(src["checks"])
    src["verdict"] = source_verdict(src["checks"])
    return src


# ---------- 汇总 ----------

def unknown_source(key):
    src = {
        "name": key,
        "relation": "本件不认识",
        "note": "",
        "path": "",
        "resolved": "",
        "present": False,
        "sha256": None,
        "sha256_expected": None,
        "checks": [check("S0", "证据源类型", "ABSENT",
                         "本件不认识这个证据源：%s ⇒ 未核对（不是通过）" % key)],
        "counts": None,
        "verdict": "ABSENT",
        "relayed": [],
    }
    src["counts"] = count_checks(src["checks"])
    return src


def build_receipt(spec, spec_path, spec_sha, tool_sha):
    base = os.path.dirname(os.path.abspath(spec_path))
    claims = [check_claim(c, base) for c in spec.get("claims", [])]
    summary = {
        "claims": len(claims),
        "match": sum(1 for c in claims if c["verdict"] == "MATCH"),
        "mismatch": sum(1 for c in claims if c["verdict"] == "MISMATCH"),
        "absent": sum(1 for c in claims if c["verdict"] == "ABSENT"),
        "disk": sum(1 for c in claims if c["evidence_class"] == "disk"),
        "self": sum(1 for c in claims if c["evidence_class"] == "self"),
    }

    evidence = {}
    evidence_cfg = spec.get("evidence") or {}
    for key, fn in (("pgagent", validate_pgagent), ("agentd", validate_agentd), ("journal", validate_journal)):
        if key in evidence_cfg:
            cfg = evidence_cfg.get(key)
            evidence[key] = fn(cfg if isinstance(cfg, dict) else {}, base)
    for key in evidence_cfg:
        if key not in ("pgagent", "agentd", "journal"):
            evidence[key] = unknown_source(key)

    mismatch_ids = [c["id"] for c in claims if c["verdict"] == "MISMATCH"]
    absent_ids = [c["id"] for c in claims if c["verdict"] == "ABSENT"]
    red_src = [k for k, v in evidence.items() if v["verdict"] == "RED"]
    absent_src = [k for k, v in evidence.items() if v["verdict"] == "ABSENT"]
    self_ids = [c["id"] for c in claims if c["evidence_class"] == "self"]

    if not claims:
        status = "NOT-ACCEPTED-UNVERIFIED"
        status_why = "本批 0 条声明：没有可核的东西（不是通过）"
    elif mismatch_ids or red_src:
        status = "NOT-ACCEPTED-MISMATCH"
        bits = []
        if mismatch_ids:
            bits.append("%d 条声明与盘上事实不符：%s" % (len(mismatch_ids), ", ".join(mismatch_ids)))
        if red_src:
            bits.append("证据源判红：%s" % ", ".join(red_src))
        if absent_ids:
            bits.append("另有 %d 条无法回盘核：%s" % (len(absent_ids), ", ".join(absent_ids)))
        status_why = "；".join(bits)
    elif absent_ids or absent_src or self_ids:
        status = "NOT-ACCEPTED-UNVERIFIED"
        bits = []
        if absent_ids:
            bits.append("%d 条声明无法回盘核：%s" % (len(absent_ids), ", ".join(absent_ids)))
        if absent_src:
            bits.append("证据源核不全：%s" % ", ".join(absent_src))
        if self_ids:
            bits.append("%d 条声明只有交付方自己的产物作证：%s" % (len(self_ids), ", ".join(self_ids)))
        status_why = "；".join(bits)
    else:
        status = "ACCEPTED"
        status_why = "%d 条声明全部由盘上证据复核通过，证据源无红，无仅凭自报的项" % len(claims)

    receipt = {
        "receipt_version": 1,
        "tool": {"name": "交付对账单", "version": VERSION, "sha256": tool_sha},
        "spec": {"path": spec_path, "resolved": os.path.abspath(spec_path), "sha256": spec_sha},
        "generated_at": utc_now(),
        "session": spec.get("session", os.path.basename(spec_path)),
        "delivery": spec.get("delivery", {}),
        "status": status,
        "status_why": status_why,
        "claims": claims,
        "summary": summary,
        "evidence": evidence,
        "limits": LIMITS,
    }
    return receipt


# ---------- 渲染 ----------

VERDICT_CLASS = {
    "MATCH": "ok", "MISMATCH": "bad", "ABSENT": "warn",
    "GREEN": "ok", "RED": "bad", "RELAYED": "info", "VACUOUS": "warn",
}
STATUS_CLASS = {"ACCEPTED": "ok", "NOT-ACCEPTED-MISMATCH": "bad", "NOT-ACCEPTED-UNVERIFIED": "warn"}

CSS = """
body{font-family:Consolas,'Courier New',monospace;background:#f6f6f4;color:#1b1b1b;margin:0;padding:24px;line-height:1.55}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;border-bottom:1px solid #ccc;padding-bottom:4px}
h3{font-size:14px;margin:16px 0 6px}
.meta{color:#666;font-size:12px}
.banner{margin:16px 0;padding:12px 16px;border-radius:6px;font-size:15px;font-weight:bold;border:1px solid #999}
.banner.ok{background:#e6f4ea;border-color:#2e7d32;color:#1b5e20}
.banner.bad{background:#fdecea;border-color:#c62828;color:#8e1b1b}
.banner.warn{background:#fff8e1;border-color:#f9a825;color:#7a5b00}
.banner small{display:block;font-weight:normal;margin-top:4px;font-size:12px}
table{border-collapse:collapse;width:100%;margin:6px 0 14px;font-size:12px}
th,td{border:1px solid #ccc;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#ebebe8}
td.ok{color:#1b5e20}td.bad{color:#b71c1c;font-weight:bold}td.warn{color:#7a5b00}td.info{color:#0d47a1}
.tag{display:inline-block;padding:0 5px;border-radius:3px;font-size:11px;border:1px solid #aaa}
.tag.disk{background:#e8eefc}.tag.self{background:#fce8f4}
ul{margin:4px 0 12px 20px;padding:0}li{margin:2px 0}
.foot{margin-top:28px;border-top:1px solid #bbb;padding-top:8px;color:#555;font-size:11px}
.num{font-weight:bold}
"""


def esc(v):
    return html.escape("" if v is None else str(v))


def render_html(receipt):
    s = receipt["summary"]
    ev = receipt["evidence"]
    rows = []
    for c in receipt["claims"]:
        cls = VERDICT_CLASS.get(c["verdict"], "info")
        src_tag = '<span class="tag %s">%s</span>' % (
            "disk" if c["evidence_class"] == "disk" else "self",
            "盘上" if c["evidence_class"] == "disk" else "自报")
        rows.append(
            '<tr class="claim" data-claim="%s"><td>%s</td><td>%s<br><span class="meta">%s</span></td>'
            '<td>%s</td><td>%s</td><td class="%s">%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(c["id"]), esc(c["id"]), esc(c["kind"]), esc(c["why"]),
                esc(clip(c["expected"]) if c["expected"] is not None else "—"),
                esc(clip(c["actual"]) if c["actual"] is not None else "—"),
                cls, esc(c["verdict"]), esc(c["basis"]), src_tag))
    claims_html = "\n".join(rows)

    ev_html = []
    for key, src in ev.items():
        cls = VERDICT_CLASS.get(src["verdict"], "info")
        checks = []
        for x in src["checks"]:
            xcls = VERDICT_CLASS.get(x["verdict"], "info")
            checks.append('<tr><td>%s</td><td>%s</td><td class="%s">%s</td><td>%s</td></tr>' % (
                esc(x["id"]), esc(x["desc"]), xcls, esc(x["verdict"]), esc(x["detail"])))
        relayed = []
        for r in src.get("relayed", []):
            relayed.append("<li>%s = <b>%s</b> —— %s</li>" % (esc(r["label"]), esc(r["value"]), esc(r["why"])))
        relayed_html = ("<h3>自报项（本件不重算）</h3><ul>%s</ul>" % "".join(relayed)) if relayed else ""
        ev_html.append(
            '<h2>证据源：%s <span class="tag">%s</span> <span class="%s">%s</span></h2>'
            '<div class="meta">路径 %s ｜ sha256 %s ｜ 关系：%s</div>'
            '%s<table><tr><th>编号</th><th>判据</th><th>结论</th><th>读数</th></tr>%s</table>%s' % (
                esc(src["name"]), esc(src["relation"]), cls, esc(src["verdict"]),
                esc(src["path"]), esc((src["sha256"] or "—")[:16]), esc(src["note"] or "—"),
                "", "\n".join(checks), relayed_html))

    limits = "".join("<li>%s</li>" % esc(x) for x in receipt["limits"])
    st = receipt["status"]
    banner = ('<div class="banner %s">%s<small>%s</small></div>' % (
        STATUS_CLASS.get(st, "warn"), esc(st), esc(receipt["status_why"])))
    counts = "声明 <span class='num'>%d</span> 条：MATCH <span class='num'>%d</span> ｜ MISMATCH <span class='num'>%d</span> ｜ ABSENT <span class='num'>%d</span> ｜ 盘上 %d / 自报 %d" % (
        s["claims"], s["match"], s["mismatch"], s["absent"], s["disk"], s["self"])

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>交付对账单 · %s</title><style>%s</style></head><body>
<h1>交付对账单</h1>
<div class="meta">会话 %s ｜ 生成 %s ｜ 交付方 %s</div>
%s
<p>%s</p>
<h2>逐条声明</h2>
<table><tr><th>编号</th><th>声明</th><th>期望</th><th>盘上实际</th><th>判定</th><th>依据档</th><th>来源</th></tr>
%s</table>
%s
<h2>这张单子证明不了什么</h2><ul>%s</ul>
<div class="foot">工具 sha256 %s ｜ spec sha256 %s ｜ 工具版本 %s<br>landing check: %d/%d rows</div>
</body></html>
""" % (
        esc(receipt["session"]), CSS, esc(receipt["session"]), esc(receipt["generated_at"]),
        esc((receipt.get("delivery") or {}).get("by", "—")), banner, counts, claims_html,
        "\n".join(ev_html), limits, esc(receipt["tool"]["sha256"]), esc(receipt["spec"]["sha256"]),
        esc(receipt["tool"]["version"]), len(receipt["claims"]), len(receipt["claims"]))


# ---------- 入口 ----------

def write_text(path, text):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def land_check(json_path, html_path, receipt):
    """落盘后从盘上重数，不信任内存里的那份。"""
    with open(json_path, "r", encoding="utf-8") as f:
        back = json.load(f)
    n_json = len(back.get("claims", []))
    with open(html_path, "r", encoding="utf-8") as f:
        page = f.read()
    n_html = page.count('class="claim"')
    m = re.search(r"landing check: (\d+)/(\d+) rows", page)
    total = len(receipt["claims"])
    ok = n_json == n_html == total and m is not None and int(m.group(1)) == total and int(m.group(2)) == total
    return {"claims_json": n_json, "claims_html": n_html, "claims_total": total, "ok": ok}


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--html", default=None)
    args = ap.parse_args(argv)

    spec_path = args.spec
    if not os.path.isfile(spec_path):
        sys.stderr.write("spec not found\n")
        return 1
    out_json = args.out or os.path.splitext(spec_path)[0] + ".对账单.json"
    out_html = args.html or os.path.splitext(spec_path)[0] + ".对账单.html"
    for p in (out_json, out_html):
        if os.path.abspath(p) == os.path.abspath(spec_path):
            sys.stderr.write("refusing to overwrite the spec\n")
            return 1

    try:
        spec_sha = sha256_file(spec_path)
        spec = json.loads(read_text(spec_path))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        sys.stderr.write("spec is not valid UTF-8 JSON\n")
        return 1
    if not isinstance(spec, dict):
        sys.stderr.write("spec must be a JSON object\n")
        return 1
    claims = spec.get("claims")
    if not isinstance(claims, list):
        sys.stderr.write("spec.claims must be an array\n")
        return 1
    ids = [str(c.get("id", "")).strip() if isinstance(c, dict) else "" for c in claims]
    if any(not cid for cid in ids):
        sys.stderr.write("spec: every claim needs a non-empty id\n")
        return 1
    if len(set(ids)) != len(ids):
        sys.stderr.write("spec: duplicate claim id\n")
        return 1
    if not isinstance(spec.get("evidence", {}), dict):
        sys.stderr.write("spec.evidence must be an object\n")
        return 1
    tool_sha = sha256_file(os.path.abspath(__file__))

    receipt = build_receipt(spec, spec_path, spec_sha, tool_sha)
    receipt["landing"] = {"claims_json": None, "claims_html": None,
                          "claims_total": len(receipt["claims"]), "ok": None}

    write_text(out_json, json.dumps(receipt, ensure_ascii=False, indent=1) + "\n")
    write_text(out_html, render_html(receipt))

    landing = land_check(out_json, out_html, receipt)
    receipt["landing"] = landing
    write_text(out_json, json.dumps(receipt, ensure_ascii=False, indent=1) + "\n")
    with open(out_html, "r", encoding="utf-8") as f:
        page = f.read()
    old_mark = "landing check: %d/%d rows" % (landing["claims_html"], landing["claims_total"])
    new_mark = ("landing check: %d/%d rows OK" % (landing["claims_html"], landing["claims_total"])
                if landing["ok"] else
                "landing check: MISMATCH json=%s html=%s total=%s"
                % (landing["claims_json"], landing["claims_html"], landing["claims_total"]))
    if old_mark in page:
        write_text(out_html, page.replace(old_mark, new_mark))

    for c in receipt["claims"]:
        print("%s %s %s" % (c["id"], c["verdict"], c["kind"]))
    s = receipt["summary"]
    print("summary: claims=%d match=%d mismatch=%d absent=%d self=%d disk=%d" % (
        s["claims"], s["match"], s["mismatch"], s["absent"], s["self"], s["disk"]))
    for key, src in receipt["evidence"].items():
        c = src["counts"]
        print("evidence %s: %s green=%d red=%d absent=%d vacuous=%d selfreported=%d" % (
            key, src["verdict"], c["green"], c["red"], c["absent"], c["vacuous"],
            len(src.get("relayed", []))))
    print("status: %s" % receipt["status"])
    print("landing check: %d/%d rows %s" % (landing["claims_html"], landing["claims_total"],
                                            "OK" if landing["ok"] else "MISMATCH"))
    print("wrote: json + html")

    if not landing["ok"]:
        return 1
    return RC_BY_STATUS.get(receipt["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
