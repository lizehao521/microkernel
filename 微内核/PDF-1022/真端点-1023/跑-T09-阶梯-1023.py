"""T09 八步链 · 步数上限阶梯（真端点，2026-10-23）。

目的：T09 在任务集里挂 blocked 的理由是「默认 -max-steps 6 到不了 8 步」。
这组读数把它量成阶梯：6/7/8/9/10 各 3 发，每发一个新 hubd、一个新会话，
记录跑了几步、停在哪、模型自己的 answer 里八个结果齐不齐、answer_tier。

判据（oracle）四条同时成立：
  1. calc.eval 且 class=ok 的步数 >= 8
  2. stop == 跑完
  3. answer_tier == model_says（回答必须是模型写的，不是宿主回显）
  4. 模型 answer 里出现 2,4,6,8,10,12,14,16 八个整数

口令只走环境变量，产物不含口令原文。落盘走 .part + os.replace。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
EXE = HERE / "hubd-real.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
TASK = "依次算 1+1、2+2、3+3、4+4、5+5、6+6、7+7、8+8。每一步都单独调用一次 calc.eval，不要合并成一个算式；最后把八个结果列出来。"
EXPECT = [2, 4, 6, 8, 10, 12, 14, 16]
LADDER = [6, 7, 8, 9, 10]
REPS = 3
OUT_NAME = "T09-步数上限阶梯-1023.json"


def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    return url, key


def judge(result):
    """返回 (ok, why)。scale 与 tiers 都在这一个函数里，臂打的就是它。"""
    r = result or {}
    steps = r.get("steps") or []
    ok_calc = [s for s in steps if s.get("tool") == "calc.eval" and s.get("class") == "ok"]
    answer = r.get("answer") or ""
    ints = set(int(x) for x in re.findall(r"(?<!\d)(\d+)(?!\d)", answer))
    missing = [n for n in EXPECT if n not in ints]
    if len(ok_calc) < 8:
        return False, "steps<%d(%d)" % (8, len(ok_calc))
    if r.get("stop") != "跑完":
        return False, "stop=%s" % r.get("stop")
    if r.get("answer_tier") != "model_says":
        return False, "answer_tier=%s" % r.get("answer_tier")
    if missing:
        return False, "answer_missing=%s" % missing
    return True, "ok"


def arms():
    """6 根叶子臂：判据能绿、能红，且红因各不同。"""
    good = {"stop": "跑完", "answer_tier": "model_says",
            "answer": "2, 4, 6, 8, 10, 12, 14, 16",
            "steps": [{"tool": "calc.eval", "class": "ok"}] * 8}
    cases = [
        ("全对必须绿", good, True),
        ("少一个结果必须红", dict(good, answer="2, 4, 6, 8, 10, 12, 14"), False),
        ("工具调用文本当答案必须红",
         dict(good, answer='[TOOL_CALL]{tool => "calc.eval", args => {expr => "8+8"}}[/TOOL_CALL]'), False),
        ("撞步数上限必须红", dict(good, stop="步数上限"), False),
        ("回显答案必须红", dict(good, answer_tier="measured"), False),
        ("只跑七步必须红",
         dict(good, steps=[{"tool": "calc.eval", "class": "ok"}] * 7), False),
    ]
    rows = []
    bad = 0
    for name, res, want in cases:
        got, why = judge(res)
        ok = got is want
        rows.append({"arm": name, "want_ok": want, "got_ok": got, "why": why, "pass": ok})
        if not ok:
            bad += 1
    return rows, bad


def run_one(s, idx, url, key):
    tmp = Path(tempfile.mkdtemp(prefix="ak-t09-ladder-"))
    fs = tmp / "fs"
    fs.mkdir()
    data = tmp / "data"
    data.mkdir()
    port = str(4440 + idx)
    env = dict(os.environ)
    env["HUBD_MODEL_KEY"] = key
    log_path = HERE / "读数" / ("T09-阶梯-%02d-s%s.log" % (idx, s))
    log = open(log_path, "wb")
    proc = subprocess.Popen([str(EXE),
                             "-port", port, "-data", str(data),
                             "-tools-dir", str(ROOT / "AgentHub-1021" / "src" / "hubd" / "tools"),
                             "-fs-roots", str(fs),
                             "-model-endpoint", url,
                             "-model-name", "MiniMax-M2.5",
                             "-model-key-env", "HUBD_MODEL_KEY",
                             "-model-timeout-ms", "60000",
                             "-max-steps", str(s)],
                            env=env, stdout=log, stderr=subprocess.STDOUT, cwd=str(fs))
    try:
        base = "http://127.0.0.1:%s" % port
        health = None
        for _ in range(120):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                    health = json.loads(r.read().decode("utf-8"))
                break
            except Exception:
                time.sleep(0.25)
        if health is None:
            return {"max_steps": s, "rep": idx, "error": "health never came up"}
        body = json.dumps({"text": TASK}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(base + "/api/chat", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        result, result_seen = None, False
        ev = None
        kinds = {}
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if line.startswith("event: "):
                        ev = line[7:]
                        kinds[ev] = kinds.get(ev, 0) + 1
                    elif line.startswith("data: "):
                        if ev != "result":
                            continue
                        try:
                            result = json.loads(line[6:])
                        except Exception:
                            continue
                        result_seen = True
        except Exception as e:
            return {"max_steps": s, "rep": idx, "error": "%s: %s" % (type(e).__name__, e),
                    "elapsed_ms": round((time.time() - t0) * 1000)}
        elapsed = round((time.time() - t0) * 1000)
        ok, why = judge(result)
        r0 = result or {}
        steps = r0.get("steps") or []
        return {
            "max_steps": s, "rep": idx, "result_seen": result_seen,
            "ok": ok, "why": why, "elapsed_ms": elapsed,
            "n_steps": len(steps),
            "n_ok_calc": len([x for x in steps if x.get("tool") == "calc.eval" and x.get("class") == "ok"]),
            "tool_seq": [x.get("tool") for x in steps],
            "stop": r0.get("stop"), "stop_why": r0.get("stop_why"),
            "answer_tier": r0.get("answer_tier"), "answer_why": r0.get("answer_why"),
            "sane": r0.get("sane"), "plan": r0.get("plan"),
            "fallbacks": r0.get("fallbacks"),
            "answer_head": (r0.get("answer") or "")[:300],
            "provenance": [x.get("provenance") for x in steps],
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    url, key = load_secret()
    arm_rows, arm_bad = arms()
    for r in arm_rows:
        print(json.dumps(r, ensure_ascii=True))
    if arm_bad:
        print(json.dumps({"FATAL": "arms_failed", "n": arm_bad}, ensure_ascii=True))
        return 2
    exe_sha = hashlib.sha256(EXE.read_bytes()).hexdigest()
    t_all = time.time()
    runs = []
    idx = 0
    for s in LADDER:
        for rep in range(1, REPS + 1):
            idx += 1
            rec = run_one(s, idx, url, key)
            runs.append(rec)
            print(json.dumps({"max_steps": s, "rep": rep, "ok": rec.get("ok"),
                              "why": rec.get("why"), "n_steps": rec.get("n_steps"),
                              "stop": rec.get("stop"), "tier": rec.get("answer_tier"),
                              "ms": rec.get("elapsed_ms"), "err": rec.get("error")},
                             ensure_ascii=True))
    ladder_summary = []
    for s in LADDER:
        rs = [x for x in runs if x.get("max_steps") == s]
        ladder_summary.append({
            "max_steps": s, "n": len(rs), "pass": sum(1 for x in rs if x.get("ok")),
            "n_ok_calc": [x.get("n_ok_calc") for x in rs],
            "stops": [x.get("stop") for x in rs],
            "tiers": [x.get("answer_tier") for x in rs],
            "why": [x.get("why") for x in rs],
            "errors": [x.get("error") for x in rs if x.get("error")],
        })
    body = {
        "surface": "agenthub", "shape": "T09-step-ladder",
        "task": TASK, "expect": EXPECT, "ladder": LADDER, "reps": REPS,
        "endpoint": url, "model": "MiniMax-M2.5",
        "exe_sha256": exe_sha, "exe_bytes": EXE.stat().st_size,
        "oracle": "T09-ladder-v1: >=8 calc.eval ok 且 stop=跑完 且 answer_tier=model_says 且 answer 含 2/4/6/8/10/12/14/16",
        "arms": arm_rows, "summary_ladder": ladder_summary,
        "runs": runs,
        "elapsed_ms_total": round((time.time() - t_all) * 1000),
    }
    text = json.dumps(body, ensure_ascii=False, indent=1)
    final = HERE / "读数" / OUT_NAME
    part = final.with_suffix(final.suffix + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, final)
    data = final.read_bytes()
    side = {
        "reading": str(final), "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "key_in_reading": key in text,
        "exe_sha256": exe_sha,
    }
    (HERE / "读数" / (OUT_NAME + ".landing.json")).write_text(
        json.dumps(side, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(side, ensure_ascii=True))
    for row in ladder_summary:
        print(json.dumps(row, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
