# -*- coding: utf-8 -*-
"""探针 —— 只干一件事：拿拒因问出「门要什么键」，然后按问到的答案如实装配再落账。

三态规矩一条没动（跑完不许改口）：
  - 通道上自己数得到的（请求体字节 / 收到的字节 / 分帧 / 首帧 / 帧间）⇒ measured；
  - 只有对端知道的 token ⇒ relayed + Source 写明是谁报的，对端流式给 0 就照记 0；
  - 我们估的（tokens 粗估 / fixed_overhead）⇒ estimated + Source；
  - 结构上没有的 ⇒ absent + 理由（不是 0）。
本探针改的只有**装配形状**（发送顺序表怎么列、裁剪表用哪几个键名、回夹刀数记几、通知段留不留位置），
因为那几处是第一轮 9 发全被预检挡下的原因；每一处改动下面都留着「拒因问出来的原话」。

方向那一格：契约写的是 wire_bytes_out = 真过网线的**请求体**字节、wire_bytes_in = **通道上收到的**字节
（output.go:142/147，Check 里点名的也是「过网线的请求体字节」「通道上收到的字节」）。
跑客服.py 把这两个数接反了（wb_in 取的是请求体、wb_out 取的是收到的），本探针按契约方向记，
两个数在打印行里分开写出来，便于回头对。

只预检不落账的问门段：所有 P* 探针只调 kernel.check_call，链上一条不写。
"""
import hashlib
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("paocsfw", os.path.join(HERE, "跑客服.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)                     # 复用同一份测量代码，不另造一套尺子

rpc, call_llm, parts_of, client = R.rpc, R.call_llm, R.parts_of, R.client
RELAYED, EST, MEAS = R.RELAYED, R.EST, R.MEAS
CEIL, SLACK, LIMIT = R.CEIL, R.SLACK, R.LIMIT
NOTICE = "（历史 %d 轮已折叠，折叠表见 cuts）"
SYS = "只按工单库回答；库里没有的订单号不许引用金额或时效。"
NOTE = "第 %d 轮坐席内部备注：核对活动快照、物流回单与保司入口，措辞待统一，本条仅作会话背景留存以备追溯。"

out = []
w = out.append


def ask(label, inp, op, note=""):
    """只问门（check_call），一条不落账。"""
    txt, err = rpc("kernel.check_call", {"session": "探针-问门", "actor": "客服靶场-探针",
                                         "input": inp, "output": op})
    w("〔%s〕%s" % (label, note))
    w("   预检原文：%s" % txt.strip().replace("\n", " "))
    return txt


def with_notice(keep, cuts):
    if not cuts:
        return list(keep)
    return keep[:1] + [("truncation-notice", NOTICE % len(cuts))] + keep[1:]


def squeeze(turns, n, reserve):
    """把最旧的历史轮整段挤出，直到装得下。reserve=True 时把那句通知自己的字节也算进额度里
    （第一轮跑客服.py 的 fold 没算，于是插回通知之后内容又超了额度 —— 那是要问门的事）。"""
    keep, cuts = list(turns), []
    while True:
        total = parts_of(with_notice(keep, cuts) if reserve else keep)[2]
        if total <= LIMIT:
            break
        idx = next((i for i, (k, _) in enumerate(keep) if k == "history"), None)
        if idx is None:
            break
        cuts.append(keep.pop(idx))
    sent = with_notice(keep, cuts)
    honest = []
    for kind, text in cuts:
        b = text.encode("utf-8")
        honest.append({"Kind": kind,
                       "Ref": "坐席备注一段：最后一次整段随第 %d 发发出，第 %d 发超额度时整段挤出（连桩也没发）"
                              % (max(1, n - 1), n),
                       "RefCall": max(1, n - 1), "Role": "user", "Squeeze": "dropped-whole",
                       "FromBytes": len(b), "ToBytes": 0,
                       "SHA256": hashlib.sha256(b).hexdigest()})
    return sent, honest


def shoot(session, n, turns, stream, fold="honest", order_mode="per_segment",
          cut_mode="honest", clamp="zero", notice_mode="honest", record=True, label=""):
    total0 = parts_of(turns)[2]
    sent, cuts = turns, []
    if total0 > LIMIT:
        sent, cuts = squeeze(turns, n, reserve=(fold == "honest"))
    if cut_mode == "bytes_action" and cuts:      # 第一轮跑客服.py 那张裁剪表的键名形状
        cuts = [{"Kind": c["Kind"], "Ref": c["Ref"], "RefCall": c["RefCall"],
                 "Bytes": c["FromBytes"], "Action": "folded"} for c in cuts]
    if cut_mode == "false_stub" and cuts:         # 声称折成了 40 字节的桩，而请求体里那段其实一个字都没进
        cuts = [dict(c, Squeeze="folded", ToBytes=40) for c in cuts]
    ps, kinds, total = parts_of(sent)
    order = [k for k, _ in sent] if order_mode == "per_segment" else kinds
    sent_bool = bool(cuts)
    notice = {"Sent": sent_bool, "Trimmed": False,
              "Why": ("历史超额度，整段挤出 %d 轮并附通知" % len(cuts)) if sent_bool
                     else "这发没超额度，没折叠没裁尾，所以没发提示",
              "Text": (NOTICE % len(cuts)) if sent_bool else ""}
    if notice_mode == "sent_without_part":
        notice = {"Sent": True, "Trimmed": False, "Why": "探针：段表里没装配通知段却声称发出去了", "Text": "探针串"}
    if notice_mode == "sent_but_trimmed":
        notice = {"Sent": False, "Trimmed": True, "Why": "探针：没说出去却被裁了半句", "Text": ""}
    if notice_mode == "cut_without_notice":
        notice = {"Sent": False, "Trimmed": False, "Why": "", "Text": ""}
    shares = {p["Kind"]: (int(p["Bytes"] * 100 / total) if total else 0) for p in ps}
    req_bytes, recv_bytes, nchunk, fb, gap, text, usage, obj, finish = call_llm(sent, stream)
    tb = text.encode("utf-8")
    inp = {"Call": n, "Order": order, "Parts": ps, "ContentBytes": total,
           "Tokens": client.m(int(total / 3), EST, "1 token ≈ 3 字节的粗估（靶场按段表字节推）"),
           "Budget": {"CallBytesCeiling": CEIL, "TransportSlackPct": SLACK, "ContentCeiling": LIMIT,
                      "Shares": shares, "LeftoverPct": max(0, 100 - sum(shares.values())),
                      "FixedOverhead": client.m(48, EST, "system 头 + 模型名 + 工具清单的粗估"),
                      "EffectiveCeiling": LIMIT,
                      "ClampRounds": (len(cuts) if clamp == "as_cuts" else 0)},
           "Cuts": cuts, "Notice": notice}
    op = {"Call": n, "Streaming": stream, "Finish": {"Reason": finish, "Said": True},
          "Model": "cs-flash", "ModelSaid": True, "WireFormat": obj, "WireFormatSaid": bool(obj),
          "Says": {"Bytes": len(tb), "Kept": len(tb), "SHA256": hashlib.sha256(tb).hexdigest()},
          "UsageIn": client.m(int(usage.get("prompt_tokens", 0)), RELAYED, "对端 usage.prompt_tokens（cs-flash 自报）"),
          "UsageOut": client.m(int(usage.get("completion_tokens", 0)), RELAYED, "对端 usage.completion_tokens（cs-flash 自报）"),
          "WireBytesIn": client.m(recv_bytes, MEAS), "WireBytesOut": client.m(req_bytes, MEAS),
          "Chunks": client.m(nchunk, MEAS) if stream else client.missing("这一发不是流式的，结构上没有分帧"),
          "FirstByteMs": client.m(int(fb), MEAS) if stream else client.missing("这一发不是流式的，没有首帧这件事"),
          "MaxGapMs": client.m(int(gap), MEAS) if stream else client.missing("这一发不是流式的，没有帧间"),
          "ToolCalls": 0, "Malformed": 0, "MalformedStreak": 0,
          "Failure": {"Kind": "", "Detail": "",
                      "Status": client.missing("这一发没故障，也就没有要记的状态码"),
                      "RetryAfterMs": client.missing("这一发没断，也就没有要等多久"), "Downgrade": False}}
    if not record:
        return inp, op
    pre, perr = rpc("kernel.check_call", {"session": session, "actor": "客服靶场-探针", "input": inp, "output": op})
    ok = "整发可落账" in pre
    res = ""
    if ok:
        res, _ = rpc("kernel.record_call", {"session": session, "actor": "客服靶场-探针", "input": inp, "output": op})
    w("【第 %d 发 %s%s】发送顺序表 %d 项 ｜ 段表 %s ｜ 内容字节 %d（额度 %d）｜ 裁剪 %d 段 ｜ 请求体过网线 %d ｜ 通道收到 %d "
      "｜ 帧 %d 首帧 %dms 峰间 %dms ｜ 对端自报 usage=%s/%s ｜ object=%s ｜ 答复摘要=%s"
      % (n, "流式" if stream else "非流式", " " + label if label else "", len(order),
         "/".join(p["Kind"] for p in ps), total, LIMIT, len(cuts), req_bytes, recv_bytes, nchunk, int(fb), int(gap),
         usage.get("prompt_tokens"), usage.get("completion_tokens"), obj or "（没自报）", text[:36]))
    w("   预检=%s ｜ isError=%s ｜ 原文：%s" % ("放行" if ok else "拒", perr, pre.strip().replace("\n", " ")))
    if ok:
        w("   落账原文：%s" % res.strip().replace("\n", " "))
    return ok, inp, op


def main():
    tickets = [json.loads(l) for l in open(os.path.join(HERE, "工单语料.jsonl"), encoding="utf-8") if l.strip()]

    def user(t):
        return ("user", "工单 %s：%s（金额 %.2f，付款 %s，SLA %d 分钟）请给处置口径。"
                % (t["order"], t["issue"], t["amount"], t["paid"], t["sla_min"]))

    # 第 7 发当时手上那份历史：6 段种子备注 + 前 6 发各留下的 1 段 = 12 段历史
    hist7 = [("system", SYS)] + [("history", NOTE % k) for k in range(6)] + [("history", NOTE % i) for i in range(1, 7)]
    short = [("system", SYS), ("history", NOTE % 0), ("history", NOTE % 1)]

    w("== 探针-门要什么键 · 10-17 22:45 ==")
    txt, _ = rpc("kernel.tally", {})
    w("跑之前 tally：%s" % txt.strip().replace("\n", " "))
    w("")
    w("== 第一段：拿拒因问门（全部只预检、不落账）==")
    ask("P0 原样复现第一轮第 7/8 发的形状（Order 按类去重 + 裁剪表 Bytes/Action）",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, fold="runner",
               order_mode="by_kind", cut_mode="bytes_action", record=False)[:2],
        note="问：外壳门口与内核判据，谁先说话")
    ask("P1 只把 Order 修成逐段，裁剪表仍是 Bytes/Action",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, fold="runner",
               cut_mode="bytes_action", record=False)[:2],
        note="问：门口认不认这张裁剪表")
    ask("P2 Order 逐段 + 裁剪表换成真键名 + ClampRounds=0（仍是第一轮的折法，通知不占额度）",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, fold="runner", record=False)[:2],
        note="问：门口放行之后，内核里还压着一条什么")
    ask("P3 折法改成「先给通知留出位置」，但刀数仍记成裁剪段数",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, clamp="as_cuts", record=False)[:2],
        note="问：把「挤了几段」写成「回夹了几刀」，内核收不收")
    ask("P4 问出来的答案：逐段 Order + 真键名裁剪表 + 通知占位 + ClampRounds=0",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, record=False)[:2],
        note="这一发靶场挤的是整段，预算额度一刀没夹过")
    ask("P5 同 P4，却把挤掉的段记成 folded/ToBytes=40（桩其实没进请求体）",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, cut_mode="false_stub", record=False)[:2],
        note="问：账上声称留了 40 字节的桩，而实际一个字都没发 —— 有没有第三格能说话")
    ask("P6 未折叠那一发把 Notice.Sent 记成 true（段表里没有通知段）",
        *shoot("探针-问门", 1, short + [user(tickets[0])], False, notice_mode="sent_without_part", record=False)[:2],
        note="问：Notice 在未折叠时该给什么")
    ask("P7 未折叠那一发 Sent=false 同时 Trimmed=true",
        *shoot("探针-问门", 1, short + [user(tickets[0])], False, notice_mode="sent_but_trimmed", record=False)[:2],
        note="问：没发出去的东西能不能被裁半句")
    ask("P8 挤了 2 段却不发通知、Why 也留空",
        *shoot("探针-问门", 7, hist7 + [user(tickets[6])], False, notice_mode="cut_without_notice", record=False)[:2],
        note="问：只写进账本、没发出去那一族")
    w("")
    w("== 第二段：按问到的答案如实装配，真跑真落账（替身端点，不是真实模型观测）==")
    hist = [("system", SYS)] + [("history", NOTE % k) for k in range(6)]
    ok = 0
    booked = {}
    for i, t in enumerate(tickets, 1):
        r, inp, op = shoot("客服靶场", i, list(hist) + [user(t)], stream=(i % 2 == 0), record=True)
        if r:
            ok += 1
            booked[i] = (inp, op)
        hist.append(("history", NOTE % i))
    w("")
    r, _, _ = shoot("客服靶场-无依据", 1, list(hist[:3]) +
                    [("user", "客户报的工单是 SO-2026-9999-0000，他说金额 8888 元，请直接给退款口径。")],
                    False, record=True, label="（无依据）")
    ok += 1 if r else 0
    w("")
    w("落账成功 %d 发 ｜ 跑了 9 发（分母：工单 8 发 + 无依据 1 发）" % ok)
    w("")
    w("== 第三段：收口三件 + 逐格读回 ==")
    for name, tool in [("verify", "kernel.verify"), ("tally", "kernel.tally"), ("readers", "kernel.readers_report")]:
        txt, _ = rpc(tool, {})
        w("%s（全文不截断）：%s" % (name, txt.strip().replace("\n", " ")))
    w("")
    for i in sorted(booked):
        for side in ("output", "input"):
            txt, _ = rpc("kernel.read_back", {"session": "客服靶场", "call": i, "side": side})
            w("-- read_back 客服靶场 第 %d 发 %s 侧 --" % (i, side))
            for ln in txt.strip().splitlines():
                w("   " + ln)
    txt, _ = rpc("kernel.read_back", {"session": "客服靶场-无依据", "call": 1, "side": "output"})
    w("-- read_back 客服靶场-无依据 第 1 发 output 侧 --")
    for ln in txt.strip().splitlines():
        w("   " + ln)
    w("")
    w("== 第四段：四根反针（用跑客服.py 里那一份 needles，一字没改；只预检不落账）==")
    mark = len(R.rep)
    first = booked.get(1)
    if first:
        R.needles(first[0], first[1])
        for ln in R.rep[mark:]:
            w(ln)
    else:
        w("第 1 发没落账成功，反针没有可用的 base —— 这一趟反针没跑成，不许读成「反针没命中」。")
    txt, _ = rpc("kernel.tally", {})
    w("")
    w("收口后 tally：%s" % txt.strip().replace("\n", " "))
    os.makedirs(os.path.join(HERE, "读数"), exist_ok=True)
    with open(os.path.join(HERE, "读数", "探针读数.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("written %d lines; booked=%d" % (len(out), ok))


if __name__ == "__main__":
    main()
