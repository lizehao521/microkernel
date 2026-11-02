import io
import os
import sys

sys.path.insert(0, "tasks/probe")
import rule_hit_matrix as m  # noqa: E402

g, mi, b = m.discover()
cand = dict(g + mi)
reg = set()
for r in getattr(m, "REPORTS", []):
    reg.add(r if isinstance(r, str) else str(r))
reg = {x for x in reg if x.endswith(".txt")}
void = set(getattr(m, "VOID", {}))
neither = sorted(set(cand) - reg - void)
new = "\u6784\u5efa\u6253\u5305-\u4ea4\u4ed8-1017.txt"
lines = [
    "REPORTS \u767b\u8bb0 %d \u6761" % len(reg),
    "discover \u5019\u9009 %d \uff5c\u6709\u539f\u8bdd %d \uff5c\u53ea\u6709\u952e\u540d\u5217 %d" % (len(cand), len(g), len(b)),
    "\u65b0\u7684\u4ea4\u4ed8\u8bb0\u5f55\u5728\u5019\u9009\u96c6\u91cc\u5417\uff1a%s -> %s" % (new, "\u5728" if new in cand else "\u4e0d\u5728"),
    "\u65e2\u6ca1\u767b\u8bb0\u4e5f\u4e0d\u5728\u4f5c\u5e9f\u8868\u91cc\u7684\uff1a%r" % (neither[:8],),
    "\u5019\u9009\u5168\u540d\uff1a%r" % (sorted(cand),),
]
out = os.path.join(os.environ.get("TEMP", "."), "disc-utf.txt")
with io.open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(out)
