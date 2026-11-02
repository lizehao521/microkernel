#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""边界那一发：把目标里"交互流畅 + 五档不许塌 + absent 必带理由"这两句，拿十种边界输入去量。

    python 工具/边界那一发.py [go.exe 路径]

为什么要有它：验收跑到 W13 为止，端到端那一发用的都是**形状正常**的输入（一段脏 Go、一句问题）。
可"贴进来的东西"不是只有这一形：空的、只有空白的、200KB 的、非法 UTF-8 的、语言填 ruby 的、
一行五万字的。这些形状下服务要么给结论、要么**明说给不了** —— 中间那种"默默少一半还署 measured"
才是目标禁的事。这条脚本只读地打这些发，把每种形状的读数写进 `读数/W14-边界那一发.json`。

它起在 127.0.0.1 的随机空闲端口（三台：默认 / 带 `-step-delay` 的慢服务 / 带 `-entry-cap 49` 的账满服务），
**绝不碰 8797/8799**；数据目录在 TEMP，跑完删。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "pgagent")
GO = sys.argv[1] if len(sys.argv) > 1 else "go"
WORK = os.path.join(ROOT, "TEMP-边界")
OUT = os.path.join(ROOT, "读数", "W14-边界那一发.json")

DIRTY = ("package main\n\nimport (\n\t\"fmt\"\n\t\"os\"\n)\n\nfunc load(p string) string {\n"
         "\tdata, _ := os.ReadFile(p)\n\tseed := len(data)\n\tseed := seed + 1\n"
         "\tif seed > 0 {\n\t\tfmt.Print(seed)\n\t}\n\treturn string(data)\n}\n")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sse_turn(base, body, timeout=60):
    """POST /api/turn 收 SSE；返回 (状态码, 步名, 结果对象或 None, 帧数, 毫秒, 错误文本)。"""
    req = urllib.request.Request(base + "/api/turn",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    steps, result, frames = [], None, 0
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = b""
            while True:
                chunk = r.read1(4096) if hasattr(r, "read1") else r.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    frames += 1
                    ev, data = "message", ""
                    for ln in raw.decode("utf-8", "replace").splitlines():
                        if ln.startswith("event: "):
                            ev = ln[7:].strip()
                        elif ln.startswith("data: "):
                            data += ln[6:]
                    if not data:
                        continue
                    obj = json.loads(data)
                    if ev == "step":
                        # 步名与 ran 不够用：W32 要审的是那**一句话**本身（第⑥步说"预检就拒了"、
                        # 第⑦步"没读回："后面是空的）—— 只留计数就会把发现留在内存里。
                        # basis 也得留着：W38 要判的是"第 ⑨ 步真跑了且署 measured"，
                        # 只留 ran 就分不开"跑了"与"跑了但档位写错"。
                        steps.append({"name": obj.get("name"), "ran": obj.get("ran"),
                                      "basis": obj.get("basis"), "out": obj.get("out")})
                    elif ev == "result":
                        result = obj
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace").strip()
        return e.code, steps, result, frames, int((time.time() - t0) * 1000), txt
    except Exception as e:
        return -1, steps, result, frames, int((time.time() - t0) * 1000), repr(e)
    return 200, steps, result, frames, int((time.time() - t0) * 1000), ""


def brief(status, steps, result, frames, ms, err):
    mix = (result or {}).get("provenance_mix") or {}
    # 名字也要落件：第一版只落了"步=10"这种计数，结果"少了哪三步"这一问要重跑一遍才知道
    # —— 计数不带对象，等于把发现留在内存里（读数要能自证）。
    return {"步名": ["%s%s" % (("" if x["ran"] else "×"), x["name"]) for x in steps],
            "未决原话": [(u.get("what") if isinstance(u, dict) else str(u))
                       for u in ((result or {}).get("unknowns") or [])][:4],
        "http": status,
        "帧数": frames,
        "毫秒": ms,
        "亮出的步": len(steps),
        "五档恒等": (result or {}).get("mix_identity_ok"),
        "五档": {k: mix.get(k) for k in ("measured", "estimated", "model_says", "relayed", "absent", "total")},
        "KPI": (result or {}).get("kpi_ledger_decided"),
        # 检索键以打印件为准：Result 的 JSON 名是 stop_reason（我第一版写 end_reason ⇒ 这一栏一路是 None，
        # 判据没用它所以没造成假绿，但"读数里那一栏是空的"这件事本身就该修）。
        "结束": (result or {}).get("stop_reason"),
        "未决条数": len((result or {}).get("unknowns") or []),
        "findings条数": len((result or {}).get("findings") or []),
        "错误文本": err[:220],
    }


def main():
    os.makedirs(WORK, exist_ok=True)
    rc = subprocess.run([GO, "build", "-o", os.path.join(WORK, "pgagent-边界.exe"), "."],
                        cwd=SRC, capture_output=True, text=True,
                        encoding="utf-8", errors="replace").returncode
    if rc != 0:
        print("编不出来 ⇒ 这一轮没跑")
        return 1
    exe = os.path.join(WORK, "pgagent-边界.exe")
    port = free_port()
    assert port not in (8797, 8799)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen([exe, "-port", str(port), "-data", os.path.join(WORK, "数据"), "-fake-endpoint"],
                           cwd=SRC, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    cases, problems = [], []
    假期望被判红 = False   # 先初始化：中途抛异常时下面那句"判据有牙"不能读到半个值就当验过
    srv3 = None            # 同上：账满那台的实例在 try 里才建，finally 不能读半个值就宣布"已经收干净"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)

        # 打断类的用例必须有一台"慢得下来"的服务：一圈只跑几十毫秒，点停永远赶不上。
        # 第一版就栽在这里 —— 并发那一发时好时坏（A 常常已经跑完），那不是产品的错，是我把竞态写进了考卷。
        # `-step-delay` 是应用自己提供的旋钮（main.go 里那句注释：0 = 中断只能靠程序自己造）。
        port2 = free_port()
        assert port2 not in (8797, 8799)
        srv2 = subprocess.Popen([exe, "-port", str(port2), "-data", os.path.join(WORK, "数据慢"),
                                 "-fake-endpoint", "-step-delay", "150ms"],
                                cwd=SRC, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base_slow = "http://127.0.0.1:%d" % port2
        for _ in range(60):
            try:
                urllib.request.urlopen(base_slow + "/api/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)

        # 部署侧那一形：这本账有**条数上限**（`-entry-cap`，0 = 不拦）。上面所有用例都跑在没设上限的实例上，
        # 所以"账吃不下了"这一形到现在一次没量过 —— 而它恰好是内核里唯一**不归判据表管**的那条拒绝路：
        # 门口按容量挡（mcpsrv 那句原话："这是外壳按部署方给的容量挡的，不是内核判据拒的"）。
        # 49 这个数字不是随手定的：一发恰好写 49 格 ⇒ 第一发装满、第二发必被挡，撞不撞得到全凭这个整除关系。
        port3 = free_port()
        assert port3 not in (8797, 8799)
        srv3 = subprocess.Popen([exe, "-port", str(port3), "-data", os.path.join(WORK, "数据满"),
                                 "-fake-endpoint", "-entry-cap", "49"],
                                cwd=SRC, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base_cap = "http://127.0.0.1:%d" % port3
        for _ in range(60):
            try:
                urllib.request.urlopen(base_cap + "/api/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)

        def add(名, 期望, body):
            # 期望 = (一句人话, 判据函数)。判据函数不进读数件 —— 第一发就栽在这里：
            # 把 lambda 塞进 dict 再 json.dump，直接在写件那一步崩掉，十个用例的读数全丢。
            文字, 判 = 期望
            st, steps, res, fr, ms, err = sse_turn(base, body)
            d = {"用例": 名, "期望": 文字}
            d.update(brief(st, steps, res, fr, ms, err))
            d["实际是否合期望"] = bool(判(d))
            if not d["实际是否合期望"]:
                problems.append(名)
            cases.append(d)
            print("%-26s http=%s 帧=%s 步=%s 恒等=%s KPI=%s 未决=%s err=%s" % (
                名, d["http"], fr, d["亮出的步"], d["五档恒等"], d["KPI"], d["未决条数"], d["错误文本"][:40]))

        OK200 = ("200 且五档恒等", lambda d: d["http"] == 200 and d["五档恒等"] is True)
        BAD400 = ("400 且带一句为什么", lambda d: d["http"] == 400 and d["错误文本"] != "")

        add("空代码", BAD400, {"session": "b1", "lang": "go", "code": "", "question": "这段有什么问题"})
        add("只有空白与换行", BAD400, {"session": "b2", "lang": "go", "code": "   \n\t\n  ", "question": "看看"})
        add("200KB 大粘贴", OK200, {"session": "b3", "lang": "go", "code": DIRTY + "// 填充\n" * 9000,
                                  "question": "这段有什么问题"})
        add("一行五万字无换行", OK200, {"session": "b4", "lang": "go", "code": "package main; var x = " + "1" * 50000,
                                       "question": "这段有什么问题"})
        add("非法 UTF-8 字节", OK200, json.loads('{"session":"b5","lang":"go","question":"这段有什么问题",'
                                                 '"code":"package main\\n// \\ud800 坏代理对\\nvar x = 1\\n"}'))
        add("语言填 ruby（没实现）", OK200, {"session": "b6", "lang": "ruby", "code": "def a\n  puts 1\nend\n",
                                           "question": "这段有什么问题"})
        add("lang 为空串", OK200, {"session": "b7", "lang": "", "code": DIRTY, "question": "这段有什么问题"})
        add("问题为空（只贴代码）", OK200, {"session": "b8", "lang": "go", "code": DIRTY, "question": ""})
        add("栈里没有行号", OK200, {"session": "b9", "lang": "go", "code": DIRTY, "stack": "panic: boom\n",
                                   "question": "为什么 panic"})

        # 并发两发 + 只停其中一发：停 A 不能把 B 一起带走（每发的中止是按 session+turn 点名的）。
        # 停的号写死 1：数据目录每次新建，两个 session 各自的第一发就是 turn=1（不是猜，是这件脚本自己的前提）。
        import threading
        box = {}

        def 跑(k, sess):
            st, steps, res, fr, ms, err = sse_turn(base_slow, {"session": sess, "lang": "go",
                                                          "code": DIRTY, "question": "这段有什么问题"})
            box[k] = {"http": st, "步": len(steps), "KPI": (res or {}).get("kpi_ledger_decided"),
                      "结束": (res or {}).get("stop_reason"), "帧": fr}

        th = [threading.Thread(target=跑, args=("A", "并发-A")), threading.Thread(target=跑, args=("B", "并发-B"))]
        for t in th:
            t.start()
        time.sleep(0.5)   # 慢服务每步 150ms ⇒ 这一发还在跑，停得下来
        try:
            with urllib.request.urlopen(base_slow + "/api/stop",
                                        data=json.dumps({"session": "并发-A", "turn": box.get("A", {}).get("turn", 1)}).encode(),
                                        timeout=10) as r:
                stopA = json.loads(r.read().decode())
        except Exception as e:
            stopA = {"异常": repr(e)}
        for t in th:
            t.join(timeout=60)
        a, b = box.get("A", {}), box.get("B", {})
        d = {"用例": "并发两发、只停 A", "期望": "A 被打断、B 跑完且 KPI>0", "A": a, "B": b, "停A的回话": stopA}
        d["实际是否合期望"] = bool(stopA.get("stopped") is True and a.get("结束") == "被打断"
                            and b.get("结束") == "跑完" and (b.get("KPI") or 0) >= 1
                            and a.get("步", 99) < 13)
        if not d["实际是否合期望"]:
            problems.append("并发两发、只停 A")
        cases.append(d)

        # 掐断连接（读两帧就把连接掐了）：服务端要**照样收口、照样落盘**，用 /api/history 复查
        req = urllib.request.Request(base_slow + "/api/turn",
                                     data=json.dumps({"session": "掐断", "lang": "go", "code": DIRTY,
                                                      "question": "这段有什么问题"}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        掐 = {"用例": "读两帧就掐断连接", "期望": "history 里这一发有收口（stop_reason 非空、五档恒等在）"}
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                got = 0
                while got < 2:
                    if r.readline():
                        got += 1
                    else:
                        break
            # with 退出即掐断
        except Exception as e:
            掐["异常"] = repr(e)
        time.sleep(0.4)
        try:
            with urllib.request.urlopen(base_slow + "/api/history?session=" + urllib.parse.quote("掐断"), timeout=10) as r:
                h = json.loads(r.read().decode())
        except Exception as e:
            h = {"异常": repr(e)}
        掐["history 回话"] = {"count": h.get("count"), "键": sorted(h.keys()),
                          "异常": h.get("异常", "")}   # 失败时读数要能自证为什么，别只留三个 null
        rec = (h.get("turns") or [{}])[-1] if h.get("turns") else {}
        # history 里的记录是**平铺**的（没有 result 这层），键名与 SSE 那份 Result 一致
        res = rec
        掐["history条数"] = h.get("count")
        掐["那一发的结束"] = res.get("stop_reason")
        掐["那一发的五档恒等"] = res.get("mix_identity_ok")
        掐["实际是否合期望"] = bool(掐.get("那一发的结束") and 掐.get("那一发的五档恒等") is True)
        if not 掐["实际是否合期望"]:
            problems.append("读两帧就掐断连接")
        cases.append(掐)

        add("超长问题（50KB）", OK200, {"session": "b11", "lang": "go", "code": DIRTY,
                                       "question": "这段有什么问题？" * 5000})
        add("只有栈没代码", BAD400, {"session": "b12", "lang": "go", "code": "   ", "question": "为什么 panic",
                                     "stack": "panic: boom\n\ngoroutine 1 [running]:\nmain.load(0x0)\n\t/x.go:6 +0x20\n"})
        add("二进制样子的字节", OK200, {"session": "b13", "lang": "go",
                                       "code": "package main\nvar b = []byte{0x00, 0xff, 0xfe}\n// \x01\x02\n",
                                       "question": "这段有什么问题"})

        s1, _, r1, _, _, _ = sse_turn(base, {"session": "b10", "lang": "go", "code": DIRTY, "question": "这段有什么问题"})
        s2, _, r2, _, _, _ = sse_turn(base, {"session": "b10", "lang": "go", "code": DIRTY, "question": "这段有什么问题"})
        d = {"用例": "同 session 连发两发", "期望": "两发都 200 且 turn 号不同", "一发": s1, "二发": s2,
             "一发turn": r1 and r1.get("turn"), "二发turn": r2 and r2.get("turn")}
        d["实际是否合期望"] = bool(s1 == 200 and s2 == 200 and d["一发turn"] != d["二发turn"])
        if not d["实际是否合期望"]:
            problems.append("同 session 连发两发")
        cases.append(d)

        # 停一发不存在的：不能谎报"停了"
        try:
            body = json.dumps({"session": "没有这个会话", "turn": 99}).encode()
            with urllib.request.urlopen(base + "/api/stop", data=body, timeout=10) as r:
                js = json.loads(r.read().decode())
        except Exception as e:
            js = {"异常": repr(e)}
        d = {"用例": "停一发不存在的", "期望": "stopped=false 且带那句解释", "读数": js,
             "实际是否合期望": js.get("stopped") is False and "note" in js}
        if not d["实际是否合期望"]:
            problems.append("停一发不存在的")
        cases.append(d)

        # GET /api/turn：不能当一发跑了
        try:
            with urllib.request.urlopen(base + "/api/turn", timeout=10) as r:
                code = r.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
        d = {"用例": "GET /api/turn", "期望": "405（不许当一发跑）", "http": code,
             "实际是否合期望": code == 405}
        if not d["实际是否合期望"]:
            problems.append("GET /api/turn")
        cases.append(d)

        # 账满那一形：同一 session 连打两发，第一发恰好把 49 格装满，第二发在门口被挡。
        # 这一形专门审的是**那两句话**：预检是过的、落账是被容量挡的 —— 页面要是把第⑥步说成
        # "没落账（预检就拒了）"，就是两码事说成一码事（⑤ 那步自己还亮着"预检过了"）；
        # 而第⑦步那句"没读回："后面要是空的，就是目标禁的那条：absent 没带理由。
        def 装满一发():
            st, steps, res, fr, ms, err = sse_turn(base_cap, {"session": "容量", "lang": "go",
                                                             "code": DIRTY, "question": "这段有什么问题"})
            by = {x["name"]: x for x in steps}

            def 话(n):
                return (by.get(n) or {}).get("out")

            return {"http": st, "帧": fr, "毫秒": ms, "发号": (res or {}).get("turn"),
                    "步名": ["%s%s" % (("" if x["ran"] else "×"), x["name"]) for x in steps],
                    "亮出的步": len(steps), "结束": (res or {}).get("stop_reason"),
                    "KPI": (res or {}).get("kpi_ledger_decided"),
                    "五档恒等": (res or {}).get("mix_identity_ok"),
                    "未决条数": len((res or {}).get("unknowns") or []),
                    "落账拒": (res or {}).get("ledger_reject"),
                    "预检跑": (by.get("kernel.check_call") or {}).get("ran"), "预检话": 话("kernel.check_call"),
                    "落账跑": (by.get("kernel.record_call") or {}).get("ran"), "落账话": 话("kernel.record_call"),
                    "读回跑": (by.get("kernel.read_back") or {}).get("ran"), "读回话": 话("kernel.read_back"),
                    "收口话": 话("kernel.tally"), "收口跑": (by.get("kernel.tally") or {}).get("ran"),
                    "收口档": (by.get("kernel.tally") or {}).get("basis"),
                    "未决名": [(u.get("what") if isinstance(u, dict) else str(u))
                            for u in ((res or {}).get("unknowns") or [])]}

        装1, 装2 = 装满一发(), 装满一发()
        牙 = [("第一发 200", 装1["http"] == 200),
              ("第一发落了账", 装1["落账跑"] is True),
              ("第一发 KPI≥1", (装1["KPI"] or 0) >= 1),
              ("第一发五档恒等", 装1["五档恒等"] is True),
              ("两发发号不同", 装1["发号"] != 装2["发号"]),
              ("第二发仍 200（这一发照样收口）", 装2["http"] == 200),
              ("第二发没落账", 装2["落账跑"] is False),
              ("第二发预检是过的", 装2["预检跑"] is True),
              ("第二发带那句为什么（已到上限）", "已到上限" in (装2["落账拒"] or "")),
              ("第二发 KPI 是量到的 0 不是没数", 装2["KPI"] == 0 and 装2["亮出的步"] > 0),
              ("第二发五档恒等不塌", 装2["五档恒等"] is True),
              ("第⑥步不许把门口挡说成预检拒", "预检就拒了" not in (装2["落账话"] or "")),
              ("第⑥步说的是门口挡这一形", "上限" in (装2["落账话"] or "")),
              ("第⑤步说的是内核预检那句原话（不替第⑥步领错）",
               "输入侧" in (装2["预检话"] or "") and "落账被拒" not in (装2["预检话"] or "")),
              ("落了账那一发的第⑥步带的是内核原话（不是我硬写的数）",
               "整发落账 49 条" in (装1["落账话"] or "") and "两侧共 49 格" not in (装1["落账话"] or "")),
              ("第⑥步说清这一台该敲哪个旗标（内核那句里是 -max-entries）",
               "-entry-cap" in (装2["落账话"] or "")),
              ("第⑦步那句带了理由（不是『没读回：』后面空着）",
               (装2["读回话"] or "").strip() not in ("", "没读回：")),
              # W38：第 ⑨ 步那三个是只读件，数的是那本账 —— 这一发没进账也该真打、打出内核原话。
              ("第⑨步在被挡那一发也真跑了（tally ran=true）", 装2["收口跑"] is True and 装2["收口档"] == "measured"),
              ("被挡那一发的第⑩步带的是内核五档原话（不是「没东西可印」）",
               "账 " in (装2["收口话"] or "") and "没东西可印" not in (装2["收口话"] or "")),
              ("收口既然跑了，未决里就不许再挂「收口读数拿不到」这条（假未决＝把已量说成欠账）",
               not any("收口读数" in str(u) for u in 装2["未决名"])),
              ("但『没落账』这件事仍然看得见：⑤跑⑥没跑、KPI 是量到的 0",
               装2["预检跑"] is True and 装2["落账跑"] is False and 装2["KPI"] == 0),
              ]
        合 = all(v for _, v in 牙)
        d = {"用例": "账满那一形（-entry-cap 49：第一发装满、第二发门口挡）",
             "期望": "两发都走满九步；第二发不落账、KPI 是量到的 0、第⑥⑦两句各说各的这一步且不咽原因、第⑨步照样打出内核原话",
             "牙": [[k, bool(v)] for k, v in 牙],
             "哪些牙没咬住": [k for k, v in 牙 if not v],
             "第一发": 装1, "第二发": 装2, "实际是否合期望": bool(合)}
        if not 合:
            problems.append("账满那一形")
        cases.append(d)
        print("账满那一形：一发 落账=%s KPI=%s ｜ 二发 预检=%s 落账=%s KPI=%s 拒=%s ｜ 没咬住=%s" % (
            装1["落账跑"], 装1["KPI"], 装2["预检跑"], 装2["落账跑"], 装2["KPI"],
            (装2["落账拒"] or "")[:34], d["哪些牙没咬住"] or "无"))

        # 第 ⑧ 步的三种「打了但没成」形状 + 连不上那一形。之前所有端到端都跑在假端点**正常回帧**那一形上，
        # 而失败归因那几格（fail_kind / 状态码 / 帧数 / 首帧 / 帧间 / 入线字节）正是「没量到不许写成 0」最密的地方。
        # 端点是这支探针自己在 127.0.0.1 随机端口上起的**坏端点**（模型名里就写着"不是真模型"）；
        # 真端点那条路照旧 NOT_RUN，8797/8799 一个包都没去过。
        import http.server
        import threading

        class 坏端点(http.server.BaseHTTPRequestHandler):
            # 每一发按顺序换一种坏法：429（回了但没成）→ 半路断（畸形）→ 挂着不回（超时）→ 只回 reasoning（正文空）
            剧本 = ['429', '断', '不回', 'reasoning']
            第几发 = -1

            def do_POST(self):
                坏端点.第几发 += 1
                形 = 坏端点.剧本[坏端点.第几发 % len(坏端点.剧本)]
                if 形 == '429':
                    # 正文里故意放一句"像口令"的串：产品要是读了错误体，这句话就会上屏或进账 ⇒ 那条牙必须红
                    体 = b'{"error":"rate_limited","echo":"SK-FAKE-SECRET-put-in-error-body-must-not-appear"}'
                    self.send_response(429)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Retry-After', '7')
                    self.send_header('Content-Length', str(len(体)))
                    self.end_headers()
                    self.wfile.write(体)
                elif 形 == '断':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    self.wfile.write(b'data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"head"}}]}\n\n')
                    self.wfile.flush()
                    self.wfile.write(b'data: {"choices":[{"delta":{"content":')  # 半条 JSON 就散架
                    self.wfile.flush()
                    self.connection.close()
                elif 形 == 'reasoning':
                    # 本机量过的坑：token 花在 reasoning 上、content 全程是空的、收尾=length。
                    # 只读 content 的驱动会把"没回话"当成"正常回完"—— 这一形就是来验这一条的。
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    for 行s in ('data: {"object":"chat.completion.chunk","choices":[{"delta":{"reasoning_content":"' + '思' * 40 + '"}}]}',
                               'data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"length"}],"usage":{"prompt_tokens":11,"completion_tokens":0,"total_tokens":11}}',
                               'data: [DONE]'):
                        self.wfile.write((行s + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                else:
                    time.sleep(9.0)   # 比 gatewayTimeout(4s) 长 ⇒ 客户端先走

            def log_message(self, fmt, *a):
                pass   # 别把探针自己的日志混进读数件

        端坏 = free_port()
        assert 端坏 not in (8797, 8799)
        服务坏 = http.server.ThreadingHTTPServer(('127.0.0.1', 端坏), 坏端点)
        threading.Thread(target=服务坏.serve_forever, daemon=True).start()
        端没人 = free_port()
        assert 端没人 not in (8797, 8799)   # 这个端口**故意不监听**：连不上那一形

        def 起一台带端点(基址, 名字, 附加=()):
            端 = free_port()
            assert 端 not in (8797, 8799)
            env2 = dict(os.environ, PYTHONIOENCODING='utf-8',
                        PGAGENT_BASE_URL=基址,
                        PGAGENT_MODEL='探针起的坏端点（不是真模型，本机 127.0.0.1）')
            pr = subprocess.Popen([exe, '-port', str(端), '-data', os.path.join(WORK, '数据端点' + 名字)]
                                  + list(附加),
                                  cwd=SRC, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            b2 = 'http://127.0.0.1:%d' % 端
            for _ in range(60):
                try:
                    urllib.request.urlopen(b2 + '/api/health', timeout=1).read()
                    break
                except Exception:
                    time.sleep(0.2)
            return pr, b2

        def 打一发带归因(基, 会话):
            st, steps, res, fr, ms, err = sse_turn(基, {"session": 会话, "lang": "go",
                                                       "code": DIRTY, "question": "这段有什么问题"}, timeout=45)
            by = {x["name"]: x for x in steps}
            档 = {}
            # 检索键以打印件为准：Result 里那串叫 ledger_decisions，不叫 decisions（我第一版就写错在这）
            for dd in ((res or {}).get("ledger_decisions") or []):
                档[str(dd.get("key"))] = [str(dd.get("basis")), str(dd.get("claim"))[:70]]
            return {"http": st, "KPI": (res or {}).get("kpi_ledger_decided"),
                    "五档恒等": (res or {}).get("mix_identity_ok"),
                    "结束": (res or {}).get("stop_reason"),
                    "findings条数": len((res or {}).get("findings") or []),
                    "结论摘要": ((res or {}).get("answer_summary") or '')[:160],
                    "第7步": (by.get("kernel.read_back") or {}).get("out"),
                    "第8步": (by.get("gateway") or {}).get("out"),
                    "第6步": (by.get("kernel.record_call") or {}).get("out"),
                    "第10步": (by.get("kernel.tally") or {}).get("out"),
                    "收口跑": (by.get("kernel.tally") or {}).get("ran"),
                    # 整列自洽判据（针 41 的判据本体 traceSane）的读数：每一发都带着走，
                    # 红必须上屏 —— 只活在返回值里的判据等于没有判据。
                    "自洽": (res or {}).get("trace_sane"),
                    "自洽话": (res or {}).get("trace_sane_why"),
                    "格档": 档,
                    "未决": [(u.get("what") if isinstance(u, dict) else str(u))
                           for u in ((res or {}).get("unknowns") or [])],
                    # 未决的名字不算证据，理由才算：W35 第一版这条臂只扫 what，
                    # 于是"压根没落账"那半句住在 why_absent 里，臂再怎么改都是恒过（空臂）。
                    "未决理由": [(u.get("why_absent") if isinstance(u, dict) else str(u))
                            for u in ((res or {}).get("unknowns") or [])]}

        形读 = {}
        服A, 基A = 起一台带端点('http://127.0.0.1:%d/v1' % 端坏, 'A')
        for 名 in ('429', '半路断', '超时', '只有reasoning'):
            形读[名] = 打一发带归因(基A, '端点-' + 名)
        服B, 基B = 起一台带端点('http://127.0.0.1:%d/v1' % 端没人, 'B')
        形读['连不上'] = 打一发带归因(基B, '端点-连不上')

        牙 = []
        量过的那几格 = ('chunks', 'first_byte_ms', 'max_gap_ms', 'wire_bytes_in')
        for 名, 期望归因 in (('429', 'http'), ('半路断', 'protocol'), ('超时', 'transport'), ('连不上', 'transport')):
            r = 形读[名]
            八 = r["第8步"] or ''
            格 = r["格档"]
            档名 = {k: (格.get(k) or ['没这格', ''])[0] for k in 量过的那几格}
            牙 += [
                ('%s：第 ⑧ 步点名归因=%s' % (名, 期望归因), ('归因 ' + 期望归因) in 八),
                ('%s：三态不塌（失败不许被说成"没打"）' % 名, ('没打' not in 八 and 'NOT_RUN' not in 八)),
                ('%s：这一发照样落账（KPI≥1）' % 名, (r["KPI"] or 0) >= 1),
                ('%s：五档不塌' % 名, r["五档恒等"] is True),
                # 429 那一形：状态码是真量到的，但**正文刻意没读**（错误体最容易把口令抄进读数）
                # ⇒ 帧数/首帧/帧间/入线字节这四格只能是缺席，署成 measured(0) 就是把没量写成量到。
                ('429：那四格必须是缺席（正文没读）',
                 名 != '429' or all(档名[k] == 'absent' for k in 量过的那几格)),
                ('429：第 ⑧ 步那句要自带"正文没读"的免责（不许让 0 帧看着像量到的）',
                 名 != '429' or ('没读' in 八)),
                # 反向牙：半路断那一形**真读到过帧**，修的时候不许把读过的也一起降成 absent
                ('半路断：真读到的帧数仍署 measured（不许连坐）',
                 名 != '半路断' or 档名['chunks'] == 'measured'),
                ('连不上/超时：那四格是缺席且有理由（W6 那条修过的，别退化）',
                 名 not in ('连不上', '超时') or all(档名[k] == 'absent' for k in 量过的那几格)),
                ('%s：错误体里那句假口令没上屏、没进账' % 名, 'SK-FAKE-SECRET' not in json.dumps(r, ensure_ascii=False)),
                # 整列自洽判据（针 41 的本体 traceSane）在部署侧也要过：单测里甲半边量的是同进程接缝，
                # 这台服是另一条起法 ⇒ 判据不能只在考卷里绿。
                ('%s：整列自洽判据过（trace_sane=true 且留了读数）' % 名,
                 r["自洽"] is True and bool(r["自洽话"])),
            ]
        R = 形读['只有reasoning']
        八R = R["第8步"] or ''
        牙 += [
            ('只有reasoning：第 ⑧ 步要写清"回了但正文是空的"（不许看着像正常回完）',
             '正文' in 八R and 'reasoning' in 八R.lower()),
            ('只有reasoning：不许静默 ⇒ 未决里要有一条点名这件事',
             any(('正文' in str(u)) or ('reasoning' in str(u).lower()) for u in R["未决"])),
            ('只有reasoning：账上 finish 那一格署的是端点原话 length（不许写我们自己的话）',
             'length' in (R["格档"].get('finish') or ['', ''])[1] and
             'reasoning' not in (R["格档"].get('finish') or ['', ''])[1].lower()),
            ('只有reasoning：这一形不读 retry_after_ms（没这回事就别挂成未决）',
             'retry_after_ms' not in R["格档"]),
            ('429：retry_after_ms 这一格读回来了、值是 7000ms（对端说了就别记没说）',
             (形读['429']["格档"].get('retry_after_ms') or ['', ''])[0] == 'measured' and
             '7000' in (形读['429']["格档"].get('retry_after_ms') or ['', ''])[1]),
            ('429：第 ⑧ 步把等待话原样带上（Retry-After=7）',
             '端点要等 7000ms' in (形读['429']["第8步"] or '')),
            ('连不上：这一形没有响应头 ⇒ retry_after_ms 记缺席且带理由（不许消失）',
             (形读['连不上']["格档"].get('retry_after_ms') or ['', ''])[0] == 'absent'),
            ('只有reasoning：收尾那一格署端点原话 length（不替它编收尾）', 'length' in 八R),
            ('只有reasoning：照样落账（KPI≥1）', (R["KPI"] or 0) >= 1),
            ('只有reasoning：五档不塌', R["五档恒等"] is True),
            ('只有reasoning：端点自报的 usage 停在 relayed（不许升 measured）',
             'relayed' in json.dumps(R["格档"], ensure_ascii=False)),
            ('只有reasoning：整列自洽判据过（trace_sane=true）', R["自洽"] is True),
        ]
        没咬 = [k for k, v in 牙 if not v]
        d = {"用例": "第 ⑧ 步的三种失败形状 + 连不上（本机坏端点；真端点仍 NOT_RUN）",
             "期望": "归因分得开、照样落账、状态码按事实署档、正文没读那几格不许署 measured、错误体里的串不许上屏",
             "牙": [[k, bool(v)] for k, v in 牙], "哪些牙没咬住": 没咬, "读数": 形读,
             "实际是否合期望": bool(not 没咬)}
        if 没咬:
            problems.append("第 ⑧ 步的失败形状")
        cases.append(d)
        服A.terminate()
        服A.wait(timeout=10)
        服B.terminate()
        服B.wait(timeout=10)
        服务坏.shutdown()
        print("第 ⑧ 步失败形状：429 那四格=%s ｜ 半路断 KPI=%s 第7步=%s ｜ 超时 KPI=%s ｜ 连不上 KPI=%s ｜ 没咬住=%s" % (
            {k: (形读['429']["格档"].get(k) or ['—'])[0] for k in 量过的那几格},
            形读['半路断']["KPI"], (形读['半路断']["第7步"] or '')[:26],
            形读['超时']["KPI"], 形读['连不上']["KPI"], 没咬 or '无'))

        # 第 21 形：反臂那一台（-read-back=false）。W35 的整列判据在单测里撞出的第四句假话就住在这形：
        # 账是落了的，第 ⑩ 步与未决栏却都写死"这一发没进账 / 压根没落账"。
        # 单测甲半边量的是同进程接缝，这一台是部署侧另一条起法 ⇒ 闸 4 里必须有一臂盯住它。
        服C, 基C = 起一台带端点('http://127.0.0.1:%d/v1' % 端坏, 'C', ('-read-back=false',))
        反 = 打一发带归因(基C, '反臂-自洽')
        服C.terminate()
        服C.wait(timeout=10)
        六, 七, 十 = 反["第6步"] or '', 反["第7步"] or '', 反["第10步"] or ''
        牙 = [
            ('反臂：这一发是真落了账（第 ⑥ 步带的是内核那句"整发落账"）', '整发落账' in 六),
            ('反臂：KPI 照样掉回 0（加了判据不许把反臂改绿）', 反["KPI"] == 0),
            ('反臂：第 ⑦ 步那句"没读回："后面带的是反臂的理由', 七.startswith('没读回：') and '反臂' in 七),
            ('反臂：第 ⑩ 步不许再说"没进账"（W35 抓到的第四句假话）', '没进账' not in 十),
            # W38 改口：反臂关的是"读回"，不是"收口"。那三个是只读件，账落了就该打出内核原话，
            # 所以这一形现在要的是"第 ⑩ 步带五档原话"，而"不许说没进账"那条仍然要（同一族第一句假话）。
            ('反臂：第 ⑩ 步带的是内核五档原话（收口三步不再被反臂省掉）',
             '账 ' in 十 and '没东西可印' not in 十 and 反["收口跑"] is True),
            ('反臂：未决栏一条都不许写"压根没落账"（扫的是 why_absent，不是条目名）',
             not any('压根没落账' in str(u) for u in 反["未决理由"])),
            ('反臂：整列自洽判据过、且过了也留读数', 反["自洽"] is True and bool(反["自洽话"])),
            ('反臂：五档不塌', 反["五档恒等"] is True),
        ]
        没咬 = [k for k, v in 牙 if not v]
        d = {"用例": "反臂那一形（-read-back=false）+ 整列自洽判据",
             "期望": "账落了就说落了；收口三步没打要说清是没打；判据过与不过都要留读数；KPI 仍为 0",
             "牙": [[k, bool(v)] for k, v in 牙], "哪些牙没咬住": 没咬,
             "读数": {"第6步": 六, "第7步": 七, "第10步": 十, "自洽": 反["自洽"],
                   "自洽话": 反["自洽话"], "KPI": 反["KPI"], "未决": 反["未决"],
                   "未决理由": 反["未决理由"]},
             "实际是否合期望": bool(not 没咬)}
        if 没咬:
            problems.append("反臂那一形的整列自洽")
        cases.append(d)
        print("反臂那一形：KPI=%s 自洽=%s 第10步=%s ｜ 没咬住=%s" % (
            反["KPI"], 反["自洽"], 十[:40], 没咬 or '无'))

        # 第 22 形：跨发一致性判据（chainSane）在部署侧的读数。同一会话连发三发 ⇒ 链上条数必须
        # 按每发 49 条往上涨；被门口挡下的那一发（账满那台的第二发）不许让链上多长，也不许带 KPI。
        链读 = []
        for 号 in range(3):
            st, steps, res, fr, ms, err = sse_turn(base, {"session": "跨发判据", "lang": "go",
                                                          "code": DIRTY, "question": "这段有什么问题"}, timeout=45)
            链读.append({"http": st, "跨发": (res or {}).get("chain_sane"), "话": (res or {}).get("chain_why"),
                       "KPI": (res or {}).get("kpi_ledger_decided"), "单发": (res or {}).get("trace_sane")})

        def 拿历史(基, 会话):
            u = 基 + '/api/history?session=' + urllib.parse.quote(会话)
            try:
                答 = urllib.request.urlopen(u, timeout=10)
                assert 答.status == 200, 答.status
                return json.loads(答.read().decode('utf-8')).get('turns') or []
            except Exception as e:
                return {'err': '%s：%s' % (type(e).__name__, e)}

        跨发列 = 拿历史(base, '跨发判据')
        账满列 = 拿历史(base_cap, '容量')
        牙 = []
        if isinstance(跨发列, dict):
            牙 = [('跨发这一列翻得回来', False), ('读数：%s' % 跨发列.get('err'), False)]
        else:
            链上 = [t.get('chain_entries') for t in 跨发列]
            挡 = [t for t in 账满列 if isinstance(t, dict) and t.get('ledger_reject')] if isinstance(账满列, list) else []
            牙 += [
                ('跨发：三发都过判据（chain_sane=true）',
                 len(跨发列) == 3 and all(t.get('chain_sane') is True for t in 跨发列)),
                # 增量口径：这台服上先跑过别的会话，本会话第一发进场时就带着 441 条（tally 数的是
                # 整个进程那本账，不是本会话）。所以判的是"每发涨了它自己交来的那些格"，不是绝对值。
                ('跨发：链上每发涨的条数 == 这一发自己交来的格数（增量对得上）',
                 len(链上) == 3 and all(
                     (链上[i + 1] - 链上[i]) == 跨发列[i + 1].get('turn_cells') for i in range(len(链上) - 1))),
                ('跨发：每发交来的格数是内核那句原话里的 49（不是我按判据表算出来的）',
                 all(t.get('turn_cells') == 49 for t in 跨发列)),
                ('跨发：每一发的读数都自带"对得上"与被拒计数那一维',
                 all(('对得上' in str(t.get('chain_why'))) and ('被拒计数逐发对得上' in str(t.get('chain_why'))) for t in 跨发列)),
                ('跨发：核心 KPI 与读回格数都落了盘（以前只活在当场横幅里）',
                 all(isinstance(t.get('kpi_ledger_decided'), int) and isinstance(t.get('ledger_cells'), int) for t in 跨发列)),
                ('跨发：每发都记着"落了账"（recorded=true）', all(t.get('recorded') is True for t in 跨发列)),
                ('跨发：单发判据也一并过了（trace_sane=true 三发）', all(t.get('trace_sane') is True for t in 跨发列)),
                # 同源：交回前端那一格与落盘那一格必须是同一次计算的结果（两处各算一遍就会有两个版本）
                ('跨发：SSE 那三发的判定与原话与落盘那一格逐发相同（一次计算、两处消费）',
                 len(链读) == 3 and len(跨发列) == 3 and all(
                     链读[i]['跨发'] == 跨发列[i].get('chain_sane') and str(链读[i]['话']) == str(跨发列[i].get('chain_why'))
                     for i in range(3))),
                # 反向牙：被门口挡下那一发**不该**有 KPI —— 写 0 就是把没量演成量到（本件最贵的那族假绿）
                ('账满：被挡那一发确实记在历史里（现场没造出来就别判）', len(挡) == 1),
                ('账满：被挡那一发 recorded=false 且没有 kpi_ledger_decided 这格（没量过 ≠ 0）',
                 len(挡) == 1 and 挡[0].get('recorded') is False and 'kpi_ledger_decided' not in 挡[0]),
                ('账满：被挡那一发带着内核那句拒收原话', len(挡) == 1 and '已到上限' in str(挡[0].get('ledger_reject'))),
            ]
        没咬 = [k for k, v in 牙 if not v]
        d = {"用例": "跨发一致性判据（同一会话连发三发 + 被门口挡下那一发）",
             "期望": "链上按每发 49 条涨、KPI 与读回格数落盘、被挡那发不带 KPI（没量过不是 0）",
             "牙": [[k, bool(v)] for k, v in 牙], "哪些牙没咬住": 没咬,
             "读数": {"跨发三发": 跨发列, "账满那本": 账满列, "SSE": 链读},
             "实际是否合期望": bool(not 没咬)}
        if 没咬:
            problems.append("跨发一致性判据")
        cases.append(d)
        print("跨发那一形：链上=%s ｜ 三发跨发=%s ｜ 账满那本被挡发有 KPI 吗=%s ｜ 没咬住=%s" % (
            [t.get('chain_entries') for t in 跨发列] if isinstance(跨发列, list) else 跨发列,
            [x['跨发'] for x in 链读],
            [t.get('kpi_ledger_decided', '没这格') for t in 账满列 if isinstance(t, dict) and t.get('ledger_reject')]
            if isinstance(账满列, list) else 账满列, 没咬 or '无'))

        # 自我拆穿那一发：给一个**明知是假**的期望（空代码硬说期望 200），看这份读数的"合期望"这格
        # 会不会替它开绿灯。它要是"合期望"，说明这栏是装饰，上面九条的"合期望"三个字就不能信。
        st, steps, res, fr, ms, err = sse_turn(base, {"session": "z0", "lang": "go", "code": "",
                                                      "question": "这段有什么问题"})
        d = {"用例": "自我拆穿（假期望，必须被判不达标）", "期望": "200（这是假的）", "http": st}
        d["实际是否合期望"] = bool(st == 200)
        假期望被判红 = (d["实际是否合期望"] is False)
        cases.append(d)
        print("自我拆穿那发：http=%s ⇒ 判不达标=%s（这条若判成达标，上面所有「合期望」三个字都不可信）" % (
            st, 假期望被判红))
    finally:
        if srv3 is not None:
            srv3.terminate()
            srv3.wait(timeout=10)
        srv2.terminate()
        srv2.wait(timeout=10)
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(WORK, ignore_errors=True)

    if not 假期望被判红:
        problems.append("自我拆穿那发没被判红 ⇒ 这栏「合期望」是装饰")
    out = {"生成时刻（本机钟）": time.strftime("%Y-%m-%d %H:%M:%S"),
           "分母": "自印 %d 个用例（脚本现跑现数，不是照着期望写的）" % len(cases),
           "端口": "127.0.0.1:%d（随机空闲；8797/8799 没碰）" % port,
           "TEMP 残留": os.path.isdir(WORK),
           "不达标用例": problems,
           "用例": cases}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        # default=repr 是兜底不是遮羞布：上面那条评论说的崩法，兜底会让它变成"件里多一行怪字符串"，
        # 而不是把已经跑完的十个用例一起丢掉。
        json.dump(out, f, ensure_ascii=False, indent=1, default=repr)
    print("\n分母=%d 个用例 ｜ 不达标=%d：%s" % (len(cases), len(problems), problems or "无"))
    print("写了 " + OUT + "（TEMP-边界 残留：%s）" % out["TEMP 残留"])
    # 跨件传数走结构化行（同一族规矩：父件去 grep 散文，文案一改计数就归零）。
    print("SUMMARY cases=%d bad=%d temp_left=%d" % (
        len(cases), len(problems), 1 if out["TEMP 残留"] else 0))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
