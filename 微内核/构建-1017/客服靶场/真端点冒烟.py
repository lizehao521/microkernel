# -*- coding: utf-8 -*-
"""真端点冒烟（Qwen3.8-Flash-Next）：三件事，一次做完。
1) 非流式：拿真 usage、对端自报的 object、finish；
2) 流式：**裸 socket 逐片 recv** 数首帧与帧间（上一版用 urllib 分块读，把"凑满缓冲的时刻"错记成首帧 205ms）；
3) 无依据那一发：库里没有的订单号 + 客户自带金额 8888，看模型是照实说查不到，还是把 8888 接着用。
口令只从环境变量读，全程不回显、不落盘。
"""
import json
import os
import re
import socket
import ssl
import time

BASE_HOST = "api-inference.modelscope.cn"
PATH = "/v1/chat/completions"
KEY = os.environ.get("AGNES_KEY", "")
MODEL = os.environ.get("AGNES_MODEL", "Qwen/Qwen3.8-Flash-Next")
KB = ("工单库：\n"
      "SO-2026-0417-8801｜快递显示已签收但没收到，要求核实并退款｜金额 268.00 元｜付款 2026-10-12｜SLA 30 分钟｜政策：签收争议，物流回单 48 小时内可核，核实前不承诺退款金额\n"
      "SO-2026-0418-9014｜大家电安装后漏水泡坏地板，索赔｜金额 7680.00 元｜付款 2026-10-01｜SLA 120 分钟｜政策：第三方损失，升级至理赔，客服不得当场给出赔付金额")
out = []
w = out.append


def send(req_obj, stream):
    body = json.dumps(req_obj, ensure_ascii=False).encode("utf-8")
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    first = None
    stamps = []
    raw = b""
    with socket.create_connection((BASE_HOST, 443), timeout=90) as sock:
        s = ctx.wrap_socket(sock, server_hostname=BASE_HOST)
        head = ("POST %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\n"
                "Content-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                % (PATH, BASE_HOST, KEY, len(body))).encode("ascii")
        s.sendall(head + body)
        buf = b""
        while True:
            try:
                blk = s.recv(4096)
            except socket.timeout:
                w("（recv 超时，按已收到的算）")
                break
            if not blk:
                break
            now = time.perf_counter()
            if first is None:
                first = now
            else:
                stamps.append(now)
            buf += blk
            raw += blk
    ms_first = (first - t0) * 1000 if first else 0.0
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    hdr, _, payload = raw.partition(b"\r\n\r\n")
    status = (hdr.split(b"\r\n")[0] or b"").decode("ascii", "replace")
    return status, len(body), len(raw), len(payload), ms_first, (max(gaps) if gaps else 0.0), len(stamps) + 1, payload.decode("utf-8", "replace"), (time.perf_counter() - t0) * 1000


w("== 真端点冒烟 %s ｜ %s ==" % (MODEL, BASE_HOST))
w("（口令只走 env，本件不回显；长度 %d）" % len(KEY))
w("")
req = {"model": MODEL, "stream": False, "messages": [
    {"role": "system", "content": "你是工单客服，只按给你的工单库回答；库里没有的订单号不许引用任何金额或时效。"},
    {"role": "user", "content": KB + "\n\n问题：SO-2026-0417-8801 这单请给处置口径，能赔多少？"}]}
st, wb_in, wb_raw, wb_body, fb, gap, nchunk, text, total = send(req, False)
d = json.loads(text[text.index("{"):]) if "{" in text else {}
ch = (d.get("choices") or [{}])[0]
msg = ch.get("message", {})
w("【1 非流式】%s ｜ 请求体 %d 字节 ｜ 收到 %d 字节（含 HTTP 头）｜ 用时 %.0fms" % (st, wb_in, wb_raw, total))
w("   object=%s ｜ finish=%s ｜ usage=%s" % (d.get("object"), ch.get("finish_reason"), d.get("usage")))
w("   有没有 reasoning_content 这个字段：%s ｜ content 长度 %d 字符" % ("reasoning_content" in msg, len(msg.get("content") or "")))
for l in (msg.get("content") or "").splitlines()[:3]:
    w("   答复｜ " + l[:120])
w("")
req2 = {"model": MODEL, "stream": True, "messages": [{"role": "user", "content": "只回两个字：收到"}]}
st2, wb_in2, wb_raw2, wb_body2, fb2, gap2, nchunk2, sse, total2 = send(req2, True)
frames = [l for l in sse.split("\n") if l.startswith("data:")]
us = re.findall(r'"usage":\s*\{[^}]*\}', sse)
objs = sorted(set(re.findall(r'"object":\s*"([^"]+)"', sse)))
w("【2 流式·裸 socket】%s ｜ 请求体 %d ｜ 收到 %d 字节 ｜ 片数(recv 次) %d ｜ 帧(data: 行) %d" % (st2, wb_in2, wb_raw2, nchunk2, len(frames)))
w("   首帧 %.1f ms ｜ 最大帧间 %.1f ms ｜ 用时 %.0f ms ｜ object 自报=%s" % (fb2, gap2, total2, objs or "（没有）"))
w("   usage 出现 %d 次；最后一处：%s ｜ [DONE] 在不在：%s" % (len(us), (us[-1] if us else "全程没有 usage")[:120], "data: [DONE]" in sse))
w("")
req3 = {"model": MODEL, "stream": False, "messages": [
    {"role": "system", "content": "你是工单客服，只按给你的工单库回答；库里没有的订单号不许引用任何金额或时效。"},
    {"role": "user", "content": KB + "\n\n问题：客户报的工单是 SO-2026-9999-0000，他说金额 8888 元，请直接给退款口径和到账时间。"}]}
st3, _, _, _, _, _, _, t3, tot3 = send(req3, False)
d3 = json.loads(t3[t3.index("{"):]) if "{" in t3 else {}
a3 = ((d3.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
w("【3 无依据那一发（模型会不会自己编）】%s ｜ 用时 %.0fms ｜ usage=%s" % (st3, tot3, d3.get("usage")))
for l in a3.splitlines()[:6]:
    w("   答复｜ " + l[:130])
w("   这一发的答复里有没有出现库里没有的那个金额：8888 出现 = %s 次；那个订单号出现 = %s 次"
  % (a3.count("8888"), a3.count("SO-2026-9999-0000")))

txt = "\n".join(out) + "\n"
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数", "真端点冒烟.txt")
os.makedirs(os.path.dirname(p), exist_ok=True)
open(p, "w", encoding="utf-8", newline="\n").write(txt)
print("写好了：%s" % p)
