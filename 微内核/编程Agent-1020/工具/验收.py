#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收复跑件：一条命令把目标里那几道闸跑一遍（现为 7 道），全部数字现算。

    python 工具/验收.py [go.exe 路径]

为什么要有它：目标写的是"go test 全绿 + selfcheck 该红的红 + 真开页面跑完整圈并留截图读数"。
这三句如果只能由我在会话里跑一遍、再抄进文档，那下一个人只能选择信我 —— 那不是验收，是叙述。
所以把三道闸做成可复跑的，任何一道没跑成就不写"全绿"。

三道闸 + 一条明说的做不到：
  闸 1  `go test -count=1`                     —— 退出码、Test 函数个数（现数）
  闸 2  `go run . -selfcheck`                  —— [OK ]/[RED] 两条计数，且要与自印"失败项"相等
  闸 2b `工具/闸门会红.py`                     —— 判据集必须**能红**（臂数现取，不写死），它红不了就是恒绿装饰
  闸 3  起一个本机服务，POST /api/turn 收 SSE  —— 九步语义步齐不齐、五档恒等、KPI≥1、反臂那一发 KPI=0
  闸 4  `工具/边界那一发.py`                    —— 十几种输入形状各打一发（含一发自我拆穿）
  闸 5  界面读数新鲜度对账                      —— 源码比界面读数新 ⇒ 那份读数不能替这一版 build 说话，判红
  闸 6  `工具/长会话曲线.py`（复用闸 3 那颗进程）—— 同一进程连发 30 发：每发正好 49 条、帧数一致、读者声明不许重新漂
  闸 7  `工具/跨进程那一发.py`（两程 × 两发，同一本数据目录）—— 发号必须接续、内核账必须归零、口径句必须把"此前有几发"带过来
  截图  本件自己不产像素：像素要么由人把 in-app Browser 面板切到前台后 agent 跑 take_screenshot（10-21 09:39 起这条路已走通，出图 846x638），要么跑 Edge 无头（命令见下，可照抄）

它只监听 127.0.0.1 的随机空闲端口，**绝不碰 8797/8799**；数据目录建在 TEMP，跑完删。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "pgagent")
GO = sys.argv[1] if len(sys.argv) > 1 else "go"
OUT = os.path.join(ROOT, "报告-验收.txt")
WORK = os.path.join(ROOT, "TEMP-验收")
NINE = ["intake", "shape", "select-analyzers", "analyze", "kernel.check_call",
        "kernel.record_call", "kernel.read_back", "gateway", "fold"]


