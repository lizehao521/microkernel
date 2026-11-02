#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B1 的双臂现场凭证：同一发中断，**改前那份**把正式读数截没了，**改后这份**保住上一趟。

为什么要有这一件（而不是改完就算）：这条判据长得像"写法更讲究了"，只有把它和改前的字节
摆在同一发中断下，才看得出差别落在盘上 —— 10-23 臂检那一族的原话就是
「一开跑就把上一份 82 行读数截成 0 字节，而合取件只看 mtime ⇒ 空读数被判成绿」。

两个实验，都跑**产品字节**（一份是树上这一份，一份是 `TEMP-备份/遗留修复-1025/…改前-B1前-1025`
那份逐字副本，不重写、不还原）；两臂之间只差产品字节，输入（DOC、种子读数、go、树）完全同源：

  E1 崩在第一发检查之前 —— 传一把不存在的 go.exe，`list_tests()` 里 `subprocess.run` 抛
     `FileNotFoundError`（这条路的出口是**未捕获异常**，不是件自己 return 4）。
     这一族最坏的形状：正式名被截成 **0 字节**（连一行罪名都没有）。
  E2 跑到中途被打断 —— 命令行照 AGENTS.md 那条逐字抄（真 go、真树），
     **看见子件 stdout 上第一行 `PIN-` 就 kill**（不是数秒表：机器快慢会把"打断"变成"它自己跑完了"）。
     第二形状：正式名只剩表头那一截，mtime 还是最新的。

