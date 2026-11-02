"""Read-only comparison of T12 prompt A/B/C readings.

Prints ASCII only (GBK console contract); readings stay UTF-8 on disk.
Failure shapes are derived from the recorded fields, not from prose.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
READINGS = [
    ("baseline", HERE / "读数" / "T12-真端点-20次.json"),
    ("v2", HERE / "读数" / "T12-真端点-20次-提示词v2.json"),
    ("v3", HERE / "读数" / "T12-真端点-20次-提示词v3.json"),
]


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)


def fisher_two_sided(a, b, c, d):
    # table [[a, b], [c, d]]; two-sided by summing tables with p <= observed
    n = a + b + c + d
    r1, c1 = a + b, a + c

    def p_of(x):
        return (math.comb(r1, x) * math.comb(n - r1, c1 - x)) / math.comb(n, c1)

    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    obs = p_of(a)
    return sum(p_of(x) for x in range(lo, hi + 1) if p_of(x) <= obs * 1.0000001)


def classify(r):
    if r["ok"]:
        return "ok"
    steps = r.get("steps") or 0
    if steps == 0:
        return "zero-step"
    if r.get("read_present") and not r.get("stats_present"):
        return "read-only"
    if r.get("stats_present") and not r.get("read_present"):
        return "stats-only"
    if r.get("read_present") and r.get("stats_present"):
        return "both-but-lines-wrong"
    return "other"


def main():
    rows = []
    for label, path in READINGS:
        if not path.exists():
            rows.append({"label": label, "missing": str(path)})
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        reps = d.get("reps") or []
        shapes = {}
        for r in reps:
            k = classify(r)
            shapes[k] = shapes.get(k, 0) + 1
        stops = {}
        for r in reps:
            stops[r.get("stop")] = stops.get(r.get("stop"), 0) + 1
        prov = {}
        for r in reps:
            for x in r.get("provenances") or []:
                prov[x] = prov.get(x, 0) + 1
        rows.append({
            "label": label,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "reps": len(reps),
            "ok": sum(1 for r in reps if r.get("ok")),
            "shapes": shapes,
            "stops": stops,
            "prov": prov,
            "sane": sum(1 for r in reps if r.get("sane")),
            "p50": pct([r.get("ms") or 0 for r in reps], 0.5),
            "p95": pct([r.get("ms") or 0 for r in reps], 0.95),
            "max": max([r.get("ms") or 0 for r in reps], default=None),
            "failed_reps": [r.get("rep") for r in reps if not r.get("ok")],
        })
    print(json.dumps({"rows": rows}, ensure_ascii=True, indent=1))
    base = next((r for r in rows if r.get("label") == "baseline" and "ok" in r), None)
    if base:
        for r in rows:
            if r.get("label") == "baseline" or "ok" not in r:
                continue
            p = fisher_two_sided(base["ok"], base["reps"] - base["ok"],
                                 r["ok"], r["reps"] - r["ok"])
            print("fisher baseline-vs-%s: p=%.4f" % (r["label"], p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