def run(args, cwd=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=900)
    except FileNotFoundError:
        return 127, "命令找不到：%s" % (args[0] if args else "?")
    except subprocess.TimeoutExpired:
        return 124, "超时 900 秒没回（这一闸不算跑过）"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def sse_turn(base, body, timeout=30):
    """POST /api/turn，按 SSE 帧切：返回 (步名列表, 结果对象或 None, 帧数, 毫秒)。"""
    req = urllib.request.Request(base + "/api/turn",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    steps, result, frames = [], None, 0
    t0 = time.time()
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
                    steps.append((obj.get("name"), obj.get("ran")))
                elif ev == "result":
                    result = obj
    return steps, result, frames, int((time.time() - t0) * 1000)


def main():
    t_start = time.time()   # 闸 5 只认"这一跑开始之前"的状态：闸 4 会在跑的过程中改写 读数/，
                            # 拿它自己的产物去判"命名漂了"就是自己咬自己（第一版就这样误报过 3 份）。
    problems = []
    L = ["验收复跑 · 全部数字现算（工具/验收.py）",
         "生成时刻（本机钟）：" + time.strftime("%Y-%m-%d %H:%M:%S")]

    # —— 闸 1：go test ——
    rc, out = run([GO, "test", "-count=1", "."], SRC)
    n_test = len(re.findall(r"(?m)^func Test", open(os.path.join(SRC, "pgagent_test.go"), encoding="utf-8").read()))
    tail = out.strip().splitlines()[-1] if out.strip() else "无输出"
    L.append("闸 1 go test：退出码=%d ｜ Test 函数（^func Test 现数）=%d ｜ 输出尾行：%s" % (rc, n_test, tail))
    if rc != 0:
        problems.append("闸 1 没绿")

    # —— 闸 2：selfcheck ——
    rc2, out2 = run([GO, "run", ".", "-selfcheck"], SRC)
    ok_n = len(re.findall(r"(?m)^\[OK \]", out2))
    red_n = len(re.findall(r"(?m)^\[RED\]", out2))
    m = re.search(r"失败项 (\d+)", out2)
    claimed = int(m.group(1)) if m else -1
    L.append("闸 2 selfcheck：退出码=%d ｜ [OK ]=%d ｜ [RED]=%d ｜ 自印失败项=%d ｜ 两读%s" % (
        rc2, ok_n, red_n, claimed, "一致" if red_n == claimed else "**不一致（标记口径漂了，别信这份）**"))
    if rc2 != 0 or ok_n == 0 or red_n != 0 or claimed != 0 or red_n != claimed:
        problems.append("闸 2 没绿或两读不一致")

    # —— 闸 2b：闸门会红（判据集必须能红）——
    rc3, out3 = run([GO, "version"], SRC)
    if rc3 != 0:
        L.append("闸 2b 闸门会红：没跑成（go 找不到）⇒ 这一闸是空的，不算过")
        problems.append("闸 2b 没跑")
    else:
        rc3b, out3b = run([sys.executable, os.path.join(HERE, "闸门会红.py"), GO], ROOT)
        # 只吃那行结构化 SUMMARY，不去数散文（散文改一个字，这边就报成"咬住=0"）。
        s = re.search(r"(?m)^SUMMARY arms=(\d+) bit=(\d+) empty=(\d+) control_rc=(-?\d+) "
                      r"restored_rc=(-?\d+) bad=(\d+)", out3b)
        if not s:
            L.append("闸 2b 闸门会红：退出码=%d ｜ **没印 SUMMARY** ⇒ 拿不到臂数，这一闸按没跑成算" % rc3b)
            problems.append("闸 2b 没交出机器可读的臂数")
        else:
            arms, bit, empty, rc_ctrl, rc_rest, bad = (int(x) for x in s.groups())
            L.append("闸 2b 闸门会红：退出码=%d ｜ 臂数=%d ｜ 咬住=%d/%d ｜ 空臂=%d ｜ 对照退出码=%d 还原后=%d ｜ 不达标=%d" % (
                rc3b, arms, bit, arms, empty, rc_ctrl, rc_rest, bad))
            L.append("  （咬住=注入做坏后确实红、且红的正是该点名那条；这 %d 臂的实物在那支自己的输出里逐臂列着）" % arms)
            if rc3b != 0 or arms == 0 or bit != arms or empty > 0:
                problems.append("闸 2b：判据集没能红（咬住 %d ≠ 臂数 %d）或有空臂" % (bit, arms))

    # —— 闸 3：真起服务收 SSE ——
    exe = os.path.join(WORK, "pgagent-验收.exe")
    os.makedirs(WORK, exist_ok=True)
    rc4, out4 = run([GO, "build", "-o", exe, "."], SRC)
    if rc4 != 0:
        L.append("闸 3 端到端：**没跑** —— 连 exe 都没编出来：%s" % out4.strip().splitlines()[-1:])
        problems.append("闸 3 没跑")
    else:
        port = free_port()
        assert port not in (8797, 8799), "验收件绝不碰那两本账"
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        srv = subprocess.Popen([exe, "-port", str(port), "-data", os.path.join(WORK, "数据"), "-fake-endpoint"],
                               cwd=SRC, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = "http://127.0.0.1:%d" % port
            for _ in range(60):
                try:
                    urllib.request.urlopen(base + "/api/health", timeout=1).read()
                    break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("服务 12 秒没起来 ⇒ 这一闸不算跑过")
            # 贴一段真会命中的脏 Go（同应用考卷的形状）：验收件不该依赖仓库里的 fixture 文件，
            # 否则"改了 fixture 让验收变绿"这条路就开着。
            body = {"session": "验收件", "lang": "go", "stack": "", "question": "这段有什么问题",
                    "code": ("package main\n\nimport (\n\t\"fmt\"\n\t\"os\"\n)\n\n"
                             "func load(p string) string {\n\tdata, _ := os.ReadFile(p)\n\tseed := len(data)\n"
                             "\tseed := seed + 1\n\tif seed > 0 {\n\t\tfmt.Print(seed)\n\t}\n\treturn string(data)\n}\n\n"
                             "func helper() int { return 1 }\n\nfunc helper() int { return 2 }\n")}
            steps, result, frames, ms = sse_turn(base, body)
            ran = [n for n, r in steps if r]
            missing = [n for n in NINE if n not in ran]
            mix = (result or {}).get("provenance_mix", {})
            ident = (result or {}).get("mix_identity_ok")
            kpi = (result or {}).get("kpi_ledger_decided")
            L.append("闸 3 端到端（127.0.0.1:%d，随机空闲端口）：SSE 帧=%d ｜ 用时=%dms ｜ 亮出的步=%d" % (port, frames, ms, len(steps)))
            L.append("  九步语义步：%s" % ("齐" if not missing else "**缺 %s**" % missing))
            L.append("  五档恒等：%s ｜ 五档=%s" % (ident, json.dumps(mix, ensure_ascii=False)))
            L.append("  KPI（账本真改写了结果的格数）=%s" % kpi)
            if missing or ident is not True or not kpi:
                problems.append("闸 3：九步不齐 / 恒等式不成立 / KPI 没数出动作")
            # 反臂：同一份服务上换 session 再发一发是同样的数；反臂要另起一个 -read-back=false 的进程
            srv2_port = free_port()
            assert srv2_port not in (8797, 8799)
            srv2 = subprocess.Popen([exe, "-port", str(srv2_port), "-data", os.path.join(WORK, "数据2"),
                                     "-read-back=false"], cwd=SRC, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base2 = "http://127.0.0.1:%d" % srv2_port
                for _ in range(60):
                    try:
                        urllib.request.urlopen(base2 + "/api/health", timeout=1).read()
                        break
                    except Exception:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("反臂服务没起来")
                _, r2, _, _ = sse_turn(base2, dict(body, session="验收件-反臂"))
                kpi2 = (r2 or {}).get("kpi_ledger_decided")
                L.append("反臂（同一份件，只把 -read-back 关掉）：KPI=%s（必须 0）" % kpi2)
                if kpi2 != 0:
                    problems.append("反臂没掉回 0 ⇒ KPI 数的可能不是账上的动作")
            finally:
                srv2.terminate()
                srv2.wait(timeout=10)
            # —— 闸 6：长跑不劣化。同一颗进程连发 N 发（不是另起 N 颗），只吃子件那行 SUMMARY。
            # 盯的是三件会随会话变长才现形的东西：每发还是不是正好 49 条、读者声明会不会重新开始漂（W10）、
            # 帧数与历史行数还是不是每发一致。RSS 只报数不判红——它是 append-only 的代价，挡法是 -entry-cap。
            N_LONG = 30
            rc6, out6 = run([sys.executable, os.path.join(HERE, "长会话曲线.py"), str(srv.pid), str(port),
                             str(N_LONG), os.path.join(WORK, "长会话曲线.json")])
            s6 = re.search(r"(?m)^SUMMARY turns=(\d+) bad=(\d+) frames_uniform=(\w+) chain_first=(\d+) "
                           r"chain_last=(\d+) decl_fail_total=(\d+) rss_start_mb=(\S+) rss_end_mb=(\S+) "
                           r"per_turn_kb=(\S+) hist_bytes=(\d+) hist_count=(\d+)", out6)
            if not s6:
                L.append("闸 6 长跑不劣化：退出码=%d ｜ **没印 SUMMARY** ⇒ 拿不到曲线数，这一闸按没跑成算" % rc6)
                problems.append("闸 6 没交出机器可读的曲线数")
            else:
                t6, bad6, fu6, cf6, cl6, df6, r0, rN, perkb, hb6, hc6 = [g.strip() for g in s6.groups()]
                每发条数 = (int(cl6) - int(cf6)) / (int(t6) - 1) if int(t6) > 1 else -1
                L.append("闸 6 长跑不劣化（同一进程连发 %s 发）：退出码=%d ｜ 不达标=%s ｜ 帧数一致=%s ｜ 链上 %s→%s（每发 %.0f 条，必须 49）"
                         " ｜ 读者声明没落账合计=%s ｜ RSS %s→%sMB（%s KB/发，只报数）｜ history %s 字节 / %s 行" %
                         (t6, rc6, bad6, fu6, cf6, cl6, 每发条数, df6, r0, rN, perkb, hb6, hc6))
                # 子件自己的退出码也要对上：它喊 bad>0 却把 SUMMARY 印成 bad=0，两读不一致就是假绿（W13 那一族）
                if (int(t6) != N_LONG or int(bad6) != 0 or rc6 != 0 or fu6 != "True" or int(df6) != 0
                        or int(hc6) != N_LONG or abs(每发条数 - 49) > 1e-9):
                    problems.append("闸 6：长跑这一形劣化了（子件 rc=%s / 不达标 %s / 帧数一致 %s / 每发条数 %.1f / 没落账 %s / 历史行 %s）"
                                    % (rc6, bad6, fu6, 每发条数, df6, hc6))
        except Exception as e:
            L.append("闸 3 端到端：跑的过程中出错 ⇒ %r（这一闸不算过）" % e)
            problems.append("闸 3 异常")
        finally:
            srv.terminate()
            srv.wait(timeout=10)

    # —— 闸 4：边界那一发（十几种输入形状，件自己交 SUMMARY）——
    rc5, out5 = run([sys.executable, os.path.join(HERE, "边界那一发.py"), GO], ROOT)
    s5 = re.search(r"(?m)^SUMMARY cases=(\d+) bad=(\d+) temp_left=(\d+)", out5)
    if not s5:
        L.append("闸 4 边界那一发：退出码=%d ｜ **没印 SUMMARY** ⇒ 拿不到用例数，这一闸按没跑成算" % rc5)
        problems.append("闸 4 没交出机器可读的用例数")
    else:
        cases_n, bad_n, left_n = (int(x) for x in s5.groups())
        L.append("闸 4 边界那一发：退出码=%d ｜ 用例=%d ｜ 不达标=%d ｜ TEMP 残留=%d" % (rc5, cases_n, bad_n, left_n))
        L.append("  （含一发自我拆穿：给它一个明知是假的期望，它必须被判不达标 —— 否则那份读数的「合期望」是装饰）")
        if rc5 != 0 or cases_n == 0 or bad_n > 0 or left_n > 0:
            problems.append("闸 4：边界用例有不达标（不达标 %d / 用例 %d）" % (bad_n, cases_n))

    # —— 闸 5：界面读数的新鲜度对账（把"旧读数不能替新 build 说话"这条口径变成会红的闸）——
    exts = (".go", ".js", ".html", ".css")
    srcs = []
    for dirpath, _dirs, fnames in os.walk(SRC):
        for fn in fnames:
            fp = os.path.join(dirpath, fn)
            if fn.endswith(exts) and os.path.getmtime(fp) < t_start:
                srcs.append(fp)
    newest_src = max(srcs, key=os.path.getmtime) if srcs else None
    ui_ext = (".json", ".txt", ".png")
    ui = [os.path.join(dp, fn) for dp, _d2, fs in os.walk(os.path.join(ROOT, "读数"))
          for fn in fs if fn.endswith(ui_ext) and os.path.getmtime(os.path.join(dp, fn)) < t_start
          and ("浏览器" in fn or "探针" in fn or "截图" in dp)]
    newest_ui = max(ui, key=os.path.getmtime) if ui else None
    if not newest_src or not newest_ui:
        L.append("闸 5 界面读数新鲜度：**没跑成** —— 源码件或界面读数找不到（%s / %s）" % (
            bool(newest_src), bool(newest_ui)))
        problems.append("闸 5 找不到比对象")
    else:
        ms, mu = os.path.getmtime(newest_src), os.path.getmtime(newest_ui)
        stale = [os.path.relpath(p, ROOT) for p in ui if os.path.getmtime(p) < ms]
        L.append("闸 5 界面读数新鲜度：源码 %d 件，最新是 %s（%s）｜界面读数 %d 份（浏览器/探针/截图），最新是 %s（%s）" % (
            len(srcs), os.path.relpath(newest_src, ROOT),
            time.strftime("%H:%M:%S", time.localtime(ms)),
            len(ui), os.path.relpath(newest_ui, ROOT),
            time.strftime("%H:%M:%S", time.localtime(mu))))
        L.append("  界面读数比最新源码%s %.0f 秒 ｜ 早于该源码的界面读数 %d 份（归档留着，不算错，但**不能替这一版 build 说话**）" % (
            "新" if mu >= ms else "**旧**", abs(mu - ms), len(stale)))
        # 这套"哪些算界面读数"是按文件名认的 —— 命名一漂就会漏（W17 就这么被自己漏过一次：
        # 新写的那份不含关键字，闸 5 报"最新还是 W15 那份"）。所以补一条：比源码新、却没进集合的，点名。
        outside = [os.path.relpath(os.path.join(dp, fn), ROOT)
                   for dp, _d3, fs in os.walk(os.path.join(ROOT, "读数")) for fn in fs
                   if fn.endswith(ui_ext)   # 只比"读数件"；服务端日志(.log)不是读数，别拿它算
                   and t_start > os.path.getmtime(os.path.join(dp, fn)) >= ms
                   and os.path.join(dp, fn) not in ui]
        if outside:
            L.append("  **比最新源码却没被算进界面读数的件（命名可能漂了，按文件名认的集合会漏）**：%s" % outside[:6])
            problems.append("闸 5：有 %d 份比源码还新的读数没进界面读数集合（%s）⇒ 这一闸可能是假绿，给文件名带上 浏览器/探针/截图 或把它挪走"
                            % (len(outside), outside[0]))
        if mu < ms:
            problems.append("闸 5：源码在 %s 又改过，而最新的界面读数还是旧的 ⇒ 界面类结论要重测（W15 那种分段跑）；"
                            "若你确实重测过，检查那份读数的文件名有没有带 浏览器/探针/截图 这几个字"
                            % os.path.relpath(newest_src, ROOT))

    # —— 闸 7：跨进程那一维（同一本会话文件换一颗进程）——
    # 这一维与闸 6 相反：发号**必须接续**（不许两个身份写进同一本文件），内核账**必须归零**（那是进程内的）。
    # 上一轮实测过其中一半坏了会是什么样（发号 [1,2,3,1,2,3]），所以两边都判。
    rc7, out7 = run([sys.executable, os.path.join(HERE, "跨进程那一发.py"), exe])
    s7 = re.search(r"(?m)^SUMMARY procs=(\d+) turns=(\d+) dup=(\d+) chain_b_first=(\S+) hist=(\S+) "
                   r"scope_ok=(\d+) bad=(\d+) temp_left=(\d+)", out7)
    if not s7:
        L.append("闸 7 跨进程那一发：退出码=%d ｜ **没印 SUMMARY** ⇒ 拿不到两程的数，这一闸按没跑成算" % rc7)
        problems.append("闸 7 没交出机器可读的跨进程读数")
    else:
        (p7, t7, dup7, cb7, h7, sc7, bad7, tl7) = s7.groups()
        L.append("闸 7 跨进程（两程 × 两发，同一本数据目录）：procs=%s ｜ turns=%s ｜ 发号撞车=%s ｜ "
                 "换进程后链上首发=%s（必须 49）｜ 会话文件行数=%s ｜ 口径句带过来=%s ｜ 不达标=%s ｜ TEMP 残留=%s" %
                 (p7, t7, dup7, cb7, h7, sc7, bad7, tl7))
        if (int(p7) != 2 or int(t7) != 4 or int(dup7) != 0 or cb7 != "49" or h7 != "4"
                or int(sc7) != 1 or int(bad7) != 0 or int(tl7) != 0 or rc7 != 0):
            problems.append("闸 7：跨进程那一维劣化（撞车 %s / 链上首发 %s / 行数 %s / 口径 %s / 子件 rc=%s）"
                            % (dup7, cb7, h7, sc7, rc7))

    # —— 截图那条：明说给不了 ——
    L.append("截图读数：本件自己不产像素。已经走通的两条路：")
    L.append("  A) 人把 Qoder 的 in-app Browser 面板切到前台，agent 跑 take_screenshot 就出图（10-21 09:39 第一次成功：846x638；隐藏态报 visibilityState=hidden）")
    L.append("     注意：面板只截到顶部那一块，同一段横幅的两个 build 可能逐字节相同 ⇒ 面板图证的是\"看得见\"，build 身份仍由 exe 哈希认")
    L.append("  B) msedge --headless=new --disable-gpu --window-size=1440,900 --user-data-dir=%TEMP%\\pgagent-shot "
             "--virtual-time-budget=40000 --screenshot=出图.png \"http://127.0.0.1:<端口>/?run=1\"")
    L.append("     窄屏别用 B 当读数：这台机 Edge 把窗口宽度夹在 ~528，390/320 的 PNG 内容按 528 排（见 运行记录 W9）")
    L.append("")
    N_GATE = 7   # 上面列了几道会红的闸（闸 2b 与闸 2 算同一件的正反两读；截图那条不算闸，它由人复核）
    L.append("结论：%s" % ("%d 道闸全过（截图那条按上面口径由人复核）" % N_GATE if not problems
                           else "有闸没过 —— 别看这份当绿：" + "; ".join(problems)))

    txt = "\n".join(L) + "\n"
    with open(OUT, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(txt)
    shutil.rmtree(WORK, ignore_errors=True)
    print(txt)
    print("写了 " + OUT + "（残留 TEMP-验收：%s）" % os.path.isdir(WORK))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
