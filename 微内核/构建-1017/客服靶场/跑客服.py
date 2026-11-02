# -*- coding: utf-8 -*-
"""客服靶场 runner —— 让内核接一个**有消费者形状**的负载：多轮、有历史、超额度会真裁、传输层自己数。

三态规矩（跑之前读一遍，跑完不许改口）：
  - 传输层能自己数的（wire_bytes_in/out、chunks、first_byte_ms、max_gap_ms）⇒ 量到了(measured)，值来自我数到的字节；
  - 只有对端知道的（prompt/completion tokens）⇒ 转述(relayed) + Source 写明是谁报的；对端流式给 0 就照记 0，不许补；
  - 我们估的（fixed_overhead、tokens 粗估）⇒ 估算(estimated) + Source 写依据；结构上没有的 ⇒ absent + 理由，不是记 0。
预检与落账的判定原样打印；被拒不重造载荷来糊过去（只在补齐确实缺的整块时重交，且逐次留下拒因）。
"""
import copy
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\Users\Admin\Desktop\微内核\微内核\微内核\tasks\mcp")
import client  # noqa: E402  复用仓库那份 Measure 形状，不另造一套「我以为内核收得下什么」

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL = "http://127.0.0.1:8797/mcp"
# 端点由环境变量决定：不设就是本地替身，设了就吃真流量（口令只走 env，绝不落进任何文件或读数）
LLM_URL = os.environ.get("CS_LLM", "http://127.0.0.1:8804/v1/chat/completions")
API_KEY = os.environ.get("AGNES_KEY", "")
MODEL = os.environ.get("AGNES_MODEL", "cs-flash")
_U = re.match(r"https?://([^/:]+)(?::(\d+))?(.*)$", LLM_URL)
HOST, PORT, RPATH = _U.group(1), int(_U.group(2) or (443 if LLM_URL.startswith("https") else 80)), _U.group(3)
TLS = LLM_URL.startswith("https")
REAL = "127.0.0.1" not in HOST
SESSION = os.environ.get("CS_SESSION", "客服靶场-真流量" if REAL else "客服靶场-替身")
CEIL, SLACK = 2048, 12
RELAYED, EST, MEAS, UNSET = 2, 3, 1, 0
LIMIT = int(CEIL * (100 - SLACK) / 100)
rid = [0]
rep = []
w = rep.append
CONTENT_RX = re.compile(r'"content":\s*"((?:[^"\\]|\\.)*)"')
FINISH_RX = re.compile(r'"finish_reason":\s*"([^"]+)"')
USAGE_RX = re.compile(r'"prompt_tokens":\s*(\d+),\s*"completion_tokens":\s*(\d+),\s*"total_tokens":\s*(\d+)')


