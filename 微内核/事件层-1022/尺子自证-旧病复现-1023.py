#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""尺子自证：把刚修掉的旧病分别注回内存里的尺子副本，看新臂会不会红。

（病有几条不写死在这儿 —— 末行的「自证共 N 条」由 checks 清单自己数。）

为什么要这件：A4/A5 是尺子自己的臂。它们在当前代码上「有效」只说明代码是对的，
不说明**臂在管这两件事**。这一件把病注回去，臂必须当场失效（打印「没处下手」或判红），
否则 A4b/A5 就是两条恒绿的装饰，正好是我一直骂的那族。

不改盘上的尺子：exec 一份字符串副本，OUT 指到 TEMP。
用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 尺子自证-旧病复现-1023.py
"""
import io
import json
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "证据模型核对.py")
TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "尺子自证-1023")
if not os.path.isdir(TMP):
    os.makedirs(TMP)

src = io.open(SRC, encoding="utf-8").read()
_relocated = src
src = src.replace('OUT = os.path.join(HERE, "读数-证据模型核对.txt")',
                  'OUT = os.path.join(r"%s", "out-probe.txt")' % TMP.replace("\\", "/"))
# 这一条必须有：没换掉的话三份副本会轮流盖掉真读数，最后一盖就把好读数吃干净。
assert src != _relocated, "OUT 没换到 TEMP —— 探针会盖掉盘上的读数，拒绝跑"

# 旧病一：slot() 只认字面量，追加式 SPEC["x"] = […] 读不到 ⇒ 那 7 槽被降成「仅存在性」。
R1 = (src.replace('            if base in ("SPEC", "RANGE") and isinstance(tgt.slice, ast.Constant):\n'
                  '                return base, tgt.slice.value\n'
                  '            return None\n',
                  '            return None\n'))
assert R1 != src, "旧病一没注进去（slot 的 Subscript 分支文本对不上）"

# 旧病二：audit 返回里 "mis" 写两遍，后者覆盖前者 ⇒ 符号档坏点只印不判。
R2 = src.replace('        "mis": judged,\n', '        "mis": judged,\n        "mis": mis,\n')
assert R2 != src, "旧病二没注进去（mis 那行文本对不上）"


def run(tag, code):
    """exec 一份尺子副本，回 (退出码, 符号可核条数, 每条臂的判决)。"""
    g = {"__file__": SRC, "__name__": "ruler_" + tag}
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    real_out, real_err = sys.__stdout__, sys.__stderr__
    try:
        # main() 末尾往 sys.stdout.buffer 写；换成 StringIO 会没 buffer，这里给个字节壳。
        class Shell:
            def __init__(self): self.buf = b""
            def write(self, b): self.buf += b
            buffer = property(lambda self: self)
            def flush(self): pass
        cap = Shell()
        sys.stdout = cap
        mod = types.ModuleType(g["__name__"])
        mod.__dict__.update(g)
        mod.__file__ = SRC
        exec(compile(code, SRC, "exec"), mod.__dict__)
        rc = mod.main()
        text = cap.buf.decode("utf-8", "replace")
    finally:
        sys.stdout = old
    sym = re.search(r"符号可核 (\d+) 条", text)
    verdicts = re.findall(r"^臂：(.+?) → (有效|失效)", text, re.M)
    noline = re.findall(r"^臂：(.+?) 没处下手", text, re.M)
    return {"tag": tag, "rc": rc, "sym": int(sym.group(1)) if sym else -1, "mod": mod,
            "arms": verdicts, "no_hand": noline, "text": text}


res = [run("ctrl", src), run("R1", R1), run("R2", R2)]


# ---- 第三个旧病：复合闸「红了但点不出罪名」----
# 02:0x 那趟复合跑里 go test 那一行 rc=1，而本件只留末两行 —— 末两行是包名不是 Test 名，
# 单独重跑又 rc=0，于是这次红既不能复现也不能归因。修法：红的那一道把 --- FAIL 的 Test 名
# 提取进读数行 + 全量输出落盘 + conclusion 点名是哪一行。这里把「提取」注回恒空，
# 罪名必须消失（证明是这条函数给的），而 rc 必须照旧红（证明变异没碰判据）。
GATE = os.path.join(HERE, "体检-全闸-1023.py")
gsrc = io.open(GATE, encoding="utf-8").read()
_g = gsrc.replace('ARMS = os.path.join(HERE, "读数", "臂检-全部族.jsonl")',
                  'ARMS = os.path.join(TMPG, "arms.jsonl")')
_g = _g.replace('REPORT = os.path.join(HERE, "报告-全闸.txt")',
                'REPORT = os.path.join(TMPG, "report.txt")')
_g = _g.replace('os.path.join(HERE, "读数", "红-全量-%s.txt"', 'os.path.join(TMPG, "红-全量-%s.txt"')
assert _g != gsrc and "TMPG" in _g, "复合闸探针的落点没换到 TEMP —— 它会盖掉盘上的 报告-全闸.txt，拒绝跑"
gsrc = _g
# 注病那一份：把「点名 Test」那一步拧成恒空（其余一字不动 ⇒ 判据与 rc 都不该变）
GMUT = gsrc.replace('    return re.findall(r"^--- FAIL: (\\S+)", out, re.M)', '    return []')
assert GMUT != gsrc, "旧病三没注进去（fail_names 的那行文本对不上）"

GO_CANNED = ("--- FAIL: TestFlakeExample (0.31s)\n"
             "    loop_test.go:88: 回执 12ms 超了预算\n"
             "FAIL\nFAIL\tagentkernel/cmd/agentd\t27.669s\nFAIL\n")


class _FakeCompleted:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class _FakeSubprocess:
    @staticmethod
    def run(args, cwd=None, capture_output=False, text=False, encoding=None, errors=None):
        joined = " ".join(str(a) for a in args)
        if "test" in joined:
            return _FakeCompleted(1, GO_CANNED)
        return _FakeCompleted(0, "ok (fake)\n")


class _Shell:
    """吃掉 print 的字节壳：print 递的是 str，真 stdout.buffer 递的是 bytes —— 两种都得收，
    否则探针自己先崩（崩掉的 rc 又会冒充闸红，正是这轮在修的那族）。"""
    def __init__(self):
        self.buf = b""

    @property
    def buffer(self):
        return self

    def write(self, b):
        self.buf += b if isinstance(b, bytes) else b.encode("utf-8", "replace")

    def flush(self):
        pass


def run_gate(tag, code):
    gtmp = os.path.join(TMP, "gate-" + tag)
    if not os.path.isdir(gtmp):
        os.makedirs(gtmp)
    io.open(os.path.join(gtmp, "arms.jsonl"), "w", encoding="utf-8").write(
        json.dumps({"verdict": "BIT"}) + "\n")          # 臂读数：真说过话且比树新 ⇒ 不作乱
    code = "import sys as _s\n_s.argv = [_s.argv[0]]\nTMPG = r\"%s\"\n" % gtmp.replace("\\", "/") + code
    mod = types.ModuleType("gate_" + tag)
    mod.__file__ = GATE
    mod.subprocess = _FakeSubprocess                     # 一条真进程都不起
    old_argv = list(sys.argv)
    sys.argv = [sys.argv[0]]
    cap = _Shell()
    old_out = sys.stdout
    try:
        sys.stdout = cap
        exec(compile(code, GATE, "exec"), mod.__dict__)
        # 假 subprocess 必须在 exec **之后**装：件自己顶部就 import subprocess，
        # 装早了会被这句 import 覆盖 —— 于是探针会去跑真闸（本轮真踩过：它把 6 分钟那一道
        # 起起来了，还把两把尺子的读数重刷了一遍）。装完再验一次它没被换回去。
        mod.subprocess = _FakeSubprocess
        assert mod.subprocess is _FakeSubprocess, "假 subprocess 没接上 —— 探针会跑真闸，拒绝继续"
        rc = mod.main()
    finally:
        sys.stdout = old_out
        sys.argv = old_argv
    text = cap.buf.decode("utf-8", "replace")
    rep = io.open(os.path.join(gtmp, "report.txt"), encoding="utf-8").read() \
        if os.path.isfile(os.path.join(gtmp, "report.txt")) else ""
    dumps = [f for f in os.listdir(gtmp) if f.startswith("红-全量")]
    return {"tag": tag, "rc": rc, "text": text, "report": rep, "dumps": dumps, "dir": gtmp}


gres = [run_gate("ctrl", gsrc), run_gate("GMUT", GMUT)]
for r in gres:
    row = [l for l in r["report"].splitlines() if "go test" in l]
    r["row"] = row[0] if row else ""
    r["concl"] = [l for l in r["report"].splitlines() if l.startswith("conclusion=")]
    r["concl"] = r["concl"][0] if r["concl"] else ""
    r["named"] = "红在 TestFlakeExample" in r["row"]
    r["blamed"] = "go test -count=1" in r["concl"]
    r["dump_has_fail"] = bool(r["dumps"]) and ("--- FAIL: TestFlakeExample" in io.open(
        os.path.join(r["dir"], r["dumps"][0]), encoding="utf-8").read())



def bad_point_only(mod):
    """直接问 audit：一条符号档 ref 漂到界内错行后，坏点进没进「判 rc」那份清单。

    为什么不问 rc：rc 同时还数臂的死活，注病那一份里臂本身也死了，rc=3 会被读成「抓到了」。
    判据有没有牙只能问 mis 这一份清单本身。
    """
    import json as _j
    model = _j.load(io.open(mod.MODEL, encoding="utf-8"))
    spec = mod.refresher_spec()[0]
    for n in model["nodes"]:
        if n.get("id") in spec:
            for r in n.get("sourceRefs", []):
                mm = mod.RE_REF.match(r)
                if mm and mm.group("a"):
                    n["sourceRefs"] = [("%s:2" % mm.group("path")) if x == r else x for x in n["sourceRefs"]]
                    a = mod.audit(model)
                    return len(a["sym_bad"]), len(a["mis"])
    return None


for r in res:
    r["bite"] = bad_point_only(r["mod"])

lines = []
def w(f, *a):
    lines.append(f % a if a else f)
w("尺子自证 · 把旧病注回内存里的尺子副本（不动盘上的尺子，也不起真进程）")
w("基准 = 当前 证据模型核对.py；R1 = 追加式 SPEC 读不到；R2 = mis 被重复键覆盖")
w("复合闸那三行 = 基准 体检-全闸 / GMUT = 把「点名 Test」拧成恒空（探针进程全假，只喂一段 canned go test）")
w("")
for r in res:
    dead = [n for n, v in r["arms"] if v == "失效"] + ["%s（没处下手）" % n for n in r["no_hand"]]
    b = r["bite"]
    w("%-4s rc=%s ｜ 符号可核 %d 条 ｜ 臂判 %d 条 ｜ 臂红/失效 %d 条 ｜ 一条真漂移：sym_bad=%s mis=%s",
      r["tag"], r["rc"], r["sym"], len(r["arms"]), len(dead),
      "-" if b is None else b[0], "-" if b is None else b[1])
    for d in dead:
        w("      ↳ %s", d)
w("")
for r in gres:
    w("复合闸 %-5s rc=%s ｜ 罪名进线=%s ｜ conclusion 点名这一道=%s ｜ 全量落盘含 FAIL=%s ｜ 落盘文件=%s",
      r["tag"], r["rc"], r["named"], r["blamed"], r["dump_has_fail"], ",".join(r["dumps"]) or "-")
    w("      ↳ 行原文：%s", r["row"][:150])
w("")
w("注：R2 那一份 rc=3 不是坏点被抓 —— 是 A4b 自己失效把 rc 拖红的。")
w("    所以判「有没有牙」只看上面那对数：sym_bad>0 而 mis=0 = 只印不判。")
w("")
ctrl = res[0]
r1, r2 = res[1], res[2]
checks = [
    ("基准：rc=0 且所有臂都判成有效", ctrl["rc"] == 0 and all(v == "有效" for _, v in ctrl["arms"])),
    ("基准：符号可核 53 条（与 锚点刷新.py 自印的 refs total=53 对齐）", ctrl["sym"] == 53),
    ("R1：A5 必须失效或没处下手（旧 parse 读不到追加槽）",
     any("A5" in n for n, v in r1["arms"] if v == "失效") or any("A5" in n for n in r1["no_hand"])),
    ("R1：符号可核掉回 32（21 条被降成仅存在性，正是这次的病）", r1["sym"] == 32),
    ("R2：A4b 必须失效（坏点进不了判 rc 的清单）",
     any("A4b" in n for n, v in r2["arms"] if v == "失效")),
    ("基准：一条真漂移既进 sym_bad 也进 mis（打印的那份和判 rc 的那份是同一份）",
     bool(ctrl["bite"]) and ctrl["bite"][0] > 0 and ctrl["bite"][1] > 0),
    ("R2：同一条漂移 sym_bad>0 而 mis=0 ⇒ 重复键确实让判据没了牙（修法不是可有可无）",
     bool(r2["bite"]) and r2["bite"][0] > 0 and r2["bite"][1] == 0),
    ("复合闸·基准：红的那一道把 Test 名写进了读数行，且 conclusion 点名是哪一道不绿",
     gres[0]["named"] and gres[0]["blamed"]),
    ("复合闸·基准：红的那一道的全量输出落到读数目录且含那行 --- FAIL（罪名之外还留现场）",
     gres[0]["dump_has_fail"]),
    ("复合闸·GMUT：把点名拧成恒空后罪名必须消失，而 rc 照旧=3 ⇒ 归因靠这条函数，且变异没碰判据",
     (not gres[1]["named"]) and gres[1]["rc"] == 3 and gres[1]["blamed"]),
]
for name, ok in checks:
    w("判：%s ｜ %s", "过" if ok else "不过", name)
bad = sum(1 for _, ok in checks if not ok)
w("")
w("结论：%d 条自证不过。每个旧病各有一条臂钉住，注回去就红；基准全绿（自证共 %d 条，条数由这份清单自己数）。" % (bad, len(checks)) if bad == 0
  else "结论：%d 条自证不过（共 %d 条）—— 上面点名的那条臂没在管它声称管的事。" % (bad, len(checks)))
out = "\n".join(lines) + "\n"
io.open(os.path.join(HERE, "读数", "尺子自证-旧病复现-1023.txt"), "w", encoding="utf-8").write(out)
sys.__stdout__.buffer.write(out.encode("utf-8"))
sys.exit(0 if bad == 0 else 3)
