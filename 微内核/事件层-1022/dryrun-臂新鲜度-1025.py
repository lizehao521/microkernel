#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B2（10-25）：臂读数「新鲜度」这两把尺子的 dry-run 翻转表 —— **只算，不改任何 rc**。

现场有两处判据都拿「读数比树旧」当开关，而两个开关的方向相反：

1. `验收-事件层-1022.py` 的 NO-ARM 那一行只在 `arms["fresh"]` 为真时才判 ⇒
   读数一旧，**所有**针的「没有臂」都不算了，`conclusion=ALL-PINS-GREEN-WITH-ARMS` 照发；
2. `体检-全闸-1023.py` 的臂读数体检 STALE 只 WARN、不进 bad ⇒ 过期永不影响退出码。

把 1 的新鲜度开关关掉、把 2 升成红，各会让几道进 bad？这个数作者要先看见才好圈。
本件不动那两件一根手指：全部读盘、算两遍、**改前/改后两个数并排印**，不并进同一句。

第三件事顺手量：这条判据**覆盖面能不能自扩** —— 今天它只比 `cmd/agentd/*.go` 的 mtime，
而 10-25 这趟真正改的是 `mcpsrv/*.go` 与 `cmd/agentd` 之外的文件。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe dryrun-臂新鲜度-1025.py
只读；不跑 go（Test 名按源码扫，所以与「刚重跑一遍验收」不同源，这一点自己印出来）。
退出码：0 算完了；4 输入读不到（读不到就明写读不到，不折成 0 条针）。
"""
import importlib.util
import io
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ACC = os.path.join(HERE, "验收-事件层-1022.py")
REPORT_ALL = os.path.join(HERE, "报告-全闸.txt")
OUT = os.path.join(HERE, "报告-dryrun-臂新鲜度-1025.txt")
PART = OUT + ".part"
# 树根、臂读数名、验收读数名**都从 验收-事件层-1022.py 里取**（见 main 里的 load_acc）：
# 在这儿重写一遍相对路径就是第二份定义，它会在下一次挪目录时说假话（10-25 现场：
# 第一版自己拼 `../微内核/微内核/微内核` 多拼了一层，件直接 FileNotFoundError）。
SRC = None
ARMS = None
REPORT_ACC = None

lines = []
rows_out = []   # 逐针的结构化行，末尾的 landing check 按它自证


def emit(s):
    lines.append(s)


def say(s):
    # 控制台只走 ASCII：GBK 下打印中文标点会崩，而崩掉的是退出码（rc=1 会冒充闸红）。
    print(s.encode("ascii", "backslashreplace").decode("ascii"))


def read(p):
    if not os.path.isfile(p):
        return None
    return io.open(p, encoding="utf-8", errors="replace").read()


def fmt(ts):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))


def load_acc():
    """把 验收-事件层-1022.py 当模块读进来（它 `__main__` 有守卫，import 不会跑任何闸）。
    针名表、MAP、NOT_MEASURABLE 都从它那里取 —— 抄一份到这里就是第二份定义，会漂。"""
    spec = importlib.util.spec_from_file_location("acc1022", ACC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def tests_from_source():
    d = os.path.join(SRC, "cmd", "agentd")
    names = []
    for f in sorted(os.listdir(d)):
        if not f.endswith("_test.go"):
            continue
        names += [mm.group(1) for mm in re.finditer(r"^func (Test\w+)\(", read(os.path.join(d, f)) or "", re.M)]
    return sorted(set(names))


def newest_in(rel_dirs):
    vals = []
    for rd in rel_dirs:
        d = os.path.join(SRC, *[p for p in rd.split("/") if p])
        if not os.path.isdir(d):
            continue
        vals += [os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".go")]
    return max(vals) if vals else 0.0


def main():
    global SRC, ARMS, REPORT_ACC
    m = load_acc()
    SRC, ARMS, REPORT_ACC = m.SRC, m.ARMS, m.REPORT
    emit("== 0 · 输入（全部只读；分母自己印）==")
    emit("   树根/读数名取自 %s：SRC=%s ｜ 树在=%s"
         % (os.path.basename(ACC), SRC, os.path.isdir(SRC)))
    if not os.path.isdir(SRC):
        emit("   !! 树根不存在 ⇒ 这一件算不了，退出 4（不算 0 条针）")
        return 4
    names, errs = m.pins_from_doc()
    emit("   针名表来源=%s ｜ 现读 %d 条针 ｜ 解析错误=%s"
         % (os.path.basename(ACC), len(names) if names else 0, errs or "无"))
    if not names:
        emit("   !! 针名表是空的 —— 后面每张表都会在空集上成立，这种数不作数")
        return 4
    all_tests = tests_from_source()
    arm_txt = read(ARMS)
    if arm_txt is None:
        emit("   !! 读不到臂读数 %s ⇒ ①②都算不了（这不是 0 根臂，是没这份读数）" % ARMS)
        return 4
    rows = [json.loads(l) for l in arm_txt.splitlines() if l.strip()]
    acc_txt = read(REPORT_ACC)
    health_txt = read(REPORT_ALL)
    emit("   Test 名来源=按 cmd/agentd/*_test.go 源码扫（不跑 go）｜ 现数 %d 支" % len(all_tests))
    emit("   臂读数=%s ｜ 现数 %d 行 ｜ mtime=%s" % (os.path.basename(ARMS), len(rows), fmt(os.path.getmtime(ARMS))))
    emit("   落盘·验收=%s（%s）｜ 落盘·全闸=%s（%s）"
         % (os.path.basename(REPORT_ACC), fmt(os.path.getmtime(REPORT_ACC)) if acc_txt else "读不到",
            os.path.basename(REPORT_ALL), fmt(os.path.getmtime(REPORT_ALL)) if health_txt else "读不到"))

    # 落盘那份自己印的分母，与我这一趟现数的对账（两个自印分母要互相对账）
    ref_tests = ref_rows = None
    if acc_txt:
        mm = re.search(r"doc_pins=(\d+) ｜ tests_in_package=(\d+) ｜ arm_rows=(\S+)", acc_txt)
        if mm:
            ref_tests, ref_rows = int(mm.group(2)), int(mm.group(3))
    emit("   对账：落盘 tests_in_package=%s vs 现扫 %d ⇒ %s ｜ 落盘 arm_rows=%s vs 现数 %d ⇒ %s"
         % (ref_tests, len(all_tests),
            "—" if ref_tests is None else ("同" if ref_tests == len(all_tests) else "**不同**（10-25 之后加了针就会不同）"),
            ref_rows, len(rows), "—" if ref_rows is None else ("同" if ref_rows == len(rows) else "**不同**")))

    a_agentd = newest_in(["cmd/agentd"])
    a_tree = newest_in(["cmd/agentd", "mcpsrv", "."])
    arms_mt = os.path.getmtime(ARMS)
    stale_now = arms_mt < a_agentd
    stale_wide = arms_mt < a_tree

    emit("== 1 · 这条新鲜度判据今天比的是谁（覆盖面）==")
    emit("   判据现范围=只比 cmd/agentd/*.go ｜ 树里最新 %s ｜ 读数 %s ⇒ %s"
         % (fmt(a_agentd), fmt(arms_mt), "STALE" if stale_now else "FRESH"))
    emit("   自扩一档=cmd/agentd + mcpsrv + 根包 .go ｜ 树里最新 %s ⇒ %s"
         % (fmt(a_tree), "STALE" if stale_wide else "FRESH"))
    for rd in ["cmd/agentd", "mcpsrv", "."]:
        d = os.path.join(SRC, *[p for p in rd.split("/") if p])
        if not os.path.isdir(d):
            continue
        newer = [f for f in sorted(os.listdir(d))
                 if f.endswith(".go") and os.path.getmtime(os.path.join(d, f)) > arms_mt]
        emit("   比读数新的 .go ｜ %-11s %d 个%s"
             % (rd, len(newer), ("（最新 %s）" % newer[-1]) if newer else ""))

    # ---- ① NO-ARM：把 fresh 开关关掉，几根针从「无判定」变 NO-ARM ----
    per_pin = {}
    noarm_in_reading = 0
    reading_stale = False
    concl_before = None
    if acc_txt:
        for mm in re.finditer(r"^PIN-(\S+) (\S+) (\S+) tests=(\d+) rc=(-?\d+) arms_BIT=(\d+)", acc_txt, re.M):
            # 组序 = 屏上的列序：1=编号 2=针名 3=绿/红 4=tests 5=rc 6=arms_BIT。
            # 第一版把 arms 取成了 5（那是 rc），于是这张表里「落盘臂」整列都是 0 —— 数对了列才叫数。
            per_pin[mm.group(2)] = {"tests": int(mm.group(4)), "rc": int(mm.group(5)),
                                    "arms": int(mm.group(6))}
        noarm_in_reading = len(re.findall(r"NO-ARM", acc_txt))
        reading_stale = "ARM-READING-STALE" in acc_txt
        for l in acc_txt.splitlines():
            if l.startswith("conclusion="):
                concl_before = l[len("conclusion="):].strip()

    def bite_of(tests):
        return sum(1 for d in rows
                   if any(re.search(re.escape(x), str(d.get("test", ""))) for x in tests)
                   and str(d.get("verdict", "")).startswith("BIT"))

    emit("== 2 · ① 验收那件：fresh 开关关掉之后（逐针）==")
    emit("   落盘那趟自己印的：ARM-READING-STALE=%s ｜ NO-ARM 出现 %d 次 ｜ conclusion=%s"
         % ("是（那一趟抑制了 NO-ARM）" if reading_stale else "否", noarm_in_reading,
            concl_before or "读不到"))
    covered = set()
    flips = 0
    zero = 0
    mism = 0
    tmism = 0
    for name in names:
        key = name.replace("针", "").strip()
        pat = m.MAP.get(key)
        mine = [t for t in all_tests if pat and re.search(pat, t)]
        covered.update(mine)
        nb = bite_of(mine)
        nm = key in m.NOT_MEASURABLE
        before = ("抑制（那趟读数旧 ⇒ 这一行不发）" if reading_stale
                  else ("NO-ARM" if nb == 0 and not nm else "不发"))
        after = "NO-ARM 进 bad" if (nb == 0 and not nm) else "不发"
        flip = before != after and after.startswith("NO-ARM")
        flips += 1 if flip else 0
        zero += 1 if (nb == 0 and not nm) else 0
        p = per_pin.get(name, {})
        if p and p.get("arms") != nb:
            mism += 1
        if p and p.get("tests") != len(mine):
            tmism += 1
        rows_out.append({"pin": name, "tests": len(mine), "arms_now": nb,
                         "arms_reading": p.get("arms"), "not_measurable": nm,
                         "after": after})
        emit("   %-6s tests=%-3d（落盘 %-4s）臂咬=%-3d（落盘 %-4s）落盘rc=%-4s ｜ 改前 %-26s 改后 %s%s"
             % (name, len(mine), p.get("tests", "—"), nb, p.get("arms", "—"), p.get("rc", "—"),
                before, after, "  ⇐ 翻转" if flip else ""))

    tf = m.tests_by_file()
    holes = sorted(t for t in set(all_tests) - covered if tf.get(t, "").startswith("events"))
    outside = sorted(t for t in set(all_tests) - covered if not tf.get(t, "").startswith("events"))
    nb = bite_of(holes)
    before = "抑制（那趟读数旧）" if reading_stale else ("NO-ARM" if nb == 0 else "不发")
    after = "NO-ARM 进 bad" if nb == 0 else "不发"
    flips += 1 if (before != after and after.startswith("NO-ARM")) else 0
    zero += 1 if nb == 0 else 0
    emit("   EXTRA  tests=%-3d 现数臂咬=%-3d 落盘臂=%-4s ｜ 改前 %-26s 改后 %s%s"
         % (len(holes), nb, per_pin.get("本面其余针", {}).get("arms", "—"), before, after,
            "  ⇐ 翻转" if before != after and after.startswith("NO-ARM") else ""))
    emit("   现数：针 %d 条 + EXTRA 1 条 ｜ 「没臂且没写理由」%d 条 ｜ 开关一关多出来的判定 %d 条"
         % (len(names), zero, flips))
    emit("   与落盘那趟不一致的：臂咬数 %d 条、tests 数 %d 条（今天这棵树比那趟多了针，映射也动过 —— "
         "两张表不同源，别把它们读成一趟）" % (mism, tmism))
    emit("   其余信息：本面未覆盖的 events* Test %d 支 ｜ 本面之外 %d 支" % (len(holes), len(outside)))
    emit("   conclusion 改前（落盘逐字）=%s" % (concl_before or "读不到"))
    emit("   conclusion 改后（按上面那个翻转数**算**，不是重跑出来的）=%s"
         % ("仍是 ALL-PINS-GREEN-WITH-ARMS（翻转 0 条 ⇒ 开关今天没有牙在这一批数据上）"
            if flips == 0 else "%d 行不合格（= 改前那条 + 新判定的 %d 条）" % (flips, flips)))

    # ---- ② 全闸那件：STALE 从 WARN 升成红 ----
    emit("== 3 · ② 体检-全闸：把「读数比树旧」从只 WARN 升成进 bad ==")
    if health_txt is None:
        emit("   !! 读不到 %s ⇒ 这一栏空着，不猜今天几道绿" % os.path.basename(REPORT_ALL))
    else:
        gates = re.findall(r"^(.+?)\s+rc=(-?\d+)\s+\d+s", health_txt, re.M)
        bad_now = [k.strip() for k, v in gates if int(v) != 0]
        arm_line = [l for l in health_txt.splitlines() if l.startswith("arm-reading")]
        emit("   落盘那份：解析到 %d 道闸 ｜ rc≠0 的 %d 道%s ｜ 那行臂体检逐字=%s"
             % (len(gates), len(bad_now), ("：%s" % ", ".join(bad_now)) if bad_now else "",
                arm_line[0] if arm_line else "（没有这行）"))
        emit("   改前（只 WARN）：进 bad +%d 道（今天判据范围下状态=%s）"
             % (0, "STALE" if stale_now else "FRESH"))
        emit("   改后·范围不变（升成红）：进 bad +%d 道 ｜ 状态=%s"
             % (1 if stale_now else 0, "STALE" if stale_now else "FRESH"))
        emit("   改后·范围自扩（含 mcpsrv/根包）：进 bad +%d 道 ｜ 状态=%s"
             % (1 if stale_wide else 0, "STALE" if stale_wide else "FRESH"))
        emit("   上面这两个 +1 是**同一道闸**（臂体检那一行），不是两道；与 ① 那个翻转数也不是同一批闸 —— 别相加。")

    # ---- 自检：这张表自己有没有牙 ----
    emit("== 4 · 自检：这张表不是恒 0，反面也不恒过 ==")
    n_after = sum(1 for r in rows_out if r["after"].startswith("NO-ARM"))
    emit("   正臂（该响的）：改后会发 NO-ARM %d 条 = 上面「没臂且没写理由」%d 条 ⇒ %s"
         % (n_after, zero, "对得上" if n_after == zero else "**对不上，这张表自己坏了**"))
    emit("   反臂（不该响的）：写了 NOT_MEASURABLE 的 %d 条里，改后仍进 bad 0 条 ⇒ 守卫没把它们算成缺陷（该 0，实测 %d）"
         % (sum(1 for r in rows_out if r["not_measurable"]),
            sum(1 for r in rows_out if r["not_measurable"] and r["after"].startswith("NO-ARM"))))
    emit("   恒 0 检查：这一列的最小值 = %s（不是空集算出来的 0，是真的量到每根针各有几根臂）"
         % (min([r["arms_now"] for r in rows_out]) if rows_out else "没有针"))
    emit("   现数臂咬 =0 的针有几条：%d" % sum(1 for r in rows_out if r["arms_now"] == 0))
    if zero == 0:
        emit("   !! 正臂这一趟**没有现场**：这批数据里每根针都至少有一根咬住的臂 ⇒ 翻转数只能是 0，"
             "所以这张表今天只回答「开关关掉会不会多红」（不会），**不回答**「关掉之后 NO-ARM 会不会红」—— "
             "那一半要等哪天真出现一根没臂的针才算量过。别把 0 读成这条判据有牙。")

    emit("== 5 · 这一件交什么、不交什么 ==")
    emit("   交：上面这些只算出来的数（两个口径并排、逐针点名、覆盖面自量）。")
    emit("   不交：不改 验收-事件层-1022.py / 体检-全闸-1023.py 的任何退出码语义 —— 那要作者圈。")
    emit("   不跑 go：所以这张表的 tests 数是按源码扫的；与「刚重跑一遍验收」的数不同源，不同源就明写不同源。")

    w = io.open(PART, "w", encoding="utf-8", newline="\n")
    for l in lines:
        w.write(l + "\n")
    w.close()
    os.replace(PART, OUT)
    got = read(OUT)
    n = len(got.splitlines()) if got else -1
    ok = n == len(lines)
    say("landing check: %s %d/%d rows ｜ %d pin rows ｜ %s"
        % ("OK" if ok else "MISMATCH", n, len(lines), len(rows_out), os.path.basename(OUT)))
    for l in lines:
        say(l)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        say("ABORT-BEFORE-LAND %r ｜ 正式名未动" % (exc,))
        raise SystemExit(1)
    raise SystemExit(code)
