# -*- coding: utf-8 -*-
"""fakellm_cs —— 客服靶场用的**替身端点**（不是真模型）。

它证明什么、不证明什么（照 tasks/probe/fakellm.py 那条自我限制写死在这儿）：
  证明：传输层形状 —— 线字节、SSE 分帧数、首帧时刻、帧间间隔、对端自报的 object 与 usage 字段。
  不证明：模型的客服水平，也不证明数字对不对 —— 它的回答按语料查表，查不到就照实说查不到。

它故意复刻 10-17 那条真端点上量到的形状（#47 那族）：
  非流式：usage 给真数；流式：usage 三个数**全 0**（对端在流式里不把账给你）。
这样靶场能自然产出「relayed 0 与 measured N 字节并排落在同一发」的账，
而不是靠人手工编一发 —— 区别很重要：前者是业务形状撞出来的，后者是我造给判据看的。
"""
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

CORPUS = [json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "工单语料.jsonl"),
                                       encoding="utf-8") if l.strip()]
BY_ORDER = {t["order"]: t for t in CORPUS}
ADDR = ("127.0.0.1", 8804)


def answer(prompt):
    """按语料查表；查不到就照实说 —— 靶场要的是「有没有依据」，不是回答漂不漂亮。"""
    hit = re.findall(r"SO-2026-\d{4}-\d{4}", prompt)
    if not hit:
        return "没有订单号，无法核实。请提供订单号。", "absent:无单号", False
    t = BY_ORDER.get(hit[-1])
    if t is None:
        return ("订单号 %s 在工单库里查不到，我不能凭它给任何金额或时效。" % hit[-1], "absent:库里没有", False)
    body = ("%s｜%s｜金额 %.2f 元｜付款 %s｜SLA %d 分钟｜政策：%s"
            % (t["order"], t["issue"], t["amount"], t["paid"], t["sla_min"], t["policy"]))
    return body, "KB:" + t["order"], True


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            return None, raw
        prompt = ""
        for m in req.get("messages", []):
            c = m.get("content")
            prompt += (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)) + "\n"
        return req, prompt.encode("utf-8")

    def do_GET(self):
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        req, sent = self._body()
        if req is None:
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        stream = bool(req.get("stream"))
        text, basis, known = answer(sent.decode("utf-8", "replace"))
        comp = "chat.completion.chunk" if stream else "chat.completion"
        # 故意按「有依据 / 无依据」把回答里的数字带上或不带 —— 判据要能对质的是账，不是这句话
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in re.findall(r".{1,12}", text, re.S):
                chunk = {"object": comp, "choices": [{"delta": {"content": piece}, "index": 0, "finish_reason": None}],
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.02)
            last = {"object": comp, "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            self.wfile.write(("data: " + json.dumps(last, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        usage = {"prompt_tokens": len(sent) // 3, "completion_tokens": len(text) // 3,
                 "total_tokens": (len(sent) + len(text)) // 3}
        out = {"id": "cs-%d" % int(time.time() * 1000), "object": comp, "model": req.get("model", "cs-flash"),
               "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
               "usage": usage, "x_evidence": basis, "x_known": known}
        b = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


if __name__ == "__main__":
    print("fakellm_cs on http://%s:%d/v1/chat/completions ｜ 语料 %d 单" % (ADDR[0], ADDR[1], len(CORPUS)), flush=True)
    HTTPServer(ADDR, H).serve_forever()
