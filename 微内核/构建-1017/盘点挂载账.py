"""挂载通道只读盘点：把 tally / verify / readers_report 原文拿回来，
再把 read_back 两侧每一格的 Basis 摊开逐名数，看 measured 那一桶到底是哪些格。"""
import json
import urllib.request

URL = "http://127.0.0.1:8797/mcp"
BASIS = {0: "没填", 1: "量到了", 2: "转述", 3: "估算", 4: "模型自己说", 5: "缺席"}


def rpc(method, params=None, i=[0]):
    i[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": i[0], "method": method,
                       "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8"))
    c = d.get("result", {}).get("content", [])
    return "".join(x.get("text", "") for x in c), bool(d.get("result", {}).get("isError"))


def show(label, method, params=None):
    txt, err = rpc(method, params)
    print("--- %s（isError=%s）---" % (label, err))
    print(txt.strip()[:900])
    print()
    return txt


show("tally", "tools/call", {"name": "kernel.tally", "arguments": {}})
show("verify", "tools/call", {"name": "kernel.verify", "arguments": {}})
show("readers_report", "tools/call", {"name": "kernel.readers_report", "arguments": {}})

buckets = {}
for side in ("input", "output"):
    txt, err = rpc("tools/call", {"name": "kernel.read_back",
                                 "arguments": {"session": "mount-check", "call": 1, "side": side}})
    print("--- read_back %s（isError=%s）前 700 字 ---" % (side, err))
    print(txt.strip()[:700])
    lines = txt.splitlines()
    for l in lines:
        for b, name in BASIS.items():
            if name in l:
                buckets.setdefault(name, []).append("%s: %s" % (side, l.strip()[:70]))
    print()
print("=== 按出处桶逐名计数（我从 read_back 行数里现数）===")
for name in BASIS.values():
    print("  %-8s %d 行" % (name, len(buckets.get(name, []))))
print()
for name, rows in buckets.items():
    if name == "量到了":
        print("「量到了」逐行：")
        for r in rows[:40]:
            print("   " + r)
