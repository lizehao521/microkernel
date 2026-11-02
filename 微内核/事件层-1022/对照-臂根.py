# -*- coding: utf-8 -*-
"""一次性对照件（M5 #113-1 的核账）：合并前五件 jsonl 与合并后 臂检-全部族.jsonl 逐根比 verdict。

用法：python 对照-臂根.py   （读 读数/合并前-现跑/*.jsonl 与 读数/臂检-全部族.jsonl）
产物：读数/合并前后对照-臂根.md ；退出码 0 = 共有根 verdict 全部一致且新族 G 全咬。
控制台只走 ASCII（GBK），中文进 md。
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_DIR = os.path.join(HERE, "读数", "合并前-现跑")
NEW = os.path.join(HERE, "读数", "臂检-全部族.jsonl")
OUT = os.path.join(HERE, "读数", "合并前后对照-臂根.md")

# 合并前 jsonl 的「片段不唯一」后缀（旧 A 件把 NOT-WIRED 混进 blind 的档案形状）需要归一
def norm(name):
    return name.replace("(片段不唯一)", "").strip()


old = {}
for p in sorted(glob.glob(os.path.join(OLD_DIR, "臂检-*.jsonl"))):
    for ln in open(p, encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            old[norm(r["arm"])] = (os.path.basename(p), r["verdict"])
new = {}
for ln in open(NEW, encoding="utf-8"):
    if ln.strip():
        r = json.loads(ln)
        new[norm(r["arm"])] = (r.get("family", "?"), r["verdict"], r.get("control_rc"),
                               r.get("mutant_rc"), r.get("mutant_build_broken"))

rows, mismatch, only_new, only_old = [], 0, [], []
for name in sorted(set(old) | set(new), key=lambda s: (s.split()[0], s)):
    o, n = old.get(name), new.get(name)
    if o and n:
        same = o[1] == n[1]
        if not same:
            mismatch += 1
        rows.append((name.split()[0], name, o[1], n[1], n[0], "一致" if same else "不一致",
                     str(n[2]), str(n[3]), str(n[4])))
    elif n:
        only_new.append(name)
        rows.append((name.split()[0], name, "absent（合并前没有这根）", n[1], n[0], "新增根",
                     str(n[2]), str(n[3]), str(n[4])))
    else:
        only_old.append(name)
        rows.append((name.split()[0], name, o[1], "absent（合并后丢了这根！）", "-", "丢失", "-", "-", "-"))

# 三态不塌：absent 必带为什么 —— 上面的「absent（合并前没有这根）」就是理由列。
bit_new = sum(1 for v in new.values() if v[1].startswith("BIT"))
g_bad = [n for n, v in new.items() if v[0] == "G" and not v[1].startswith("BIT")]

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write("# 合并前后臂根逐根对照（读数现跑，勿手抄）\n\n")
    f.write("- 合并前（五件 jsonl 现跑副本，读数/合并前-现跑/）：%d 根\n" % len(old))
    f.write("- 合并后（读数/臂检-全部族.jsonl）：%d 根，咬 %d\n" % (len(new), bit_new))
    f.write("- 共有根 verdict 不一致：%d ｜ 只在合并后（G 族新增）：%d ｜ 只在合并前（丢根要追问）：%d\n\n"
            % (mismatch, len(only_new), len(only_old)))
    f.write("| 编号 | 臂全名 | 合并前 verdict | 合并后 verdict | 族 | 对照 | 对照rc | 变异rc | mutant_build_broken |\n")
    f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
    for r in rows:
        f.write("| %s |\n" % " | ".join(str(x) for x in r))
    if only_old:
        f.write("\n## 只在合并前出现的根（不许悄悄丢）\n\n")
        for n in only_old:
            f.write("- %s（%s）\n" % (n, old[n][0]))

print("shared %d | mismatch %d | only-new %d | only-old %d | new-bit %d/%d"
      % (len(new) - len(only_new), mismatch, len(only_new), len(only_old), bit_new, len(new)))
print("markdown: %s" % OUT)
if only_old or mismatch or g_bad:
    sys.exit(2)
sys.exit(0)