判据（本件自己的 rc）：改后必须**逐字保住**上一趟那份（sha 相等），改前必须**丢掉**它。
两边都保住 = 我的改动没生效；两边都丢掉 = 换名这条路没接上 —— 两种都判红，因为
"臂没接上=恒 0，与尺子没牙同形"。E2 还多一条前置：没真打断成 ⇒ 这一发**判不了**，
不许把"没打断"写成"两臂都对"。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 落盘自证-开局截断-1025.py <go.exe> <树根>
控制台只走 ASCII（GBK 会崩在中文上，崩掉的是退出码契约）；读数落 报告/落盘自证-开局截断-1025.txt。
退出码：0 两个实验都成对（改后保住 / 改前丢掉）；2 形状不对或 E2 没打断成；3 环境没备齐。
"""
import hashlib
import io
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

PY = sys.executable
GO = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/Admin/sdk/go/bin/go.exe"
SRC = sys.argv[2] if len(sys.argv) > 2 else r"C:/Users/Admin/Desktop/微内核/微内核/微内核"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # 微内核现场根
FIXED = os.path.join(HERE, "验收-事件层-1022.py")  # 产品字节（改后）
PRE = os.path.join(ROOT, "TEMP-备份", "遗留修复-1025", "事件层-1022",
                   "验收-事件层-1022.py.改前-B1前-1025")
DOC = os.path.join(ROOT, "研究-协同工作-1022.md")
SEED = os.path.join(ROOT, "TEMP-备份", "遗留修复-1025", "事件层-1022",
                    "报告-验收.txt.改前现那份-1025")  # 上一趟的完整读数，当"改前就在那儿"的凭据
OUT_DIR = os.path.join(HERE, "报告")
OUT = os.path.join(OUT_DIR, "落盘自证-开局截断-1025.txt")
SCRIPT_NAME = "验收-事件层-1022.py"               # 两个实验里都按这个名放（脚本按 __file__ 找邻居）
DEADLINE = 240                                    # E2 等"第一行 PIN-"的最长秒数，不是打断时刻
NO_GO = r"C:/Users/Admin/sdk/go/bin/no-such-go.exe"

_lines = []


def say(s):
    _lines.append(s)
    sys.stdout.write(s.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def sha256(p):
    if not os.path.isfile(p):
        return "absent"
    return hashlib.sha256(io.open(p, "rb").read()).hexdigest()[:16]


def size_rows(p):
    if not os.path.isfile(p):
        return "absent", "absent"
    raw = io.open(p, "rb").read()
    n = len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
    return len(raw), n


def prep(tag):
    """造一棵临时目录：<父>/<tag>/验收-事件层-1022.py，旁边摆一份"上一趟的完整读数"。

    DOC 放在**父目录**，因为被试件按 `HERE/../研究-协同工作-1022.md` 找它 —— 这是它的既有规矩，
    本件不改它一个字（改了就不是产品字节）。两个实验都必须带上 DOC：
    少了它，被试件在 `pins_from_doc()` 那一步就走「读不到 DOC ⇒ 印一行罪名 ⇒ 照样落盘」的出口，
    那一出口会名正言顺地换掉正式读数，测的就不是"开局截断"这一族了（本件第一版就栽在这里）。
    """
    base = os.path.join(os.environ.get("TEMP", "/tmp"), "ak-1025-b1", tag)
    shutil.rmtree(base, ignore_errors=True)
    d = os.path.join(base, "事件层")
    os.makedirs(d)
    shutil.copyfile(DOC, os.path.join(base, os.path.basename(DOC)))
    shutil.copyfile(FIXED if tag.startswith("fixed") else PRE, os.path.join(d, SCRIPT_NAME))
    shutil.copyfile(SEED, os.path.join(d, "报告-验收.txt"))
    return d


def spawn(d, go):
    """-u：子件 stdout 不缓冲，否则 `PIN-` 那行还压在它的 8 KB 缓冲区里，我这边永远等不到触发点。"""
    return subprocess.Popen([PY, "-u", os.path.join(d, SCRIPT_NAME), go, SRC], cwd=d,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")


def pump(stream, sink):
    for ln in stream:
        sink.put(("out", ln.rstrip("\n")))
    sink.put(("eof", ""))


def verdict(label, official_sha, seed_sha, part_rows, extra):
    kept = official_sha == seed_sha
    say("  %-26s 正式名 sha=%s（改前那一份=%s）⇒ %s ｜ .part 行数=%s ｜ %s"
        % (label, official_sha, seed_sha, "保住上一趟" if kept else "被这一趟改了",
           part_rows, extra))
    return kept


def part_rows_of(d):
    p = os.path.join(d, "报告-验收.txt.part")
    return size_rows(p)[1] if os.path.isfile(p) else "没有 .part 这个文件"


def e1():
    say("== E1 崩在第一发检查之前（不存在的 go.exe：`list_tests()` 抛未捕获异常）==")
    res = {}
    for tag, label in (("fixed-e1", "改后（.part+replace）"), ("pre-e1", "改前（开局截正式名）")):
        d = prep(tag)
        official = os.path.join(d, "报告-验收.txt")
        seed_sha = sha256(official)
        p = spawn(d, NO_GO)
        q = queue.Queue()
        threading.Thread(target=pump, args=(p.stdout, q), daemon=True).start()
        threading.Thread(target=pump, args=(p.stderr, q), daemon=True).start()
        p.wait(timeout=DEADLINE)
        rows = []
        while not q.empty():
            kind, ln = q.get()
            if kind == "out" and ln.strip():
                rows.append(ln)
        emitted = [r for r in rows if r.startswith("PIN-") or r.startswith("source=")]
        kept = verdict(label, sha256(official), seed_sha, part_rows_of(d),
                       "子件 rc=%s，崩前上屏的读数行数=%d（%s）"
                       % (p.returncode, len(emitted), "一行都没 emit" if not emitted else emitted[0][:40]))
        res[tag] = (kept, size_rows(official), emitted)
        if emitted:
            say("  前置不对：这一发在崩之前已经 emit 了 %d 行（第一行 %s）⇒ 崩的位置不在「第一行之前」，"
                "E1 测的不是「开局截断」这一族" % (len(emitted), emitted[0][:60]))
    ok_fixed = res["fixed-e1"][0] and not res["fixed-e1"][2]
    ok_pre = (not res["pre-e1"][0]) and not res["pre-e1"][2]
    say("  E1 结论：改后保住=%s ｜ 改前丢掉=%s（改后=%s 改前=%s 字节/行）"
        % (ok_fixed, ok_pre, res["fixed-e1"][1], res["pre-e1"][1]))
    return ok_fixed and ok_pre


def e2():
    say("== E2 跑到中途被打断（触发点=子件自己印的第一行 `PIN-`，上限 %d 秒）==" % DEADLINE)
    res = {}
    for tag, label in (("fixed-e2", "改后（.part+replace）"), ("pre-e2", "改前（开局截正式名）")):
        d = prep(tag)
        official = os.path.join(d, "报告-验收.txt")
        seed_sha = sha256(official)
        p = spawn(d, GO)
        q = queue.Queue()
        threading.Thread(target=pump, args=(p.stdout, q), daemon=True).start()
        threading.Thread(target=pump, args=(p.stderr, q), daemon=True).start()
        trigger, t0 = None, time.time()
        while time.time() - t0 < DEADLINE:
            try:
                kind, ln = q.get(timeout=1.0)
            except queue.Empty:
                if p.poll() is not None:
                    break
                continue
            if kind == "eof":
                break
            if ln.startswith("PIN-"):
                trigger = ln
                break
        alive = p.poll() is None
        if alive:
            p.kill()
        p.wait(timeout=30)
        interrupted = bool(trigger) and alive
        kept = verdict(label, sha256(official), seed_sha, part_rows_of(d),
                       "打断在 %s（等了 %.1f 秒，kill 时还在跑=%s）"
                       % (trigger[:46] if trigger else "没等到第一行 PIN-", time.time() - t0, alive))
        res[tag] = (kept, interrupted, size_rows(official), trigger)
        if not interrupted:
            say("  这一臂判不了：子件在第一个 `PIN-` 之前就自己收口了 ⇒ 「中途打断」这个前提没成立，"
                "不拿它当证据")
    ok_fixed = res["fixed-e2"][0]
    ok_pre = (not res["pre-e2"][0])
    both_interrupted = res["fixed-e2"][1] and res["pre-e2"][1]
    say("  E2 结论：改后保住=%s ｜ 改前丢掉=%s（改后=%s 改前=%s 字节/行）｜ 两臂都真打断=%s"
        % (ok_fixed, ok_pre, res["fixed-e2"][3], res["pre-e2"][3], both_interrupted))
    return ok_fixed and ok_pre and both_interrupted


def main():
    for p, why in ((FIXED, "改后那份不在"), (PRE, "改前备份不在（它才是这一判的对照字节）"),
                   (SEED, "上一趟的完整读数不在（没有它就没有「保住」可言）"),
                   (DOC, "研究-协同工作-1022.md 不在（被试件按它数针）")):
        if not os.path.isfile(p):
            say("ENV-BAD %s：%s" % (why, p))
            return 3
    if not os.path.isfile(GO):
        say("ENV-BAD go.exe 不在：%s —— E2 要真跑，不许拿假端点冒充" % GO)
        return 3
    say("产品字节：改后 %s ｜ %d B ｜ sha %s" % (os.path.basename(FIXED), os.path.getsize(FIXED), sha256(FIXED)))
    say("对照字节：改前 %s ｜ %d B ｜ sha %s" % (os.path.basename(PRE), os.path.getsize(PRE), sha256(PRE)))
    say("种子读数：%s ｜ %d B ｜ sha %s（两臂开跑前它就在正式名上）"
        % (os.path.basename(SEED), os.path.getsize(SEED), sha256(SEED)))
    say("两臂只差产品字节；输入同源：DOC=%s ｜ go=%s ｜ 树=%s" % (DOC, GO, SRC))
    say("")
    r1 = e1()
    say("")
    r2 = e2()
    say("")
    say("双臂成对：%s（E1）%s（E2）—— 两半都要「改后保住 / 改前丢掉」，缺一半就是臂没接上"
        % ("OK" if r1 else "BAD", "OK" if r2 else "BAD"))
    os.makedirs(OUT_DIR, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(_lines) + "\n")
    n = len(io.open(OUT, encoding="utf-8").read().splitlines())
    sys.stdout.write(("landing check: %s %d/%d rows\n" % (OUT, n, len(_lines)))
                     .encode("ascii", "backslashreplace").decode("ascii"))
    return 0 if (r1 and r2) else 2


if __name__ == "__main__":
    sys.exit(main())
