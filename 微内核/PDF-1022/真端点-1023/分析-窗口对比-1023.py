"""窗口对窗口：同一题在两趟重复里的过/败做精确 Fisher，翻转要不要写成"波动"用 p 说话。

只读两份落盘读数，不写文件。没有 scipy，2x2 用超几何精确算法。
所有打印 ensure_ascii，避开 GBK 控制台崩退出码。
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ("oracle_ok", "model_ok", "steps_ok", "answer_ok")


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def fisher_exact(a, b, c, d):
    """两独立二项计数 (a 成功/b 失败 vs c 成功/d 失败) 的精确 p（双侧，按概率不高于观察表）。"""
    n = a + b + c + d
    if n == 0 or (a + b) == 0 or (c + d) == 0:
        return None

    def lp(k):
        return math.lgamma(k + 1)

    def prob(x1, x2, r1, r2):
        if x1 < 0 or x2 < 0 or x1 > r1 or x2 > r2:
            return 0.0
        return math.exp(lp(r1) + lp(r2) + lp(x1 + x2) + lp(r1 + r2 - x1 - x2)
                        - lp(x1) - lp(x2) - lp(r1 - x1) - lp(r2 - x2) - lp(n))

    r1, r2 = a + b, c + d
    p_obs = prob(a, c, r1, r2)
    tot = 0.0
    lo, hi = max(0, r1 - (n - r2)), min(r1, n - r2)
    for x1 in range(lo, hi + 1):
        x2 = (a + c) - x1
        pv = prob(x1, x2, r1, r2)
        if pv <= p_obs * (1 + 1e-9):
            tot += pv
    return min(1.0, tot)


def tally(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    runs = d.get("runs") or []
    per = {}
    for x in runs:
        if x.get("err") or "session_new_exception" in (x.get("misses") or []):
            continue  # 传输失败不进任何窗口对比
        t = per.setdefault(x.get("id"), {"n": 0, "oracle_ok": 0, "model_ok": 0,
                                         "steps_ok": 0, "answer_ok": 0, "fake": 0})
        t["n"] += 1
        for k in KEYS:
            if x.get(k if k != "oracle_ok" else "ok"):
                t[k if k != "oracle_ok" else "oracle_ok"] += 1
        if (not x.get("ok")) and x.get("stop") == "跑完" \
                and (x.get("answer_tier") or "missing") == "model_says":
            t["fake"] += 1
    return {"reading": path.name, "rows": len(runs), "per": per,
            "exe": (d.get("exe") or {}).get("sha256"),
            "task_set_sha256": d.get("task_set_sha256")}


def main():
    args = [a for a in sys.argv[1:] if a]
    if len(args) < 2:
        print(json.dumps({"fatal": "need two reading filenames"}))
        return 2
    A, B = (tally(HERE / "读数" / a) for a in args)
    print(json.dumps({"A": {k: v for k, v in A.items() if k != "per"},
                      "B": {k: v for k, v in B.items() if k != "per"},
                      "same_exe": A["exe"] == B["exe"],
                      "same_task_set": A["task_set_sha256"] == B["task_set_sha256"]},
                     ensure_ascii=True))

    overall = {}
    for tag, T in (("A", A), ("B", B)):
        n = sum(t["n"] for t in T["per"].values())
        k = sum(t["oracle_ok"] for t in T["per"].values())
        overall[tag] = {"n": n, "oracle_ok": k, "rate": round(k / n, 4) if n else None,
                        "wilson95": wilson(k, n),
                        "tasks_all_pass": sum(1 for t in T["per"].values() if t["oracle_ok"] == t["n"]),
                        "tasks_any_fail": sum(1 for t in T["per"].values() if t["oracle_ok"] < t["n"])}
    p_overall = fisher_exact(
        overall["A"]["oracle_ok"], overall["A"]["n"] - overall["A"]["oracle_ok"],
        overall["B"]["oracle_ok"], overall["B"]["n"] - overall["B"]["oracle_ok"])
    print(json.dumps({"overall": overall, "fisher_p_A_vs_B": p_overall,
                      "distinguishable_at_0.05": (p_overall is not None and p_overall < 0.05)},
                     ensure_ascii=True))

    ids = sorted(set(A["per"]) | set(B["per"]))
    rows = []
    for i in ids:
        ta, tb = A["per"].get(i), B["per"].get(i)
        if not ta or not tb:
            rows.append({"id": i, "note": "absent in one window",
                         "A": ta["n"] if ta else 0, "B": tb["n"] if tb else 0})
            continue
        p = fisher_exact(ta["oracle_ok"], ta["n"] - ta["oracle_ok"],
                         tb["oracle_ok"], tb["n"] - tb["oracle_ok"])
        ca = ta["oracle_ok"] == ta["n"]
        cb = tb["oracle_ok"] == tb["n"]
        ci_a, ci_b = wilson(ta["oracle_ok"], ta["n"]), wilson(tb["oracle_ok"], tb["n"])
        overlap = bool(ci_a and ci_b and ci_a[0] <= ci_b[1] and ci_b[0] <= ci_a[1])
        rows.append({"id": i, "A": "%d/%d" % (ta["oracle_ok"], ta["n"]),
                     "B": "%d/%d" % (tb["oracle_ok"], tb["n"]),
                     "A_rate": round(ta["oracle_ok"] / ta["n"], 3),
                     "B_rate": round(tb["oracle_ok"] / tb["n"], 3),
                     "fisher_p": None if p is None else round(p, 4),
                     "ci_overlap": overlap,
                     "category_flip": ca != cb,
                     "fake_A": ta["fake"], "fake_B": tb["fake"]})
    for r in rows:
        print(json.dumps({"task": r}, ensure_ascii=True))
    flips = [r["id"] for r in rows if r.get("category_flip")]
    sig = [r["id"] for r in rows if r.get("fisher_p") is not None and r["fisher_p"] < 0.05]
    sep = [r["id"] for r in rows if r.get("ci_overlap") is False]
    print(json.dumps({"summary": {"tasks": len(rows), "category_flips": flips,
                                  "significant_tasks": sig, "ci_disjoint_tasks": sep,
                                  "fake_total_A": sum(r.get("fake_A", 0) for r in rows),
                                  "fake_total_B": sum(r.get("fake_B", 0) for r in rows)}},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
