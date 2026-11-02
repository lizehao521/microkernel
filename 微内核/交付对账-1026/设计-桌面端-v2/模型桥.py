# -*- coding: utf-8 -*-
"""微核台·模型桥（可选组件）。

边界：
- 只监听 127.0.0.1；不对外开端口。
- 口令只从环境变量 WEIHETAI_MODEL_KEY 读，不写文件、不进日志、不回显。
- 只接受“问题 + 去标识证据摘要”，摘要字段有白名单；记忆、操作者、路径、哈希、回执一律拒收。
- 端点未配置时明确答“未配置”，不伪造成功；上游失败映射成可读错误，不塌成 0。

环境变量：
  WEIHETAI_MODEL_BASE_URL  端点基址（OpenAI 兼容；可带 /v1，也可直接给 /chat/completions）
  WEIHETAI_MODEL           模型名
  WEIHETAI_MODEL_KEY       口令（可缺省，给本机假端点用；真端点通常必填）
  WEIHETAI_MODEL_TIMEOUT   秒，默认 30，允许 1..120
  WEIHETAI_MODEL_MAX_TOKENS 默认 700，允许 64..4096

用法：python 模型桥.py [--port 0]
"""
import argparse
import atexit
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(errors="backslashreplace")
sys.stderr.reconfigure(errors="backslashreplace")

BASE = Path(__file__).resolve().parent
READOUT = BASE / "读数"
ADDR_FILE = READOUT / "模型桥地址.txt"
LOG_FILE = READOUT / "模型桥-日志.jsonl"
VERSION = "0.1.0"
STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")
BOOT_ID = os.urandom(3).hex()

BOUNDARY = "只发问题 + 去标识证据摘要；不发记忆、操作者、文件路径、sha256、回执、口令"

BASE_URL = (os.environ.get("WEIHETAI_MODEL_BASE_URL") or "").strip()
MODEL = (os.environ.get("WEIHETAI_MODEL") or "").strip()
KEY = (os.environ.get("WEIHETAI_MODEL_KEY") or "").strip()
try:
    TIMEOUT = max(1.0, min(120.0, float(os.environ.get("WEIHETAI_MODEL_TIMEOUT") or 30)))
except ValueError:
    TIMEOUT = 30.0
try:
    MAX_TOKENS = max(64, min(4096, int(os.environ.get("WEIHETAI_MODEL_MAX_TOKENS") or 700)))
except ValueError:
    MAX_TOKENS = 700

LOCK = threading.RLock()
STATE = {
    "calls": 0,
    "last_error": "",
    "last_ms": None,
    "last_upstream_status": None,
}

ALLOWED_TOP = {"deliveries", "not_same_run"}
ALLOWED_DELIVERY = {"id", "title", "agent", "verdict", "counts", "claims"}
ALLOWED_CLAIM = {"id", "text", "verdict", "basis", "why"}
ALLOWED_COUNTS = {"MATCH", "MISMATCH", "ABSENT"}
FORBIDDEN_KEYS = {
    "memory", "operator", "path", "paths", "sha256", "hash", "receipt", "receipts",
    "key", "token", "secret", "env", "owner",
}
FORBIDDEN_TEXT = ("C:\\", "/Users/", "/home/", "记忆/", "回执/", "api_key", "bearer ")
HEX_HASH = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40,64}(?![0-9a-fA-F])")
MAX_DIGEST_CHARS = 16000

SYSTEM_PROMPT = """你是微核台的“模型转述员”。你只能依据用户消息里的证据摘要回答，不得使用摘要以外的事实。

规则：
1. 中文；先给结论，再说依据；总长不超过 180 字。
2. 只许引用摘要里出现的声明编号（如 D1-C4）；不要编造编号。
3. 数字只能照抄摘要里的计数，不得加总、外推或估算。
4. “核不了”不许说成通过；“模型推断”不许说成实测；摘要不足就写“核不了：<缺什么>”。
5. 对话只读：不得建议或代替收 / 退 / 挂起。
6. 不输出 Markdown，不输出代码块。

输出一个 JSON 对象：
{"title":"不超过18字","text":"结论与依据","refs":["D1-C4"]}
refs 只能取摘要里出现的声明编号；没有可引用的就写空数组。"""


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def base_host(url):
    try:
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""
    except ValueError:
        return ""


