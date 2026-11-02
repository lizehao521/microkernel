#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收复跑件：一条命令把 AgentHub 的闸全跑完，全部数字现算（结论里的道数也现数，不写死）。

    python 工具/验收.py <go.exe 路径>

为什么要有这支件而不是"我跑过了"：文档里的数会随代码漂（Test 个数、selfcheck 条数、事件种类、
工具数）。手写第二次就要出错，所以口径落在这里 —— 任何一道没跑成就不写"全绿"。

闸号：
  闸 1  go test -count=1            —— 退出码 + Test 函数个数（现数）
  闸 1b 前端语法 node --check        —— app.js 语法不过 ⇒ 整页静默死掉，Go 侧全绿也救不了
  闸 2  hubd -selfcheck             —— [OK ]/[RED] 两读一致，且退出码为 0
  闸 3  起服收一发 SSE              —— 七类事件齐、五档加总对得上、整列自洽为真、屏幕脏字 0
  闸 4  反臂（同一份件，只改旗标）  —— -max-steps 1 必须停在上限；默认旗标下写文件必须被门口挡下
  闸 5  扩展那一维                  —— 临时放一个带 triggers 的清单，工具数 +1 且能被自然语言选起
  闸 6  界面读数新鲜度              —— 源码比界面读数新 ⇒ 那份读数不能替这一版 build 说话，判红
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "hubd")
GO = sys.argv[1] if len(sys.argv) > 1 else "go"
OUT = os.path.join(ROOT, "报告-验收.txt")

跑过 = []
红 = []
没跑 = []   # NOT_RUN 的闸：不算过，也不算红，但必须写在结论里
L = []


def run(args, cwd, timeout=600):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except FileNotFoundError as e:
        跑过.append((args[0], 127, 0))
        return 127, "命令找不到：%s" % e
    except subprocess.TimeoutExpired:
        跑过.append((args[0], 124, 0))
        return 124, "超时没回（这一闸不算跑过）"
    跑过.append((args[0], p.returncode, len((p.stdout or "") + (p.stderr or ""))))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def 空端口():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    assert p not in (8797, 8799), "内核交付件的端口不许占"
    return p


