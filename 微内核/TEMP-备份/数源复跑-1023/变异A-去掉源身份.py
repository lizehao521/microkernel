"""只读分析：一发答案里的每个数字，能不能在它自己那题的来源里找到。

判据只查"该出现的数出现了"，从不查"不该出现的数没出现"。这里补那半边，把答案里
的数字逐个分三档 ——
  literal   题目 / 判据 expected（numbers、must_text、any_groups）/ 该题 requires 点名的
            文件正文与目录里的文件名逐字有；
  arith     由那些源数用加减（<=3 个；源数 <=COMBO_CAP 的题放宽到 4 个）或乘除（2 个）
            组合得出，并点名用了哪几个；
  orphan    两档都不认 ⇒ 只是候选，要人读，工具不下"编造"的结论。
只有 gets 没有 reads 的题（B05）答案源是实时端点、盘上没有 ⇒ unscoreable，不塌成 orphan。
跑件落的是 answer[:400]，可能截短 ⇒ 单独数 possibly_truncated。
每题的源数集与组合表算一次缓存复用。打印不写盘；打印全走 ensure_ascii。
"""
import itertools
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "业务任务-13.jsonl"
FX = HERE / "业务现场"
HEAD_CAP = 400
COMBO_CAP = 14
REPORTED = ("pass", "fake_close", "step_cap", "echo_close")

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
TSEP_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _load(tag, fname):
    import importlib.util
    spec = importlib.util.spec_from_file_location(tag, HERE / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = _load("agg_mod", "汇总-业务重复-1023.py")
bucket = AGG.bucket


def norm(tok):
    return tok.replace(",", "") if TSEP_RE.match(tok) else tok


def nums(text):
    out = []
    for m in NUM_RE.finditer(text or ""):
        raw = m.group(0).rstrip(".,")
        if not raw:
            continue
        try:
            out.append((raw, float(norm(raw))))
        except ValueError:
            pass
    return out


def load_tasks():
    return {t["id"]: t for t in (json.loads(x) for x in
            TASKS.read_text(encoding="utf-8").splitlines() if x.strip())}


def sanctioned(task):
    """Return (literal_values, base_values, unscoreable, sources)."""
    req = task.get("requires") or {}
    literal, base, sources = set(), set(), []
    unscoreable = bool(req.get("gets")) and not any(
        req.get(k) for k in ("reads", "lists", "stats"))
    for key in ("reads", "stats"):
        for rel in req.get(key) or []:
            p = FX / rel
            if p.is_file():
                vals = [v for _, v in nums(p.read_text(encoding="utf-8"))]
                literal.update(vals)
                base.update(vals)
                sources.append(rel)
            else:
                sources.append("MISSING:" + rel)
    for rel in req.get("lists") or []:
        d = FX / rel
        if d.is_dir():
            for f in sorted(d.iterdir()):
                vals = [v for _, v in nums(f.name)]
                literal.update(vals)
                base.update(vals)
                sources.append(rel + "/" + f.name)
        else:
            sources.append("MISSING-DIR:" + rel)
    for field in ("numbers", "must_text", "any_groups"):
        blob = json.dumps(task.get(field), ensure_ascii=False)
        literal.update(v for _, v in nums(blob))
    literal.update(v for _, v in nums(task.get("question") or ""))
    return literal, base, unscoreable, sources


def explain_map(base):
    """value -> (rule, operands); also returns whether the relaxed cap was used."""
    bs = sorted(set(base))
    relaxed = len(bs) <= COMBO_CAP
    sizes = (1, 2, 3, 4) if relaxed else (1, 2, 3)
    em = {}
    for a, b in itertools.permutations(bs, 2):
        em.setdefault(round(a * b, 4), ("乘", [a, b]))
        if b:
            em.setdefault(round(a / b, 4), ("除", [a, b]))
    for size in sizes:
        for combo in itertools.combinations(bs, size):
            for signs in itertools.product((1, -1), repeat=size):
                if signs[0] == -1:
                    continue
                acc = sum(s * x for s, x in zip(signs, combo))
                pos = [x if s > 0 else -x for s, x in zip(signs, combo)]
                em.setdefault(round(acc, 4), ("加减", pos))
    return em, relaxed


_PACK = {}


def task_pack(task):
    tid = task["id"]
    if tid not in _PACK:
        literal, base, unscoreable, sources = sanctioned(task)
        em, relaxed = explain_map(base)
        _PACK[tid] = (literal, em, unscoreable, sources, len(set(base)), relaxed)
    return _PACK[tid]


UNITS = (100, 1000, 10000, 100000, 1000000)


def answer_numbers(head):
    """Number tokens in the answer, skipping leading list ordinals like '3. 扩展坞'."""
    out = []
    for s in SENT_SPLIT.split(head or ""):
        st = s.strip()
        if not st:
            continue
        for m in NUM_RE.finditer(st):
            raw = m.group(0).rstrip(".,")
            if not raw:
                continue
            if "." not in raw and m.start() == 0:
                nxt = st[m.end():m.end() + 1]
                after = st[m.end() + 1:m.end() + 2]
                if nxt in ("、", ")") or (nxt == "." and not after.isdigit()):
                    continue
            try:
                out.append((raw, float(norm(raw))))
            except ValueError:
                pass
    return out


def classify(row, task):
    head = row.get("answer_head") or ""
    literal, em, unscoreable, sources, _nb, _rel = task_pack(task)
    hits = []
    for raw, v in answer_numbers(head):
        if v in literal:
            hits.append({"raw": raw, "value": v, "tier": "literal"})
            continue
        rule = em.get(round(v, 4))
        if rule:
            hits.append({"raw": raw, "value": v, "tier": "arith",
                         "rule": rule[0], "operands": rule[1]})
            continue
        scaled = next(((u, round(v * u, 4)) for u in UNITS if round(v * u, 4) in literal), None)
        if scaled:
            hits.append({"raw": raw, "value": v, "tier": "unit",
                         "scale": scaled[0], "source": scaled[1]})
        else:
            hits.append({"raw": raw, "value": v, "tier": "orphan"})
    tiers = {}
    for h in hits:
        tiers[h["tier"]] = tiers.get(h["tier"], 0) + 1
    return {
        "id": row.get("id"), "pass": row.get("pass"), "bucket": row.get("__bucket__"),
        "unscoreable": unscoreable,
        "head_chars": len(head),
        "possibly_truncated": len(head) >= HEAD_CAP,
        "numbers": len(hits),
        "orphan_values": sorted({h["raw"] for h in hits if h["tier"] == "orphan"}),
        "arith_operands": [h["operands"] for h in hits if h["tier"] == "arith"],
        "tiers": tiers,
        "sources": sources,
    }


def share(k, n):
    return round(k / n, 4) if n else None


def pool(docs):
    rows = []
    for i, d in enumerate(docs):
        src = "%d:%s" % (i, d.get("__source__") or "?")
        for r in d["runs"]:
            r = dict(r)
            r["__bucket__"] = bucket(r)
            r["__src__"] = src
            rows.append(r)
    return rows


def row_key(r):
    """一发在合并里的身份 = 源 + 题 + 趟。只按 (题,趟) 会把不同落盘读数的同名键吃掉：
    13x20 与 三题x20 都有 B01 的 pass 1..20，那是 40 个独立发，不是 20 个。"""
    return (None, r.get("id"), r.get("pass"))  # MUT: 退化成旧的 (题,趟) 身份


def analyze(rows, tasks):
    scored = {k: [] for k in REPORTED}
    transport = unscoreable = unknown_task = 0
    for r in rows:
        b = r.get("__bucket__")
        if b == "transport":
            transport += 1
            continue
        t = tasks.get(r.get("id"))
        if t is None:
            unknown_task += 1
            continue
        c = classify(r, t)
        if c["unscoreable"]:
            unscoreable += 1
            continue
        scored.setdefault(b, []).append(c)
    out = {"transport_skipped": transport, "unscoreable_skipped": unscoreable,
           "unknown_task_skipped": unknown_task,
           "all_scored_rows": sum(len(v) for v in scored.values()),
           "unscoreable_why": "该题只有 gets：答案源是实时端点(/api/health)，盘上没有，不判 orphan"}
    for name in REPORTED:
        lst = scored.get(name, [])
        n = len(lst)
        orph = [c for c in lst if c["orphan_values"]]
        distinct = {}
        for c in orph:
            for v in c["orphan_values"]:
                distinct[v] = distinct.get(v, 0) + 1
        out[name] = {
            "rows": n,
            "numbers_total": sum(c["numbers"] for c in lst),
            "rows_with_orphan": len(orph),
            "rows_with_orphan_rate": share(len(orph), n),
            "orphan_number_hits": sum(len(c["orphan_values"]) for c in lst),
            "distinct_orphan_values": dict(sorted(distinct.items(), key=lambda kv: (-kv[1], kv[0]))),
            "rows_arith_supported": sum(1 for c in lst if c["tiers"].get("arith")),
            "tiers_total": {k: sum(c["tiers"].get(k, 0) for c in lst)
                            for k in ("literal", "arith", "unit", "orphan")},
            "possibly_truncated": sum(1 for c in lst if c["possibly_truncated"]),
            "by_task": {str(tid): {"rows": sum(1 for c in lst if c["id"] == tid),
                                   "orphan_rows": sum(1 for c in lst if c["id"] == tid and c["orphan_values"]),
                                   "fixture_numbers": task_pack(tasks[tid])[4],
                                   "relaxed": task_pack(tasks[tid])[5]}
                        for tid in sorted({c["id"] for c in lst})},
            "examples": orph[:8],
        }
    out["unreported_buckets"] = {k: len(v) for k, v in scored.items() if k not in REPORTED}
    return out


HEDGE_WORDS = ("未标注", "未给出", "没有注明", "假设", "若按", "如果", "如需", "无法计算", "未知", "按经验", "默认")
SENT_SPLIT = re.compile(r"[。；;\n]")


def token_re(raw):
    return re.compile(r"(?<![\d.])" + re.escape(raw) + r"(?![\d])")


def sentences_with(head, raw):
    """Sentences in head that actually carry this number token (token-boundary matched)."""
    out = []
    for s in SENT_SPLIT.split(head or ""):
        if s.strip() and token_re(raw).search(s.strip()):
            out.append(s.strip())
    return out


def hedge_of(sentence):
    return [w for w in HEDGE_WORDS if w in sentence]


STANDING_HEDGE = ("未标注", "未给出", "没有注明", "未知", "无法计算")


def claim_context(head, raw):
    """(那句话, hedge 词)。回看上一分句只认"缺依据"那类（未标注/未给出），
    "如果/若按"这种条件句只管它自己那句――否则下一句的直陈会被上一句洗白。
    """
    parts = [p.strip() for p in SENT_SPLIT.split(head or "")]
    for i, s in enumerate(parts):
        if s and token_re(raw).search(s):
            hedged = hedge_of(s)
            if not hedged and i >= 1:
                hedged = [w for w in hedge_of(parts[i - 1]) if w in STANDING_HEDGE]
            return s, hedged
    return "", []


def scored_classified(rows, tasks):
    """(row, classification) for every row the ruler can actually score -- one skip rule,
    shared by the sampling view and the family view so the two can't drift apart."""
    for r in rows:
        b = r.get("__bucket__")
        if b == "transport":
            continue
        t = tasks.get(r.get("id"))
        if t is None:
            continue
        c = classify(r, t)
        if c["unscoreable"]:
            continue
        yield r, c


FAMILY_ORDER = ("tool_receipt", "noise_path_or_name", "chain_unmeasured", "assumed_premise",
                "needs_human")
FAMILY_MEANING = {
    "tool_receipt": "fs.read/text.stats 回执里工具自印的数，已回盘核对，不是模型主张",
    "noise_path_or_name": "这个值只出现在路径段或 UTF-8 这类编码名里，不是答案主张的数（尺子盲区）",
    "chain_unmeasured": "链式算式（先减再除再乘 100），本尺子只做 <=3 项加减/2 项乘除，够不到（盲区）",
    "assumed_premise": "所在句用了题目和文件都没给的税率/系数前提（这族才是编前提）",
    "needs_human": "四族都不认，只能人读，工具不下结论",
}

PATH_NOISE_RE = re.compile(r"[A-Za-z]:[\\/][^\s｜;；]*|[Uu][Tt][Ff]-\d+|hubd-[A-Za-z0-9_\-]+")


def strip_noise(sentence):
    """Remove path segments and encoding names; digits living only there are not claims."""
    return PATH_NOISE_RE.sub(" ", sentence or "")


def family_of(value, sentence, row):
    if not token_re(value).search(strip_noise(sentence)):
        return "noise_path_or_name"
    if TOOL_ECHO_RE.match((row.get("answer_head") or "").strip()):
        return "tool_receipt"
    if "税" in sentence:
        return "assumed_premise"
    if "/" in sentence and "%" in sentence:
        return "chain_unmeasured"
    return "needs_human"


def adjudicate(rows, tasks):
    """给每个孤立数归一个族，族按该值所在的那句话判、命中数必须等于 orphan hits 总数。"""
    fam = {k: {"hits": 0, "values": {}, "by_bucket": {}, "by_task": {}, "example": None,
               "hits_hedged": 0, "hits_asserted": 0} for k in FAMILY_ORDER}
    rows_seen = {k: set() for k in FAMILY_ORDER}
    rows_by_bucket = {k: {} for k in FAMILY_ORDER}
    row_hedged = {}
    total = 0
    for r, c in scored_classified(rows, tasks):
        b = r.get("__bucket__")
        for v in c["orphan_values"]:
            s, hedged = claim_context(r.get("answer_head"), v)
            k = family_of(v, s, r)
            slot = fam[k]
            slot["hits"] += 1
            total += 1
            slot["values"][v] = slot["values"].get(v, 0) + 1
            slot["by_bucket"][b] = slot["by_bucket"].get(b, 0) + 1
            slot["by_task"][r.get("id")] = slot["by_task"].get(r.get("id"), 0) + 1
            rows_seen[k].add(row_key(r))
            rows_by_bucket.setdefault(k, {}).setdefault(b, set()).add(row_key(r))
            key = (k,) + row_key(r)
            row_hedged[key] = row_hedged.get(key, True) and bool(hedged)
            if hedged:
                slot["hits_hedged"] = slot.get("hits_hedged", 0) + 1
            else:
                slot["hits_asserted"] = slot.get("hits_asserted", 0) + 1
            if slot["example"] is None and s:
                slot["example"] = {"value": v, "id": r.get("id"), "pass": r.get("pass"),
                                   "bucket": b, "sentence": s, "hedged": hedged}
    for k in FAMILY_ORDER:
        fam[k]["rows"] = len(rows_seen[k])
        fam[k]["rows_by_bucket"] = {b: len(s) for b, s in rows_by_bucket[k].items()}
        fam[k]["rows_hedged"] = sum(1 for (kk, _s, _i, _p), v in row_hedged.items()
                                    if kk == k and v)
        fam[k]["rows_asserted"] = fam[k]["rows"] - fam[k]["rows_hedged"]
        fam[k]["values"] = dict(sorted(fam[k]["values"].items(), key=lambda kv: (-kv[1], kv[0])))
    fam["needs_human"]["same_value_in_other_families"] = {
        v: {k: fam[k]["values"][v] for k in FAMILY_ORDER
            if k not in ("needs_human", "noise_path_or_name") and v in fam[k]["values"]}
        for v in fam["needs_human"]["values"]}
    return {"orphan_hits_in": total,
            "orphan_hits_out": sum(fam[k]["hits"] for k in FAMILY_ORDER),
            "families_close": total == sum(fam[k]["hits"] for k in FAMILY_ORDER),
            "meanings": FAMILY_MEANING, "families": fam}


def orphan_samples(rows, tasks, per_value=2):
    """value -> [{id, bucket, sentence, hedged}] so a human can adjudicate each hit."""
    seen = {}
    for r, c in scored_classified(rows, tasks):
        b = r.get("__bucket__")
        for v in c["orphan_values"]:
            slot = seen.setdefault(v, {"value": v, "hits": 0, "by_bucket": {}, "samples": []})
            slot["hits"] += 1
            slot["by_bucket"][b] = slot["by_bucket"].get(b, 0) + 1
            if len(slot["samples"]) < per_value:
                s, hedged = claim_context(r.get("answer_head"), v)
                if s:
                    slot["samples"].append({"id": r.get("id"), "pass": r.get("pass"),
                                            "bucket": b, "sentence": s, "hedged": hedged})
    return dict(sorted(seen.items(), key=lambda kv: -kv[1]["hits"]))


def file_metrics(rel):
    p = FX / rel
    raw = p.read_bytes()
    txt = raw.decode("utf-8")
    lines = txt.splitlines()
    seg = txt.split("\n")
    return {"path": rel, "bytes": len(raw), "codepoints": len(txt),
            "lines": len(lines), "blank_lines": sum(1 for L in lines if not L.strip()),
            "lines_alt": len(seg),
            "blank_lines_alt": sum(1 for L in seg if not L.strip()),
            "trailing_newline": txt.endswith("\n")}


CLAIM_KINDS = (
    ("blank_lines", r"空行\s*(\d+)"),
    ("codepoints", r"码元\s*(\d+)"),
    ("bytes", r"字节\s*(\d+)"),
    ("bytes", r"(?<![\w-])(\d+)\s*字节"),
    ("codepoints", r"(?<![\w-])(\d+)\s*码元"),
    ("lines", r"(?<!空)(?<!序)(?<!一)行\s*(\d+)"),
)


def fixture_rel(path):
    for sep in ("/fixture/", "\\fixture\\"):
        if sep in (path or ""):
            return path.split(sep, 1)[1].lstrip("\\/")
    return None


TOOL_ECHO_RE = re.compile(r"^[a-z_]+\.[a-z_]+：")
CLAIM_CONTEXT_SKIP = ("最长一行", "在第", "行长度")


def claim_units(head):
    """(kind, value) pairs that read as assertions about the file as a whole."""
    found = set()
    for kind, pat in CLAIM_KINDS:
        for m in re.finditer(pat, head or ""):
            before = (head or "")[max(0, m.start() - 12):m.start()]
            if any(w in before for w in CLAIM_CONTEXT_SKIP):
                continue
            found.add((kind, int(m.group(1))))
    return found


def check_one_claim(kind, val, paths):
    """Compare one claim under BOTH line conventions; never pick the flattering one silently."""
    for rel in sorted(paths):
        if not (FX / rel).is_file():
            continue
        fm = file_metrics(rel)
        cand = sorted({v for v in (fm.get(kind), fm.get(kind + "_alt")) if v is not None})
        if not cand:
            continue
        if val in cand:
            return "ok", rel, cand, len(cand) > 1
        return "wrong", rel, cand, len(cand) > 1
    return None, None, None, False


def metrics_claims(rows, tasks):
    """答案里凡是"字节/码元/行/空行 N"这种关于文件本身的断言，回盘上核对。

    分两档：以 fs.read：/text.stats：这类回执开头的，数数是工具自己印的，不算模型断言；
    剩下散文里的才是模型关于文件的说法。行/空行盘上有两种口径（splitlines 与按换行切段），
    两种都认，并把"两口径本就不同"单独计数，不拿一种去判另一种死刑。
    """
    ok = wrong = unparsed = divergent = 0
    detail = []
    groups = {}
    for r in rows:
        if r.get("__bucket__") == "transport":
            continue
        head = r.get("answer_head") or ""
        paths = {fixture_rel(e.get("path")) for e in (r.get("trail") or [])
                 if isinstance(e, dict) and fixture_rel(e.get("path"))}
        if not paths:
            continue
        gkey = "tool_receipt" if TOOL_ECHO_RE.match(head.strip()) else "model_prose"
        g = groups.setdefault(gkey, {"rows": 0, "claims": 0, "ok": 0, "wrong": 0, "unmatched": 0})
        units = sorted(claim_units(head))
        if units:
            g["rows"] += 1
        for kind, val in units:
            g["claims"] += 1
            state, rel, cand, dv = check_one_claim(kind, val, paths)
            if dv:
                divergent += 1
            if state is None:
                unparsed += 1
                g["unmatched"] += 1
                detail.append({"id": r.get("id"), "pass": r.get("pass"), "group": gkey,
                               "kind": kind, "claimed": val,
                               "why": "这一发的 trail 里没有能对上的 fixture 文件"})
            elif state == "ok":
                ok += 1
                g["ok"] += 1
            else:
                wrong += 1
                g["wrong"] += 1
                detail.append({"id": r.get("id"), "pass": r.get("pass"),
                               "bucket": r.get("__bucket__"), "group": gkey,
                               "kind": kind, "claimed": val, "file": rel,
                               "actual_both_conventions": cand})
    return {"claims_checked": ok + wrong + unparsed, "claims_ok": ok, "claims_wrong": wrong,
            "claims_unmatched": unparsed,
            "claims_line_convention_divergent": divergent,
            "by_source": groups,
            "why_unmatched": "trail 的 path 落不在 业务现场/ 下，或这题读的是端点不是文件",
            "detail": detail[:12]}


def load_one(name):
    p = Path(name)
    if not p.is_absolute() and not p.exists():
        p = HERE / "读数" / name
    d = json.loads(p.read_text(encoding="utf-8"))
    d["__source__"] = p.name
    return d


TASKS_ALL = load_tasks()


def tnum(tid, head):
    return classify({"id": tid, "pass": 1, "answer_head": head, "__bucket__": "pass"},
                    TASKS_ALL[tid])


def selftest():
    red = []
    # arm1: a number that is nowhere in the invoice must be orphan
    red.append(("arm1 编的数要孤立",
                tnum("B01", "含税合计 1280 元，另有运费 9731 元。")["orphan_values"] == ["9731"]))
    # arm1b: the same shape without the bogus number stays clean (screen is not always-red)
    red.append(("arm1b 有源的不许响",
                tnum("B01", "含税合计 1280 元，其中运费 0 元。")["orphan_values"] == []))
    # arm2: thousand separators must not false-red (the reports write 1,250,000)
    red.append(("arm2 千分位不误判",
                tnum("B11", "销售部 1,250,000 元，财务部 1,184,000 元。")["orphan_values"] == []))
    # arm3: oracle-named derived number (66000) is supported
    red.append(("arm3 判据点名的派生数有源",
                tnum("B11", "两份报表差 66000 元。")["orphan_values"] == []))
    # arm4: sum of 4 budget lines (51500) needs the relaxed cap, arith must name operands
    c = tnum("B02", "已发生合计 51500 元，超支 1500 元。")
    red.append(("arm4 四项求和放宽后有源",
                c["orphan_values"] == [] and any(sum(o) == 51500 for o in c["arith_operands"])))
    # arm5: the relaxation is per task and visible (log-heavy task must NOT be relaxed)
    red.append(("arm5 放宽上限按题点名",
                task_pack(TASKS_ALL["B02"])[5] is True and task_pack(TASKS_ALL["B04"])[5] is False))
    # arm6: gets-only task is unscoreable, not orphan
    c = tnum("B05", "ok=true，注册了 12 个工具。")
    red.append(("arm6 端点题记 unscoreable", c["unscoreable"] is True and c["orphan_values"] == []))
    # arm7: truncation flag honest both ways
    red.append(("arm7 满 400 字符标可能截短", bool(tnum("B01", "x" * HEAD_CAP)["possibly_truncated"])))
    red.append(("arm7b 短答案不许标截短", not tnum("B01", "合计 1280 元。")["possibly_truncated"]))
    # arm8: two chained operations are beyond arith => orphan; the tool admits the limit
    red.append(("arm8 链式运算落 orphan（不假装会算）",
                tnum("B07", "可用率 99.8958%。")["orphan_values"] == ["99.8958"]))
    # arm9: version strings named by must_text are supported
    red.append(("arm9 版本号不误判",
                tnum("B12", "VERSION 是 2.4.1，变更日志最新 2.4.0，不一致。")["orphan_values"] == []))
    # arm10: a missing fixture file is named instead of silently treated as empty
    lit2, base2, uns2, src2 = sanctioned({"id": "X", "requires": {"reads": ["不存在/没有.txt"]}})
    red.append(("arm10 现场缺文件要点名",
                base2 == set() and any(s.startswith("MISSING") for s in src2)))
    # arm11: buckets come from the shared aggregator; transport beats ok=True
    red.append(("arm11 分桶复用主件",
                bucket({"ok": True, "err": "x"}) == "transport" and bucket({"ok": True}) == "pass"))
    # arm12: empty answer counts 0 numbers instead of crashing or flagging
    c = tnum("B01", "")
    red.append(("arm12 空答案数 0 个数字", c["numbers"] == 0 and c["orphan_values"] == []))
    # arm13: row accounting closes on a real reading - no row silently dropped
    docs = [load_one("业务任务-13x5-真端点-修判据v3.json")]
    rows = pool(docs)
    res = analyze(rows, TASKS_ALL)
    summed = (res["all_scored_rows"] + res["transport_skipped"] + res["unscoreable_skipped"]
              + res["unknown_task_skipped"])
    red.append(("arm13 逐发归账闭合（分母不吞发）", summed == len(rows)))
    # arm14: rows outside the four reported buckets are named, not dropped
    red.append(("arm14 没点名的桶要显式列出",
                sum(res["unreported_buckets"].values())
                == res["all_scored_rows"] - sum(res[k]["rows"] for k in REPORTED)))
    # arm15: injecting a bogus number into a REAL passing row must light the screen
    hit = None
    for r in rows:
        if r.get("ok"):
            orig = classify(r, TASKS_ALL[r["id"]])
            fake = dict(r)
            fake["answer_head"] = (r.get("answer_head") or "") + " 另计赔付 77777 元。"
            inj = classify(fake, TASKS_ALL[r["id"]])
            if inj["orphan_values"] == ["77777"] and orig["orphan_values"] == []:
                hit = r["id"]
                break
    red.append(("arm15 往真好账里塞数必被咬", hit is not None))
    # arm16: a number beyond the 400-char window is invisible - the scope limit is asserted
    beyond = ("合计 1280 元。" + "补" * 400 + " 77777 元")[:HEAD_CAP]
    c = tnum("B01", beyond)
    red.append(("arm16 窗口外的数扫不到（口径写死）",
                c["orphan_values"] == [] and bool(c["possibly_truncated"])))
    # arm17: the sentence that carries an orphan number must be quotable, and the quote must hold it
    head = "含税合计按 6% 算是 1356.8 元。合计本身是 1280 元。"
    ss = sentences_with(head, "1356.8")
    red.append(("arm17 孤立数要能摘出原句且原句含该数",
                len(ss) == 1 and "1356.8" in ss[0] and "1280" not in ss[0]))
    # arm18: hedge flag works both directions
    red.append(("arm18 hedge 两个方向都认",
                hedge_of("发票未标注税率，若按 6% 算得 1356.8 元") != []
                and hedge_of("含税合计 1356.8 元，已确认无误") == []))
    # arm19: samples are attached to the right bucket and value, nothing invented
    demo = [{"id": "B01", "pass": 1, "__bucket__": "pass", "answer_head": head},
            {"id": "B01", "pass": 2, "__bucket__": "fake_close", "answer_head": "含税 9731 元。"}]
    samp = orphan_samples(demo, TASKS_ALL, per_value=2)
    red.append(("arm19 抽样按桶归对、值不许凭空",
                samp.get("1356.8", {}).get("by_bucket") == {"pass": 1}
                and samp.get("9731", {}).get("by_bucket") == {"fake_close": 1}
                and all("9731" in s["sentence"] for s in samp["9731"]["samples"])))
    # arm20: list ordinals must not be counted as claims, real numbers in the same line must be
    c = tnum("B13", "库存低于 10 的商品名称：\n1. 机械键盘（库存 4）\n3. 扩展坞（库存 2）")
    red.append(("arm20 题号序号不当数、正文数照算", c["orphan_values"] == [] and c["numbers"] >= 3))
    c = tnum("B13", "共 3 项低于阈值，其中 9731 项紧急。")
    red.append(("arm20b 非句首的数照常判", "9731" in c["orphan_values"] and "3" in c["orphan_values"]))
    # arm21: unit rewrite (万元) is a source, not a fabrication
    c = tnum("B11", "销售部 125 万元，财务部 118.4 万元，差 6.6 万元。")
    red.append(("arm21 万元换算算有源", c["orphan_values"] == []
                and c["tiers"].get("unit", 0) >= 2))
    # arm21b: the unit rule must not swallow the invented tax numbers
    c = tnum("B01", "含税合计 1356.80 元（按 6% 税率，税金 76.8 元，系数 1.06）。")
    red.append(("arm21b 税率那族不许被单位规则吃掉",
                set(c["orphan_values"]) >= {"1356.80", "76.8", "1.06"}))
    # arm22: chained arithmetic still lands orphan (the screen admits the reach limit)
    red.append(("arm22 链式运算仍落 orphan",
                tnum("B07", "可用率 = (43,200 - 45) / 43,200 = 99.896%。")["orphan_values"] == ["99.896"]))
    # arm23: file metrics on disk are the yardstick for "字节 N / 码元 N" claims
    m = file_metrics("客户/投诉.csv")
    red.append(("arm23 现场文件度量自印", m["bytes"] > 0 and m["codepoints"] > 0
                and m["bytes"] >= m["codepoints"] and m["lines"] == 6))
    # arm24: a true metrics claim verifies ok, a wrong one is named with expected value
    trail = [{"tool": "fs.read", "path": "C:\\x\\hubd-t\\fixture/" + "客户/投诉.csv".replace("/", "\\")}]
    good = {"id": "B09", "pass": 1, "__bucket__": "pass",
            "answer_head": "读到 %d 字节（UTF-8 码元 %d 个）" % (m["bytes"], m["codepoints"]),
            "trail": [{"tool": "fs.read", "path": "C:\\x\\hubd-t\\fixture\\客户\\投诉.csv"}]}
    badr = dict(good)
    badr["answer_head"] = "读到 %d 字节" % (m["bytes"] + 1)
    res2 = metrics_claims([good], TASKS_ALL)
    res3 = metrics_claims([badr], TASKS_ALL)
    red.append(("arm24 真度量核对过、假度量要点名",
                res2["claims_ok"] >= 1 and res3["claims_wrong"] == 1
                and res3["detail"][0]["actual_both_conventions"] == [m["bytes"]]))
    # arm25: a metric claim with no readable file in that row's trail is unmatched, not silently ok
    nopath = {"id": "B09", "pass": 1, "__bucket__": "pass", "answer_head": "字节 190", "trail": []}
    res4 = metrics_claims([nopath], TASKS_ALL)
    red.append(("arm25 对不上文件的要单开一档", res4["claims_checked"] == 0))
    nopath2 = {"id": "B09", "pass": 1, "__bucket__": "pass", "answer_head": "字节 190",
               "trail": [{"tool": "http.get", "path": "/api/health"}]}
    red.append(("arm25b 端点 trail 不冒认文件断言", metrics_claims([nopath2], TASKS_ALL)["claims_checked"] == 0))
    # arm26: "最长一行 50 字节" is a per-line stat, not a claim about the file's total bytes
    perline = {"id": "B01", "pass": 1, "__bucket__": "pass",
               "answer_head": "text.stats： 字节 190 ｜ 最长一行 50 字节，在第 4 行",
               "trail": [{"tool": "text.stats",
                          "path": "C:\\x\\fixture\\财务\\发票-2026-031.txt"}]}
    r6 = metrics_claims([perline], TASKS_ALL)
    red.append(("arm26 单行字节数不当文件总字节", r6["claims_wrong"] == 0
                and all(d["kind"] != "bytes" or d["claimed"] != 50 for d in r6["detail"])))
    # arm27: the two line conventions both count, so text.stats' 7行/空行1 must not be judged wrong
    fm1 = file_metrics("财务/发票-2026-031.txt")
    red.append(("arm27 盘上行数两口径并存", fm1["lines"] + 1 == fm1["lines_alt"]
                and fm1["trailing_newline"] and fm1["blank_lines"] + 1 == fm1["blank_lines_alt"]))
    alt = {"id": "B01", "pass": 1, "__bucket__": "pass",
           "answer_head": "text.stats： 字节 %d ｜ 行 %d（空行 %d）" % (fm1["bytes"], fm1["lines_alt"], fm1["blank_lines_alt"]),
           "trail": [{"tool": "text.stats", "path": "C:\\x\\fixture\\财务\\发票-2026-031.txt"}]}
    r7 = metrics_claims([alt], TASKS_ALL)
    red.append(("arm27b 工具口径的行数判过不判错", r7["claims_wrong"] == 0 and r7["claims_ok"] >= 3
                and r7["claims_line_convention_divergent"] >= 2))
    # arm28: a receipt echo and a prose claim are counted apart; the echo is not the model's assertion
    echo = {"id": "B01", "pass": 2, "__bucket__": "echo_close",
            "answer_head": "fs.read：C:\\x\\fixture\\财务\\发票-2026-031.txt ｜ 读到 %d 字节" % fm1["bytes"],
            "trail": [{"tool": "fs.read", "path": "C:\\x\\fixture\\财务\\发票-2026-031.txt"}]}
    r8 = metrics_claims([echo, badr], TASKS_ALL)
    red.append(("arm28 回执与散文分档计", r8["by_source"]["tool_receipt"]["claims"] >= 1
                and r8["by_source"]["model_prose"]["wrong"] == 1
                and r8["by_source"]["tool_receipt"]["wrong"] == 0))
    # arm29: "UTF-8" is an encoding name, not a codepoint count -- the real receipt must be clean
    fm2 = file_metrics("财务/发票-2026-031.txt")
    rec = {"id": "B01", "pass": 5, "__bucket__": "step_cap",
           "answer_head": "fs.read：C:\\x\\fixture\\财务\\发票-2026-031.txt ｜ 读到 %d 字节（UTF-8 码元 %d 个）"
                          % (fm2["bytes"], fm2["codepoints"]),
           "trail": [{"tool": "fs.read", "path": "C:\\x\\fixture\\财务\\发票-2026-031.txt"}]}
    r9 = metrics_claims([rec], TASKS_ALL)
    red.append(("arm29 UTF-8 里的 8 不当码元数", r9["claims_wrong"] == 0 and r9["claims_ok"] == 2))
    red.append(("arm29b 真在数前的码元数照认",
                sorted(claim_units("共 112 码元")) == [("codepoints", 112)]))
    # arm30-34: every orphan hit must land in a named family, by the sentence it sits in
    frows = [
        {"id": "B01", "pass": 1, "__bucket__": "step_cap",
         "answer_head": "fs.read：C:\\x\\fixture\\财务\\发票-2026-031.txt ｜ 读到 777 字节（UTF-8 码元 112 个）",
         "trail": []},
        {"id": "B01", "pass": 2, "__bucket__": "pass",
         "answer_head": "含税合计为 4321 元（按 9% 税率）。", "trail": []},
        {"id": "B07", "pass": 3, "__bucket__": "pass",
         "answer_head": "可用率 = (43,200 - 45) / 43,200 = 77.7%", "trail": []},
        {"id": "B09", "pass": 4, "__bucket__": "fake_close",
         "answer_head": '--path "C:\\Users\\hubd-biz-real-abc12\\fixture\\客户\\投诉.csv"', "trail": []},
        {"id": "B13", "pass": 5, "__bucket__": "pass",
         "answer_head": "库存低于 10 的商品有 987654 件。", "trail": []},
    ]
    fam = adjudicate(frows, TASKS_ALL)["families"]
    red.append(("arm30 回执数归 tool_receipt 不脏模型", "777" in fam["tool_receipt"]["values"]))
    red.append(("arm31 税率句归 assumed_premise", "4321" in fam["assumed_premise"]["values"]))
    red.append(("arm32 链式算式归 chain_unmeasured", "77.7" in fam["chain_unmeasured"]["values"]))
    red.append(("arm33 目录名数字归 noise_path_or_name", "12" in fam["noise_path_or_name"]["values"]))
    red.append(("arm34 谁都不认的归 needs_human", "987654" in fam["needs_human"]["values"]))
    # arm36: in a receipt row, the byte/codepoint counts are the tool's numbers;
    #          the digits living only in the path or in "UTF-8" are not claims at all
    s_rec = ("fs.read：C:\\Users\\Temp\\hubd-biz-real-j6s_pu2t\\fixture\\客户\\客户名单.csv"
             " ｜ 读到 257 字节（UTF-8 码元 209 个）")
    row_rec = {"answer_head": s_rec}
    red.append(("arm36 回执字节数不算目录噪声",
                family_of("257", s_rec, row_rec) == "tool_receipt"
                and family_of("209", s_rec, row_rec) == "tool_receipt"
                and family_of("6", s_rec, row_rec) == "noise_path_or_name"))
    red.append(("arm37 编码名与目录名里的单个数字归噪声",
                family_of("8", s_rec, row_rec) == "noise_path_or_name"
                and family_of("2", s_rec, row_rec) == "noise_path_or_name"))
    # arm38: a needs_human value that also shows up with its算式 elsewhere is reported, not condemned
    f38 = adjudicate([{"id": "B07", "pass": 1, "__bucket__": "pass",
                       "answer_head": "可用率 = (43,200 - 45) / 43,200 = 77.7%", "trail": []},
                      {"id": "B07", "pass": 8, "__bucket__": "pass",
                       "answer_head": "停机 45 分钟，可用率约 77.7%。", "trail": []}],
                     TASKS_ALL)["families"]
    red.append(("arm38 同值在别族出现过要点名",
                f38["needs_human"]["same_value_in_other_families"].get("77.7")
                == {"chain_unmeasured": 1}))
    a35 = adjudicate(frows, TASKS_ALL)
    red.append(("arm35 族闭合且与逐值视图同分母",
                a35["families_close"] and a35["orphan_hits_in"]
                == sum(v["hits"] for v in orphan_samples(frows, TASKS_ALL).values())))
    # arm46: hedge is counted per row, and a row that asserts anything is not a "hedged" row
    f46 = adjudicate([{"id": "B01", "pass": 1, "__bucket__": "pass",
                       "answer_head": "如果按 9% 税率算则为 4321 元。含税合计 5567 元（按 9% 税率）。",
                       "trail": []},
                      {"id": "B01", "pass": 2, "__bucket__": "pass",
                       "answer_head": "未标注税率；按 9% 税率算则为 4321 元。", "trail": []}],
                     TASKS_ALL)["families"]["assumed_premise"]
    red.append(("arm46 hedge 按行判、有一句直陈就不算 hedge 行",
                f46["rows"] == 2 and f46["rows_hedged"] == 1 and f46["rows_asserted"] == 1
                and f46["hits_hedged"] + f46["hits_asserted"] == f46["hits"]))
    # arm47: rows_by_bucket must never exceed the hit count of that bucket
    f47 = adjudicate(frows, TASKS_ALL)["families"]
    red.append(("arm47 行数与命中数同源自洽（行<=命中）",
                all(sum(v.values()) <= fam2["hits"]
                    for fam2 in f47.values() for v in [fam2["rows_by_bucket"]])
                and all(n <= fam2["by_bucket"].get(b, 0)
                        for fam2 in f47.values() for b, n in fam2["rows_by_bucket"].items())))
    # arm48: "未标注" is a standing disclaimer and covers the next clause; "如果" does not
    red.append(("arm48 缺依据管下一句、条件句只管自己",
                claim_context("未标注税率；按 9% 税率算则为 4321 元", "4321")[1] == ["未标注"]
                and claim_context("如果按 9% 税率算则为 4321 元。含税合计 5567 元", "5567")[1] == []))
    # arm49: the per-value view and the family view must share one denominator
    a49s = sum(v["hits"] for v in orphan_samples(frows, TASKS_ALL).values())
    red.append(("arm49 逐值视图与族视图同分母",
                a49s == adjudicate(frows, TASKS_ALL)["orphan_hits_in"]))
    # arm50: zero must print as 0, not vanish into null (三态不许塌)
    a50 = adjudicate([{"id": "B01", "pass": 1, "__bucket__": "pass",
                       "answer_head": "含税合计 5567 元（按 9% 税率）。", "trail": []}],
                     TASKS_ALL)["families"]
    red.append(("arm50 每一族都带 hedge 两格且不为 null",
                all(isinstance(a50[k].get("hits_hedged"), int)
                    and isinstance(a50[k].get("hits_asserted"), int) for k in FAMILY_ORDER)
                and a50["assumed_premise"]["hits_hedged"] == 0
                and a50["assumed_premise"]["hits_asserted"] >= 1))
    # arm51/52/53: row identity across pooled sources. 13x20 与 三题x20 都有 B01 的 pass 1..20，
    # 那是两本独立跑次，只按 (题,趟) 归并就会把 28 发印成 18 发。
    a51row = {"id": "B01", "pass": 1, "__bucket__": "pass", "trail": [],
              "answer_head": "含税合计 4321 元（按 9% 税率）。"}
    d51 = pool([{"__source__": "A.json", "runs": [dict(a51row)]},
                {"__source__": "B.json", "runs": [dict(a51row)]}])
    f51 = adjudicate(d51, TASKS_ALL)["families"]["assumed_premise"]
    red.append(("arm51 合并里同名键的两发算两发（源进身份）",
                len(d51) == 2 and f51["rows"] == 2 and f51["values"].get("4321") == 2
                and f51["rows_asserted"] == 2 and f51["rows_hedged"] == 0))
    d52 = pool([{"runs": [dict(a51row)]}, {"runs": [dict(a51row)]}])
    f52 = adjudicate(d52, TASKS_ALL)["families"]["assumed_premise"]
    red.append(("arm52 同名读数列两遍也不塌（索引兜底，臂前提是两趟都没 __source__）",
                len(d52) == 2 and f52["rows"] == 2
                and len({r["__src__"] for r in d52}) == 2))
    # 叶子臂：身份不是"每出现一次算一次"――同一源同一 (题,趟) 仍是同一发
    f53 = adjudicate([dict(a51row, __src__="0:A.json"), dict(a51row, __src__="0:A.json")],
                     TASKS_ALL)["families"]["assumed_premise"]
    red.append(("arm53 同一源同一发重复出现仍算一发",
                f53["rows"] == 1 and f53["values"].get("4321") == 2))
    fails = [n for n, okv in red if not okv]
    for n, okv in red:
        print(json.dumps({"arm": n, "ok": bool(okv)}, ensure_ascii=True))
    print(json.dumps({"arms": len(red), "selftest_fails": len(fails), "failed": fails},
                     ensure_ascii=True))
    return 1 if fails else 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not names:
        names = ["业务任务-13x20-真端点.json",
                 "业务任务-13x5-真端点-修判据v3.json",
                 "业务任务-三题x20-真端点.json"]
    docs = [load_one(n) for n in names]
    rows = pool(docs)
    print(json.dumps({"sources": len(docs), "pooled_rows": len(rows),
                      "exe": docs[0].get("exe"),
                      "task_set_sha256": docs[0].get("task_set_sha256"),
                      "fixture_files": sum(1 for p in FX.rglob("*") if p.is_file()),
                      "head_cap": HEAD_CAP, "combo_cap": COMBO_CAP,
                      "task_set": TASKS.name}, ensure_ascii=True))
    res = analyze(rows, TASKS_ALL)
    summed = (res["all_scored_rows"] + res["transport_skipped"] + res["unscoreable_skipped"]
              + res["unknown_task_skipped"])
    print(json.dumps({"row_accounting": {"pooled_rows": len(rows), "summed": summed,
                                         "closes": summed == len(rows)},
                      "transport_skipped": res["transport_skipped"],
                      "unscoreable_skipped": res["unscoreable_skipped"],
                      "unscoreable_why": res["unscoreable_why"],
                      "unreported_buckets": res["unreported_buckets"],
                      "note": "只扫答案前 400 字符；orphan 是候选，不下编造结论"},
                     ensure_ascii=True))
    for k in REPORTED:
        print(json.dumps({"bucket": k,
                          **{kk: vv for kk, vv in res[k].items() if kk != "examples"}},
                         ensure_ascii=True))
    for k in REPORTED:
        for ex in res[k]["examples"]:
            print(json.dumps({"example": k, **ex}, ensure_ascii=True))
    samples = orphan_samples(rows, TASKS_ALL)
    print(json.dumps({"orphan_values_distinct": len(samples),
                      "orphan_hits_total": sum(v["hits"] for v in samples.values()),
                      "note": "每个孤立数摘原句给人判：hedge 非空 = 那句话自己标了假设/缺依据"},
                     ensure_ascii=True))
    for v, slot in samples.items():
        print(json.dumps({"orphan_value": v, **slot}, ensure_ascii=True))
    adj = adjudicate(rows, TASKS_ALL)
    print(json.dumps({"adjudicate": {k: adj[k] for k in
                                     ("orphan_hits_in", "orphan_hits_out", "families_close",
                                      "meanings")},
                      "note": "族按所在句判；tool_receipt/chain_unmeasured/noise 是尺子盲区，"
                              "assumed_premise 才是编前提"}, ensure_ascii=True))
    for k in FAMILY_ORDER:
        print(json.dumps({"family": k, **adj["families"][k]}, ensure_ascii=True))
    mc = metrics_claims(rows, TASKS_ALL)
    print(json.dumps({"metrics_claims": mc,
                      "note": "\u5b57\u8282/\u7801\u5143/\u884c/\u7a7a\u884c\u8fd9\u7c7b\u5173\u4e8e\u6587\u4ef6\u672c\u8eab\u7684\u65ad\u8a00"
                              "\u56de\u76d8\u4e0a\u6838\uff1bunmatched \u4e0d\u662f\u9519\uff0c\u662f\u8fd9\u4e00\u53d1\u7684 trail \u5bf9\u4e0d\u4e0a\u73b0\u573a\u6587\u4ef6"},
                     ensure_ascii=True))
    for d in mc["detail"]:
        print(json.dumps({"metrics_claim": d}, ensure_ascii=True))


if __name__ == "__main__":
    main()