def chat_url(url):
    b = url.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return b + "/chat/completions"


def configured():
    return bool(BASE_URL and MODEL)


def redact(text, limit=300):
    s = str(text or "")
    if KEY:
        s = s.replace(KEY, "***")
    s = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1***", s)
    s = re.sub(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*)[^,\s}]+", r"\1***", s)
    s = s.replace("\x00", "")
    return s[:limit]


def log_event(event, **fields):
    rec = {"at": now_iso(), "event": event, "version": VERSION}
    rec.update(fields)
    try:
        READOUT.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def health():
    with LOCK:
        st = dict(STATE)
    return {
        "ok": True,
        "service": "weihetai-model-bridge",
        "version": VERSION,
        "boot_id": BOOT_ID,
        "started_at": STARTED_AT,
        "state": "ready" if configured() else "unconfigured",
        "provider": "openai-compatible",
        "model": MODEL,
        "base_host": base_host(BASE_URL),
        "key_present": bool(KEY),
        "timeout_s": TIMEOUT,
        "max_tokens": MAX_TOKENS,
        "boundary": BOUNDARY,
        "calls": st["calls"],
        "last_error": st["last_error"],
        "last_ms": st["last_ms"],
        "last_upstream_status": st["last_upstream_status"],
        "why": "" if configured() else "未设置 WEIHETAI_MODEL_BASE_URL / WEIHETAI_MODEL",
    }


def validate_digest(digest):
    if not isinstance(digest, dict):
        return "摘要必须是对象"
    extra = set(digest) - ALLOWED_TOP
    if extra:
        return "摘要含未允许的顶层字段：" + ", ".join(sorted(extra))
    dels = digest.get("deliveries")
    if not isinstance(dels, list) or not (1 <= len(dels) <= 10):
        return "deliveries 必须是 1..10 的数组"
    sizes = {"claims": 0}
    for d in dels:
        if not isinstance(d, dict):
            return "deliveries 的元素必须是对象"
        extra = set(d) - ALLOWED_DELIVERY
        if extra:
            return "交付项含未允许字段：" + ", ".join(sorted(extra))
        for k in ("id", "title", "agent", "verdict"):
            if not isinstance(d.get(k), str) or not d.get(k).strip():
                return f"交付项缺 {k}"
        counts = d.get("counts")
        if not isinstance(counts, dict) or set(counts) - ALLOWED_COUNTS:
            return "counts 只允许 MATCH / MISMATCH / ABSENT"
        for k, v in counts.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                return f"counts.{k} 必须是非负整数"
        claims = d.get("claims")
        if not isinstance(claims, list) or not (1 <= len(claims) <= 100):
            return "claims 必须是 1..100 的数组"
        sizes["claims"] += len(claims)
        for c in claims:
            if not isinstance(c, dict):
                return "claims 的元素必须是对象"
            extra = set(c) - ALLOWED_CLAIM
            if extra:
                return "声明含未允许字段：" + ", ".join(sorted(extra))
            for k in ("id", "text", "verdict", "basis", "why"):
                if not isinstance(c.get(k), str):
                    return f"声明缺 {k}"
            if len(c.get("text", "")) > 300 or len(c.get("why", "")) > 600:
                return "声明文本过长"
    nsr = digest.get("not_same_run")
    if nsr is not None:
        if not isinstance(nsr, list) or len(nsr) > 10 or any(not isinstance(x, str) for x in nsr):
            return "not_same_run 必须是字符串数组（≤10）"
    blob = json.dumps(digest, ensure_ascii=False)
    if len(blob) > MAX_DIGEST_CHARS:
        return f"摘要超过 {MAX_DIGEST_CHARS} 字符"
    low = blob.lower()
    for bad in FORBIDDEN_TEXT:
        if bad.lower() in low:
            return "摘要含疑似本机路径 / 口令字样：" + bad
    if HEX_HASH.search(blob):
        return "摘要含疑似哈希值（40-64 位十六进制）"
    for k in walk_keys(digest):
        if k.lower() in FORBIDDEN_KEYS:
            return "摘要含未允许的键：" + k
    return ""


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v)


