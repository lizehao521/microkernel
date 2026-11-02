# 题间分辨力：把"这把尺子在 n 发上能看见几发失败"算成盘上读数（只读，不落盘 ⇒ 自己重定向）
#
# 为什么单开一件：报告 §3.8/§3.9 里"n=20 需 ≥5 发失败""n=40 需 ≥6 发"这类话原先是我口算的，
# 没有 path:line 也没有读数。这件只做两件事：① 已知答案臂（闭式 2*C(n,k)/C(2n,k)，用 math.comb
# 现算，与被测件不同实现）；② 对一份落盘读数印逐题分母 + 全部两两 Fisher + Bonferroni 后的计数。
# Fisher 与 wilson 一律从 分析-配对检验-1023.py 取，不在本件重写（重写就有第二把尺子）。
#
# 用法：
#   python 分析-题间分辨力-1023.py --selftest
#   python 分析-题间分辨力-1023.py 读数/业务任务-13x40-真端点.json
import json
import math
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from importlib.util import module_from_spec, spec_from_file_location  # noqa: E402

_spec = spec_from_file_location("pt", str(HERE / "分析-配对检验-1023.py"))
pt = module_from_spec(_spec)
_spec.loader.exec_module(pt)


def closed_form_two_sided(n, k):
    """一列全对（40/40 那种满分题）时，双尾精确 Fisher 的闭式 = 2*C(n,k)/C(2n,k)，封顶 1。

    独立于 pt.fisher_2x2 的实现（math.comb 整数比），专供臂用。
    """
    if k == 0:
        return 1.0
    return min(1.0, 2 * math.comb(n, k) / math.comb(2 * n, k))


