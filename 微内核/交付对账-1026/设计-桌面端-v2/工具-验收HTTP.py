# -*- coding: utf-8 -*-
"""微核台本地服务的 HTTP 验收：只打 127.0.0.1，做规则/安全/落盘核对。
用法：python 工具-验收HTTP.py [--base http://127.0.0.1:PORT]
默认从 读数/服务地址.txt 读地址。控制台只打印 ASCII；报告写 UTF-8。
"""
import argparse
import hashlib
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
READOUT = BASE / "读数" / "验收-HTTP.txt"
ADDR = BASE / "读数" / "服务地址.txt"
REPORT = []
RESULTS = []


def sha(b):
    return hashlib.sha256(b).hexdigest()


def note(line=""):
    REPORT.append(line)


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    REPORT.append(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))
    print(("PASS " if ok else "FAIL ") + name)


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def raw(self, method, path, data=None, headers=None, timeout=20):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
        except Exception as e:
            return 0, {}, str(e).encode("utf-8", "replace")

    def json(self, method, path, obj=None, headers=None, raw=None):
        h = {"Content-Type": "application/json"} if (obj is not None or raw is not None) else {}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(obj, ensure_ascii=False).encode("utf-8") if obj is not None else None)
        st, hd, body = self.raw(method, path, data=data, headers=h)
        try:
            return st, hd, json.loads(body.decode("utf-8"))
        except Exception:
            return st, hd, {"_raw": body[:400].decode("utf-8", "replace")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    args = ap.parse_args()
    base = args.base.strip()
    if not base:
        if not ADDR.exists():
            print("RESULT FAIL no base url and no readout address file")
            return 2
        base = ADDR.read_text(encoding="utf-8").splitlines()[0].strip()
    if not re.match(r"^http://127\.0\.0\.1:\d+/$", base):
        print("RESULT FAIL base must be loopback http url:", base)
        return 2
    c = Client(base)
    note("BASE " + base)
    note("")

    # ---------- read-only surface ----------
    st, hd, page = c.raw("GET", "/")
    html_file = BASE / "微核台.html"
    check("GET / 200", st == 200, f"status={st}")
    check("GET / bytes match build", html_file.exists() and page == html_file.read_bytes(), f"got={len(page)} file={html_file.stat().st_size if html_file.exists() else 'missing'}")
    check("GET / sha match build", sha(page) == sha(html_file.read_bytes()) if html_file.exists() else False)
    csp = hd.get("Content-Security-Policy", "")
    check("CSP self only", "default-src 'self'" in csp and "connect-src 'self'" in csp, csp[:160])
    check("nosniff", hd.get("X-Content-Type-Options") == "nosniff")
    text = page.decode("utf-8")
    check("single-file no <link>", "<link" not in text.lower())
    check("single-file no script src", not re.search(r"<script[^>]+src=", text, re.I))
    ext = re.findall(r"https?://([^/\"'\s<>]+)", text)
    check("no external hosts in page", not ext, ",".join(sorted(set(ext))))

    st, _, health = c.json("GET", "/api/health")
    check("health ok", st == 200 and health.get("ok") is True and health.get("version") == "0.3.0-prototype", health)

    check("page has model control", 'id="modelPill"' in text and 'id="useModel"' in text and "模型转述" in text)
    check("page has model toggle copy", "用模型解释（发去标识摘要）" in text and "不发记忆" in text)

    st, _, s = c.json("GET", "/api/state")
    check("state 200", st == 200 and s.get("ok") is True, f"status={st}")
    mdl = s.get("model") or {}
    check("state model off by default", mdl.get("state") == "off" and mdl.get("calls") == 0, f"state={mdl.get('state')} calls={mdl.get('calls')}")
    check("state model boundary declared", "不发记忆" in (mdl.get("boundary") or ""), mdl.get("boundary"))
    st, _, mo = c.json("GET", "/api/model")
    check("api model off", st == 200 and (mo.get("model") or {}).get("state") == "off", f"status={st}")
    st, _, mr = c.json("POST", "/api/dialogue", {"q": "模型接入了吗？", "use_model": True})
    ma = mr.get("answer") or {}
    check("use_model without bridge absent", st == 200 and ma.get("tier") == "absent" and ma.get("title") == "模型未接入", f"tier={ma.get('tier')} title={ma.get('title')}")
    check("use_model without bridge 0 calls", ma.get("source") == "model" and ma.get("model_calls") == 0, f"source={ma.get('source')} calls={ma.get('model_calls')}")
    ds = s.get("evidence", {}).get("deliveries", [])
    check("state 3 deliveries", len(ds) == 3, f"got={len(ds)}")
    claims = [c2 for d in ds for c2 in d.get("claims", [])]
    check("state 16 claims", len(claims) == 16, f"got={len(claims)}")
    check("claims basis all disk/absent", all(c2.get("basis") in ("disk", "absent") for c2 in claims))
    for d in ds:
        cs = d.get("claims", [])
        cnt = d.get("counts", {})
        actual = {k: sum(1 for x in cs if x.get("verdict") == k) for k in ("MATCH", "MISMATCH", "ABSENT")}
        check("counts add up " + d["id"], cnt.get("MATCH") == actual["MATCH"] and cnt.get("MISMATCH") == actual["MISMATCH"] and cnt.get("ABSENT") == actual["ABSENT"], f"field={cnt} actual={actual}")
    d1 = next(d for d in ds if d["id"] == "D-1026-01")
    d2 = next(d for d in ds if d["id"] == "D-1026-02")
    d3 = next(d for d in ds if d["id"] == "D-1026-03")
    check("D1 allowed only reject", d1.get("allowed") == ["reject"], d1.get("allowed"))
    check("D2 allowed accept+reject", d2.get("allowed") == ["accept", "reject"], d2.get("allowed"))
    check("D3 allowed reject+hold", d3.get("allowed") == ["reject", "hold"], d3.get("allowed"))
    c1 = {x["id"]: x for x in d1["claims"]}
    c3 = {x["id"]: x for x in d3["claims"]}
    check("D1-C4/C5 mismatch", c1["D1-C4"]["verdict"] == "MISMATCH" and c1["D1-C5"]["verdict"] == "MISMATCH")
    check("D1-C6 + D3-C5 absent", c1["D1-C6"]["verdict"] == "ABSENT" and c3["D3-C5"]["verdict"] == "ABSENT")
    check("absent claims carry why", all(x.get("why") for x in claims if x["verdict"] == "ABSENT"))

    bd = s.get("bundles", {})
    pg, ag, kn = bd.get("pgagent"), bd.get("agentd"), bd.get("kernel")
    check("bundle pgagent 13 steps", pg and pg["counts"]["steps"] == 13 and len(pg["steps"]) == 13, pg and pg.get("counts"))
    check("bundle agentd 14 events / 2 runs", ag and ag["counts"]["events"] == 14 and ag["counts"]["runs"] == 2 and len(ag["events"]) == 14, ag and ag.get("counts"))
    check("bundle kernel 49 rows", kn and len(kn["rows"]) == 49 and kn["block"]["rows"] == 49, kn and len(kn.get("rows", [])))
    check("kernel basis sums to 49", kn and sum(kn["basis_mix"].values()) == 49, kn and kn.get("basis_mix"))
    check("kernel hash 49/49", kn and kn["checks"]["payload_hash_ok"] == 49 and kn["checks"]["block_links_ok"] == 48)
    check("pgagent code not executed", pg and pg["execution"]["code_executed"] is False and pg["execution"]["real_model_calls"] == 0)

    # bundle source hashes vs raw files
    for name, obj, raw_rel in (("pgagent", pg, pg["source"]["file"]), ("agentd", ag, ag["source"]["file"]), ("kernel", kn, kn["source"]["file"])):
        raw = BASE / raw_rel
        check("raw hash " + name, raw.exists() and sha(raw.read_bytes()) == obj["source"]["sha256"], raw_rel)
    idx = bd.get("index", {})
    bad_idx = []
    for f in idx.get("files", []):
        rel = ("证据/" + f["file"]) if f.get("file") else (("证据/raw/" + f["name"]) if f.get("name") else "")
        p = BASE / rel
        if not p.exists() or sha(p.read_bytes()) != f["sha256"]:
            bad_idx.append(rel or f.get("kind"))
    check("index file hashes all match", not bad_idx, ",".join(bad_idx))

    k = s.get("kernel", {})
    check("kernel gate done", k.get("state") == "done", f"state={k.get('state')} why={k.get('why')}")
    check("kernel gate rc=0 bad=0", k.get("rc") == 0 and k.get("checks_bad") == 0, f"rc={k.get('rc')} bad={k.get('checks_bad')}")
    check("kernel counts non-zero", (k.get("checks_ok") or 0) > 0, f"ok={k.get('checks_ok')} unknown={k.get('unknown_lines')}")
    check("kernel exe hash 64 hex", bool(re.fullmatch(r"[0-9a-f]{64}", k.get("exe_sha256") or "")))
    ro = BASE / k.get("readout", "")
    roj = json.loads(ro.read_text(encoding="utf-8")) if ro.exists() else {}
    check("kernel readout matches snapshot", roj.get("rc") == k.get("rc") and roj.get("checks_ok") == k.get("checks_ok") and roj.get("checks_bad") == k.get("checks_bad") and roj.get("exe_sha256") == k.get("exe_sha256"), k.get("readout"))

    # ---------- dialogue ----------
    questions = [
        ("测试过了吗？", "measured", "不符"),
        ("有没有执行代码？", "measured", "没有执行"),
        ("真实模型复核过吗？", "measured", "不符"),
        ("这版能收吗？", "measured", "三单"),
        ("哪些核不了？", "absent", "2 条核不了"),
        ("证据在哪？", "measured", "证据索引"),
        ("49 格在哪？", "measured", "49"),
        ("事件断线可续吗？", "absent", "核不了"),
        ("内核快闸跑了吗？", "measured", "内核快闸"),
        ("我的记忆在哪？", "measured", "只在本机"),
        ("上次为什么退？", "absent", "还没有决定"),
        ("帮我收下这单", "refused", "不能收"),
        ("帮我写一首诗", "refused", "不在本机"),
        ("明天天气怎么样？", "refused", "不在本机"),
        ("怎么用？", "measured", "能做什么"),
        ("为什么不能收？", "measured", "为什么 D-1026-01 不能收"),
    ]
    for q, tier, frag in questions:
        st, _, r = c.json("POST", "/api/dialogue", {"q": q})
        a = r.get("answer", {})
        ok = st == 200 and a.get("tier") == tier and frag in (a.get("title", "") + a.get("text", "")) and a.get("model_calls") == 0 and a.get("source") == "local_rules"
        check("dialogue " + q, ok, f"status={st} tier={a.get('tier')} title={a.get('title')}")
        note("  Q " + q + " -> [" + str(a.get("tier")) + "] " + str(a.get("title")) + " refs=" + str(len(a.get("refs") or [])))
    st, _, mem = c.json("GET", "/api/memory")
    check("dialogue persisted 16+", len(mem.get("memory", {}).get("dialogue", [])) >= 16, len(mem.get("memory", {}).get("dialogue", [])))
    check("dialogue rows have q/tier/text", all(x.get("q") and x.get("tier") and x.get("text") for x in mem["memory"]["dialogue"]))

    # ---------- decision rules ----------
    receipts_before = {p.name for p in (BASE / "回执").glob("receipt-*.html")}
    def dec(did, action, reason="", headers=None):
        return c.json("POST", "/api/decision", {"delivery_id": did, "action": action, "reason": reason}, headers=headers)

    st, _, r = dec("D-1026-01", "accept", "想直接收")
    check("D1 accept disallowed", st == 409 and r.get("error") == "DISALLOWED", f"status={st} err={r.get('error')}")
    st, _, r = dec("D-1026-02", "hold", "想挂起")
    check("D2 hold disallowed", st == 409 and r.get("error") == "DISALLOWED", f"status={st} err={r.get('error')}")
    st, _, r = dec("D-1026-03", "accept", "想直接收")
    check("D3 accept disallowed", st == 409 and r.get("error") == "DISALLOWED", f"status={st} err={r.get('error')}")
    st, _, r = dec("D-1026-01", "reject", "短理由")
    check("reject short reason 422", st == 422 and r.get("error") == "REASON_REQUIRED", f"status={st} err={r.get('error')}")
    st, _, r = dec("NO-SUCH", "reject", "x")
    check("unknown delivery 404", st == 404 and r.get("error") == "NO_DELIVERY", f"status={st} err={r.get('error')}")

    st, _, r = dec("D-1026-01", "reject", "测试声明没有盘上证据")
    d1r = r.get("decision", {})
    rc1 = r.get("receipt", {})
    check("D1 reject accepted", st == 200 and d1r.get("action") == "reject" and rc1.get("file"), f"status={st} err={r.get('error')}")
    p1 = BASE / rc1.get("file", "")
    rtext = p1.read_text(encoding="utf-8") if p1.exists() else ""
    check("D1 receipt exists", p1.exists() and p1.stat().st_size == rc1.get("bytes") and sha(p1.read_bytes()) == rc1.get("sha256"), rc1.get("file"))
    check("D1 receipt has 6 claims", all(("D1-C%d" % i) in rtext for i in range(1, 7)))
    check("D1 receipt has reason", "测试声明没有盘上证据" in rtext)
    check("D1 receipt has kernel readout", ("rc=" + str(k.get("rc"))) in rtext and (k.get("exe_sha256") or "x")[:16] in rtext)
    check("D1 receipt self-contained", "<style>" in rtext and "http://" not in rtext and "https://" not in rtext)
    st, _, r = dec("D-1026-01", "reject", "再退一次")
    check("D1 repeat 409", st == 409 and r.get("error") == "ALREADY_DECIDED", f"status={st} err={r.get('error')}")

    st, _, r = dec("D-1026-02", "accept", "")
    d2r = r.get("decision", {})
    check("D2 accept accepted", st == 200 and d2r.get("action") == "accept" and d2r.get("reason"), f"status={st} err={r.get('error')}")
    p2 = BASE / r.get("receipt", {}).get("file", "")
    check("D2 receipt exists", p2.exists() and sha(p2.read_bytes()) == r.get("receipt", {}).get("sha256"))

    st, _, r = dec("D-1026-03", "hold", "证据缺席，无法判断")
    d3r = r.get("decision", {})
    check("D3 hold accepted", st == 200 and d3r.get("action") == "hold", f"status={st} err={r.get('error')}")
    p3 = BASE / r.get("receipt", {}).get("file", "")
    check("D3 receipt exists", p3.exists() and sha(p3.read_bytes()) == r.get("receipt", {}).get("sha256"))
    st, _, r = dec("D-1026-03", "reject", "改主意了")
    check("D3 repeat 409", st == 409 and r.get("error") == "ALREADY_DECIDED", f"status={st} err={r.get('error')}")

    st, _, mem = c.json("GET", "/api/memory")
    decs = mem["memory"]["decisions"]
    check("memory 3 decisions", len(decs) == 3, len(decs))
    check("memory decisions have receipts", all(x.get("receipt", {}).get("sha256") for x in decs))
    mf = BASE / mem["meta"]["file"]
    check("memory file hash matches meta", mf.exists() and sha(mf.read_bytes()) == mem["meta"]["sha256"])
    receipts_now = {p.name for p in (BASE / "回执").glob("receipt-*.html")}
    new_receipts = receipts_now - receipts_before
    want_receipts = {p1.name, p2.name, p3.name}
    check("receipt files 3 new", new_receipts == want_receipts, ",".join(sorted(new_receipts)))

    # ---------- preference / reason template ----------
    st, _, r = c.json("POST", "/api/memory/reason", {"text": "验收模板甲"})
    check("reason add", st == 200 and "验收模板甲" in (r.get("reasons") or []), f"status={st}")
    st, _, r = c.json("POST", "/api/memory/reason", {"text": "短"})
    check("reason too short 422", st == 422, f"status={st}")
    st, _, r = c.json("POST", "/api/memory/reason/delete", {"text": "验收模板甲"})
    check("reason delete", st == 200 and "验收模板甲" not in (r.get("reasons") or []), f"status={st}")
    st, _, r = c.json("POST", "/api/memory/preferences", {"operator_name": "验收操作者", "require_reason": True})
    check("preference save", st == 200 and r.get("preferences", {}).get("operator_name") == "验收操作者", f"status={st}")
    st, _, r = c.json("GET", "/api/memory/export")
    check("memory export json", st == 200 and r.get("preferences", {}).get("operator_name") == "验收操作者", f"status={st}")

    # ---------- security ----------
    st, _, r = dec("D-1026-02", "accept", "跨站", headers={"Origin": "http://evil.example"})
    check("cross-origin POST 403", st == 403 and r.get("error") == "ORIGIN_REJECTED", f"status={st} err={r.get('error')}")
    st, _, r = c.json("POST", "/api/memory/preferences", raw=b'{"operator_name":"x"}', headers={"Content-Type": "text/plain"})
    check("text/plain POST 400", st == 400 and r.get("error") == "BAD_JSON", f"status={st} err={r.get('error')}")
    big = json.dumps({"q": "a" * 66000}).encode("utf-8")
    st, _, r = c.json("POST", "/api/dialogue", raw=big)
    check("oversized POST 400", st == 400, f"status={st} err={r.get('error')}")
    up = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(up.hostname, up.port, timeout=10)
    conn.putrequest("POST", "/api/dialogue")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "70000")
    conn.endheaders()
    conn.send(b"{}")
    resp = conn.getresponse()
    check("declared 70KB POST 400", resp.status == 400, f"status={resp.status}")
    resp.read()
    conn.close()
    st, _, r = c.json("GET", "/api/receipt/" + urllib.parse.quote("../记忆/记忆.json", safe=""))
    check("receipt traversal 400", st == 400 and r.get("error") == "BAD_NAME", f"status={st} err={r.get('error')}")
    st, _, r = c.json("POST", "/api/nope", {})
    check("unknown POST 404", st == 404, f"status={st}")

    # restore operator name, then clear decisions/dialogue (keep preferences + reasons)
    c.json("POST", "/api/memory/preferences", {"operator_name": "本机操作者"})
    st, _, r = c.json("POST", "/api/memory/clear", {"confirm": "CLEAR"})
    check("memory clear", st == 200 and not r.get("memory", {}).get("decisions") and not r.get("memory", {}).get("dialogue"), f"status={st}")
    st, _, r = c.json("POST", "/api/memory/clear", {})
    check("memory clear needs confirm", st == 422 and r.get("error") == "CONFIRM_REQUIRED", f"status={st}")
    st, _, mem = c.json("GET", "/api/memory")
    check("clear kept preferences", mem["memory"]["preferences"].get("operator_name") == "本机操作者" and len(mem["memory"]["preferences"].get("reasons", [])) >= 3)

    # ---------- readouts ----------
    note("")
    note("READOUTS")
    note("html bytes=%d sha256=%s" % (len(page), sha(page)))
    note("deliveries=%d claims=%d" % (len(ds), len(claims)))
    note("kernel rc=%s ok=%s bad=%s unknown=%s exe=%s elapsed_ms=%s" % (k.get("rc"), k.get("checks_ok"), k.get("checks_bad"), k.get("unknown_lines"), k.get("exe_sha256"), k.get("elapsed_ms")))
    note("pgagent steps=%s trace_sane=%s chain_sane=%s code_executed=%s" % (pg["counts"]["steps"], pg["sanity"]["trace_sane"], pg["sanity"]["chain_sane"], pg["execution"]["code_executed"]))
    note("agentd events=%s runs=%s turns_settled=%s runs_settled=%s" % (ag["counts"]["events"], ag["counts"]["runs"], ag["counts"]["turns_settled"], ag["counts"]["runs_settled"]))
    note("kernel rows=%s basis=%s" % (len(kn["rows"]), json.dumps(kn["basis_mix"], ensure_ascii=False)))
    note("model state=%s calls=%s boundary=%s" % (mdl.get("state"), mdl.get("calls"), mdl.get("boundary")))
    note("receipts=" + ",".join(receipts_now))
    note("note: receipts from this HTTP acceptance remain in 回执/; the script cleared decisions/dialogue afterwards.")

    bad = [n for n, ok in RESULTS if not ok]
    note("")
    note("RESULT " + ("PASS" if not bad else "FAIL") + " checks=%d/%d" % (len(RESULTS) - len(bad), len(RESULTS)))
    READOUT.write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    print("RESULT " + ("PASS" if not bad else "FAIL") + " checks=%d/%d" % (len(RESULTS) - len(bad), len(RESULTS)))
    print("REPORT 读数/验收-HTTP.txt")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