def claim_index(digest):
    idx = {}
    for d in digest.get("deliveries") or []:
        for c in d.get("claims") or []:
            cid = c.get("id")
            if cid and cid not in idx:
                idx[cid] = c.get("text") or ""
    return idx


def parse_model_json(content):
    s = str(content or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            obj = json.loads(s[a:b + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {"title": "模型解释", "text": s[:2000], "refs": []}


def normalize_refs(raw_refs, text, idx):
    refs = []
    seen = set()

    def add(cid):
        cid = str(cid or "").strip()
        if cid in idx and cid not in seen:
            seen.add(cid)
            label = cid + " " + idx[cid][:20]
            refs.append({"kind": "claim", "id": cid, "label": label})

    if isinstance(raw_refs, list):
        for r in raw_refs:
            if isinstance(r, str):
                add(r)
            elif isinstance(r, dict):
                add(r.get("id"))
            if len(refs) >= 6:
                break
    if len(refs) < 6:
        for cid in re.findall(r"\bD\d+-C\d+\b", str(text or "")):
            add(cid)
            if len(refs) >= 6:
                break
    return refs


def upstream_explain(question, digest):
    if not configured():
        return 503, {"ok": False, "error": "NO_ENDPOINT", "why": "模型桥未配置端点：设置 WEIHETAI_MODEL_BASE_URL / WEIHETAI_MODEL 后重启", "call_made": False, "calls": STATE["calls"]}
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"question": question, "evidence": digest}, ensure_ascii=False)},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "weihetai-model-bridge/" + VERSION}
    if KEY:
        headers["Authorization"] = "Bearer " + KEY
    req = urllib.request.Request(chat_url(BASE_URL), data=body, headers=headers, method="POST")
    t0 = time.time()
    with LOCK:
        STATE["calls"] += 1
        STATE["last_error"] = ""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read(2_000_000)
            status = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(2000).decode("utf-8", "replace")
        except Exception:
            detail = ""
        why = f"端点返回 HTTP {e.code}：" + redact(detail)
        with LOCK:
            STATE["last_error"] = f"UPSTREAM_{e.code}"
            STATE["last_ms"] = int((time.time() - t0) * 1000)
            STATE["last_upstream_status"] = e.code
        log_event("explain", ok=False, error=f"UPSTREAM_{e.code}", status=e.code, ms=STATE["last_ms"], question_chars=len(question), digest_chars=len(json.dumps(digest, ensure_ascii=False)))
        return 502, {"ok": False, "error": f"UPSTREAM_{e.code}", "why": why, "call_made": True, "calls": STATE["calls"], "upstream_status": e.code}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        timed = isinstance(e, TimeoutError) or "timed out" in str(reason).lower() or "timeout" in str(reason).lower()
        err = "TIMEOUT" if timed else "UPSTREAM_UNREACHABLE"
        why = (f"端点 {TIMEOUT:.0f}s 内没有回应" if timed else "端点不可达：" + redact(reason))
        with LOCK:
            STATE["last_error"] = err
            STATE["last_ms"] = int((time.time() - t0) * 1000)
        log_event("explain", ok=False, error=err, ms=STATE["last_ms"], question_chars=len(question), digest_chars=len(json.dumps(digest, ensure_ascii=False)))
        return 504 if timed else 502, {"ok": False, "error": err, "why": why, "call_made": True, "calls": STATE["calls"]}

    ms = int((time.time() - t0) * 1000)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        choices = data.get("choices") or []
        content = choices[0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    except Exception:
        with LOCK:
            STATE["last_error"] = "BAD_RESPONSE"
            STATE["last_ms"] = ms
        log_event("explain", ok=False, error="BAD_RESPONSE", status=status, ms=ms, upstream_bytes=len(raw))
        return 502, {"ok": False, "error": "BAD_RESPONSE", "why": "端点回了非 OpenAI 兼容的响应或空 choices", "call_made": True, "calls": STATE["calls"], "upstream_status": status}

    obj = parse_model_json(content)
    title = str(obj.get("title") or "模型解释").strip()[:40]
    text = str(obj.get("text") or "").strip()[:2000]
    if not text:
        text = str(content or "").strip()[:2000]
    idx = claim_index(digest)
    refs = normalize_refs(obj.get("refs"), text, idx)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    with LOCK:
        STATE["last_error"] = ""
        STATE["last_ms"] = ms
        STATE["last_upstream_status"] = status
    log_event("explain", ok=True, status=status, ms=ms, question_chars=len(question), digest_chars=len(json.dumps(digest, ensure_ascii=False)), upstream_bytes=len(raw))
    return 200, {
        "ok": True,
        "title": title,
        "text": text,
        "refs": refs,
        "model": MODEL,
        "provider": "openai-compatible",
        "ms": ms,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage.get(k), int)},
        "call_made": True,
        "calls": STATE["calls"],
        "boundary": BOUNDARY,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "WeihetaiModelBridge/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/health":
            return self._send(200, health())
        return self._send(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/explain":
            return self._send(404, {"ok": False, "error": "NOT_FOUND"})
        if self.headers.get("Origin"):
            return self._send(403, {"ok": False, "error": "ORIGIN_REJECTED", "why": "模型桥只接受本机服务调用，不接受浏览器跨源请求"})
        if self.headers.get("X-Weihetai-Bridge") != "1":
            return self._send(403, {"ok": False, "error": "BRIDGE_HEADER_REQUIRED", "why": "缺少 X-Weihetai-Bridge: 1"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 65536:
            return self._send(400, {"ok": False, "error": "BAD_SIZE", "why": "请求体需为 1..64KB"})
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(400, {"ok": False, "error": "BAD_TYPE", "why": "需要 application/json"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, {"ok": False, "error": "BAD_JSON"})
        question = str(body.get("question") or "").strip()
        if not question or len(question) > 500:
            return self._send(400, {"ok": False, "error": "BAD_QUESTION", "why": "问题需为 1..500 字"})
        why = validate_digest(body.get("digest"))
        if why:
            log_event("rejected", error="BAD_DIGEST", why=why[:200], question_chars=len(question))
            return self._send(400, {"ok": False, "error": "BAD_DIGEST", "why": why, "call_made": False})
        code, obj = upstream_explain(question, body["digest"])
        return self._send(code, obj)


def write_addr(port):
    try:
        READOUT.mkdir(parents=True, exist_ok=True)
        text = (
            f"http://127.0.0.1:{port}/\n"
            f"BOOT {BOOT_ID} VERSION {VERSION}\n"
            f"started_at {STARTED_AT}\n"
            "state " + ("ready" if configured() else "unconfigured") + "\n"
        )
        tmp = ADDR_FILE.with_suffix(".txt.part")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, ADDR_FILE)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = srv.server_address[1]
    write_addr(port)
    print(f"MODEL_BRIDGE http://127.0.0.1:{port}/", flush=True)
    print(f"STATE {'ready' if configured() else 'unconfigured'}", flush=True)
    print(f"MODEL {MODEL or '-'}", flush=True)
    print(f"BASE_HOST {base_host(BASE_URL) or '-'}", flush=True)
    print(f"KEY_PRESENT {str(bool(KEY)).lower()}", flush=True)
    print("BOUNDARY ascii-only-log; no key in files", flush=True)
    log_event("start", port=port, state="ready" if configured() else "unconfigured", model=MODEL, base_host=base_host(BASE_URL))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        log_event("stop", port=port)


if __name__ == "__main__":
    atexit.register(lambda: log_event("exit"))
    main()
