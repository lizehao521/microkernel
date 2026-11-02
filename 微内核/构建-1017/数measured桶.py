"""把 read_back 的每一行按 `键名 basis 值` 拆开，机械地数出：
measured 这一桶里，值其实是「是/否/空/0 段」这类**调用方断言的旗标或空文本**的有几格。
分母也印，不让你只看到分子。"""
import json
import re
import urllib.request

URL = "http://127.0.0.1:8797/mcp"
FLAG = re.compile(r"^(是|否|（这一格是空的）|（空）|0 段.*|（裁剪表是空的）|)$")


def rpc(method, params=None, i=[0]):
    i[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": i[0], "method": method, "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8"))
    c = d.get("result", {}).get("content", [])
    return "".join(x.get("text", "") for x in c), bool(d.get("result", {}).get("isError"))


def cells(side, call):
    txt, err = rpc("tools/call", {"name": "kernel.read_back",
                                 "arguments": {"session": "mount-check", "call": call, "side": side}})
    out = []
    for l in txt.splitlines():
        m = re.match(r"^([a-z_0-9]+)\s+(measured|estimated|relayed|absent|model_says|unset)\s+(.*)$", l.strip())
        if m:
            out.append(m.groups())
    return txt, out


for call in (1, 2, 3):
    total = 0
    buckets = {}
    flagged = []
    hits = 0
    for side in ("input", "output"):
        txt, cs = cells(side, call)
        if "没有" in txt[:80] or "读不到" in txt[:80] or not cs:
            continue
        hits += 1
        for key, basis, val in cs:
            total += 1
            buckets[basis] = buckets.get(basis, 0) + 1
            if basis == "measured" and FLAG.match(val.strip()):
                flagged.append((side, key, val.strip()[:40]))
    if not hits:
        print("第 %d 发：read_back 两侧都没有内容 ⇒ 这一发不存在（不再往下数）" % call)
        continue
    print("第 %d 发：读到 %d 侧 ｜ 格子分母 %d ｜ 按出处桶 %s" % (call, hits, total, buckets))
    print("   其中记成 measured 但值是旗标/空文本/0 段的：%d 格" % len(flagged))
    for side, key, val in flagged:
        print("     %-6s %-22s 值=%r" % (side, key, val))
    print()