def arms():
    out = []
    # 臂 1：尺子与闭式在 n=20 逐点相等（§3.8 印过 4 发 0.106 / 5 发 0.0471 / 7 发 0.0083）
    out.append(("n=20 逐点等于闭式",
                all(round(pt.fisher_2x2(20 - k, 20, 20, 20), 4) == round(closed_form_two_sided(20, k), 4)
                    for k in range(1, 9))))
    out.append(("n=20 复现 §3.8 的 0.106/0.0471/0.0083",
                [round(pt.fisher_2x2(20 - k, 20, 20, 20), 4) for k in (4, 5, 7)] == [0.106, 0.0471, 0.0083]))
    # 臂 2：n=40 的临界发数（raw 0.05 与 Bonferroni α=0.05/78）
    ladder = {k: pt.fisher_2x2(40 - k, 40, 40, 40) for k in range(1, 13)}
    raw = min(k for k in ladder if ladder[k] < 0.05)
    bonf = min(k for k in ladder if ladder[k] < 0.05 / 78)
    out.append(("n=40 与满分题比 raw<0.05 需 6 发、过 Bonferroni 需 11 发",
                raw == 6 and bonf == 11))
    # 臂 3：谎发臂 —— 少乘 2（当成单尾）必须与尺子不等，否则臂 1 恒真
    out.append(("少乘 2 的单尾值与尺子不等（臂不是空转）",
                all(round(closed_form_two_sided(20, k) / 2, 4) != round(pt.fisher_2x2(20 - k, 20, 20, 20), 4)
                    for k in range(1, 8))))
    # 臂 4：尺子对"两列一样"必须给 1.0（恒等情形不许显著）
    out.append(("同分母同命中 p=1.0", pt.fisher_2x2(30, 40, 30, 40) == 1.0))
    # 臂 5：wilson 走的是同一件，不重算 —— 区间必须包住自己的点估计，且同率下分母越长区间越窄
    pts = [(36, 40), (18, 20), (458, 486), (40, 40)]
    ws = [pt.wilson(k, n) for k, n in pts]
    out.append(("wilson 区间包住各自点估计",
                all(lo <= k / n <= hi for (k, n), (lo, hi) in zip(pts, ws))))
    out.append(("同率 0.9 下 n=100 的区间比 n=40 窄",
                (ws2 := [pt.wilson(k, n) for k, n in ((36, 40), (90, 100))])[1][1] - ws2[1][0]
                < ws2[0][1] - ws2[0][0]))
    # 臂 6：分档谓词钉在 err 上，不是钉在 name 上。
    #   这行断言必须是"逐题身份相等"，不能只比 kept/dropped 计数 —— 第一版只比计数，
    #   把 `err` 换成 `not name` 的变异件照样通过（两行被换着剔、总数不变），是空转臂。
    syn = [{"id": "X", "name": "有名但传输失败", "err": "boom", "ok": True},
           {"id": "Z", "err": None, "ok": True},
           {"id": "X", "name": "正常但没过", "ok": False}]
    per6, kept6, drop6 = per_task_transport_split(syn)
    out.append(("剔传输按 err 不按 name（逐题身份：X=0/1、Z=1/1，kept 2 / dropped 1）",
                kept6 == 2 and drop6 == 1 and per6 == {"X": (0, 1), "Z": (1, 1)}))
    # 臂 7：缺 ok 的留下行算不过，不许静默算过
    per7, kept7, _ = per_task_transport_split([{"id": "Y", "err": None}])
    out.append(("缺 ok 的留下行算不过", kept7 == 1 and per7["Y"] == (0, 1)))
    # 臂 8：显著对清单必须列全，不许截断成"最小的那几对"。
    #   造 1 个满分 + 7 个同弱（27/34）：满分 vs 每个弱题各一对显著 = 7 对 > 6，
    #   只印 ps[:6] 的写法会漏一对 ⇒ by_task 求和不等于 2×清单长度，这根臂就红。
    syn8 = {"P": (40, 40)}
    syn8.update({chr(ord("A") + i): (27, 34) for i in range(7)})
    lst8, cnt8 = significant_pairs(syn8, 0.05)
    out.append(("显著对列全 7 对、按题计数和=2×清单、弱题之间一对都没有",
                len(lst8) == 7 and sum(cnt8.values()) == 14
                and all(x[1] == "P" for x in lst8) and cnt8.get("P") == 7))
    # 臂 8b：alpha 是活的，不是写死的 0.05。α=1.5 ⇒ 28 对全进（p 最大 1.0，恒小于 1.5）；
    #   α=0.05 ⇒ 只剩满分 vs 弱题 7 对。同分同命中的那一对 p=1.0，在 α=0.05 下必须一根都不点
    #   （注意：α=1.0 不能当"全进"用 —— p=1.0 不小于 1.0，这条我第一版就写错了）。
    out.append(("alpha 真在过滤（1.5 ⇒ 28 对、0.05 ⇒ 7 对；同分同命中 ⇒ 0 对）",
                len(significant_pairs(syn8, 1.5)[0]) == 28
                and len(significant_pairs(syn8, 0.05)[0]) == 7
                and significant_pairs({"Q": (30, 40), "R": (30, 40)}, 0.05)[0] == []))
    return out


def significant_pairs(per, alpha):
    """逐题分母两两精确 Fisher，返回 (p<alpha 的 [(p, a, b)] 升序全量, 每题参与显著对的次数)。"""
    ps = sorted((round(pt.fisher_2x2(per[a][0], per[a][1], per[b][0], per[b][1]), 6), a, b)
                for a, b in combinations(per, 2))
    low = [x for x in ps if x[0] < alpha]
    cnt = {}
    for _, a, b in low:
        cnt[a] = cnt.get(a, 0) + 1
        cnt[b] = cnt.get(b, 0) + 1
    return low, dict(sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])))


