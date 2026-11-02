"""只读分析：失败发有没有「前兆」——收口前那一步是不是刚失败过、步数/耗时是否与过账发不同。

分桶复用 汇总-业务重复-1023.py 的 bucket()（唯一出处，不在这里重写优先级）；
Fisher 复用 分析-配对检验-1023.py 的 fisher_2x2()（那条线已 --selftest 过 8 个已知答案）。
连续量（步数、耗时）用固定种子的置换检验，种子与次数都印出来。
传输那桶的分位不并进模型分母：字段缺失的发在逐发统计里是 absent，不是 0。
不写任何文件，只打印；ensure_ascii 避开 GBK 控制台崩退出码。
"""
import importlib.util
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
READINGS = HERE / "读数"


def _load(mod_name, file_name):
    spec = importlib.util.spec_from_file_location(mod_name, HERE / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


AGG = _load("agg_mod", "汇总-业务重复-1023.py")
STAT = _load("stat_mod", "分析-配对检验-1023.py")
bucket = AGG.bucket
fisher_2x2 = STAT.fisher_2x2
wilson = AGG.wilson

STEP_KEYS_ABSENT = "每步字段整排缺失（传输发）"


def classes_of(row):
    cl = row.get("classes")
    return list(cl) if isinstance(cl, list) else None


def any_failed(row):
    cl = classes_of(row)
    if cl is None:
        return None
    return any(c != "ok" for c in cl)


def last_failed(row):
    cl = classes_of(row)
    if cl is None or not cl:
        return None
    return cl[-1] != "ok"


def nsteps(row):
    cl = classes_of(row)
    return None if cl is None else len(cl)


def share(rows, fn):
    vals = [fn(r) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0, "true": 0, "rate": None}
    t = sum(1 for v in vals if v)
    return {"n": len(vals), "true": t, "rate": round(t / len(vals), 4)}


def num_summary(rows, fn):
    vals = [fn(r) for r in rows]
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return {"n": 0, "median": None, "mean": None, "min": None, "max": None}
    return {"n": len(vals),
            "median": round(statistics.median(vals), 2),
            "mean": round(statistics.fmean(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2)}


def perm_test(a, b, seed=20261023, n_perm=20000):
    """两组均值差的双侧置换检验。返回观测差、p、种子与次数；样本太小或有一组空则 None。"""
    if len(a) < 2 or len(b) < 2:
        return None
    pooled = list(a) + list(b)
    na = len(a)
    obs = statistics.fmean(a) - statistics.fmean(b)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        d = statistics.fmean(pooled[:na]) - statistics.fmean(pooled[na:])
        if abs(d) >= abs(obs) - 1e-12:
            hits += 1
    return {"diff_obs": round(obs, 3),
            "p": round((hits + 1) / (n_perm + 1), 5),
            "n_perm": n_perm, "seed": seed,
            "n_a": na, "n_b": len(b)}


def rate_fisher(pass_rows, fail_rows, fn, label):
    """把某个前兆标志按 过账发 vs 假收口发 摆成 2x2，走已自测的精确 Fisher。"""
    def cnt(rows):
        vals = [fn(r) for r in rows]
        vals = [v for v in vals if v is not None]
        return sum(1 for v in vals if v), len(vals)
    k1, n1 = cnt(pass_rows)
    k2, n2 = cnt(fail_rows)
    p = fisher_2x2(k1, n1, k2, n2) if n1 and n2 else None
    p_full = fisher_exact_unrounded(k1, n1, k2, n2) if n1 and n2 else None
    return {"flag": label,
            "pass": f"{k1}/{n1}", "fail": f"{k2}/{n2}",
            "k_pass": k1, "n_pass": n1, "k_fail": k2, "n_fail": n2,
            "pass_rate": round(k1 / n1, 4) if n1 else None,
            "fail_rate": round(k2 / n2, 4) if n2 else None,
            "fisher_exact_two_sided_p": p,
            "fisher_p_rounding_note": "上一条保留 4 位小数，极小值会显示 0.0；结论用下一条",
            "fisher_p_unrounded": p_full}


def rate_fisher_matched(pass_rows, fail_rows, fn, label):
    """同题对照：把过账发限制在「出过假收口的那些题」上，再去掉题难度这个混淆。
    不限的话，一步本来就通不过题的题会把过账组推高/压低，得到的差不属于假收口本身。"""
    ids = {r.get("id") for r in fail_rows}
    p_rows = [r for r in pass_rows if r.get("id") in ids]
    res = rate_fisher(p_rows, fail_rows, fn, label)
    res["scope"] = f"restricted to {len(ids)} task ids that produced a fake close"
    res["pass_rows_in_scope"] = len(p_rows)
    return res


def fisher_exact_unrounded(k1, n1, k2, n2):
    """与 分析-配对检验-1023.py 同一条超几何双侧规则，但不舍入。
    那边只保留 4 位小数 ⇒ 极小值会印成 0.0，上屏不许写「p=0」，所以这里给未舍入值。"""
    if n1 <= 0 or n2 <= 0:
        return None
    K, N = k1 + k2, n1 + n2
    if K > N:
        return None
    lo, hi = max(0, K - n2), min(n1, K)

    def prob(a):
        return math.comb(n1, a) * math.comb(n2, K - a) / math.comb(N, K)

    p_obs = prob(k1)
    return sum(prob(a) for a in range(lo, hi + 1) if prob(a) <= p_obs * (1 + 1e-9))


def transport_cluster(rows):
    """传输发的归因线索：发前 health、按题/按趟的分布、相邻发生时刻的间隔。"""
    tr = [r for r in rows if bucket(r) == "transport"]
    alive = sum(1 for r in tr if r.get("hub_alive_before_session") is True)
    unk = sum(1 for r in tr if r.get("hub_alive_before_session") is None)
    by_id, by_pass = {}, {}
    for r in tr:
        by_id[r.get("id")] = by_id.get(r.get("id"), 0) + 1
        by_pass[r.get("pass")] = by_pass.get(r.get("pass"), 0) + 1
    ats = sorted(r.get("at") or "" for r in tr)
    gaps = []
    prev = None
    for a in ats:
        try:
            cur = _parse_iso(a)
        except Exception:
            cur = None
        if cur is not None and prev is not None:
            gaps.append(round((cur - prev).total_seconds(), 1))
        prev = cur if cur is not None else prev
    return {"n": len(tr),
            "hub_alive_before_session_true": alive,
            "hub_alive_before_session_absent": unk,
            "by_task": dict(sorted(by_id.items())),
            "by_pass": dict(sorted(by_pass.items())),
            "gap_between_transport_s": gaps}


def _parse_iso(s):
    from datetime import datetime
    return datetime.fromisoformat(s)


def strata_of(ok_rows, fakes):
    """按题分层：这道题有没有「1 步就通过判据」的过账发。
    有 ⇒ 该题上「假收口只走 1 步」不是判据构造出来的；没有 ⇒ 1 步必不过，关联有构造成分。
    这一层是防我自己把机械相关说成能力发现。"""
    admit = {r.get("id") for r in ok_rows if nsteps(r) == 1}
    out = {}
    for name, test in (("题允许1步过", True), ("题不允许1步过", False)):
        f = [r for r in fakes if (r.get("id") in admit) == test]
        o = [r for r in ok_rows if (r.get("id") in admit) == test]
        out[name] = {"tasks_with_fake": sorted({r.get("id") for r in f}),
                     "fake_rows": len(f),
                     "fake_one_step": sum(1 for r in f if nsteps(r) == 1),
                     "pass_rows": len(o),
                     "pass_one_step": sum(1 for r in o if nsteps(r) == 1)}
    return out


def analyze(doc):
    runs = doc.get("runs") or []
    bs = {}
    for r in runs:
        b = bucket(r)
        bs[b] = bs.get(b, 0) + 1
    model = [r for r in runs if bucket(r) != "transport"]
    ok_rows = [r for r in model if r.get("ok")]
    fakes = [r for r in model if bucket(r) == "fake_close"]
    echoes = [r for r in model if bucket(r) == "echo_close"]
    caps = [r for r in model if bucket(r) == "step_cap"]
    others = [r for r in model if bucket(r) == "other"]
    out = {
        "reading_rows": len(runs),
        "buckets": bs,
        "bucket_sum": sum(bs.values()),
        "model_denominator": len(model),
        "absent_note": f"{len(runs) - len(model)} 发每步字段整排缺失（传输），不进逐发分布统计",
        "steps_pass_vs_fake": {
            "pass": num_summary(ok_rows, nsteps),
            "fake_close": num_summary(fakes, nsteps),
            "perm_test_diff_of_means": perm_test(
                [v for v in (nsteps(r) for r in ok_rows) if isinstance(v, (int, float))],
                [v for v in (nsteps(r) for r in fakes) if isinstance(v, (int, float))])},
        "ms_pass_vs_fake": {
            "pass": num_summary(ok_rows, lambda r: r.get("ms")),
            "fake_close": num_summary(fakes, lambda r: r.get("ms")),
            "perm_test_diff_of_means": perm_test(
                [v for v in (r.get("ms") for r in ok_rows) if isinstance(v, (int, float))],
                [v for v in (r.get("ms") for r in fakes) if isinstance(v, (int, float))])},
        "prognosis_flags": [
            rate_fisher(ok_rows, fakes, any_failed, "本发里有 ≥1 步 class!=ok"),
            rate_fisher(ok_rows, fakes, last_failed, "收口前最后一步 class!=ok"),
            rate_fisher(ok_rows, fakes, lambda r: (r.get("estimated_steps") or 0) > 0,
                         "本发含 ≥1 步 estimated"),
            rate_fisher(ok_rows, fakes, lambda r: (nsteps(r) == 1),
                         "本发只有 1 步（早收口）")],
        "same_task_control": {
            "why": "题难度是混淆：有的题一步本来就通不过判据，不限题的话差值不全是假收口带来的",
            "flags": [
                rate_fisher_matched(ok_rows, fakes, lambda r: (nsteps(r) == 1),
                                    "同题：本发只有 1 步"),
                rate_fisher_matched(ok_rows, fakes, any_failed,
                                    "同题：本发里有 ≥1 步 class!=ok")],
            "one_step_rate_by_task": {
                tid: {"pass_rows": len([r for r in ok_rows if r.get("id") == tid]),
                      "pass_one_step": sum(1 for r in ok_rows
                                           if r.get("id") == tid and nsteps(r) == 1),
                      "fake_rows": len([r for r in fakes if r.get("id") == tid]),
                      "fake_one_step": sum(1 for r in fakes
                                           if r.get("id") == tid and nsteps(r) == 1)}
                for tid in sorted({r.get("id") for r in fakes})}},
        "strata": strata_of(ok_rows, fakes),
        "zero_step_rows": {
            "in_fake_close": sum(1 for r in fakes if (nsteps(r) == 0)),
            "in_pass": sum(1 for r in ok_rows if (nsteps(r) == 0))},
        "other_shapes": {
            "echo_close": {"n": len(echoes), "tiers": sorted({str(r.get("answer_tier")) for r in echoes})},
            "step_cap": {"n": len(caps), "tiers": sorted({str(r.get("answer_tier")) for r in caps})},
            "other": {"n": len(others), "ids": sorted({str(r.get("id")) for r in others})}},
        "transport": transport_cluster(runs),
    }
    out["fake_rate_wilson"] = wilson(len(fakes), len(model))
    return out


def jprint(obj):
    print(json.dumps(obj, ensure_ascii=True, sort_keys=True))


def load_one(name):
    path = Path(name)
    if not path.is_absolute() and not path.exists():
        path = READINGS / name
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path, json.loads(path.read_text(encoding="utf-8"))


def pool(docs):
    """按源合并 runs 并自印每源分桶：pooled_rows 必须等于 row_sum，否则有源被吃掉。"""
    merged, per_source = [], {}
    for name, doc in docs:
        rs = doc.get("runs") or []
        for r in rs:
            r["_src"] = name
        merged.extend(rs)
        bs = {}
        for r in rs:
            bs[bucket(r)] = bs.get(bucket(r), 0) + 1
        per_source[name] = {"rows": len(rs), "buckets": bs}
    return merged, per_source


def main():
    if "--selftest" in sys.argv:
        return selftest()
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not names:
        names = ["业务任务-13x20-真端点.json"]
    docs = []
    for nm in names:
        try:
            path, doc = load_one(nm)
        except FileNotFoundError as e:
            jprint({"fatal": f"reading not found: {e}"})
            return 2
        docs.append((path.name, doc))
        jprint({"file": path.name, "exe": doc.get("exe"),
                "task_set_sha256": doc.get("task_set_sha256"),
                "passes_declared": doc.get("passes_declared"),
                "arms_ok": doc.get("arms_ok")})
    merged, per_source = pool(docs)
    jprint({"sources": len(per_source),
            "pooled_sources": per_source,
            "pooled_rows": len(merged),
            "row_sum": sum(v["rows"] for v in per_source.values())})
    if len(names) > 1:
        jprint({"pool_caveat": "pooled = independent runs from different windows; same exe/task "
                               "set, different local conditions -> direction check only"})
    jprint(analyze({"runs": merged}))
    return 0


def selftest():
    """合成现场：已知答案。跑件对每一臂都印它自己的前提。"""
    fails = 0

    def check(name, got, want):
        nonlocal fails
        ok = got == want
        if not ok:
            fails += 1
        print(json.dumps({"arm": name, "got": got, "want": want, "ok": ok}, ensure_ascii=True))

    def row(rid, p, ok, clss, ms, err=None, tier="model_says", stop="跑完", est=0):
        return {"id": rid, "pass": p, "ok": ok, "classes": clss, "ms": ms,
                "err": err, "answer_tier": tier, "stop": stop,
                "estimated_steps": est, "hub_alive_before_session": True,
                "at": f"2026-10-23T16:{p:02d}:00+08:00", "trail": [], "misses": [] if ok else ["answer_not_executed"]}

    # 臂 1：桶优先级 —— 传输必须压过 ok=True（这条被真臂抓过一次）
    mixed = [row("B01", 1, True, ["ok"], 1000, err="ConnectionReset"),
             row("B01", 2, True, ["ok"], 1000),
             row("B01", 3, False, ["ok", "error"], 1000),
             row("B01", 4, False, ["ok"], 1000, tier="measured"),
             row("B01", 5, False, ["ok"], 1000, stop="步数上限")]
    bs = {}
    for r in mixed:
        bs[bucket(r)] = bs.get(bucket(r), 0) + 1
    check("arm1_bucket_precedence", bs, {"transport": 1, "pass": 1, "fake_close": 1,
                                        "echo_close": 1, "step_cap": 1})

    a = analyze({"runs": mixed})
    # 臂 2：分母口径 —— 传输发不许进逐发分布（n_model=4，缺失发被点名）
    check("arm2_model_denominator", a["model_denominator"], 4)
    check("arm2_transport_excluded_from_steps",
          a["steps_pass_vs_fake"]["pass"]["n"] + a["steps_pass_vs_fake"]["fake_close"]["n"], 2)

    # 臂 3：前兆标志 —— 假收口发每发最后一步都失败、过账发都不失败。
    # n=2 vs n=2 时精确 Fisher 的最小可达值是 1/3（两条尾巴各 1/6），所以这里必须印出 0.3333
    # 并断言它等于直接调用 —— 这条臂第一次跑红过，红的是我对功效的预期，不是这件。
    hard = [row("B01", 1, True, ["ok", "ok"], 1000),
            row("B01", 2, True, ["ok"], 1200),
            row("B01", 3, False, ["ok", "error"], 900),
            row("B01", 4, False, ["error"], 950)]
    a3 = analyze({"runs": hard})
    flag = [f for f in a3["prognosis_flags"] if f["flag"].startswith("收口前最后一步")][0]
    check("arm3_flag_rates", (flag["pass"], flag["fail"]), ("0/2", "2/2"))
    check("arm3_p_equals_direct_call", flag["fisher_exact_two_sided_p"], fisher_2x2(0, 2, 2, 2))
    check("arm3_n2_vs_n2_floor_is_one_third", flag["fisher_exact_two_sided_p"], 0.3333)

    # 臂 3b：分得开时必须显著（0/12 vs 6/6，手算两侧 p = 2/C(18,6) = 1.078e-4）
    sep = [row("B01", i, True, ["ok", "ok"], 1000) for i in range(1, 13)] + \
          [row("B01", 20 + i, False, ["ok", "error"], 900) for i in range(1, 7)]
    a3b = analyze({"runs": sep})
    f3b = [f for f in a3b["prognosis_flags"] if f["flag"].startswith("收口前最后一步")][0]
    check("arm3b_rates", (f3b["pass"], f3b["fail"]), ("0/12", "6/6"))
    check("arm3b_equals_direct_call", f3b["fisher_exact_two_sided_p"], fisher_2x2(0, 12, 6, 6))
    check("arm3b_significant", f3b["fisher_exact_two_sided_p"] < 0.001, True)

    # 臂 4：没有差别时必须不显著（恒红的尺子也没牙）—— 两组前兆率相同 ⇒ p=1.0
    even = [row("B01", 1, True, ["ok", "error"], 1000),
            row("B01", 2, True, ["ok", "error"], 1000),
            row("B01", 3, False, ["ok", "error"], 1000),
            row("B01", 4, False, ["ok", "error"], 1000)]
    a4 = analyze({"runs": even})
    f4 = [f for f in a4["prognosis_flags"] if f["flag"].startswith("收口前最后一步")][0]
    check("arm4_no_difference_gives_p1", f4["fisher_exact_two_sided_p"], 1.0)

    # 臂 5：置换检验可复现（同种子同 p）+ 全零步数要数出来，不许塌成 None
    v = [1, 2, 3, 4, 5]
    t1 = perm_test(v, [9, 8, 7], seed=1234, n_perm=500)
    t2 = perm_test(v, [9, 8, 7], seed=1234, n_perm=500)
    check("arm5_perm_reproducible", (t1["p"], t1["diff_obs"]), (t2["p"], t2["diff_obs"]))
    check("arm5_perm_shows_seed", (t1["seed"], t1["n_perm"]), (1234, 500))
    zeros = [row("B01", 1, False, [], 800)]
    a5 = analyze({"runs": zeros})
    check("arm5_zero_step_counted_not_none",
          a5["steps_pass_vs_fake"]["fake_close"]["n"], 1)
    check("arm5_zero_step_median", a5["steps_pass_vs_fake"]["fake_close"]["median"], 0.0)

    # 臂 6：传输发按 health 归因 —— 发前 alive 为 absent 时必须单列，不许折进 true
    tr = [row("B01", 1, True, ["ok"], 1000, err="ConnectionReset"),
          {"id": "B02", "pass": 2, "ok": False, "err": "ConnectionReset", "misses": ["session_new_exception"]}]
    a6 = analyze({"runs": tr})
    check("arm6_transport_absent_separate",
          (a6["transport"]["hub_alive_before_session_true"],
           a6["transport"]["hub_alive_before_session_absent"]), (1, 1))

    # 臂 7：池化不许吃掉发 —— 三源合并 pooled_rows 必须等于逐源 rows 之和，
    # 且空源（没有 runs 键）要如实印 0 而不是被忽略；分桶要逐源分开
    d1 = {"runs": [row("B01", 1, True, ["ok"], 1000), row("B01", 2, False, ["error"], 900)]}
    d2 = {"runs": [row("B02", 1, True, ["ok"], 1000, err="ConnectionReset")]}
    d3 = {"runs": []}
    mg, ps = pool([("a.json", d1), ("b.json", d2), ("c.json", d3)])
    check("arm7_pool_eats_nothing", (len(mg), sum(v["rows"] for v in ps.values())), (3, 3))
    check("arm7_per_source_buckets",
          {k: v["buckets"] for k, v in ps.items()},
          {"a.json": {"pass": 1, "fake_close": 1}, "b.json": {"transport": 1}, "c.json": {}})
    # 臂 7b：整件对并排三源出的 pooled 计数，必须等于手工把两源合起来跑 analyze 的计数
    a_pool = analyze({"runs": mg})
    f7 = [x for x in a_pool["prognosis_flags"] if x["flag"].startswith("收口前最后一步")][0]
    check("arm7b_pooled_counts_from_rows_not_strings",
          (f7["k_pass"], f7["n_pass"], f7["k_fail"], f7["n_fail"]), (0, 1, 1, 1))

    # 臂 8：早收口这条必须接在 classes 长度上（不是 ms、不是 tools 数量）
    early = [row("B01", i, True, ["ok", "ok"], 1000) for i in range(1, 5)] + \
            [row("B01", 10 + i, False, ["ok"], 1000) for i in range(1, 4)]
    a8 = analyze({"runs": early})
    f8 = [x for x in a8["prognosis_flags"] if x["flag"].startswith("本发只有 1 步")][0]
    check("arm8_early_flag_counts",
          (f8["k_pass"], f8["n_pass"], f8["k_fail"], f8["n_fail"]), (0, 4, 3, 3))
    check("arm8_early_flag_equals_direct", f8["fisher_exact_two_sided_p"], fisher_2x2(0, 4, 3, 3))
    check("arm8_flag_list_has_four", len(a8["prognosis_flags"]), 4)

    # 臂 9：同题对照必须真的把别的题摘掉 —— B01 的过账发全是 1 步、B04 的全是 2 步，
    # 假收口只在 B04。不限题时 1 步率是 3/6，限题后必须是 0/3（否则这道控制是假的）
    conf = [row("B01", i, True, ["ok"], 1000) for i in range(1, 4)] + \
           [row("B04", i, True, ["ok", "ok"], 1000) for i in range(1, 4)] + \
           [row("B04", 10 + i, False, ["ok"], 900) for i in range(1, 3)]
    a9 = analyze({"runs": conf})
    un = [x for x in a9["prognosis_flags"] if x["flag"].startswith("本发只有 1 步")][0]
    mt = [x for x in a9["same_task_control"]["flags"] if x["flag"].startswith("同题：本发只有 1 步")][0]
    check("arm9_unmatched_scope", (un["k_pass"], un["n_pass"]), (3, 6))
    check("arm9_matched_scope_drops_other_tasks",
          (mt["k_pass"], mt["n_pass"], mt["pass_rows_in_scope"]), (0, 3, 3))
    check("arm9_matched_denominator_smaller", mt["n_pass"] < un["n_pass"], True)
    check("arm9_by_task_table_keys", sorted(a9["same_task_control"]["one_step_rate_by_task"]), ["B04"])

    # 臂 10：未舍入 p 必须等于手算的超几何和；且在 4 位舍入会塌成 0.0001/0.0 的表上必须仍 >0
    check("arm10_hand_1_over_3", abs(fisher_exact_unrounded(0, 2, 2, 2) - 1 / 3) < 1e-15, True)
    check("arm10_hand_1_over_35", abs(fisher_exact_unrounded(0, 4, 3, 3) - 1 / 35) < 1e-15, True)
    check("arm10_matches_rounded_sibling",
          abs(fisher_exact_unrounded(0, 12, 6, 6) - fisher_2x2(0, 12, 6, 6)) <= 5e-5, True)
    tiny = fisher_exact_unrounded(43, 182, 12, 15)
    check("arm10_tiny_table_not_zero", (tiny > 0, fisher_2x2(43, 182, 12, 15)), (True, 0.0))
    check("arm10_degenerate_stays_none", fisher_exact_unrounded(0, 0, 3, 3), None)

    # 臂 11：分层要把「题允不允许 1 步过」真的分开 —— conf 现场里 B01 有 1 步过账发、B04 没有，
    # 两发假收口都在 B04 ⇒ 「允许」层假收口必须 0 发，「不允许」层必须 2/2，不许两层的数互相串
    st11 = a9["strata"]
    check("arm11_allow_stratum", st11["题允许1步过"],
          {"tasks_with_fake": [], "fake_rows": 0, "fake_one_step": 0,
           "pass_rows": 3, "pass_one_step": 3})
    check("arm11_deny_stratum", st11["题不允许1步过"],
          {"tasks_with_fake": ["B04"], "fake_rows": 2, "fake_one_step": 2,
           "pass_rows": 3, "pass_one_step": 0})

    print(json.dumps({"selftest_fails": fails}, ensure_ascii=True))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
