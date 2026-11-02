# 跨进程那一发：同一本会话文件换一次进程，哪些数必须继续对、哪些数必须重来。
# 用法：python 工具/跨进程那一发.py <exe 路径>
# 为什么单独一件：闸 6 量的是"同一颗进程连发不劣化"，这一件量的是"进程换了之后身份与账本还对不对"。
# 两件事的形状不同 —— 上一轮实测过：换进程后发号会重新从 1 起（把两个身份写进同一本文件），
# 而内核账必须从 49 重来（它是进程内的）。一个要接续、一个要归零，混了就说明没人盯着。
# 纪律：只起 127.0.0.1 的随机空闲端口，绝不碰 8797/8799；数据目录在 TEMP，跑完删；数字现印。

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "TEMP-跨进程")
SESSION = "跨进程那一本"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    assert p not in (8797, 8799), "那两本是内核研究账"
    return p


def start(exe, port, data, extra=None):
    args = [exe, "-port", str(port), "-data", data] + (extra or [])
    p = subprocess.Popen(args, cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1).read()
            return p, base
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("服务 %d 秒没起来" % port)


def turn(base, code, question):
    """跑一发，收回：发号、第 ⑩ 步那两个数、五档恒等、KPI。"""
    body = json.dumps({"session": SESSION, "code": code, "question": question,
                       "lang": "go", "stack": ""}).encode("utf-8")
    req = urllib.request.Request(base + "/api/turn", data=body,
                                 headers={"Content-Type": "application/json"})
    no = None
    tally = ""
    mix_ok = None
    kpi = None
    steps = 0
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r:
            ln = raw.decode("utf-8", "replace").strip()
            if not ln.startswith("data: "):
                continue
            o = json.loads(ln[6:])
            if "findings" in o:
                mix_ok = o.get("mix_identity_ok")
                kpi = o.get("kpi_ledger_decided")
            elif o.get("name") == "kernel.tally":
                tally = o.get("out") or ""
                steps += 1
            elif "turn" in o and "session" in o and "name" not in o and "step" not in o:
                no = o["turn"]
    m = re.search(r"账 (\d+) 条", tally)
    chain = int(m.group(1)) if m else None
    s = re.search(r"本进程至今落了 (\d+) 发", tally)
    landed = int(s.group(1)) if s else None
    c = re.search(r"这一本会话文件此前有 (\d+) 发", tally)
    prior = int(c.group(1)) if c else None
    if "此前没有往轮" in tally:
        prior = 0
    return {"question": question, "turn": no, "chain": chain, "landed": landed, "prior": prior,
            "mix_ok": mix_ok, "kpi": kpi, "tally_len": len(tally)}


def hist_count(base):
    with urllib.request.urlopen(base + "/api/history?session=" + urllib.parse.quote(SESSION), timeout=20) as r:
        return json.loads(r.read().decode("utf-8")).get("count")


def main():
    if len(sys.argv) < 2:
        print("用法：python 工具/跨进程那一发.py <exe 路径>")
        return 2
    exe = sys.argv[1]
    if not os.path.isfile(exe):
        print("SUMMARY procs=0 turns=0 dup=0 chain_b_first=0 hist=0 scope_ok=0 bad=1 temp_left=0")
        print("  不达标: exe 不在（%s）⇒ 这一件没跑成，不算过" % exe)
        return 1
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    data = os.path.join(WORK, "数据")
    code = ("package main\n\nimport (\n\t\"fmt\"\n\t\"os\"\n)\n\n"
            "func load(p string) string {\n\tdata, _ := os.ReadFile(p)\n\tseed := len(data)\n"
            "\tseed := seed + 1\n\tif seed > 0 {\n\t\tfmt.Print(seed)\n\t}\n\treturn string(data)\n}\n\n"
            "func helper() int { return 1 }\n\nfunc helper() int { return 2 }\n")
    got = []
    bad = []
    alive = []
    procs = 0
    try:
        # 进程 A：两发
        pa, base_a = start(exe, free_port(), data)
        procs += 1
        alive.append(pa)
        for i in (1, 2):
            got.append(dict(proc="A", **turn(base_a, code, "A 第 %d 发" % i)))
        pa.terminate()
        pa.wait(timeout=10)
        # 进程 B：同一本数据目录，再两发
        pb, base_b = start(exe, free_port(), data)
        procs += 1
        alive.append(pb)
        for i in (1, 2):
            got.append(dict(proc="B", **turn(base_b, code, "B 第 %d 发" % i)))
        hc = hist_count(base_b)
        pb.terminate()
        pb.wait(timeout=10)
    except Exception as e:
        bad.append("跑的过程中出错：%r" % e)
        hc = None
    finally:
        for pr in alive:            # 只收自己起的进程；已经 terminate 过的不再碰
            if pr.poll() is None:
                pr.terminate()
                try:
                    pr.wait(timeout=10)
                except Exception:
                    pr.kill()
        shutil.rmtree(WORK, ignore_errors=True)

    号 = [g["turn"] for g in got]
    dup = len(号) - len(set(号))
    if dup:
        bad.append("发号在同一本会话文件里撞车：%s（dup=%d）⇒ 两个身份写进了同一本账" % (号, dup))
    if 号 and 号 != sorted(号):
        bad.append("发号不递增：%s" % 号)
    b1 = next((g for g in got if g["proc"] == "B"), None)
    a2 = [g for g in got if g["proc"] == "A"][-1] if any(g["proc"] == "A" for g in got) else None
    if b1 is None or b1["chain"] != 49:
        bad.append("换进程后内核账没从 49 重来（B 第一发链上=%s，要 49）⇒ 那是进程内的账，不许接着上一程数"
                   % (b1 and b1["chain"]))
    if a2 is not None and a2["chain"] != 98:
        bad.append("A 第二发链上=%s（要 98）⇒ 每发正好 49 条这条断了" % a2["chain"])
    if b1 is not None and b1["prior"] != 2:
        bad.append("B 第一发的口径句没把'此前有 2 发'带过来（读到 %s）⇒ 跨进程那半句话在骗人" % (b1 and b1["prior"]))
    if b1 is not None and b1["landed"] != 1:
        bad.append("B 第一发报'本进程至今落了 %s 发'（要 1）⇒ 进程内计数没归零" % b1["landed"])
    if hc != len(got) or hc != 4:
        bad.append("会话文件行数=%s（要 4，两程之和）⇒ 换进程把往轮弄丢了" % hc)
    for g in got:
        if g["mix_ok"] is not True:
            bad.append("%s 那一发五档恒等式没成立" % g["question"])
        if not g["kpi"]:
            bad.append("%s 那一发 KPI=0（接缝装着、读回也开着）" % g["question"])

    scope_ok = 1 if (b1 and b1["prior"] == 2 and b1["landed"] == 1) else 0
    print("逐发读数：")
    for g in got:
        print("  %s %s：发号=%s 链上=%s 本进程落了=%s 此前有=%s 恒等=%s KPI=%s" %
              (g["proc"], g["question"], g["turn"], g["chain"], g["landed"], g["prior"], g["mix_ok"], g["kpi"]))
    for b in bad:
        print("  不达标: " + b)
    print("SUMMARY procs=%d turns=%d dup=%d chain_b_first=%s hist=%s scope_ok=%d bad=%d temp_left=%d" %
          (procs, len(got), dup, b1 and b1["chain"], hc, scope_ok, len(bad), 1 if os.path.isdir(WORK) else 0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
