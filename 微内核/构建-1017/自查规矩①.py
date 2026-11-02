"""自己复现那三条断言（只走 check_call —— 它按设计一条都不写回链）。
先立正对照：仓库自带驱动那份合法载荷必须被放行；它不放行就是我这套对接写错了，不是内核红。
然后逐名只改一个地方，看门说什么：
  A 量到了(Basis=1) + Source 空 + N=4096          —— 契约说这些格的出处列是 owner，预期放行
  B 估算(Basis=3) + Source 空                     —— 「规矩①」该不该有 enforcing 分支
  C 非法码(Basis=9) + 带 Source                   —— Basis 值域校不校验
  D 转述(Basis=2) + Source 空                      —— 与 B 同族，分开数
  E Cuts 整块不给 vs 给空表                        —— 「没给与给了零值是两件事」在这一族生不生效
"""
import copy
import json
import sys
import urllib.request

sys.path.insert(0, r"C:\Users\Admin\Desktop\微内核\微内核\微内核\tasks\mcp")
import client  # noqa: E402  复用仓库自带的合法载荷，不另造一套「我以为内核收得下什么」

URL = "http://127.0.0.1:8797/mcp"


def call(tool, args, i=[0]):
    i[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": i[0], "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    res = d.get("result", {})
    txt = "".join(x.get("text", "") for x in res.get("content", []))
    return txt, res.get("isError")


def verdict(txt):
    if "会被拒" in txt or "参数被拒" in txt or "整发拒收" in txt:
        return "拒"
    if "自洽" in txt or "可落账" in txt or "预检与落账同判" in txt or "会收下" in txt:
        return "放行"
    return "读不出"


def run(label, inp, out, session):
    txt, err = call("kernel.check_call", {"session": session, "actor": "selfcheck",
                                          "input": inp, "output": out})
    print("[%s] 判定=%s ｜ isError=%s" % (label, verdict(txt), err))
    print("      原文：%s" % txt.strip().replace("\n", " ")[:300])
    return txt


base_in, base_out = copy.deepcopy(client.INPUT1), copy.deepcopy(client.OUTPUT1)
run("正对照·仓库自带合法载荷", base_in, base_out, "sc-base")

a = copy.deepcopy(base_out)
a["WireBytesIn"] = client.m(4096, 1)          # 量到了，Source 空
run("A Basis=1 + Source 空 + N=4096", base_in, a, "sc-a")

b = copy.deepcopy(base_out)
b["WireBytesIn"] = client.m(4096, 3, "")       # 估算，Source 空 —— 规矩① 该管的形状
run("B Basis=3 估算 + Source 空", base_in, b, "sc-b")

c = copy.deepcopy(base_out)
c["WireBytesIn"] = client.m(4096, 9, "我编一个值域外的码")
run("C Basis=9 非法码 + 带 Source", base_in, c, "sc-c")

d = copy.deepcopy(base_out)
d["WireBytesIn"] = client.m(4096, 2, "")       # 转述，Source 空
run("D Basis=2 转述 + Source 空", base_in, d, "sc-d")

e1 = copy.deepcopy(base_in)
e2 = copy.deepcopy(base_in)
e1.pop("Cuts")                                 # 没给
e2["Cuts"] = []                                # 给了空表
t1 = run("E1 Cuts 整块不给", e1, base_out, "sc-e1")
t2 = run("E2 Cuts 给空表", e2, base_out, "sc-e2")
print("E1 与 E2 的回话逐字相同 = %s（%s 字 / %s 字）" % (t1 == t2, len(t1), len(t2)))

# 到这儿为止全部是 check_call —— 它按设计只读副本、一条都不写回链。
# 故意不把上面任何一发 record_call 落进链：B/C/D 带的是我编的 4096 与值域外的码，
# 落进真账就是把假数字钉进哈希链（那是污染，不是实验）。
# Cuts 的「没给 vs 空表」对照交给已经落过的两发（第 1 发省 Cuts、第 2 发给空表），读回来比逐格文本。
print()
for call_no in (1, 2):
    txt, err = call("kernel.read_back", {"session": "mount-check", "call": call_no, "side": "input"})
    keep = [l.strip() for l in txt.splitlines() if any(k in l for k in ("folded", "clipped", "dropped"))]
    print("第 %d 发读回裁剪三格：%s" % (call_no, " ｜ ".join(keep)))

tally, _ = call("kernel.tally", {})
print()
print("收口 tally 原文：%s" % tally.strip()[:400])
