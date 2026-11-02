"""汇总尺子的反臂：拿 TEMP 里的假账打，证明它会红，且好账不误伤。

每条臂是叶子：复制落盘读数到 TEMP，单点篡改，再用 汇总-业务重复-1023.py 跑那份副本。
正式读数一个字节都不动。臂不合格直接非零退出。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGG = HERE / "汇总-业务重复-1023.py"
SRC = HERE / "读数" / "业务任务-三题x20-真端点.json"
PY = sys.executable


def run(path):
    r = subprocess.run([PY, str(AGG), str(path)], capture_output=True, timeout=120)
    lines = [ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    out = {}
    for ln in lines:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        out.update(o)
    return r.returncode, out, r.stderr.decode("utf-8", "replace")[:200]


def bsum(o):
    """不变量：桶的总和 == 件自己印的 bucket_sum == 发数。"""
    fb = o.get("fail_buckets") or {}
    return sum(fb.values()), o.get("bucket_sum"), (o.get("denominator_check") or {}).get("runs", {}).get("recounted")


def load(tmp, name):
    p = tmp / name
    shutil.copyfile(SRC, p)
    return p, json.loads(p.read_text(encoding="utf-8"))


def save(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def main():
    if not SRC.exists():
        print(json.dumps({"fatal": "source reading missing", "src": str(SRC)}))
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="agg-arms-"))
    arms = []
    try:
        # 1. 对照：好账不许误伤
        p, d = load(tmp, "control.json")
        rc, o, _ = run(save(p, d))
        tot, declared, runs = bsum(o)
        ok = (rc == 0 and o["all_match"] is True and declared == tot == runs)
        arms.append({"arm": "好账不误伤（对照必须不响）", "expect": "match 且桶和=印的=发数",
                     "got": "%s buckets=%s/%s runs=%s" % (
                         "match" if o["all_match"] else "MISMATCH", tot, declared, runs),
                     "pass": ok})

        # 2. 翻一发的 ok，summary 不动 ⇒ 重数必须和跑件印的打架
        p, d = load(tmp, "flip.json")
        flipped = 0
        for r in d["runs"]:
            if r.get("ok"):
                r["ok"] = False
                flipped += 1
                break
        rc, o, _ = run(save(p, d))
        bad = o["denominator_check"]["oracle_ok"]
        ok = (rc == 0 and o["all_match"] is False
              and bad["match"] is False and bad["recounted"] < bad["printed_by_runner"])
        arms.append({"arm": "改一发结果不动账（重数必须红）", "expect": "oracle_ok mismatch",
                     "got": "%s vs %s" % (bad["recounted"], bad["printed_by_runner"]),
                     "flipped": flipped, "pass": ok})

        # 3. 只改跑件印的 summary，不动 runs ⇒ 必须红在同一格
        p, d = load(tmp, "inflate.json")
        d["summary"]["oracle_ok"] += 1
        rc, o, _ = run(save(p, d))
        bad = o["denominator_check"]["oracle_ok"]
        mism = [k for k, v in o["denominator_check"].items() if not v["match"]]
        ok = (rc == 0 and bad["match"] is False and mism == ["oracle_ok"])
        arms.append({"arm": "虚增账面数（只有那一格红）", "expect": "only oracle_ok",
                     "got": ",".join(mism) or "none", "pass": ok})

        # 4. 给一发过账注入传输异常 ⇒ 必须从模型分母里摘掉，且不进 oracle 分子
        p, d = load(tmp, "transport.json")
        base_rc, base_o, _ = run(p)
        for r in d["runs"]:
            if r.get("ok"):
                r["err"] = "ConnectionResetError: injected"
                break
        rc, o, _ = run(save(p, d))
        n0 = base_o["on_model_denominator"]["n"]
        n1 = o["on_model_denominator"]["n"]
        flag = o.get("transport_flagged_ok")
        ok = (rc == 0 and o["fail_buckets"].get("transport") == base_o["fail_buckets"].get("transport", 0) + 1
              and n1 == n0 - 1
              and o["on_model_denominator"]["oracle_ok"] == base_o["on_model_denominator"]["oracle_ok"] - 1
              and flag == 1)
        arms.append({"arm": "传输失败单开账（分母要掉、分子也要掉、带异常又标过账的要点名）",
                     "expect": "transport+1 且 n-1 且 ok-1 且 flagged=1",
                     "got": "transport=%s->%s n=%d->%d ok=%d->%d flagged=%s" % (
                         base_o["fail_buckets"].get("transport"), o["fail_buckets"].get("transport"),
                         n0, n1,
                         base_o["on_model_denominator"]["oracle_ok"],
                         o["on_model_denominator"]["oracle_ok"], flag),
                     "pass": ok})

        # 5. 把一发标成撞步数上限 ⇒ 归因必须跟着走
        p, d = load(tmp, "cap.json")
        for r in d["runs"]:
            if r.get("ok"):
                r["ok"] = False
                r["stop"] = "步数上限"
                r["misses"] = ["injected"]
                break
        rc, o, _ = run(save(p, d))
        tot, declared, runs = bsum(o)
        ok = (rc == 0 and o["fail_buckets"].get("step_cap", 0) >= 1 and declared == tot == runs)
        arms.append({"arm": "撞上限的发要归进 step_cap", "expect": "step_cap>=1 且桶和=印的=发数",
                     "got": "%s buckets=%s/%s runs=%s" % (
                         json.dumps(o["fail_buckets"], ensure_ascii=False)[:90], tot, declared, runs),
                     "pass": ok})

        # 6. 桶的不变量：任何情况下 bucket_sum == runs
        bad_inv = []
        for f in sorted(tmp.glob("*.json")):
            rc, o, err = run(f)
            tot, declared, runs = bsum(o)
            if not (rc == 0 and declared == tot == runs):
                bad_inv.append("%s(%s/%s/%s rc=%s)" % (f.name, tot, declared, runs, rc))
        arms.append({"arm": "桶和恒等于发数（副本全集）", "expect": "no violation",
                     "got": ",".join(bad_inv) or "none", "pass": not bad_inv})

        for a in arms:
            print(json.dumps(a, ensure_ascii=True))
        dead = [a["arm"] for a in arms if not a["pass"]]
        print(json.dumps({"arms": len(arms), "arms_ok": not dead,
                          "blind": dead}, ensure_ascii=True))
        return 0 if not dead else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
