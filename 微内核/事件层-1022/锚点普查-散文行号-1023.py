# -*- coding: utf-8 -*-
"""散文行号普查（只读 · 不是闸 · 不参与任何判据合取）。

为什么有这件：`锚点核对.py` 只核 `evidence.md` 那张表，而全现场 md 里还有一批
`xxx.go:NNN` 形式的引用散在验收件、收口表、说明书与 AGENTS 里 —— 那些号没有任何一把尺子在看。
E5-E9 落码后 `cmd/agentd/loop.go` 的一批号整体 +97 漂了（交接 §2j 记了现场），所以要把「有多少、
哪些能判、哪些判不了」变成一条命令能重跑的东西，而不是这一轮的一次性 grep。

三态（不许塌成两态）：
  OK        被引那句点名的标识符，确实出现在被指那一行的 ±窗口 内
  DRIFT     号仍在文件行数内，抽出的符号**在这个文件里别处找得到、就是不在那一行** —— 位置活着、说的不是
            那件事（最难发现的一族，且能给出「现应在第几行」）
  NOCUE     号在范围内，但抽出的符号在这个文件里**一处都找不到** —— 这一档是**本件的抽取失手**
            （散文词/中文文案被当成标识符），不许读成「那处引用坏了」
  OOB       号越过文件末尾
  NOID      那句里没有可核标识符（纯散文），本件判不了 —— 记成判不了，不折算成 OK 也不折算成坏
  AMBIG     同一个 .go 文件名在好几棵树里都有，件不猜是哪一棵
臂（叶子，两条，缺一条整份结论作废）：
  A-坏  内存副本里把一条真引用改成指向「同一文件里在范围内、但确实不含那个符号」的一行 —— 必须数出 DRIFT
  A-好  把一条真引用的号改成它自己所在的行 —— 必须 OK 且 DRIFT=0（否则这把尺子谁都判得响）
  两臂的「响的前提」都印在屏上：坏臂那行的内容与是否在范围内；前提不成立的 0 分档是臂没接上，不是尺子没牙。
退出码只回答「这次普查可不可信」：臂没响 / 一个都没判动 / 落盘不配平 = 3；破没破是发现，不是本件的红。
用法：`python 锚点普查-散文行号-1023.py <树1> <树2>` —— 传的是**目录**，不是 go.exe（别抄全闸那条命令行）。
一棵树如果 0 个 .go，TREE 行会印 0：那是传错了，不是「这个范围没东西」。传重叠的树（父目录 + 子目录）不改变分档，件按绝对路径去重。
"""
import os
import re
import sys
import glob

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.dirname(__file__))
OUT = os.path.join(ROOT, "读数", "锚点普查-散文行号.txt")
REF = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\.go:([0-9]{2,4})")
ID = re.compile(r"\b[A-Za-z_][A-Za-z_0-9]{5,}\b")
STOP = {"loop", "events", "checklog", "mcpsrv", "trace", "false", "true", "func", "test",
        "const", "var", "string", "return", "range", "struct", "error", "fmt", "time",
        "http", "json", "jsonl", "sse"}


def load_trees(paths):
    """每棵被扫树：basename -> 该 basename 的**全部**命中 [(rel, 行列表), ...]，按相对路径排序。

    这里原来写成 `one[basename] = (rel, lines)` —— 被扫范围里有 8 个 `main.go`，它们互相覆盖，
    谁最后留下由 glob 的目录序列决定（**不是被检内容**）。实测到的两处：
    ① 旧版 TREE 行报 `微内核=54 个 .go`，而那棵树实际有 62 个 .go —— 字典键数被当成了文件数，8 份同名直接吃掉；
    ② 用旧版快照（`TEMP-备份/锚点普查-快照-同名basename被dict吃掉那版.py`，sha `49816aa16602`）加一个"翻转列举序"的开关
      跑同一件、同一树参数：`REV=0` 得 `DRIFT=43 OOB=6`，`REV=1` 得 `DRIFT=49 OOB=0` —— 只翻顺序，6 条从越界翻成漂。
      （那份对照扫的是 `TEMP-备份/*.md`，件按自身目录找 md，所以 72/43/49 这几个数**不是现场数**，只能当"会改档"的证据。）
    一份读数会因为文件系统列举顺序而变档，它就是不可复算的，所以改成存列表 + 排序 + 撞名一律进 AMBIG。
    另：02:18 与 02:29 那两趟的 `OOB=0 / OOB=2` 之差**不是**这条病，是扫描范围之差（一棵 `cmd/agentd` ↔ 整棵内核树），
    同一个范围内现在连跑三趟逐字相同 —— 别把口径差记成 bug，也别把 bug 记成口径差。
    """
    trees = []
    for p in paths:
        one = {}
        for f in glob.glob(os.path.join(p, "**", "*.go"), recursive=True):
            rel = os.path.relpath(f, p).replace("\\", "/")
            try:
                with open(f, encoding="utf-8") as h:
                    lines = h.read().splitlines()
            except Exception:
                continue
            one.setdefault(os.path.basename(f), []).append((rel, lines, os.path.abspath(f)))
        for k in one:
            one[k].sort(key=lambda x: x[0])
        trees.append((p, one))
    return trees


