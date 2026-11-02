"""只读汇总：从落盘那份重数，并与跑件自己印的 summary 对账。

不写任何文件，只打印。失败按形分桶（传输 / 撞步数上限 / 回显收口 / 假收口 / 其它），
传输那桶单开，不计进模型能力分母。所有打印走 ensure_ascii，避开 GBK 控制台崩退出码。
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def bucket(row):
    # 传输优先：带异常的发不许因为 ok=True 就被算成过账（否则模型分母虚高）
    if row.get("err") or "session_new_exception" in (row.get("misses") or []):
        return "transport"
    if row.get("ok"):
        return "pass"
    if row.get("stop") == "步数上限":
        return "step_cap"
    if (row.get("answer_tier") or "missing") == "measured":
        return "echo_close"
    if row.get("misses"):
        return "fake_close"
    return "other"


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "业务任务-13x20-真端点.json"
    p = Path(name)
    if not p.is_absolute():
        p = HERE / "读数" / name
    if not p.exists():
        print(json.dumps({"fatal": "reading not found", "path": str(p)}, ensure_ascii=True))
        return 2
    d = json.loads(p.read_text(encoding="utf-8"))
    runs = d.get("runs") or []
    s = d.get("summary") or {}

    def cnt(pred):
        return sum(1 for x in runs if pred(x))

    recount = {
        "runs": len(runs),
        "oracle_ok": cnt(lambda x: x.get("ok")),
        "model_ok": cnt(lambda x: x.get("model_ok")),
        "steps_ok": cnt(lambda x: x.get("steps_ok")),
        "answer_ok": cnt(lambda x: x.get("answer_ok")),
        "sane": cnt(lambda x: x.get("sane")),
    }
    transport = [x for x in runs if bucket(x) == "transport"]
    model_runs = [x for x in runs if bucket(x) != "transport"]

    print(json.dumps({"reading": p.name, "bytes": p.stat().st_size,
                      "declared_passes": d.get("passes_declared"),
                      "only": d.get("only"), "tasks_run": d.get("tasks_run"),
                      "exe": d.get("exe"), "arms_ok": d.get("arms_ok"),
                      "task_set_sha256": d.get("task_set_sha256"),
                      "fatal": d.get("fatal")}, ensure_ascii=True))

    agree = {}
    for k, v in recount.items():
        declared = s.get(k if k != "runs" else "runs")
        agree[k] = {"recounted": v, "printed_by_runner": declared,
                    "match": declared == v}
    print(json.dumps({"denominator_check": agree,
                      "all_match": all(a["match"] for a in agree.values())},
                     ensure_ascii=True))

    bs = {}
    for x in runs:
        bs[bucket(x)] = bs.get(bucket(x), 0) + 1
    print(json.dumps({"fail_buckets": bs,
                      "bucket_sum": sum(bs.values()),
                      "transport_flagged_ok": cnt(
                          lambda x: (x.get("err")
                                     or "session_new_exception" in (x.get("misses") or []))
                          and bool(x.get("ok"))),
                      "transport_rows": [{"id": x.get("id"), "pass": x.get("pass"),
                                          "err": x.get("err"),
                                          "hub_alive": x.get("hub_alive_before_session")}
                                         for x in transport],
                      "model_denominator": len(model_runs)}, ensure_ascii=True))

    ok_m = sum(1 for x in model_runs if x.get("ok"))
    mo_ok = sum(1 for x in model_runs if x.get("model_ok"))
    print(json.dumps({"on_model_denominator": {
        "n": len(model_runs), "oracle_ok": ok_m, "wilson95": wilson(ok_m, len(model_runs)),
        "model_ok": mo_ok, "wilson95_model_ok": wilson(mo_ok, len(model_runs))}},
        ensure_ascii=True))

    per_task = {}
    for x in runs:
        t = per_task.setdefault(x.get("id"), {"runs": 0, "ok": 0, "model_ok": 0,
                                              "buckets": {}, "stops": {}})
        t["runs"] += 1
        t["ok"] += 1 if x.get("ok") else 0
        t["model_ok"] += 1 if x.get("model_ok") else 0
        b = bucket(x)
        t["buckets"][b] = t["buckets"].get(b, 0) + 1
        if not x.get("ok"):
            st = str(x.get("stop"))
            t["stops"][st] = t["stops"].get(st, 0) + 1
    for tid in sorted(per_task):
        t = per_task[tid]
        t["rate"] = round(t["ok"] / t["runs"], 4) if t["runs"] else None
        t["wilson95"] = wilson(t["ok"], t["runs"])
    print(json.dumps({"per_task": per_task}, ensure_ascii=True))

    tiers = {}
    for x in runs:
        k = x.get("answer_tier") or "missing"
        tiers[k] = tiers.get(k, 0) + 1
    stops = {}
    for x in runs:
        stops[str(x.get("stop"))] = stops.get(str(x.get("stop")), 0) + 1
    mss = sorted(x.get("ms") or 0 for x in model_runs)

    def pct(q):
        if not mss:
            return None
        i = min(len(mss) - 1, max(0, int(math.ceil(q * len(mss))) - 1))
        return mss[i]
    print(json.dumps({"answer_tiers": tiers, "stops": stops,
                      "ms_p50": pct(0.5), "ms_p90": pct(0.9), "ms_p95": pct(0.95),
                      "ms_max": mss[-1] if mss else None,
                      "estimated_steps_total": sum(x.get("estimated_steps") or 0 for x in runs),
                      "printed_summary": {k: s.get(k) for k in
                                          ("oracle_ok", "model_ok", "steps_ok", "answer_ok",
                                           "tasks_both_passes", "tasks_any_pass",
                                           "ms_p50", "ms_p95", "ms_max")}},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
