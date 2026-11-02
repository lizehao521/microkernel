import json
import os
from pathlib import Path

base = Path(r"C:\Users\Admin\Desktop\微内核\交付对账-1026\设计-桌面端-v2")
report = json.loads((base / "读数" / "对比度-全屏.json").read_text(encoding="utf-8"))
print("BUILD", report["build"], report["when"])
for s in report["states"]:
    print(f'{s["name"]:18s} checked={s["checked"]:4d} fail={s["failureCount"]} grad={s["skip"]["gradientApprox"]:4d} disabled={s["skip"]["disabled"]:3d} opacity={s["skip"]["opacity"]:3d} aria={s["skip"]["ariaHidden"]:4d}')
print("TOTALS", json.dumps(report["totals"], ensure_ascii=False))

shots = base / "读数" / "截图-v2"
print("SHOTS")
for p in sorted(shots.glob("*.png")):
    print(p.name, p.stat().st_size)

mem = json.loads((base / "记忆" / "记忆.json").read_text(encoding="utf-8"))
print("MEMORY", len(mem["decisions"]), len(mem["dialogue"]), mem["preferences"]["operator_name"], len(mem["preferences"]["reasons"]))
print("RECEIPTS", len(list((base / "回执").glob("receipt-*.html"))))

claim_data = json.loads((base / "证据" / "交付.json").read_text(encoding="utf-8"))
for d in claim_data["deliveries"]:
    counts = {}
    for c in d["claims"]:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    print("DELIVERY", d["id"], d["title"], counts)