def ambiguous_names(trees):
    """被扫范围里同名 .go 不止一份的 basename —— 排序后返回 [(名字, 份数)]，自己印当分母。

    份数按 **abspath 去重** 数：两棵树有包含关系时（传 `微内核/微内核` 又传 `cmd/agentd`）
    同一个文件会命中两次，那不是歧义，把它数成歧义等于用参数写法造假分母。
    """
    seen = {}
    for _, one in trees:
        for k, v in one.items():
            seen.setdefault(k, set()).update(ap for _, _, ap in v)
    return sorted([(k, len(v)) for k, v in seen.items() if len(v) > 1])


def find_in(name, trees):
    """跨树展平成 [(root, rel, 行列表), ...] —— 同一棵树里的同名也算多次命中（以前只数「跨树」，同树撞名看不见）。"""
    hits, seen = [], set()
    for root, one in trees:
        for rel, lines, ap in one.get(name, []):
            if ap in seen:
                continue
            seen.add(ap)
            hits.append((root, rel, lines))
    return hits


def census(md_files, trees, win=2, exclude=("evidence.md",)):
    rows = {"OK": 0, "DRIFT": 0, "NOCUE": 0, "OOB": 0, "NOID": 0, "AMBIG": 0}
    bad = []
    total = 0
    for md in md_files:
        if os.path.basename(md) in exclude:
            continue
        with open(md, encoding="utf-8", errors="replace") as h:
            for lineno, text in enumerate(h, 1):
                for m in REF.finditer(text):
                    name, n = m.group(1) + ".go", int(m.group(2))
                    total += 1
                    hits = find_in(name, trees)
                    if len(hits) == 0:
                        rows["NOFILE"] = rows.get("NOFILE", 0) + 1
                        bad.append((md, lineno, "NOFILE", name, n, "-"))
                        continue
                    if len(hits) > 1:
                        rows["AMBIG"] += 1
                        bad.append((md, lineno, "AMBIG", name, n,
                                    "同名共 %d 份：%s" % (len(hits), ",".join(rel for _, rel, _ in hits))))
                        continue
                    _, rel, src = hits[0]
                    if n > len(src):
                        rows["OOB"] += 1
                        bad.append((md, lineno, "OOB", name, "%d>%d" % (n, len(src)),
                                    "解析到 %s（共 %d 行）" % (rel, len(src))))
                        continue
                    ids = [x for x in ID.findall(text)
                           if x.lower() not in STOP and x not in (m.group(1), name)]
                    if not ids:
                        rows["NOID"] += 1
                        continue
                    lo, hi = max(0, n - 1 - win), n + win
                    window = " ".join(src[lo:hi])
                    if any(x in window for x in ids):
                        rows["OK"] += 1
                        continue
                    # 不在窗口 —— 再分一刀：这个符号在同文件的别处找得到吗？
                    # 找得到 => DRIFT（真漂，能给现应在第几行）；找不到 => NOCUE（本件抽取失手，别当坏引用）
                    cues = []
                    for x in ids[:3]:
                        pat = re.compile(r"\b%s\b" % re.escape(x))
                        lines = [i + 1 for i, ln in enumerate(src)
                                 if pat.search(ln) and not (lo <= i < hi)]
                        if lines:
                            cues.append("%s@%s" % (x, ",".join(map(str, lines[:3]))))
                    kind = "DRIFT" if cues else "NOCUE"
                    rows[kind] += 1
                    bad.append((md, lineno, kind, name, n,
                                ("解析到 %s ｜ " % rel) + (("现应 " + " ".join(cues)) if cues
                                else "抽出的词=%s（同文件里没有）|| 那行=%s" % (
                                    ",".join(ids[:3]), src[n - 1].strip()[:44]))))
    return rows, bad, total