def 起服(exe, 端口, 额外=None, 环=None):
    args = [exe, "-port", str(端口), "-data", os.path.join(tempfile.gettempdir(), "hubd-验收-数据-%d" % 端口),
            "-tools-dir", os.path.join(SRC, "tools")] + (额外 or [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if 环:
        env.update(环)
    p = subprocess.Popen(args, cwd=SRC, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % 端口, timeout=1) as r:
                if r.status == 200:
                    return p, json.loads(r.read().decode())
        except Exception:
            time.sleep(0.25)
    p.kill()
    raise RuntimeError("服务 15 秒没起来 ⇒ 这一闸不算跑过")


def 收SSE(端口, 话, 秒=60):
    req = urllib.request.Request("http://127.0.0.1:%d/api/chat" % 端口,
                                 data=json.dumps({"text": 话}).encode(),
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=秒)
    buf, 帧 = "", []
    while True:
        b = r.read(1024)
        if not b:
            break
        buf += b.decode("utf-8", "replace")
        while "\n\n" in buf:
            块, buf = buf.split("\n\n", 1)
            if 块.strip():
                帧.append(块)
    类, 结 = {}, None
    for 块 in 帧:
        k, d = "", ""
        for l in 块.split("\n"):
            if l.startswith("event: "):
                k = l[7:].strip()
            elif l.startswith("data: "):
                d = l[6:]
        类[k] = 类.get(k, 0) + 1
        if k == "result":
            结 = json.loads(d)
    return r.status, 类, 结, "\n".join(帧)


def 收页面(址):
    """把首页整页拉回来：JS 语法错时 SSE 照样通，但页面是死的 —— 这一读专治那种"后端全绿、前端全黑"。"""
    import urllib.request
    with urllib.request.urlopen(址, timeout=10) as r:
        return r.read().decode("utf-8", "replace"), r.status


def main():
    L.append("AgentHub 验收复跑 · 全部数字现算（工具/验收.py）")
    L.append("生成时刻（本机钟）：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))

    # —— 闸 1：go test ——
    rc, out = run([GO, "test", "-count=1", "./..."], SRC)
    n_test = len(re.findall(r"^func Test", open(os.path.join(SRC, "hubd_test.go"), encoding="utf-8").read(), re.M))
    L.append("闸 1 go test：退出码=%d ｜ Test 函数（^func Test 现数）=%d ｜ 尾行：%s" % (rc, n_test, out.strip().splitlines()[-1:]))
    if rc != 0:
        红.append("闸 1 没绿")

    # —— 闸 1b：前端脚本语法自检（一个 JS 语法错会让整页静默死掉：
    #      头不动、时间线空、注册表 0 行，而 Go 那边一切正常）——
    js = os.path.join(SRC, "web", "app.js")
    rc, out = run(["node", "--check", js], SRC)
    if rc == 127:
        L.append("闸 1b 前端语法（node --check）：NOT_RUN —— 本机找不到 node ⇒ 这一道没跑，别当过")
        没跑.append("闸 1b 没跑（缺 node）")
    else:
        L.append("闸 1b 前端语法（node --check app.js）：退出码=%d ｜ %s" % (rc, out.strip()[:180] or "语法过"))
        if rc != 0:
            红.append("闸 1b：app.js 语法不过 ⇒ 页面会整页静默死掉（Go 侧全绿也救不了）")

    # —— 编出 exe（后面三道闸都要用它；go run 会让"跑的是哪一份"这件事含糊）——
    exe = os.path.join(ROOT, "构建-hubd", "hubd-验收.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    rc, out = run([GO, "build", "-o", exe, "."], SRC)
    if rc != 0:
        L.append("闸 2–5：**没跑** —— exe 编不出来：%s" % out.strip()[-300:])
        红.append("闸 2–5 没跑")
        return 收尾()
    字 = os.path.getsize(exe)
    哈希 = hashlib.sha256(open(exe, "rb").read()).hexdigest()[:16]
    L.append("  （跑的就是这一份：%s ｜ %d 字节 ｜ sha16 %s）" % (os.path.relpath(exe, ROOT), 字, 哈希))

    # —— 闸 2：selfcheck ——
    rc, out = run([exe, "-selfcheck"], SRC)
    ok = len(re.findall(r"^\[OK \]", out, re.M))
    bad = len(re.findall(r"^\[RED\]", out, re.M))
    自印 = re.findall(r"合计 (\d+) 条 ｜ \[RED\] (\d+) 条", out)
    L.append("闸 2 selfcheck：退出码=%d ｜ [OK ]=%d ｜ [RED]=%d ｜ 自印=%s ｜ 两读%s" % (
        rc, ok, bad, 自印, "一致" if 自印 and int(自印[0][0]) == ok + bad and int(自印[0][1]) == bad else "不一致"))
    if rc != 0 or bad != 0 or not 自印 or int(自印[0][0]) != ok + bad:
        红.append("闸 2 没绿或两读不一致")

    端 = 空端口()
    try:
        p, 健康 = 起服(exe, 端)
    except Exception as e:
        L.append("闸 3–5：**没跑** —— %s" % e)
        红.append("闸 3–5 没跑")
        return 收尾()
    try:
        # —— 闸 3：真收一发 SSE ——
        st, 类, 结, 原 = 收SSE(端, "列一下当前目录，按大小排，再统计最大的那个文件有多少行")
        件 = ["meta", "plan", "tool_status", "tool_result", "answer_delta", "result", "done"]
        缺 = [x for x in 件 if x not in 类]
        脏 = [w for w in ["undefined", "NaN", "[object Object]", "map[", "%!"] if w in 原]
        L.append("闸 3 端到端（127.0.0.1:%d）：HTTP=%d ｜ 事件种类=%s ｜ 步=%d ｜ 结束=%s" % (端, st, 类, len(结["steps"]), 结["stop"]))
        L.append("  五档=%s ｜ 加总对得上=%s ｜ 整列自洽=%s ｜ 屏幕脏字=%s ｜ 工具数=%d" % (
            结["mix"], 结["mix_ok"], 结["sane"], 脏, 健康["tools"]))
        # 页面自述端点也要活着：JS 语法错时 SSE 照样通，但整页是死的
        页, _ = 收页面("http://127.0.0.1:%d/" % 端)
        有脚本 = "/api/chat" in 页 and 'id="calls"' in 页
        L.append("  首页=%d 字节 ｜ 含 #calls 与 /api/chat 接线=%s" % (len(页), 有脚本))
        if 缺 or not 有脚本 or not 结 or 结["mix_ok"] is not True or 结["sane"] is not True or 脏 or st != 200:
            红.append("闸 3：事件缺 %s / 恒等 %s / 自洽 %s / 脏字 %s" % (缺, 结 and 结["mix_ok"], 结 and 结["sane"], 脏))

        # —— 闸 4：反臂（同一份件，只改旗标）——
        端2 = 空端口()
        p2, _ = 起服(exe, 端2, ["-max-steps", "1"])
        try:
            _, 类2, 结2, _ = 收SSE(端2, "列一下当前目录，按大小排，再统计最大的那个文件有多少行")
            咬住 = 结2["stop"] in ("步数上限", "重复失败即停") and len(结2["steps"]) <= 1
            L.append("闸 4a 反臂（-max-steps 1）：步=%d ｜ 结束=%s ｜ 上限真的在管=%s ｜ 整列自洽=%s" % (
                len(结2["steps"]), 结2["stop"], 咬住, 结2["sane"]))
            if not 咬住 or 结2["sane"] is not True:
                红.append("闸 4a：步数上限没管住（结束=%s 步=%d）" % (结2["stop"], len(结2["steps"])))
        finally:
            p2.kill()
        _, 类3, 结3, _ = 收SSE(端, "把结论存成笔记「验收.md」")
        挡 = [o for o in 结3["steps"] if o["tool"] == "notes.write"]
        咬住3 = bool(挡) and 挡[0]["class"] == "refused" and 挡[0]["attempts"] == 0 and 挡[0]["evidence"] == "absent"
        L.append("闸 4b 反臂（默认不放行写文件）：走没走=%s ｜ 类别=%s ｜ 试了几次=%s ｜ 读数档=%s" % (
            bool(挡), 挡 and 挡[0]["class"], 挡 and 挡[0]["attempts"], 挡 and 挡[0]["evidence"]))
        if not 咬住3:
            红.append("闸 4b：没放行却被调起了，或被调起却没记 absent 带理由")

        # —— 闸 5：扩展那一维（临时清单）——
        目 = os.path.join(tempfile.gettempdir(), "hubd-验收-清单")
        os.makedirs(目, exist_ok=True)
        名 = "验收探针.json"
        with open(os.path.join(目, 名), "w", encoding="utf-8") as f:
            json.dump({"name": "验收探针", "summary": "取这台服自己的 health", "risk": "net_local",
                       "timeout_ms": 2000, "retry": {"attempts": 1, "backoff_ms": 10, "backoff_max_ms": 50},
                       "triggers": ["探一下验收"],
                       "invoke": {"kind": "http_get", "url": "http://127.0.0.1:%d/api/health" % 端}}, f, ensure_ascii=False)
        端3 = 空端口()
        p3, 健康3 = 起服(exe, 端3, ["-tools-dir", 目])
        try:
            tjs = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/tools" % 端3, timeout=5).read().decode())
            多了 = any(s["name"] == "验收探针" for s in tjs["specs"])
            _, _, 结4, _ = 收SSE(端3, "探一下验收")
            走了 = [o for o in 结4["steps"] if o["tool"] == "验收探针"]
            L.append("闸 5 扩展那一维：specs=%d ｜ 探针在册=%s ｜ 自然语言选起=%s ｜ 类别=%s ｜ 出处档=%s ｜ 被拒清单=%d" % (
                tjs["count"], 多了, bool(走了), 走了 and 走了[0]["class"], 走了 and 走了[0]["evidence"], len(tjs.get("rejected") or [])))
            if not 多了 or not 走了 or 走了[0]["class"] != "ok":
                红.append("闸 5：放一个清单没变成「能被自主选起并真跑」")
        finally:
            p3.kill()
            os.remove(os.path.join(目, 名))
    finally:
        p.kill()

    # —— 闸 6：界面读数新鲜度 ——
    源 = []
    # 前端文件也是源码：改了 CSS 却不重测界面读数，正是"绿得完全合理却描述的是上一版"那一族。
    for 根, _, 件名 in os.walk(SRC):
        for f in 件名:
            if f.endswith((".go", ".css", ".html", ".js")) and not f.endswith("_test.go"):
                源.append(os.path.join(根, f))
    源 = [x for x in 源 if os.path.sep + "tools" not in x]
    最新源 = max(源, key=os.path.getmtime) if 源 else None
    读目录 = os.path.join(ROOT, "读数")
    界面 = [os.path.join(读目录, f) for f in os.listdir(读目录)
            if f.endswith((".json", ".txt")) and any(k in f for k in ("浏览器", "SSE", "截图"))]
    截图目录 = os.path.join(读目录, "截图")
    if os.path.isdir(截图目录):
        界面 += [os.path.join(截图目录, f) for f in os.listdir(截图目录) if f.endswith(".png")]
    if not 最新源 or not 界面:
        L.append("闸 6 界面读数新鲜度：**没跑成** —— 找不到源码或界面读数")
        红.append("闸 6 找不到比对象")
    else:
        最新读 = max(界面, key=os.path.getmtime)
        新 = os.path.getmtime(最新读) - os.path.getmtime(最新源)
        L.append("闸 6 界面读数新鲜度：源码 %d 件，最新是 %s ｜ 界面读数 %d 份，最新是 %s ｜ 读数比源码新 %s" % (
            len(源), os.path.basename(最新源), len(界面), os.path.relpath(最新读, ROOT),
            ("%.0f 秒" % 新 if 新 > 0 else "**旧了 %.0f 分钟 ⇒ 界面类结论要重测**" % (-新 / 60))))
        if 新 < 0:
            红.append("闸 6：源码在 %s 又改过，最新的界面读数还是旧的" % os.path.basename(最新源))

    return 收尾()


def 收尾():
    L.append("")
    L.append("跑了 %d 条命令：%s" % (len(跑过), "；".join("%s→rc=%d(%d 字节)" % t for t in 跑过)))
    # 道数现数，不写死：加一道闸却忘了改"六道"这种话，报告就会一直说六道 —— 数出来的才作数。
    道 = len([x for x in L if x.startswith("闸 ")])
    L.append("结论：现数 %d 行闸读数%s" % (道, "全过" if not 红 and not 没跑 else "没全过"))
    if 红:
        L.append("  红的是：%s" % "；".join(红))
    if 没跑:
        L.append("  NOT_RUN：%s" % "；".join(没跑))
    txt = "\n".join(L) + "\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    print("写了 %s" % OUT)
    return 0 if not 红 else 1   # NOT_RUN 不判失败，但写在结论里，不当"过"


if __name__ == "__main__":
    sys.exit(main())
