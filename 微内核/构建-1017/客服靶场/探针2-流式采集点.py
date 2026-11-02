# -*- coding: utf-8 -*-
"""探针2 —— 问一件事：那三格「传输层·流式回调」的采集点是真在帧上取的，还是退化的。

只打传输层自己数到的东西（块大小、每块到达时刻、响应头），不碰账、不碰内核。
用的请求与 跑客服.py 的 call_llm 同一份装配（同一段历史 + 同一条工单），
所以读数可以和 探针读数.txt 里那一发对得上。
"""
import importlib.util
import json
import os
import socket
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("paocsfw2", os.path.join(HERE, "跑客服.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
call_llm = R.call_llm

out = []
w = out.append
NOTE = "第 %d 轮坐席内部备注：核对活动快照、物流回单与保司入口，措辞待统一，本条仅作会话背景留存以备追溯。"
turns = [("system", "只按工单库回答；库里没有的订单号不许引用金额或时效。")] + \
        [("history", NOTE % k) for k in range(6)] + \
        [("user", "工单 SO-2026-0417-8802：商品与页面描述不符（内存容量），要求退货退款并承担运费（金额 1299.00，"
                  "付款 2026-10-09，SLA 60 分钟）请给处置口径。")]

w("== 探针2 · 流式采集点是真回调还是退化读数 · 10-17 22:55 ==")
msgs = [{"role": "user", "content": t} for _, t in turns]
body = json.dumps({"model": "cs-flash", "stream": True,
                   "messages": [{"role": "system", "content": "你是工单客服，只按工单库回答，库里没有就不编。"}] + msgs},
                  ensure_ascii=False).encode("utf-8")

# 一、走 跑客服.py 用的那把尺子（urllib + read(2048)），把每一块的到达时刻逐块打出来
req = urllib.request.Request(R.LLM, data=body, method="POST")
req.add_header("Content-Type", "application/json")
t0 = time.perf_counter()
blocks = []
with urllib.request.urlopen(req, timeout=25) as r:
    w("响应头（urllib 看到的）：%s" % dict(r.headers))
    while True:
        n0 = time.perf_counter()
        blk = r.read(2048)
        if not blk:
            break
        blocks.append((len(blk), round((n0 - t0) * 1000), round((time.perf_counter() - t0) * 1000)))
total_ms = round((time.perf_counter() - t0) * 1000)
w("urllib 这把尺子读到的块数 = %d ｜ 整趟耗时 %dms" % (len(blocks), total_ms))
for i, (n, at, done) in enumerate(blocks, 1):
    w("   块 %d：%d 字节 ｜ 进 read() 于 +%dms ｜ 出 read() 于 +%dms" % (i, n, at, done))
wb_in, wb_out, nchunk, fb, gap, text, usage, obj, finish = call_llm(turns, True)
w("同一发再按 call_llm 跑一遍：线请求体 %d ｜ 通道收到 %d ｜ 数到的分帧 %d ｜ 首块 %dms ｜ 峰间 %dms ｜ usage=%s"
  % (wb_in, wb_out, nchunk, int(fb), int(gap), usage))
w("（对得上探针读数.txt 第 2 发那几格：chunks=%d、first_byte_ms=%d、max_gap_ms=%d）" % (nchunk, int(fb), int(gap)))

# 二、裸 socket 逐字节读，看对是不是一口气到齐（SSE 的帧本身是分次 flush 出来的）
s = socket.create_connection(("127.0.0.1", 8804), timeout=25)
s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1:8804\r\nContent-Type: application/json\r\n"
          b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
t0 = time.perf_counter()
sizes = []
while True:
    n0 = time.perf_counter()
    blk = s.recv(4096)
    if not blk:
        break
    sizes.append((len(blk), round((n0 - t0) * 1000)))
s.close()
w("裸 socket 收到的片数 = %d ｜ 整趟 %dms" % (len(sizes), round((time.perf_counter() - t0) * 1000)))
for i, (n, at) in enumerate(sizes[:20], 1):
    w("   片 %d：%d 字节 ｜ 到达 +%dms" % (i, n, at))
w("")
w("判读要问的：如果 urllib 那把尺子只拿到 1 块，那么 first_byte_ms 记的就不是「首帧」而是「整包读完」，")
w("           max_gap_ms 恒 0（没有第二块就没有帧间），chunks 是从收到的字节里数 \\n\\n 数出来的 —— 三格的词还在，")
w("           取数点已经不是流式回调那一个。这一条只能由靶场自己的读数说，不能由猜。")

os.makedirs(os.path.join(HERE, "读数"), exist_ok=True)
with open(os.path.join(HERE, "读数", "探针2-流式采集点.txt"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(out) + "\n")
print("written %d lines" % len(out))