def main():
    trees = load_trees(sys.argv[1:3] if len(sys.argv) > 2 else
                       [os.path.join(ROOT, "..", "微内核", "微内核", "cmd", "agentd")])
    if not any(one for _, one in trees):
        print("rc=4 被扫树读不到 .go（不是 0 处引用，是根本没数到东西）")
        return 4
    md_files = sorted(glob.glob(os.path.join(ROOT, "*.md")))
    rows, bad, total = census(md_files, trees)

    # --- 两条叶子臂（都在临时文件上跑，不动盘上任何被检文件） ---
    # 探针：从任一棵树里取一个「真在某一行的函数名」，好臂指它自己那一行，坏臂指同一文件里不含它的一行。
    # 探针文件必须是**无歧义 basename** —— 拿撞名的那份当探针，判动会落在 AMBIG 档上，臂响的不是 DRIFT/OK。
    amb = ambiguous_names(trees)
    nm, sym, good_n, bad_n, src, prel = None, None, 0, 0, None, ""
    for root, one in trees:
        for name, cands in one.items():
            if len(find_in(name, trees)) > 1:
                # 按**跨树去重后的份数**筛，不是本树份数：传了两棵有包含关系的树时，
                # 本树唯一的名字在普查里照样落 AMBIG，臂响的就不是 OK/DRIFT —— 臂看着响，其实没接上。
                continue
            for rel, lines, _ in cands:
                for i, ln in enumerate(lines, 1):
                    mm = re.match(r"\s*func (?:\([^)]*\) )?([A-Za-z_][A-Za-z_0-9]{5,})\(", ln)
                    if not mm:
                        mm = re.match(r"\s*func ([A-Za-z_][A-Za-z_0-9]{5,})\(", ln)
                    if mm:
                        nm, sym, good_n, src, prel = name, mm.group(1), i, lines, rel
                        break
                if nm:
                    break
            if nm:
                break
        if nm:
            break
    if not nm:
        print("ARM 造不出探针（树里没找到可命名的函数）—— 臂没法证牙，整份结论作废")
        return 3
    # 坏臂必须落在「两位数且在行数内」的行上：REF 只认 [0-9]{2,4}，指到 :1 根本不进引用表，
    # 于是 判动=0 看起来像尺子没牙，实际是臂没接上 —— 这两种要能分开，所以这里把前提写死并印出来。
    bad_n = 10
    while bad_n <= len(src) and (sym in src[bad_n - 1] or not src[bad_n - 1].strip()):
        bad_n += 1
    in_range = bad_n <= len(src)
    if not in_range:
        bad_n = len(src) + 5   # 退到文件末尾之外 —— 那一档是 OOB，也算抓到
    fake = os.path.join(ROOT, "_臂检-临时.md")

    def run_on(text):
        with open(fake, "w", encoding="utf-8") as h:
            h.write(text)
        try:
            return census([fake], trees, exclude=())
        finally:
            if os.path.exists(fake):
                os.remove(fake)

    gr, _, gt = run_on("// %s 在 %s:%d\n" % (sym, nm, good_n))
    br, _, bt = run_on("// %s 在 %s:%d\n" % (sym, nm, bad_n))
    arm_good = (gt == 1 and gr.get("OK", 0) == 1 and gr.get("DRIFT", 0) == 0)
    # 坏臂只认 DRIFT/OOB 这两档：符号在文件里别处找得到却说不在那一行（=真漂），或号越过末尾。
    # 若它落到 NOCUE，说明探针本身选坏了（那个符号压根不在文件里）—— 臂没接上，不算抓到。
    arm_bad = (bt == 1 and (br.get("DRIFT", 0) + br.get("OOB", 0)) == 1)
    print("TREE %s" % " | ".join("%s=%d 个 .go（%d 个 basename）" % (
        os.path.basename(r.rstrip('/')), sum(len(v) for v in one.values()), len(one)) for r, one in trees))
    print("SCAN md=%d 树=%d 引用总数=%d（只扫 %s 与 %s 这两处，别的树要传 argv 进来）" % (
        len(md_files), len(trees), total, os.path.basename(ROOT),
        ",".join(os.path.basename(r.rstrip('/')) for r, _ in trees)))
    print("同名 basename=%d 个（这些名字的引用一律进 AMBIG，件不猜是哪一份）：%s" % (
        len(amb), ", ".join("%s×%d" % (k, c) for k, c in amb[:10]) if amb else "无"))
    print("分档 " + " ".join("%s=%d" % (k, rows.get(k, 0)) for k in
          ("OK", "DRIFT", "NOCUE", "OOB", "NOFILE", "AMBIG", "NOID")))
    print("判不了的档：NOID（那句是纯散文）与 AMBIG（被扫范围里同名 .go 不止一份，同树内撞名也算）—— 都不折算成好，也不折算成坏")
    print("抽取失手的档：NOCUE —— 抽出的词在那个文件里根本没有，多半是散文词/中文文案被当成标识符；"
          "**这一档不许读成「那处引用坏了」**")
    for b in bad[:20]:
        print("  坏 %-46s md行%-4d %s %s:%s %s" % (os.path.basename(b[0]), b[1], b[2], b[3], b[4], b[5]))
    if len(bad) > 20:
        print("  ...（其余 %d 条：这条命令重跑就全印，别抄进文档）" % (len(bad) - 20))
    print("ARM-好 探针=%s（解析到 %s，同名份数=%d）:%d 符号=%s -> 分档=%s 判动=%d  %s" % (
        nm, prel, len(find_in(nm, trees)), good_n, sym, gr, gt, "OK" if arm_good else "没响（尺子没牙）"))
    print("ARM-坏 探针=%s:%d（那行不含 %s）在范围内=%s 那行=[%s] -> 分档=%s 判动=%d  %s" % (
        nm, bad_n, sym, in_range,
        src[bad_n - 1].strip()[:40] if bad_n <= len(src) else "<越过末尾>",
        br, bt, "抓到" if arm_bad else "没响（尺子没牙）"))

    body = []
    body.append("锚点普查（散文里写死的 xxx.go:NNN）—— 只读、不是闸，rc 只回答这次普查可不可信")
    body.append("TREE " + " | ".join("%s=%d 个 .go（%d 个 basename）" % (
        os.path.basename(r.rstrip('/')), sum(len(v) for v in one.values()), len(one)) for r, one in trees))
    body.append("同名 basename=%d 个：%s ｜ 这些名字的引用一律进 AMBIG（同树内撞名也算，件不猜哪一份）" % (
        len(amb), ", ".join("%s×%d" % (k, c) for k, c in amb) if amb else "无"))
    body.append("SCAN md=%d 引用总数=%d（范围=%s/*.md + 传入的树）" % (len(md_files), total, os.path.basename(ROOT)))
    body.append("分档 " + " ".join("%s=%d" % (k, rows.get(k, 0)) for k in
              ("OK", "DRIFT", "NOCUE", "OOB", "NOFILE", "AMBIG", "NOID")))
    body.append("口径：DRIFT=符号在同文件别处找得到(真漂，给现应行号)；NOCUE=抽取失手(不算坏引用)；"
                "NOID/AMBIG=判不了(不折好也不折坏)；OOB=号越过被解析那一份的末尾（那一份是谁写在同一行里）")
    for b in bad:
        body.append("坏\t%s\tmd行%d\t%s\t%s:%s\t%s" % (b[0], b[1], b[2], b[3], b[4], b[5]))
    body.append("ARM-好 %s %s:%d 解析到=%s 同名份数=%d 符号=%s 判动=%d" % (
        "OK" if arm_good else "NORESPONSE", nm, good_n, prel, len(find_in(nm, trees)), sym, gt))
    body.append("ARM-坏 %s %s:%d 在范围内=%s 判动=%d" % ("抓到" if arm_bad else "NORESPONSE", nm, bad_n, in_range, bt))
    txt = "\n".join(body) + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    part = OUT + ".part"
    with open(part, "w", encoding="utf-8") as h:
        h.write(txt)
    os.replace(part, OUT)
    with open(OUT, encoding="utf-8") as h:
        landed = h.read().splitlines()
    # 自证那两行用 print 直接上屏，绝不写回被数的那个 list（交接 §2h/§2i 那笔账）
    print("landing: %s %d lines %d bytes" % (OUT, len(landed), os.path.getsize(OUT)))
    ok_land = len(landed) == len(body)
    print("landing check: %s (%d/%d lines)" % ("OK" if ok_land else "MISMATCH", len(landed), len(body)))
    judged = sum(rows.get(k, 0) for k in ("OK", "DRIFT", "NOCUE", "OOB"))
    bad_rc = (not arm_bad) or (arm_good is False) or (judged == 0 and total > 0) or (not ok_land)
    print("rc 归因: 坏臂没响=%s 好臂没响=%s 一条都没判动=%s 落盘不配平=%s" % (
        not arm_bad, arm_good is False, judged == 0 and total > 0, not ok_land))
    print("注意：破没破（DRIFT/OOB 的多少）是本件的发现，不是本件的红 —— 别拿 rc=0 读成「引用都对」；"
          "反过来 rc=3 也不等于「引用都坏了」，它只说这一次普查不可信。")
    return 3 if bad_rc else 0


if __name__ == "__main__":
    sys.exit(main())
