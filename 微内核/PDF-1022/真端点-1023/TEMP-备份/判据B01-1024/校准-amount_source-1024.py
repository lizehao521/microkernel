"""Scratch calibration for the B01 amount-source rule (read-only, prints only)."""
import json, re, sys, decimal, unicodedata, pathlib

REAL = pathlib.Path(r"C:/Users/Admin/Desktop/微内核/PDF-1022/真端点-1023")
sys.path.insert(0, str(REAL))
import importlib.util
spec = importlib.util.spec_from_file_location("runner", str(REAL / "跑-业务任务-1023.py"))
# never execute main(); import module body only
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

NUM_RE = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d])")
UNITS_AFTER = ("元", "块", "圆")
LABELS = ("合计", "税额", "含税", "金额", "单价", "总价", "小计", "税率", "价", "费")


def canon(tok):
    d = decimal.Decimal(tok.replace(",", ""))
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def money_flags(text):
    t = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in NUM_RE.finditer(t):
        tok = m.group(0)
        rest = t[m.end():m.end() + 3]
        before = t[max(0, m.start() - 16):m.start()]
        if re.match(r"^\s*%", rest):
            continue
        unit = any(rest.lstrip().startswith(u) for u in UNITS_AFTER) or before.rstrip().endswith("¥")
        label = any(l in before for l in LABELS)
        if unit or label:
            out.append({"tok": tok, "canon": canon(tok), "unit": unit, "label": label,
                        "ctx": t[max(0, m.start() - 14):m.end() + 4]})
    return out


def allowed(task, fx):
    vals = set()
    q = (task["question"] or "").replace("{fx}", "").replace("{hub}", "")
    for tok in NUM_RE.findall(unicodedata.normalize("NFKC", q)):
        vals.add(canon(tok))
    srcs = []
    for frag in (task.get("requires") or {}).get("reads") or []:
        srcs.append(frag)
    for frag in (task.get("requires") or {}).get("stats") or []:
        srcs.append(frag)
    for frag in srcs:
        p = fx / frag
        if not p.exists():
            print(json.dumps({"fixture_missing": str(p)}, ensure_ascii=False))
            continue
        for tok in NUM_RE.findall(unicodedata.normalize("NFKC", p.read_text(encoding="utf-8", errors="replace"))):
            vals.add(canon(tok))
    return vals, srcs


FILES = ["业务任务-13x20-真端点.json", "业务任务-13x5-真端点-修判据v3.json",
         "业务任务-三题x20-真端点.json", "业务任务-13x40-真端点.json"]
tasks = {}
for line in (REAL / "业务任务-13.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        t = json.loads(line)
        tasks[t["id"]] = t
fx = REAL / "业务现场"
al, srcs = allowed(tasks["B01"], fx)
print(json.dumps({"b01_allowed": sorted(al, key=lambda x: (len(x), x)),
                  "allowed_sources": srcs}, ensure_ascii=False))

rows = []
for f in FILES:
    d = json.loads((REAL / "读数" / f).read_text(encoding="utf-8"))
    for r in d.get("runs") or []:
        if r.get("id") != "B01":
            continue
        rows.append((f, r))
print(json.dumps({"b01_rows_total": len(rows)}, ensure_ascii=False))

n_ms = n_ok = n_at_cap = n_flagged = 0
unit_only = label_only = disagree = 0
for f, r in rows:
    tier = r.get("answer_tier")
    if tier != "model_says":
        continue
    n_ms += 1
    head = r.get("answer_head") or ""
    if len(head) >= 400:
        n_at_cap += 1
    flags = money_flags(head)
    unsourced = [x for x in flags if x["canon"] not in al]
    u = [x for x in unsourced if x["unit"]]
    l = [x for x in unsourced if not x["unit"]]
    if u and not l:
        unit_only += 1
    elif l and not u:
        label_only += 1
    elif u and l:
        disagree += 1
    if unsourced:
        n_flagged += 1
        print(json.dumps({"win": f.replace("业务任务-", "").replace("-真端点", "").replace("-修判据v3", ""),
                          "pass": r.get("pass"), "ok": r.get("ok"),
                          "answer_ok": r.get("answer_ok"),
                          "misses": r.get("misses"),
                          "unsourced": [{"t": x["tok"], "u": x["unit"], "l": x["label"],
                                         "ctx": x["ctx"]} for x in unsourced],
                          "head": head}, ensure_ascii=False))
print(json.dumps({"summary": {"model_says": n_ms, "flagged_rows": n_flagged,
              "rows_at_400_cap": n_at_cap, "unit_only": unit_only,
              "label_only": label_only, "both": disagree}}, ensure_ascii=False))
