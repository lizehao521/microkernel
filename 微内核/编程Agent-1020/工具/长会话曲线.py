# 长会话曲线：量"同一发一路点下去会不会变坏"，不是"单发能不能跑通"。
# 用法：python 工具/长会话曲线.py <pid> <端口> <发数> [读数落点]
#   pid 是必需项：RSS 只能从进程身上取，调用方先起服务再把 pid 交进来。
# 纪律：所有数现量现印；量不到的记 None 并在 SUMMARY 里点名，绝不写 0。
# 控制台是 GBK，print 里不许出现 ✓ / ⇒ 这类会崩的字符。

import io
import json
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request

def rss_bytes(pid):
    # 用 PowerShell 现取 WorkingSet64；拿不到就返回 None（不返回 0）。
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Id %d).WorkingSet64" % int(pid)],
            capture_output=True, timeout=20)
        s = out.stdout.decode("utf-8", "replace").strip()
        v = int("".join(ch for ch in s if ch.isdigit()))
        return v if v > 0 else None
    except Exception:
        return None

def one_turn(port, idx, code, question):
    body = json.dumps({"session": "长会话曲线", "code": code,
                       "question": question, "lang": "auto", "stack": ""}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d/api/turn" % port, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    steps, frames, result, decl_fail, chain = [], 0, None, 0, None
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r:
            ln = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not ln.startswith("data: "):
                continue
            frames += 1
            obj = json.loads(ln[6:])
            if "step" in obj:
                steps.append(obj["step"])
                txt = (obj.get("out") or "") + " " + (obj.get("name") or "")
                if "没落账" in txt:
                    decl_fail += 1
                if "链上共" in txt:
                    digits = "".join(ch for ch in txt.split("链上共")[-1] if ch.isdigit())
                    if digits:
                        chain = int(digits)
            elif "findings" in obj or "provenance_mix" in obj:
                result = obj
    return {"turn": idx, "ms": round((time.time() - t0) * 1000), "frames": frames,
            "steps": len(steps), "step_names_ok": steps == list(range(1, len(steps) + 1)),
            "decl_fail_lines": decl_fail, "chain_entries": chain,
            "mix": (result or {}).get("provenance_mix"),
            "mix_ok": (result or {}).get("mix_identity_ok"),
            "kpi": (result or {}).get("kpi_ledger_decided"),
            "findings": len((result or {}).get("findings") or [])}

def main():
    if len(sys.argv) < 4:
        print("用法：python 工具/长会话曲线.py <pid> <端口> <发数> [读数落点]")
        return 2
    pid, port, n = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    out_path = sys.argv[4] if len(sys.argv) > 4 else "读数/W26-浏览器-长会话资源曲线.json"

    samples_every = max(1, n // 5)
    turns, rss_curve = [], []
    for i in range(1, n + 1):
        # 代码逐发变长：让"往轮负载"是真的在涨，不是同一发重复 50 次
        code = "def f%d(x):\n" % i + "".join("    y%d = x + %d\n" % (k, k) for k in range(i % 12))
        rec = one_turn(port, i, code, "长会话第 %d 发" % i)
        turns.append(rec)
        if i % samples_every == 0 or i == n or i == 1:
            rb = rss_bytes(pid)
            rss_curve.append({"turn": i, "rss_bytes": rb})
            print("turn=%d ms=%d frames=%d chain=%s decl_fail=%s rss=%s" %
                  (i, rec["ms"], rec["frames"], rec["chain_entries"], rec["decl_fail_lines"],
                   rb if rb is None else round(rb / 1048576.0, 2)))

    hist_url = "http://127.0.0.1:%d/api/history?session=%s" % (port, urllib.parse.quote("长会话曲线"))
    t0 = time.time()
    with urllib.request.urlopen(hist_url, timeout=30) as r:
        hb = r.read()
    hist = json.loads(hb.decode("utf-8"))
    hist_ms = round((time.time() - t0) * 1000)

    bad = []
    for rec in turns:
        if rec["steps"] < 13:
            bad.append("turn %d 步数=%d（不足 13）" % (rec["turn"], rec["steps"]))
        if not rec["step_names_ok"]:
            bad.append("turn %d 步号不递增" % rec["turn"])
        if rec["mix_ok"] is not True:
            bad.append("turn %d 五档恒等式没成立" % rec["turn"])
    if hist.get("count") != n:
        bad.append("history count=%r 与发的次数 %d 对不上" % (hist.get("count"), n))
    firsts = [t["decl_fail_lines"] for t in turns]
    if firsts[0] > 0:
        bad.append("第 1 发就出现读者声明没落账 %d 行（W10 的修法漂了）" % firsts[0])
    if any(x > 0 for x in firsts[1:]):
        bad.append("后面某发又出现没落账：%s" % [i + 1 for i, x in enumerate(firsts) if x > 0])
    if len(turns) > 4:
        head = statistics.median([t["ms"] for t in turns[:5]])
        tail = statistics.median([t["ms"] for t in turns[-5:]])
        if tail > head * 3 + 200:
            bad.append("末段每发中位耗时 %sms 是首段 %sms 的 %.1f 倍：会话变长在拖慢这一发" %
                       (round(tail), round(head), tail / max(head, 1)))
    else:
        head = tail = None

    rs0 = rss_curve[0]["rss_bytes"]
    rsN = rss_curve[-1]["rss_bytes"]
    per_turn_kb = round((rsN - rs0) / 1024.0 / (n - 1), 1) if (rs0 and rsN and n > 1) else None

    summary = {"发数": n, "pid": pid, "端口": port,
               "每发耗时ms_首段中位": head, "每发耗时ms_末段中位": tail,
               "每发耗时ms_全部": [t["ms"] for t in turns],
               "帧数_全部相等": len(set(t["frames"] for t in turns)) == 1,
               "帧数": turns[0]["frames"],
               "链上条数_首末": [turns[0]["chain_entries"], turns[-1]["chain_entries"]],
               "读者声明没落账行数_逐发": firsts,
               "RSS曲线MB": [{"turn": s["turn"], "MB": (round(s["rss_bytes"] / 1048576.0, 2)
                                                    if s["rss_bytes"] else None)} for s in rss_curve],
               "每发RSS增量KB": per_turn_kb,
               "history_bytes": len(hb), "history_count": hist.get("count"),
               "history_ms": hist_ms,
               "五档_末发": turns[-1]["mix"], "KPI_逐发": [t["kpi"] for t in turns],
               "不达标": bad}
    with io.open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"件": "W26 长会话资源曲线（服务端侧；界面侧另量）", "口径": summary,
                   "逐发": turns}, f, ensure_ascii=False, indent=1)
    print("SUMMARY turns=%d bad=%d frames_uniform=%s chain_first=%s chain_last=%s "
          "decl_fail_total=%d rss_start_mb=%s rss_end_mb=%s per_turn_kb=%s hist_bytes=%d hist_count=%s" %
          (n, len(bad), summary["帧数_全部相等"], turns[0]["chain_entries"], turns[-1]["chain_entries"],
           sum(firsts),
           "None" if not rs0 else round(rs0 / 1048576.0, 2),
           "None" if not rsN else round(rsN / 1048576.0, 2),
           "None" if per_turn_kb is None else per_turn_kb,
           len(hb), hist.get("count")))
    for b in bad:
        print("  不达标: " + b)
    print("写了 " + out_path)
    return 1 if bad else 0

if __name__ == "__main__":
    import urllib.parse
    sys.exit(main())
