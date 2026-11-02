"""配对/两组检验，带已知答案自检。

为什么要有自检：这段口径前两次在内联命令行里算，一次把 p 算成恒 1（超几何写崩），
一次把不存在的传输发数当成拉分母的因素写进了记忆。检验件自己也要能被证明会红。

用法：
  件 --selftest                     跑已知答案臂
  件 --pairs A.json B.json [C.json] 同一任务集的多臂：逐发配对符号检验 + 两组 Fisher + Wilson
只读，不写盘。打印 ensure_ascii。
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def lnchoose(n, k):
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_2x2(k1, n1, k2, n2):
    """双侧精确 Fisher：表 [[a, n1-a],[K-a, n2-(K-a)]]，列和 K 固定。"""
    N, K = n1 + n2, k1 + k2
    if N == 0:
        return None

    def logp(a):
        b = K - a
        if a < 0 or b < 0 or a > n1 or b > n2:
            return -math.inf
        return lnchoose(n1, a) + lnchoose(n2, b) - lnchoose(N, K)

    lo, hi = max(0, K - n2), min(n1, K)
    obs = logp(k1)
    tot = 0.0
    for a in range(lo, hi + 1):
        lp = logp(a)
        if lp <= obs + 1e-12:
            tot += math.exp(lp)
    return round(min(1.0, tot), 4)


def sign_test(pairs):
    """pairs: [(okA, okB), ...]，只取两边都不是传输失败的发。b=A 败 B 过，c=A 过 B 败。"""
    b = sum(1 for x, y in pairs if y and not x)
    c = sum(1 for x, y in pairs if x and not y)
    m = b + c
    if m == 0:
        return {"b": b, "c": c, "m": m, "p": None}
    k = min(b, c)
    tail = sum(math.comb(m, i) for i in range(0, k + 1)) / 2.0 ** m
    return {"b": b, "c": c, "m": m, "p": round(min(1.0, 2 * tail), 4)}


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def selftest():
    arms = []
    a = fisher_2x2(10, 20, 10, 20)
    arms.append({"arm": "两组全等必须 p=1", "got": a, "pass": a == 1.0})
    b = fisher_2x2(0, 20, 20, 20)
    arms.append({"arm": "极端对立必须很小", "got": b, "pass": b is not None and b < 1e-6})
    c = fisher_2x2(7, 20, 0, 20)
    hand = round(2 * math.comb(20, 7) / math.comb(40, 7), 4)
    arms.append({"arm": "7/20 vs 0/20 必须等于手算 2*C(20,7)/C(40,7)",
                 "got": c, "hand": hand, "pass": c == hand})
    d = fisher_2x2(7, 20, 10, 20)
    arms.append({"arm": "7/20 vs 10/20 应分不开", "got": d, "pass": d is not None and d > 0.05})
    s = sign_test([(False, True)] * 6 + [(True, False)] * 3)
    arms.append({"arm": "符号检验 6:3 应不显著", "got": s["p"], "pass": s["p"] > 0.05})
    s2 = sign_test([(False, True)] * 10)
    arms.append({"arm": "符号检验 10:0 应显著", "got": s2["p"], "pass": s2["p"] < 0.05})
    s3 = sign_test([(True, True), (False, False)])
    arms.append({"arm": "全一致的配对给 m=0 而不是 p=1", "got": str(s3), "pass": s3["m"] == 0 and s3["p"] is None})
    w = wilson(0, 20)
    arms.append({"arm": "0/n 的区间上限仍要小于 1", "got": w, "pass": w[1] < 0.2})
    for x in arms:
        print(json.dumps({"selftest": x}, ensure_ascii=True))
    return 0 if all(x["pass"] for x in arms) else 1


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = d.get("reps") or d.get("runs") or []
    out = {}
    for r in rows:
        key = r.get("rep") if r.get("rep") is not None else (r.get("id"), r.get("pass"))
        transport = bool(r.get("err")) or "session_new_exception" in (r.get("misses") or [])
        out[key] = {"ok": bool(r.get("ok")), "transport": transport,
                   "stop": r.get("stop"), "misses": r.get("misses")}
    return d, out


def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"fatal": "need --selftest or --pairs f1 f2 [f3]"}))
        return 2
    if args[0] == "--selftest":
        return selftest()
    if args[0] != "--pairs" or len(args) < 3:
        print(json.dumps({"fatal": "bad args"}))
        return 2
    metas, data = {}, {}
    for f in args[1:]:
        p = Path(f)
        if not p.is_absolute():
            p = HERE / "读数" / f
        d, m = load(p)
        tag = p.stem
        metas[tag] = {"file": p.name, "rows": len(m),
                      "exe": (d.get("exe") or {}).get("sha256"),
                      "task": d.get("task") or d.get("task_set_sha256"),
                      "transport": sum(1 for v in m.values() if v["transport"]),
                      "ok": sum(1 for v in m.values() if v["ok"])}
        data[tag] = m
    tags = list(metas)
    for t in tags:
        mo = metas[t]
        k = sum(1 for v in data[t].values() if v["ok"] and not v["transport"])
        n = sum(1 for v in data[t].values() if not v["transport"])
        print(json.dumps({"arm": mo, "name": t, "excl_transport": {"k": k, "n": n,
                      "rate": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}},
                         ensure_ascii=True))
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            t1, t2 = tags[i], tags[j]
            common = sorted(set(data[t1]) & set(data[t2]))
            pr = [(data[t1][k]["ok"], data[t2][k]["ok"])
                  for k in common
                  if not data[t1][k]["transport"] and not data[t2][k]["transport"]]
            st = sign_test(pr)
            k1, n1 = metas[t1]["ok"], metas[t1]["rows"]
            k2, n2 = metas[t2]["ok"], metas[t2]["rows"]
            same_keys = data[t1] and data[t2] and len(common) == len(data[t1]) == len(data[t2])
            print(json.dumps({"compare": t1 + " vs " + t2,
                              "paired_keys": len(common), "pairable": bool(same_keys),
                              "sign": st, "fisher_all_rows": fisher_2x2(k1, n1, k2, n2),
                              "direction": "second_better" if st["b"] > st["c"] else
                                           ("first_better" if st["c"] > st["b"] else "tie")},
                             ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
