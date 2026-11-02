#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4 + 路 A/B 撞车那条 P0 的真二进制核对（临时件，跑完就把读数落进 读数/）。

三件事，都用**建好的 exe**（go run 会把两读塌成一读）：
  1) 同一对落点连跑三趟 → 这本日志是跨趟合并的 → 走 -check-log：四支判据必须全绿（P0 复发就红）；
  2) -events-serve 起在跑的过程中：抓 stderr 那行地址 → 连打两次同一个游标 → 序列必须逐条相同；
  3) 判据红的那一头也要有现场：拿一本坏日志（把某发的 counts 改翻倍）→ -check-log 必须 RED 且 rc=4。

用法：C:/Users/Admin/sdk/py314/python.exe E4真负载核对.py
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

GO = r"C:/Users/Admin/sdk/go/bin/go.exe"
ROOT = os.environ.get("AGENTD_TREE") or r"C:/Users/Admin/Desktop/微内核/微内核/微内核"  # 默认跑推广后的真树
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数", "E4真负载.jsonl")
RE_ADDR = re.compile(r"http://([\d\.]+:\d+)/events")

rows = []


def emit(step, ok, **kw):
    d = {"step": step, "ok": bool(ok), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d.update(kw)
    rows.append(d)
    print("%s %s | %s" % ("PASS" if ok else "FAIL", step,
                          " ".join("%s=%s" % (k, v) for k, v in kw.items() if not isinstance(v, (list, dict)))))
    return bool(ok)


def run_exe(exe, *args, **kw):
    cwd = kw.pop("cwd", ROOT)
    r = subprocess.run([exe] + list(args), cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=kw.pop("timeout", 180))
    return r.returncode, r.stdout, r.stderr


def main():
    work = tempfile.mkdtemp(prefix="E4真负载-")
    exe = os.path.join(work, "agentd.exe")
    t0 = time.time()
    b = subprocess.run([GO, "build", "-o", exe, "./cmd/agentd"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if b.returncode != 0:
        print("BUILD-FAIL", b.stdout, b.stderr)
        return 4
    h = hashlib.sha256(open(exe, "rb").read()).hexdigest()[:12]
    emit("S0 exe 现建（判的是这一份，不是 go run）", True, sha256_12=h, build_s=round(time.time() - t0, 1))

    log = os.path.join(work, "x3.events.jsonl")
    jrn = os.path.join(work, "x3.jsonl")
    rcs = []
    for i in range(3):
        rc, so, se = run_exe(exe, "-script", "happy", "-max-turns", "20",
                             "-journal-out", jrn, "-events-out", log, "-trace-out", "")
        rcs.append(rc)
    n_lines = sum(1 for _ in open(log, encoding="utf-8"))
    emit("S9 同一对落点连跑三趟", all(rc == 0 for rc in rcs), 退出码=rcs, 事件条数=n_lines)

    # 1) 跨趟合并日志走 -check-log。两次判读，各答各的问题：
    #    · 宽松上限：答「结构对不对」（第一条是回执、序号接续、counts 与账对得上、尾游标接得上）—— 闸吃这一条；
    #    · 契约预算 100ms：答「宿主承认收到它有多慢」—— 这是**发现**，不是闸。
    #    两次的读数都印出来，谁也不许冒充谁（M2 路 A 的 P1-⑤、路 B 的 P1-①②同一件事）。
    rc, so, se = run_exe(exe, "-check-log", log, "-ack-limit-ms", "60000")
    lines = [l.split("\t") for l in so.splitlines() if l.startswith("check-log")]
    verdicts = {l[1]: l[3] for l in lines if len(l) >= 4}
    oks = [k for k, v in verdicts.items() if v == "GREEN"]
    reds = [k for k, v in verdicts.items() if v == "RED"]
    why = " ".join(l[4] for l in lines if len(l) >= 5 and l[3] == "RED")[:200]
    口径 = [l for l in lines if l[1] == "口径"]
    rc9, so9, _ = run_exe(exe, "-check-log", log, "-ack-limit-ms", "100")
    red9 = [l.split("	") for l in so9.splitlines() if len(l.split("	")) >= 4 and l.split("	")[3] == "RED"]
    maxack = max([e.get("accept", {}).get("ack_ms") or 0 for e in
                  [json.loads(l) for l in open(log, encoding="utf-8") if l.strip()]
                  if e.get("kind") == "turn_accepted"] or [0])
    emit("S10 跨趟日志结构判据全绿（路 A/B 的 P0 现场）",
         rc == 0 and not reds and len(oks) == 4,
         判据数=len(verdicts), 绿=len(oks), 红=len(reds), rc=rc, 红的读数=why,
         口径=(口径[0][2] if len(口径) > 0 else "没印"),
         契约预算100下的红=[l[1] for l in red9], 最大ack_ms=maxack, rc预算100=rc9)

    # 2) 逐发对账：结算里那份 counts 必须等于这一发（session+run+turn）自己的条数
    evs = [json.loads(l) for l in open(log, encoding="utf-8") if l.strip()]
    actual, settled = {}, {}
    for e in evs:
        k = (e.get("session"), e.get("run"), e.get("turn"))
        if e.get("settle"):
            settled[k] = e["settle"].get("counts", {})
        elif e.get("kind") not in ("run_started", "run_settled", "turn_settled", "turn_interrupted"):
            actual.setdefault(k, {})
            actual[k][e.get("state")] = actual[k].get(e.get("state"), 0) + 1
    mismatch = []
    for k, want in actual.items():
        got = settled.get(k, {})
        if any(got.get(s, 0) != n for s, n in want.items()) or any(want.get(s, 0) != n for s, n in got.items()):
            mismatch.append("%s/%s#%s got=%s want=%s" % (k[0], (k[1] or "")[-6:], k[2], got, want))
    emit("S11 counts 逐块与账对得上（独立复算，不套 Go 的口径）",
         not mismatch and len(settled) >= 12, 有结算的发=len(settled), 对不上的=mismatch[:4])

    # 3) 坏日志那一头：把 counts 翻倍 → -check-log 必须 RED 且 rc=4
    bad = os.path.join(work, "bad.events.jsonl")
    with open(bad, "w", encoding="utf-8", newline="\n") as f:
        for e in evs:
            if e.get("settle"):
                e = dict(e)
                e["settle"] = dict(e["settle"])
                e["settle"]["counts"] = {k: v * 2 for k, v in e["settle"].get("counts", {}).items()}
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rc2, so2, _ = run_exe(exe, "-check-log", bad)
    red2 = [l.split("\t") for l in so2.splitlines() if "\tRED\t" in l]
    emit("S12 谎报 counts 的日志必须 RED（这条命令会红）",
         rc2 == 4 and len(red2) > 0 and any("Settlement" in l[1] for l in red2),
         rc=rc2, 红的支数=len(red2), 第一句=(red2[0][4][:120] if red2 else ""))

    # 4) 跑的过程中起投送层：连打两次同一游标，序列必须逐条相同
    proc = subprocess.Popen([exe, "-script", "happy", "-max-turns", "20", "-shot-delay", "600ms",
                             "-journal-out", os.path.join(work, "sse.jsonl"),
                             "-events-out", os.path.join(work, "sse.events.jsonl"),
                             "-events-serve", "-trace-out", ""],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    addr = None
    deadline = time.time() + 25
    serr = []
    while time.time() < deadline and addr is None:
        line = proc.stderr.readline()
        if not line:
            break
        serr.append(line.rstrip())
        m = RE_ADDR.search(line)
        if m:
            addr = m.group(1)
    if not addr:
        emit("S13 跑的过程中投送层起得来", False, stderr尾部=serr[-3:])
        proc.kill()
    else:
        time.sleep(1.2)  # 让日志先落几条
        cur = None
        base = "http://%s/events" % addr
        with urllib.request.urlopen(base, timeout=5) as r:
            first_body = r.read().decode("utf-8", "replace")
        ids1 = [l[4:] for l in first_body.splitlines() if l.startswith("id: ")]
        cur = ids1[len(ids1) // 2] if ids1 else None
        # 跑的过程中只断一件事：**读得到东西**（首连非空、游标带 run 轴）。
        # 两次重放是否同序列，不能在进程还在追加的时候比 —— 上一版就这么错的：
        # 尾巴一直在长，i2 与 i3 天然不等，量的是我这把尺子的时机，不是投送层的性质。
        seg = [x.split(":") for x in ids1]
        four = all(len(x) == 4 for x in seg)
        emit("S13a 跑的过程中读得到、游标带 run 轴", len(ids1) > 0 and four,
             地址=addr, 首连条数=len(ids1), 游标段数=max(len(x) for x in seg), 游标=cur)
        # 坏游标那一头也当场验（投送层还活着）
        try:
            urllib.request.urlopen(urllib.request.Request(base, headers={"Last-Event-ID": "junk-not-a-cursor"}), timeout=5)
            code = 200
        except Exception as ex:
            code = getattr(ex, "code", 0)
        emit("S14 坏游标给 409（不当首连重播整本）", code == 409, http_code=code, 异常=repr(ex) if code != 409 else "")
        killed_log = os.path.join(work, "sse.events.jsonl")
        base2, cur2 = base, cur
        assert cur2, "游标没定出来 —— 后面几步不作数"
        proc.kill()
        proc.wait(timeout=20)
        # 「同一游标重放两次同序列」这一条在真进程上**测不了**，记 NOT_MEASURABLE：
        # 投送层的生命周期绑在这一趟进程上 —— 进程活着日志就一直在长（两次读天然不等），
        # 进程一停 socket 就没了（没有服务端可读）。这条性质的正确测法是封板日志 + HTTP：
        # 由 events_sse_test.go 的 TestReplayTwiceGivesSameSequence 钉（Go 侧已跑）。
        # 架构后果要作者拍：界面（E7）要断线重连，投送层就得在收口之后继续活着。
        emit("S13b 停笔后重放两次同序列", False,
             状态="NOT_MEASURABLE", 为什么="投送层随进程生死：进程在时日志还在长，进程停时端口已关"
             "；这条性质由 events_sse_test.go 的 TestReplayTwiceGivesSameSequence 在封板日志上钉")
        rcx, _, _ = run_exe(exe, "-script", "happy", "-max-turns", "20", "-journal-out", os.path.join(work, "done.jsonl"),
                            "-events-out", os.path.join(work, "done.events.jsonl"), "-trace-out", "")
        rc3, so3, _ = run_exe(exe, "-check-log", os.path.join(work, "done.events.jsonl"))
        green3 = sum(1 for l in so3.splitlines() if chr(9) + "GREEN" + chr(9) in l)
        emit("S15 自然跑完的一趟 -check-log 四支全绿", rcx == 0 and rc3 == 0 and green3 == 4, 跑完rc=rcx, rc=rc3, 绿的支数=green3)
        rc4, so4, _ = run_exe(exe, "-check-log", killed_log)
        red4 = [l.split(chr(9)) for l in so4.splitlines() if chr(9) + "RED" + chr(9) in l]
        # 「点名半结算」这句话术在本轮被拆成了两支（同一性质、两种说法）：
        #   events.go:179  开了账（有 run_started）却没有 run_settled —— 收口没走完/被半路杀掉
        #   events.go:194  那一发有 N 条事件却没有结算 —— 半结算
        # -check-log 每支只印它自己第一条错，所以同一本被杀的账上先撞哪一支取决于杀在第几步。
        # 判据盯的是「有没有一支把没收口点出来」，两支话术任一即算；别的红（如预算超）不算点名。
        def _names(t):
            return t[1] if len(t) > 1 else "?"

        def _msg(t):
            return t[4] if len(t) > 4 else ""

        hit = next((t for t in red4
                    if "却没有结算" in _msg(t)
                    or ("却没有 run_settled" in _msg(t) and "开了账" in _msg(t))), None)
        emit("S16 半路被杀的日志必须 RED 且点名半结算（新牙在真二进制上响）", rc4 == 4 and hit is not None,
             rc=rc4, 红的支数=len(red4), 红的支名=",".join(_names(t) for t in red4) or "-",
             点名的支=(_names(hit) if hit else "没有一支点名没收口"),
             走的话术=("半结算(194)" if hit is not None and "却没有结算" in _msg(hit)
                       else "开了账无run_settled(179)" if hit else "-"),
             第一句=(_msg(red4[0])[:110] if red4 else "没有红"))
        # 反臂（叶子）：把上面那段点名逻辑打在**自然跑完**的那本账上 —— 那里没有没收口的红，
        # 若这条也"点名成功"，说明判据松到什么都算，S16 的绿不作数。
        hit0 = next((t for t in (l.split(chr(9)) for l in so3.splitlines() if chr(9) + "RED" + chr(9) in l)
                     if "却没有结算" in _msg(t)
                     or ("却没有 run_settled" in _msg(t) and "开了账" in _msg(t))), None)
        emit("S16b 反臂：同一套点名逻辑打在跑完的账上必须不响（响=S16 松到什么都算）", hit0 is None,
             对照那本的红支数=len([1 for l in so3.splitlines() if chr(9) + "RED" + chr(9) in l]),
             居然点名了=(_names(hit0) if hit0 else "无"))

    # 「读数 <路径>」这句话以前只是宣称：件里从头到尾没往 OUT 写过一行，
    # 盘上那份是旧版件的化石（里面还有一条本轮代码里已经不存在的行名）。
    # 现在先落盘，再**从落盘那份**数 —— 上屏的数和文件内容同源，不许一个在内存一个在盘上。
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    part = OUT + ".part"
    with open(part, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(part, OUT)
    with open(OUT, encoding="utf-8") as f:
        on_disk = [json.loads(l) for l in f if l.strip()]
    landed = len(on_disk) == len(rows)
    nm = sum(1 for r in on_disk if str(r.get("状态", "")).startswith("NOT_"))
    bad_n = sum(1 for r in on_disk if not r["ok"]) - nm
    print("steps %d | passed %d | failed %d | 未测 %d | 读数 %s"
          % (len(on_disk), len(on_disk) - bad_n - nm, bad_n, nm, OUT))
    print("landing check: %s (%d/%d rows, %d bytes)"
          % ("OK" if landed else "MISMATCH", len(on_disk), len(rows), os.path.getsize(OUT)))
    return 0 if (bad_n == 0 and landed) else 3


if __name__ == "__main__":
    sys.exit(main())
