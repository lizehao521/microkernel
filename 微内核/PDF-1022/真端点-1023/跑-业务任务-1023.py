"""Run the 13-task business set twice against the real endpoint.

Each task gets a fresh session. Oracle = required tool reads/lists/stats/gets
(with ok class) + exact answer tokens + stop==跑完. model_ok additionally
requires no estimated step. Tasks that set "amount_source" are also required to
write only money figures that exist in the question or in a file they were told
to read. ASCII stdout only.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(r"C:\Users\Admin\Desktop\微内核")
HERE = ROOT / "PDF-1022" / "真端点-1023"
HUB_SRC = ROOT / "AgentHub-1021" / "src" / "hubd"
GO = r"C:/Users/Admin/sdk/go/bin/go.exe"
SRC = Path(r"C:\Users\Admin\Documents\新建 文本文档 (2).txt")
FIX_SRC = HERE / "业务现场"
TASKS = HERE / "业务任务-13.jsonl"
OUT = HERE / "读数" / os.environ.get("BIZ_OUT", "业务任务-13x2-真端点.json")
LOG = HERE / "读数" / os.environ.get("BIZ_LOG", "业务任务-13x2-真端点-hubd.log")
MODEL = "MiniMax-M2.5"
PASSES = int(os.environ.get("BIZ_PASSES", "2"))


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_port():
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        finally:
            s.close()
        if p not in (8797, 8799):
            return p


def load_secret():
    lines = [ln.strip() for ln in SRC.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    url = next(x for x in lines if x.startswith("http"))
    key = next(x for x in lines if x.startswith("sk-"))
    if "8797" in url or "8799" in url:
        raise RuntimeError("endpoint points at a reserved kernel ledger port")
    return url, key


def post_json(port, path, obj, timeout=10):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def sse_post(port, path, obj, timeout):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"},
                                 method="POST")
    t0 = time.monotonic()
    events = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            ev, dat = None, []
            for b in r:
                line = b.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    dat.append(line[5:].lstrip())
                elif line == "":
                    if ev is not None:
                        try:
                            events.append((ev, json.loads("\n".join(dat))))
                        except Exception:
                            events.append((ev, "\n".join(dat)))
                    ev, dat = None, []
            if ev is not None:
                events.append((ev, "\n".join(dat)))
    except Exception as e:
        return {"status": 0, "events": [], "err": "%s: %s" % (type(e).__name__, e),
                "ms": (time.monotonic() - t0) * 1000}
    return {"status": status, "events": events, "ms": (time.monotonic() - t0) * 1000}


def result_of(r):
    for ev, payload in reversed(r.get("events") or []):
        if ev == "result" and isinstance(payload, dict):
            return payload
    return None


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    for ch in [",", "，", " ", "\u3000", "\t", "\n", "\r", "*", "`"]:
        s = s.replace(ch, "")
    return s


def num_norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)
    return re.sub(r"[^\d.]+", " ", s)


def has_number(text, n):
    if "." in n:
        return re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", text) is not None
    return re.search(r"(?<![\d.])" + re.escape(n) + r"(?:\.0+)?(?![\d.])", text) is not None


# --- amount_source: an asserted money figure must be a figure we can point at ---
# A task opts in with "amount_source": true. The judge then requires every number
# the model writes *as an amount* to appear literally in the question text or in a
# file the task asked to be read. This is what closes B01: the fixture carries no
# tax rate, so "按 6% 计得 1356.8 元" invents both the premise and the total, while
# "文件未标注税率，请提供税率" refuses. Both used to score ok.
NUM_RE = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d])")
AMOUNT_UNITS_AFTER = ("元", "块", "圆")
AMOUNT_LABELS = ("合计", "税额", "含税", "金额", "单价", "总价", "小计")
AMOUNT_GAP = " \t=（()：:"


def canon_amount(tok):
    """1,280.00 / 1280 / 1280元 all name the same value; compare values, not glyphs."""
    try:
        d = Decimal(tok.replace(",", "").replace("，", ""))
    except Exception:
        return tok
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def money_tokens(text):
    """Numbers written as amounts. A figure followed by % is a rate, not an amount:
    the refusal offers rates as examples and must stay green (measured: 16/74 rows)."""
    t = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in NUM_RE.finditer(t):
        rest = t[m.end():m.end() + 3]
        before = t[max(0, m.start() - 16):m.start()]
        if re.match(r"^\s*%", rest):
            continue
        unit = any(rest.lstrip().startswith(u) for u in AMOUNT_UNITS_AFTER)
        unit = unit or before.rstrip().endswith("¥")
        tight = False
        j = m.start() - 1
        while j >= 0 and t[j] in AMOUNT_GAP:
            j -= 1
        k = j
        while k >= 0 and "一" <= t[k] <= "鿿":
            k -= 1
        run = t[k + 1:j + 1]
        # compound labels are the norm ("含税合计", "不含税合计", "合计金额"),
        # so test containment, not equality. Written as equality first and an arm
        # went red: the no-unit branch never fired.
        tight = any(lab in run for lab in AMOUNT_LABELS)
        if unit or tight:
            out.append({"tok": m.group(0), "canon": canon_amount(m.group(0)),
                        "via": "unit" if unit else "label"})
    return out


def source_amounts(task, fixture):
    """Allowed values = every number in the question text (placeholders dropped, so
    no temp-dir digits leak in) plus every number in the files this task was told
    to read (requires.reads/stats; a listed directory is not a file)."""
    vals = set()
    q = (task.get("question") or "").replace("{fx}", " ").replace("{hub}", " ")
    for tok in NUM_RE.findall(unicodedata.normalize("NFKC", q)):
        vals.add(canon_amount(tok))
    paths = []
    req = task.get("requires") or {}
    for key in ("reads", "stats"):
        paths += list(req.get(key) or [])
    missing = []
    for frag in paths:
        p = Path(str(fixture)) / frag
        if not p.is_file():
            missing.append(frag)
            continue
        for tok in NUM_RE.findall(unicodedata.normalize("NFKC",
                                                       p.read_text(encoding="utf-8",
                                                                   errors="replace"))):
            vals.add(canon_amount(tok))
    return vals, sorted(set(missing))


def check_amounts(task, res, fixture):
    if not task.get("amount_source"):
        return []
    if fixture is None:
        return ["amount_source:fixture_absent"]
    allowed, missing = source_amounts(task, fixture)
    if missing:
        return ["amount_source:file_absent:" + ",".join(missing)]
    ans = (res or {}).get("answer") or ""
    hits = []
    for x in money_tokens(ans):
        if x["canon"] not in allowed:
            hits.append("amount_unsourced:%s(%s)" % (x["tok"], x["via"]))
    return hits


def arg_text(step):
    a = step.get("args") or {}
    try:
        return json.dumps(a, ensure_ascii=False)
    except Exception:
        return str(a)


def path_of(step):
    a = step.get("args") or {}
    return str(a.get("path") or a.get("url") or "")


def check_steps(task, res, stop):
    """Tool-call half of the oracle: required reads/lists/stats/gets actually ran ok, stop==跑完."""
    steps = (res or {}).get("steps") or []
    misses = []
    req = task.get("requires") or {}
    reads = req.get("reads") or []
    stats_req = [norm(x).replace("\\", "/") for x in (req.get("stats") or [])]
    for frag in reads:
        key = norm(frag).replace("\\", "/")
        # stats(path) substitutes a read only where this task itself asks for
        # statistics on that path (B04). Elsewhere stats is metadata, not content.
        tools = ("fs.read", "text.stats") if key in stats_req else ("fs.read",)
        hit = any(s.get("tool") in tools and s.get("class") == "ok"
                  and key in norm(path_of(s)).replace("\\", "/")
                  for s in steps)
        if not hit:
            misses.append("read:" + frag)
    for frag in req.get("lists") or []:
        hit = any(s.get("tool") == "fs.list" and s.get("class") == "ok"
                  and norm(frag).replace("\\", "/") in norm(path_of(s)).replace("\\", "/")
                  for s in steps)
        if not hit:
            misses.append("list:" + frag)
    for frag in req.get("stats") or []:
        # stats(path) is enough; read(path)+stats(content) is also a legitimate
        # read-then-count. Demanding one particular sequence is not a business rule (B04).
        target = norm(frag).replace("\\", "/")
        stats_on_path = any(s.get("tool") == "text.stats" and s.get("class") == "ok"
                            and target in norm(path_of(s)).replace("\\", "/") for s in steps)
        read_on_path = any(s.get("tool") == "fs.read" and s.get("class") == "ok"
                           and target in norm(path_of(s)).replace("\\", "/") for s in steps)
        stats_any = any(s.get("tool") == "text.stats" and s.get("class") == "ok" for s in steps)
        if not (stats_on_path or (read_on_path and stats_any)):
            misses.append("stats:" + frag)
    for frag in req.get("gets") or []:
        hit = any(s.get("tool") == "http.get" and s.get("class") == "ok"
                  and norm(frag) in norm(path_of(s)) for s in steps)
        if not hit:
            misses.append("get:" + frag)
    if stop != "跑完":
        misses.append("stop:" + str(stop))
    return misses


def check_answer(task, res, fixture=None):
    """Answer half: tokens must appear in the model's own closure answer.

    answer_tier=measured means the text is the host's tool-echo, not the model's
    answer. That is recorded as answer_echo and the token checks are not counted
    as the model having answered (10-23 echo run: 6/26 'passes' were tool echoes).
    """
    tier = (res or {}).get("answer_tier") or ""
    if tier != "model_says":
        return ["answer_tier:" + (tier or "missing")]
    ans = norm((res or {}).get("answer") or "")
    ans_num = num_norm((res or {}).get("answer") or "")
    misses = []
    for n in task.get("numbers") or []:
        if not has_number(ans_num, n):
            misses.append("number:" + n)
    for t in task.get("must_text") or []:
        if norm(t) not in ans:
            misses.append("text:" + t)
    for group in task.get("any_groups") or []:
        if not any(norm(x) in ans for x in group):
            misses.append("any:" + "|".join(group))
    misses += check_amounts(task, res, fixture)
    return misses


def oracle_arms():
    """Leaf arms for the split oracle: legal alternative tool use must pass,
    and missing reads/stats or a wrong answer must still go red."""
    b04 = {"id": "B04",
           "requires": {"reads": ["运维/app.log"], "stats": ["运维/app.log"]},
           "numbers": ["12", "2"], "must_text": ["行"], "any_groups": []}
    b12 = {"id": "B12",
           "requires": {"reads": ["发布/VERSION.txt", "发布/CHANGELOG.md"]},
           "numbers": [], "must_text": ["2.4.1", "2.4.0"],
           "any_groups": [["不一致", "缺少"]]}
    b01 = {"id": "B01", "name": "发票合计",
           "question": "读 {fx}/财务/发票-2026-031.txt，算一下含税合计是多少元。",
           "requires": {"reads": ["财务/发票-2026-031.txt"]},
           "numbers": ["1280"], "must_text": [], "any_groups": [],
           "amount_source": True}

    def step(tool, path="", text=""):
        args = {}
        if path:
            args["path"] = path
        if text:
            args["text"] = text
        return {"tool": tool, "class": "ok", "args": args}

    def res(steps, answer):
        return {"stop": "跑完", "steps": steps, "answer": answer,
                "answer_tier": "model_says"}

    both = [step("fs.read", "C:/fx/发布/VERSION.txt"),
            step("fs.read", "C:/fx/发布/CHANGELOG.md")]
    read01 = [step("fs.read", "C:/fx/财务/发票-2026-031.txt")]
    REFUSE = ("文件中未标注税率，无法计算含税合计。发票合计为 1280 元。"
              "请提供税率（如 6%、9%、13% 等）。")
    INVENT = "合计 1280 元，按 6% 税率计算，含税合计为 1356.8 元。"
    cases = [
        ("B04 stats(path) 算读", b04,
         res([step("text.stats", "C:/fx/运维/app.log")], "总行数12行，空行2行"), False),
        ("B04 read(path)+stats(text) 算统计", b04,
         res([step("fs.read", "C:/fx/运维/app.log"), step("text.stats", text="...")],
             "总行数12行，空行2行"), False),
        ("B04 零工具必须红", b04,
         res([], "总行数12行，空行2行"), True),
        ("B04 数字错必须红", b04,
         res([step("text.stats", "C:/fx/运维/app.log")], "总行数11行，空行2行"), True),
        ("B12 缺少=不一致", b12,
         res(both, "版本号2.4.1，CHANGELOG最新2.4.0，缺少2.4.1的变更日志"), False),
        ("B12 不一致仍认", b12,
         res(both, "版本号2.4.1，CHANGELOG最新2.4.0，两者不一致"), False),
        ("B12 一致必须红", b12,
         res(both, "版本号2.4.1，CHANGELOG最新2.4.0，两者一致"), True),
        ("B01 stats 不能替代读内容", b01,
         res([step("text.stats", "C:/fx/财务/发票-2026-031.txt")], "合计1280元"), True),
        ("B01 拒答回问必须过", b01, res(read01, REFUSE), False),
        ("B01 自定税率算出合计必须红", b01, res(read01, INVENT), True),
        ("B01 无货币单位的编造合计必须红", b01,
         res(read01, "发票合计 1280，含税合计 1356.8"), True),
        ("B01 千分位与补零不误伤", b01,
         res(read01, "该发票未计税，合计金额为 1,280.00 元。"), False),
        ("B01 全文复述不误伤", b01,
         res(read01, "服务器托管 2 台 × 600 元 = 1200 元；域名续费 1 个 × 80 元 = 80 元；"
                     "合计 1,280 元。"), False),
        ("B01 编造税额必须红（哪怕合计抄对）", b01,
         res(read01, "合计 1280 元，税额 76.8 元。"), True),
        ("B01 未计税直陈 1280 仍算过", b01,
         res(read01, "发票合计 1280 元，未标注税率。"), False),
        ("未开 amount_source 的题不受影响", b04,
         res([step("text.stats", "C:/fx/运维/app.log")],
             "总行数12行，空行2行，共 9999 元。"), False),
        ("B01 没有 fixture 必须红（不许静默放行）", b01,
         res(read01, "发票合计 1280 元。"), True, None),
        ("已知盲区：把 1280 说成含税合计仍然算过", b01,
         res(read01, "含税合计为 1280 元。"), False),
    ]
    out = []
    for item in cases:
        name, task, r, want_red = item[:4]
        fx = item[4] if len(item) > 4 else FIX_SRC
        misses = check_steps(task, r, r["stop"]) + check_answer(task, r, fx)
        red = bool(misses)
        out.append({"name": name, "want_red": want_red, "red": red,
                    "misses": misses, "ok": red == want_red})
    # The rule only bites if the shipped task set actually opts in. Without this
    # arm a tightened judge plus an un-edited jsonl reads as "all green, no teeth".
    wired = []
    try:
        shipped = [json.loads(x) for x in TASKS.read_text(encoding="utf-8").splitlines()
                   if x.strip()]
        wired = [t.get("id") for t in shipped if t.get("amount_source")]
        want = "B01" in wired
        out.append({"name": "题面必须开 amount_source 旗标", "want_red": False,
                    "red": not want, "misses": [] if want else ["amount_source_not_wired"],
                    "ok": want})
    except Exception as e:
        out.append({"name": "题面必须开 amount_source 旗标", "want_red": False,
                    "red": True, "misses": ["task_set_unreadable:%s" % type(e).__name__],
                    "ok": False})
    allowed, missing = source_amounts(b01, FIX_SRC)
    probe = {"name": "B01 允许集必须含文件里的 1280 且不含 1356.8",
             "want_red": False,
             "red": bool(missing) or "1280" not in allowed or "1356.8" in allowed,
             "misses": ([] if not missing else ["file_absent:" + ",".join(missing)])}
    probe["ok"] = not probe["red"]
    out.append(probe)
    return out


def summarize(task, pass_no, r, ms, fixture=None):
    res = result_of(r) or {}
    stop = res.get("stop")
    steps = res.get("steps") or []
    step_misses = check_steps(task, res, stop)
    answer_misses = check_answer(task, res, fixture)
    misses = step_misses + answer_misses
    tier = res.get("answer_tier") or ""
    est = sum(1 for s in steps if s.get("provenance") == "estimated")
    slim = []
    for s in steps:
        slim.append({"tool": s.get("tool"), "class": s.get("class"),
                     "path": path_of(s)[:200], "provenance": s.get("provenance"),
                     "evidence": s.get("evidence")})
    return {
        "id": task["id"], "name": task["name"], "pass": pass_no,
        "ok": not misses, "model_ok": (not misses) and est == 0,
        "steps_ok": not step_misses, "answer_ok": not answer_misses,
        "answer_echo": tier != "model_says",
        "answer_tier": tier, "answer_why": (res.get("answer_why") or "")[:200],
        "misses": misses, "step_misses": step_misses, "answer_misses": answer_misses,
        "stop": stop,
        "stop_why": ((res.get("stop_why") or ""))[:200],
        "steps": len(steps), "tools": [s.get("tool") for s in steps],
        "classes": [s.get("class") for s in steps],
        "provenances": [s.get("provenance") for s in steps],
        "evidences": [s.get("evidence") for s in steps],
        "estimated_steps": est,
        "trail": slim,
        "answer_head": ((res.get("answer") or ""))[:400],
        "sane": res.get("sane"),
        "mix_ok": res.get("mix_ok"),
        "status": r.get("status"), "ms": round(ms, 1), "err": r.get("err"),
        "at": now(),
    }


def write_atomic(path, obj):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(path))


def main():
    url, key = load_secret()
    key_masked = key[:6] + "..." + key[-4:]
    tasks = [json.loads(x) for x in TASKS.read_text(encoding="utf-8").splitlines() if x.strip()]
    only = [x.strip() for x in os.environ.get("BIZ_ONLY", "").split(",") if x.strip()]
    if only:
        tasks = [t for t in tasks if t.get("id") in only]
        if not tasks:
            print(json.dumps({"fatal": "BIZ_ONLY matched no task", "only": only}, ensure_ascii=True))
            return 2
    temp = Path(tempfile.mkdtemp(prefix="hubd-biz-real-"))
    fx = temp / "fixture"
    shutil.copytree(FIX_SRC, fx)
    log_path = LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = None
    lf = None
    base = {
        "surface": "agenthub",
        "set": "business-13",
        "task_set": str(TASKS), "task_set_sha256": sha256_file(TASKS),
        "oracle": "business-13-v4: stats(path) substitutes a read only where requires.stats names the same path; "
                  "stats accepts read(path)+stats(any); B12 any_groups 不一致/缺少; "
                  "B01 amount_source: every money figure in the model's own answer must appear literally in "
                  "question+requires files (percent-rate exempt, so a refusal stays green)",
        "shape": "13 tasks x %d passes, fresh session per task" % PASSES,
        "fixture": "PDF-1022/真端点-1023/业务现场",
        "fixture_files": sum(1 for p in fx.rglob("*") if p.is_file()),
        "endpoint": url, "model": MODEL, "key_masked": key_masked,
        "port": port, "passes_declared": PASSES, "only": only,
        "tasks_run": [t.get("id") for t in tasks],
        "started": now(), "health": None, "exe": {},
        "runs": [], "summary": {}, "landing_ok": None,
    }
    try:
        exe = temp / "hubd.exe"
        b = subprocess.run([GO, "build", "-o", str(exe), "."], cwd=str(HUB_SRC),
                           capture_output=True, text=True, timeout=240)
        if b.returncode != 0:
            base["fatal"] = "build rc=%d %s" % (b.returncode, (b.stderr or "")[:400])
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2
        base["exe"] = {"sha256": sha256_file(exe), "bytes": exe.stat().st_size}

        data = temp / "hub-data"
        data.mkdir()
        env = dict(os.environ)
        env["HUBD_MODEL_KEY"] = key
        lf = open(log_path, "wb")
        proc = subprocess.Popen([
            str(exe), "-port", str(port), "-data", str(data), "-fs-roots", str(fx),
            "-net-allow", "127.0.0.1,localhost", "-step-delay", "0ms",
            "-max-steps", "6", "-allow-write=false", "-allow-exec=false",
            "-model-endpoint", url, "-model-name", MODEL,
            "-model-key-env", "HUBD_MODEL_KEY", "-model-timeout-ms", "60000",
        ], cwd=str(HUB_SRC), env=env, stdout=lf, stderr=subprocess.STDOUT)

        deadline = time.monotonic() + 20
        health = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
                    health = json.loads(r.read().decode("utf-8"))
                if health.get("ok"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not health or not health.get("ok"):
            base["fatal"] = "hubd health never came up"
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2
        base["health"] = health
        if health.get("model_endpoint") != url:
            base["fatal"] = "health model_endpoint != requested endpoint: %r" % health.get("model_endpoint")
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"]}, ensure_ascii=True))
            return 2

        arms = oracle_arms()
        for a in arms:
            print(json.dumps({"arm": a["name"], "ok": a["ok"], "red": a["red"],
                              "misses": a["misses"]}, ensure_ascii=True))
        base["arms"] = arms
        base["arms_ok"] = all(a["ok"] for a in arms)
        if not base["arms_ok"]:
            base["fatal"] = "oracle arms did not meet expectation"
            write_atomic(OUT, base)
            print(json.dumps({"fatal": base["fatal"], "arms": arms}, ensure_ascii=True))
            return 2

        for pass_no in range(1, PASSES + 1):
            for task in tasks:
                alive = True
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=2) as hr:
                        alive = bool(json.loads(hr.read().decode("utf-8")).get("ok"))
                except Exception as he:
                    alive = False
                try:
                    st, body = post_json(port, "/api/session/new", {})
                except Exception as e:
                    row = {"id": task["id"], "pass": pass_no, "ok": False, "model_ok": False,
                           "steps_ok": False, "answer_ok": False, "answer_echo": True,
                           "misses": ["session_new_exception"], "err": "%s: %s" % (type(e).__name__, e),
                           "hub_alive_before_session": alive, "at": now()}
                    base["runs"].append(row)
                    write_atomic(OUT, base)
                    print(json.dumps(row, ensure_ascii=True))
                    if not alive:
                        base["fatal"] = "hubd died before %s pass %d (health probe failed)" % (task["id"], pass_no)
                        break
                    continue
                if st != 200 or not body.get("ok"):
                    row = {"id": task["id"], "pass": pass_no, "ok": False, "model_ok": False,
                           "steps_ok": False, "answer_ok": False, "answer_echo": True,
                           "misses": ["session_new status=%s" % st], "err": json.dumps(body)[:200],
                           "hub_alive_before_session": alive, "at": now()}
                    base["runs"].append(row)
                    write_atomic(OUT, base)
                    print(json.dumps(row, ensure_ascii=True))
                    continue
                q = task["question"].replace("{fx}", str(fx)).replace(
                    "{hub}", "http://127.0.0.1:%d" % port)
                t0 = time.monotonic()
                r = sse_post(port, "/api/chat", {"text": q}, 180)
                row = summarize(task, pass_no, r, (time.monotonic() - t0) * 1000,
                                fixture=fx)
                row["hub_alive_before_session"] = alive
                base["runs"].append(row)
                write_atomic(OUT, base)
                print(json.dumps({"id": row["id"], "pass": pass_no, "ok": row["ok"],
                                  "model_ok": row["model_ok"], "answer_tier": row["answer_tier"],
                                  "stop": row["stop"],
                                  "steps": row["steps"], "tools": row["tools"],
                                  "misses": row["misses"], "ms": row["ms"],
                                  "err": row["err"]}, ensure_ascii=True))
                time.sleep(0.2)
            if base.get("fatal"):
                break

        runs = base["runs"]
        by_task = {}
        for x in runs:
            d = by_task.setdefault(x["id"], {"ok": 0, "model_ok": 0, "runs": 0, "misses": []})
            d["runs"] += 1
            d["ok"] += 1 if x.get("ok") else 0
            d["model_ok"] += 1 if x.get("model_ok") else 0
            if not x.get("ok"):
                d["misses"].append({"pass": x.get("pass"), "misses": x.get("misses")})
        mss = sorted(x.get("ms") or 0 for x in runs)

        def pct(q):
            return mss[min(len(mss) - 1, int(round(q * (len(mss) - 1))))] if mss else None

        stops = {}
        for x in runs:
            stops[x.get("stop")] = stops.get(x.get("stop"), 0) + 1
        tiers = {}
        for x in runs:
            k = x.get("answer_tier") or "missing"
            tiers[k] = tiers.get(k, 0) + 1
        base["summary"] = {
            "runs": len(runs), "tasks": len(tasks),
            "oracle_ok": sum(1 for x in runs if x.get("ok")),
            "model_ok": sum(1 for x in runs if x.get("model_ok")),
            "steps_ok": sum(1 for x in runs if x.get("steps_ok")),
            "answer_ok": sum(1 for x in runs if x.get("answer_ok")),
            "answer_echo": sum(1 for x in runs if x.get("answer_echo")),
            "answer_tiers": tiers,
            "tasks_both_passes": sum(1 for d in by_task.values()
                                     if d["ok"] == d["runs"] and d["runs"] > 0),
            "tasks_any_pass": sum(1 for d in by_task.values() if d["ok"] > 0),
            "by_task": by_task, "stops": stops,
            "sane": sum(1 for x in runs if x.get("sane")),
            "estimated_steps": sum(x.get("estimated_steps") or 0 for x in runs),
            "ms_p50": pct(0.5), "ms_p95": pct(0.95),
            "ms_max": mss[-1] if mss else None,
            "failures": [{"id": x["id"], "pass": x["pass"], "misses": x.get("misses"),
                          "stop": x.get("stop"), "tools": x.get("tools"),
                          "answer_head": x.get("answer_head"), "err": x.get("err")}
                         for x in runs if not x.get("ok")],
        }
        base["finished"] = now()
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        if lf is not None:
            try:
                lf.close()
            except Exception:
                pass
        landing = {}
        try:
            write_atomic(OUT, base)
            text = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            landing = {
                "reading": OUT.name, "checked_at": now(),
                "reading_exists": OUT.exists(),
                "reading_bytes": OUT.stat().st_size if OUT.exists() else 0,
                "reading_sha256": sha256_file(OUT) if OUT.exists() else None,
                "log_bytes": log_path.stat().st_size if log_path.exists() else 0,
                "key_in_reading": key in text, "key_in_log": key in log_text,
            }
            side = OUT.with_suffix(".landing.json")
            side.write_text(json.dumps(landing, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(json.dumps({"landing_check_error": "%s: %s" % (type(e).__name__, e)},
                             ensure_ascii=True))
        print(json.dumps({"summary": base.get("summary"), "landing": landing,
                          "fatal": base.get("fatal"),
                          "temp_kept": str(temp) if base.get("fatal") else None}, ensure_ascii=True))
        if not base.get("fatal"):
            try:
                shutil.rmtree(temp, ignore_errors=True)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