def per_task_transport_split(rows):
    """按跑件自己写的标记分档：`err` 非空 = 本机传输那一发（建会话/HTTP 层），不进模型分母。

    不用「有没有 name」当代理 —— 那只是恰好同形；跑件写传输发时给的是 misses=session_new*
    加 err（见 跑-业务任务-1023.py:424,436），谓词要钉在写下的那个标记上。
    返回 (逐题 k/n, 留下的行数, 剔掉的行数)。留下的行里缺 `ok` 一律算不过，不许静默当过。
    """
    per, kept, dropped = {}, 0, 0
    for r in rows:
        if r.get("err"):
            dropped += 1
            continue
        kept += 1
        d = per.setdefault(r["id"], [0, 0])
        d[1] += 1
        if r.get("ok") is True:
            d[0] += 1
    return {k: tuple(v) for k, v in sorted(per.items())}, kept, dropped


def main(argv):
    if "--selftest" in argv:
        a = arms()
        bad = [n for n, ok in a if not ok]
        for n, ok in a:
            print(json.dumps({"arm": n, "ok": bool(ok)}, ensure_ascii=True))
        print(json.dumps({"arms": len(a), "selftest_fails": len(bad), "failed": bad}, ensure_ascii=True))
        return 1 if bad else 0

    names = [x for x in argv if x != "--selftest"]
    if len(names) != 1:
        print(json.dumps({"fatal": "give exactly one reading file"}, ensure_ascii=True))
        return 2
    p = Path(names[0])
    if not p.exists():
        p = HERE / "读数" / Path(names[0]).name
    if not p.exists():
        print(json.dumps({"fatal": "reading not found", "arg": names[0]}, ensure_ascii=True))
        return 3
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d.get("runs") or []
    per, kept, dropped = per_task_transport_split(rows)
    err_rows = sum(1 for r in rows if r.get("err"))
    closes = (kept + dropped == len(rows)) and dropped == err_rows
    n_passes = max(v[1] for v in per.values())
    print(json.dumps({"file": p.name, "rows": len(rows), "kept_model_denominator": kept,
                      "dropped_transport": dropped, "rows_with_err": err_rows,
                      "row_accounting_closes": bool(closes),
                      "passes_declared": d.get("passes_declared"), "tasks": len(per),
                      "exe": (d.get("exe") or {}).get("sha256", "")[:16],
                      "task_set": d.get("task_set_sha256", "")[:16]}, ensure_ascii=True))
    print(json.dumps({"per_task_model_denominator": {k: {"ok": v[0], "n": v[1]} for k, v in per.items()},
                      "ok_sum": sum(v[0] for v in per.values()),
                      "n_sum": sum(v[1] for v in per.values())}, ensure_ascii=True))
    ladder = [{"fails": k, "p": round(pt.fisher_2x2(n_passes - k, n_passes, n_passes, n_passes), 6)}
              for k in range(1, n_passes)]

    def first_below(alpha):
        hit = next((x["fails"] for x in ladder if x["p"] < alpha), None)
        return hit if hit is not None else {"absent": "跑满 %d 发也到不了 α=%g ⇒ 这一档分母问不出这个强度"
                                                            % (n_passes, alpha)}

    print(json.dumps({"ladder_vs_perfect_task": ladder, "need_fails_raw05": first_below(0.05),
                      "need_fails_bonferroni_78": first_below(0.05 / 78),
                      "alpha_bonf": round(0.05 / 78, 6)}, ensure_ascii=True))
    if not closes:
        print(json.dumps({"fatal": "row accounting did not close ⇒ 这趟的分档没接上，下面的数不作数"},
                         ensure_ascii=True))
        return 4
    ps = sorted((round(pt.fisher_2x2(per[a][0], per[a][1], per[b][0], per[b][1]), 6), a, b)
                for a, b in combinations(per, 2))
    low05, cnt05 = significant_pairs(per, 0.05)
    print(json.dumps({"pairs": len(ps),
                      "pairs_p_lt_05": len(low05),
                      "pairs_p_lt_bonferroni": sum(1 for x in ps if x[0] < 0.05 / 78),
                      "p_lt_05_pairs_full": [{"p": v, "a": a, "b": b} for v, a, b in low05],
                      "p_lt_05_by_task": cnt05,
                      "min_pairs": [{"a": a, "b": b, "p": v} for v, a, b in ps[:6]]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