def rpc(tool, args):
    rid[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": rid[0], "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode("utf-8")
    req = urllib.request.Request(KERNEL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8"))
    res = d.get("result", {})
    return "".join(x.get("text", "") for x in res.get("content", [])), res.get("isError")


def parts_of(turns):
    agg, order = {}, []
    for kind, text in turns:
        b = len(text.encode("utf-8"))
        if kind not in agg:
            agg[kind] = {"Kind": kind, "Parts": 0, "Bytes": 0}
            order.append(kind)
        agg[kind]["Parts"] += 1
        agg[kind]["Bytes"] += b
    ps = [agg[k] for k in order]
    return ps, order, sum(p["Bytes"] for p in ps)


def fold(turns, limit, refcall):
    """超额度就老实挤：整段随历史不发了（dropped-whole / ToBytes=0 / 带原文指纹），并附一段知情通知。
    两件事必须一起成立：① 插完通知之后**真的装得下**（上一版是先判字节再插通知，插完就超额度，
    内核当场报「内容 1843 超过生效额度 1802（本该被回夹；夹过 0 刀）」）；
    ② `ClampRounds` 记的是**把生效额度夹小了几刀**（input.go:229-233 每刀必须真变小），
    我这里额度一直是 1802 没动过 ⇒ 只能是 0 刀，不许为了"看起来处理过"而 +1。"""
    cuts, keep = [], [t for t in turns if t[0] != "truncation-notice"]
    while True:
        trial = list(keep)
        if cuts:
            trial.insert(1, ("truncation-notice", "（历史 %d 轮整段未发送，折叠表见 cuts）" % len(cuts)))
        _, _, total = parts_of(trial)
        if total <= limit:
            break
        idx = next((i for i, (k, _) in enumerate(keep) if k == "history"), None)
        if idx is None:
            break
        kind, text = keep.pop(idx)
        b = text.encode("utf-8")
        cuts.append({"Kind": kind,
                     "Ref": "坐席备注一段：整段随第 %d 发挤出（连桩也没发）" % refcall,
                     "RefCall": refcall, "Role": "assistant", "Squeeze": "dropped-whole",
                     "FromBytes": len(b), "ToBytes": 0, "SHA256": hashlib.sha256(b).hexdigest()})
    if cuts:
        keep.insert(1, ("truncation-notice", "（历史 %d 轮整段未发送，折叠表见 cuts）" % len(cuts)))
    return keep, cuts


def call_llm(turns, stream):
    """裸 socket 逐片 recv：首帧与帧间要的是「什么时候真开始收」。
    urllib 那种分块读会把「凑满一块的时刻」当成首帧（上一版就是这么把真端点的 1170ms 记成 205ms 的）。"""
    wire_msgs = [{"role": "user", "content": t} for _, t in turns]
    body = json.dumps({"model": MODEL, "stream": stream,
                       "messages": [{"role": "system", "content": "你是工单客服，只按工单库回答，库里没有就不编。"}] + wire_msgs},
                      ensure_ascii=False).encode("utf-8")
    head = ("POST %s HTTP/1.1\r\nHost: %s\r\n%sContent-Type: application/json\r\n"
            "Accept: text/event-stream\r\nConnection: close\r\nContent-Length: %d\r\n\r\n"
            % (RPATH, HOST, ("Authorization: Bearer %s\r\n" % API_KEY) if API_KEY else "", len(body))).encode("ascii")
    t0 = time.perf_counter()
    first, stamps, raw = None, [], b""
    with socket.create_connection((HOST, PORT), timeout=90) as sk:
        s = ssl.create_default_context().wrap_socket(sk, server_hostname=HOST) if TLS else sk
        s.sendall(head + body)
        while True:
            try:
                blk = s.recv(4096)
            except socket.timeout:
                break
            if not blk:
                break
            now = time.perf_counter()
            if first is None:
                first = now
            else:
                stamps.append(now)
            raw += blk
    ms_first = (first - t0) * 1000 if first else 0.0
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    _, _, payload = raw.partition(b"\r\n\r\n")
    src = payload.decode("utf-8", "replace")
    text, usage, obj, finish, chunks = "", {}, "", "stop", 1
    if stream:
        chunks = len([l for l in src.split("\n") if l.startswith("data:")])
        for m in CONTENT_RX.finditer(src):
            text += m.group(1)
        u = list(re.finditer(r'"prompt_tokens":\s*(\d+),\s*"completion_tokens":\s*(\d+)', src))
        if u:
            usage = {"prompt_tokens": int(u[-1].group(1)), "completion_tokens": int(u[-1].group(2))}
        obj = "chat.completion.chunk" if "chat.completion.chunk" in src else ""
        f = FINISH_RX.search(src)
        finish = f.group(1) if f else "stop"
    else:
        d = json.loads(src[src.index("{"):]) if "{" in src else {}
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message", {})
        text = msg.get("content") or ""
        rc = msg.get("reasoning_content")
        if rc:
            # 推理型模型把 token 花在 reasoning_content 上；它不是「原话」，所以不进 Says 那格的字节数，
            # 但账上要看得见有这一段 —— 否则 completion_tokens 与原话长度对不上就成了没人解释的差
            text += "\n[reasoning_content %d 字符，未计入原话字节]" % len(rc)
        usage = d.get("usage", {})
        obj = d.get("object", "")
        finish = ch.get("finish_reason") or "stop"
        usage["self_model"] = d.get("model", "")  # 对端自报的模型名，别拿我们请求里写的冒充它说过
    return len(body), len(raw), chunks, ms_first, (max(gaps) if gaps else 0.0), text, usage, obj, finish


def mk(shares_pcts, total):
    return shares_pcts, max(0, 100 - sum(shares_pcts.values()))


def book(session, n, turns, stream):
    ps, order, total = parts_of(turns)
    turns2 = turns
    cuts = []
    if total > LIMIT:
        turns2, cuts = fold(turns, LIMIT, max(1, n - 1))
        ps, order, total = parts_of(turns2)
    sent = bool(cuts)
    shares_pcts, _ = mk({p["Kind"]: (int(p["Bytes"] * 100 / total) if total else 0) for p in ps}, total)
    leftover = max(0, 100 - sum(shares_pcts.values()))
    wb_in, wb_out, nchunk, fb, gap, text, usage, obj, finish = call_llm(turns2, stream)
    tb = text.encode("utf-8")
    seg_order = [k for k, _ in turns2]  # Order 必须逐段（内核要它和段表是从同一批段数出来的），按类去重会被整发拒
    inp = {"Call": n, "Order": seg_order, "Parts": ps, "ContentBytes": total,
           "Tokens": client.m(int(total / 3), EST, "1 token ≈ 3 字节的粗估（靶场按段表字节推）"),
           "Budget": {"CallBytesCeiling": CEIL, "TransportSlackPct": SLACK, "ContentCeiling": LIMIT,
                      "Shares": shares_pcts, "LeftoverPct": leftover,
                      "FixedOverhead": client.m(48, EST, "system 头 + 模型名 + 工具清单的粗估"),
                      "EffectiveCeiling": LIMIT, "ClampRounds": 0},
           "Cuts": cuts,
           "Notice": {"Sent": sent, "Trimmed": False,
                      "Why": ("历史超额度，整段挤出 %d 段并附了知情通知；通知本身没被裁过" % len(cuts)) if sent else "这发没超额度，没挤过任何段，所以没发通知",
                      "Text": ("（历史 %d 轮整段未发送，折叠表见 cuts）" % len(cuts)) if sent else ""}}
    self_model = usage.pop("self_model", "")
    outp = {"Call": n, "Streaming": stream, "Finish": {"Reason": finish, "Said": bool(finish)},
            "Model": self_model, "ModelSaid": bool(self_model), "WireFormat": obj, "WireFormatSaid": bool(obj),
            "Says": {"Bytes": len(tb), "Kept": len(tb), "SHA256": hashlib.sha256(tb).hexdigest()},
            "UsageIn": client.m(int(usage.get("prompt_tokens", 0)), RELAYED,
                                "对端 usage.prompt_tokens（%s 自报%s）" % (MODEL, "；流式里它恒为 0 —— 对端不把账给到流式帧里" if stream else "")),
            "UsageOut": client.m(int(usage.get("completion_tokens", 0)), RELAYED,
                                 "对端 usage.completion_tokens（%s 自报%s）" % (MODEL, "；流式里它恒为 0" if stream else "")),
            # 方向按内核的定义接（output.go:142 请求体=out、:147 通道收到=in）——
            # 上一版我接反了，落进去的 9 发线字节两格是错标的，那本账只当形状用。
            "WireBytesOut": client.m(wb_in, MEAS), "WireBytesIn": client.m(wb_out, MEAS),
            "Chunks": client.m(nchunk, MEAS) if stream else client.missing("这一发不是流式的，结构上没有分帧"),
            "FirstByteMs": client.m(int(fb), MEAS) if stream else client.missing("这一发不是流式的，没有首帧这件事"),
            "MaxGapMs": client.m(int(gap), MEAS) if stream else client.missing("这一发不是流式的，没有帧间"),
            "ToolCalls": 0, "Malformed": 0, "MalformedStreak": 0,
            "Failure": {"Kind": "", "Detail": "",
                        "Status": client.missing("这一发没故障，也就没有要记的状态码"),
                        "RetryAfterMs": client.missing("这一发没断，也就没有要等多久"), "Downgrade": False}}
    pre, perr = rpc("kernel.check_call", {"session": session, "actor": "客服靶场-runner", "input": inp, "output": outp})
    ok = "整发可落账" in pre
    res = ""
    if ok:
        res, _ = rpc("kernel.record_call", {"session": session, "actor": "客服靶场-runner", "input": inp, "output": outp})
    w("【第 %d 发 %s】段表 %s ｜ 内容字节 %d（额度 %d）｜ 折叠 %d 段 ｜ 线入 %d 线出 %d ｜ 帧 %d 首帧 %dms 峰间 %dms ｜ 对端自报 usage=%s/%s ｜ object=%s ｜ 答复摘要=%s"
      % (n, "流式" if stream else "非流式", "/".join(order), total, LIMIT, len(cuts), wb_in, wb_out, nchunk,
         int(fb), int(gap), usage.get("prompt_tokens"), usage.get("completion_tokens"), obj or "（没自报）", text[:36]))
    w("   预检=%s ｜ isError=%s ｜ 原文：%s" % ("放行" if ok else "拒", perr, pre.strip().replace("\n", " ")[:700]))
    if ok:
        w("   落账原文：%s" % res.strip().replace("\n", " ")[:180])
    return ok, inp, outp


def needles(base_inp, base_out):
    cases = [
        ("N1 转述不带出处（UsageIn relayed、Source 空）", lambda o: o.__setitem__("UsageIn", client.m(120, RELAYED, ""))),
        ("N2 absent 却有数（Chunks Absent=true 且 N=7）", lambda o: o.__setitem__("Chunks", client.m(7, UNSET, "", True, "结构上没有分帧"))),
        ("N3 声称流式却没帧（Streaming=true 而 Chunks absent）", lambda o: (o.__setitem__("Streaming", True),
                                                                     o.__setitem__("Chunks", client.missing("假称流式")))),
        ("N4 usage 全 0 同时线字节记 measured（#47 那一族）", lambda o: (o.__setitem__("UsageIn", client.m(0, RELAYED, "对端流式给的 0")),
                                                                  o.__setitem__("UsageOut", client.m(0, RELAYED, "对端流式给的 0")))),
    ]
    w("")
    w("== 反针四根（只预检、不落账）==")
    for label, mut in cases:
        o = copy.deepcopy(base_out)
        mut(o)
        txt, err = rpc("kernel.check_call", {"session": "反针", "actor": "客服靶场-runner", "input": base_inp, "output": o})
        verdict = "拒" if ("会被拒" in txt or "参数被拒" in txt) else "没拦"
        w("%-56s ⇒ %s ｜ isError=%s ｜ %s" % (label, verdict, err, txt.strip().replace("\n", " ")[:200]))


def main():
    tickets = [json.loads(l) for l in open(os.path.join(HERE, "工单语料.jsonl"), encoding="utf-8") if l.strip()]
    hist = [("system", "只按工单库回答；库里没有的订单号不许引用金额或时效。")]
    for k in range(6):
        hist.append(("history", "第 %d 轮坐席内部备注：核对活动快照、物流回单与保司入口，措辞待统一，本条仅作会话背景留存以备追溯。" % k))
    w("== 客服靶场 · 带内核跑任务 10-17 22:20 ==")
    w("配置：额度上限 %d 字节、传输余量 %d%% ⇒ 内容额度 %d（这两个数是靶场设的，内核落账时会重算比对）" % (CEIL, SLACK, LIMIT))
    w("")
    ok = 0
    base_inp = base_out = None
    for i, t in enumerate(tickets, 1):
        turns = list(hist) + [("user", "工单 %s：%s（金额 %.2f，付款 %s，SLA %d 分钟）请给处置口径。"
                              % (t["order"], t["issue"], t["amount"], t["paid"], t["sla_min"]))]
        booked, inp, outp = book(SESSION, i, turns, stream=(i % 2 == 0))
        ok += 1 if booked else 0
        if base_inp is None and booked:
            base_inp, base_out = inp, outp
        hist.append(("history", "第 %d 轮坐席内部备注：核对活动快照、物流回单与保司入口，措辞待统一，本条仅作会话背景留存以备追溯。" % i))
    w("")
    w("-- 无依据那一发：客户报的订单号不在库里，还自带一个金额 --")
    turns = list(hist[:3]) + [("user", "客户报的工单是 SO-2026-9999-0000，他说金额 8888 元，请直接给退款口径。")]
    booked, _, _ = book(SESSION + "-无依据", 1, turns, stream=False)
    ok += 1 if booked else 0  # 上一版这里漏加 ⇒ 分母少 1，"8 发"其实是 9 发全落账（链上 1323→1764 = 9×49 格对得上）
    w("")
    w("== 收口 ==")
    w("落账成功 %d 发 ｜ 跑了 %d 发（分母：工单 %d 发 + 无依据 1 发）" % (ok, len(tickets) + 1, len(tickets)))
    for name, tool in [("verify", "kernel.verify"), ("tally", "kernel.tally"), ("readers", "kernel.readers_report")]:
        txt, _ = rpc(tool, {})
        txt = txt.strip().replace("\n", " ")
        w("%s：%s" % (name, txt[:420]))
    if base_out:
        needles(base_inp, base_out)
    out = "\n".join(rep) + "\n"
    os.makedirs(os.path.join(HERE, "读数"), exist_ok=True)
    with open(os.path.join(HERE, "读数", "靶场读数.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(out)


if __name__ == "__main__":
    main()
