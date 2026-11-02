"""交付包逐件 smoke：4 个入口件真跑（kresearch 不跑，理由写在读数里），
并把内核 README 点名的那条「两面各跑一遍、tools/list 逐字节对照还没有」补上。
所有端口用 8802/8803（避开挂载中的 8797），起过的进程收尾必收干净。"""
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

SRC = r"C:\Users\Admin\Desktop\微内核\微内核\微内核"
BIN = os.path.join(SRC, "..", "..", "构建-1017", "agentkernel", "bin")
OUT = os.path.join(SRC, "..", "..", "构建-1017", "日志")
rep = []
w = rep.append


def _post(url, payload, headers=None, timeout=8):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def call(kind, url, payload=None, headers=None, timeout=8):
    """把传输层结果当一等信息记：拿到状态码就记码，被重置/超时也原样记 —— 不许重试到绿。"""
    try:
        if kind == "POST":
            return ("HTTP",) + _post(url, payload or {}, headers, timeout)
        return ("HTTP",) + get(url, headers, timeout)
    except urllib.error.HTTPError as e:
        # 有状态码就必须记状态码 —— 让它落到下面的 except 会把 405 压成 'HTTPError'，读数精度就坏了
        return ("HTTP", e.code, e.read())
    except Exception as e:  # ConnectionResetError / timeout 都是可观测结果
        return ("EXC", type(e).__name__, str(e)[:60])


def dist(kind, url, payload=None, n=5, raw=None):
    """raw 给了就直接当体发（空体对照用），不给就按 payload 序列化。"""
    counts = {}
    for _ in range(n):
        if raw is not None:
            try:
                req = urllib.request.Request(url, data=raw, method="POST")
                with urllib.request.urlopen(req, timeout=8) as rr:
                    key = rr.status
            except urllib.error.HTTPError as e:
                key = e.code
            except Exception as e:
                key = type(e).__name__
        else:
            r = call(kind, url, payload)
            key = r[1]
        counts[key] = counts.get(key, 0) + 1
    return counts


def get(url, headers=None, timeout=8):
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_port(addr, want=True, limit=12):
    for _ in range(limit):
        with socket.socket() as s:
            s.settimeout(0.4)
            got = s.connect_ex(addr) == 0
        if got == want:
            return True
        time.sleep(0.4)
    return False


def killed(proc):
    """Windows 上 proc.kill() 不保证收掉，收尾用 taskkill /PID /F 兜一遍。"""
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/F"], capture_output=True)
    try:
        proc.wait(timeout=6)
    except Exception:
        pass


def rpc_line(msg):
    return json.dumps(msg, ensure_ascii=False) + "\n"


def summ(r):
    return "HTTP %s（%d 字节）" % (r[1], len(r[2])) if r[0] == "HTTP" else "传输层异常 %s" % r[1]


def body(r):
    return r[2] if r[0] == "HTTP" else b""


def main():
    # ---- 1) mcpkernel：stdio 面，行分隔 JSON-RPC ----
    exe = os.path.join(BIN, "mcpkernel.exe")
    p = subprocess.Popen([exe], cwd=SRC, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.stdin.write(rpc_line({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params":
                            {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "smoke", "version": "1"}}}).encode("utf-8"))
    p.stdin.flush()
    init_raw = p.stdout.readline()
    p.stdin.write(rpc_line({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8"))
    p.stdin.flush()
    list_raw = p.stdout.readline()
    p.stdin.close()
    killed(p)
    stdio_tools = json.loads(list_raw.decode("utf-8")).get("result", {}).get("tools", [])
    w("【mcpkernel·stdio】initialize 回 %d 字节 ｜ tools/list 回 %d 字节 ｜ 工具数 %d"
      % (len(init_raw), len(list_raw), len(stdio_tools)))

    # ---- 2) mcphttp：HTTP 面，同一个 mcpsrv ----
    addr = ("127.0.0.1", 8802)
    p = subprocess.Popen([os.path.join(BIN, "mcphttp.exe"), "-listen", "127.0.0.1:8802"],
                         cwd=SRC, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    up = wait_port(addr, True)
    url = "http://127.0.0.1:8802/mcp"
    r1 = call("POST", url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params":
                           {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "smoke", "version": "1"}}})
    r2 = call("POST", url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    b2 = body(r2)
    http_tools = json.loads(b2.decode("utf-8")).get("result", {}).get("tools", []) if b2 else []
    # 非 POST 一律 405（这条与口令无关）—— 连打 3 次看是不是每次都 405，还是偶发重置
    c405 = dist("GET", url, n=3)
    killed(p)
    wait_port(addr, False)
    w("【mcphttp·HTTP】起件=%s ｜ initialize → %s ｜ tools/list → %s（工具数 %d）｜ GET 非 POST 连打 3 次的分布 = %s"
      % ("监听就绪" if up else "没起来", summ(r1), summ(r2), len(http_tools), c405))

    # ---- 3) 逐字节对照：内核 README 点名「还没有」的那一半 ----
    a = json.dumps(stdio_tools, ensure_ascii=False).encode("utf-8")
    b = json.dumps(http_tools, ensure_ascii=False).encode("utf-8")
    w("【两面 tools/list 逐字节对照】stdio sha256=%s ｜ http sha256=%s ｜ 逐字节相同 = %s ｜ 两边各 %d 字节 ｜ 工具名首个=%s"
      % (hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest(), a == b, len(a),
         (stdio_tools[0]["name"] if stdio_tools else "—")))
    # 上面那一条比的是「同一把序列化尺子量出来的 result.tools」；原始帧也直接比一次，
    # stdio 那一面按行读、尾部多带一个换行 —— 剥掉换行之后两边应当一字不差。
    raw_stdio = list_raw.rstrip(b"\r\n")
    w("【原始帧对照】stdio 回帧 %d 字节（剥行尾换行后 %d）｜ http 回帧体 %d 字节 ｜ 两边直接逐字节相同 = %s ｜ 各自 sha256=%s / %s"
      % (len(list_raw), len(raw_stdio), len(b2), raw_stdio == b2,
         hashlib.sha256(raw_stdio).hexdigest()[:16], hashlib.sha256(b2).hexdigest()[:16]))
    if a != b:
        w("【判定】这一轮两面没拿到一致的字节 —— 就记成没验上，不重跑糊过去；上面两行是原样读数。")
    raw = io.open(os.path.join(OUT, "19-两面-tools清单.txt"), "w", encoding="utf-8", newline="\n")
    raw.write("stdio 面 tools/list 的 result.tools：\n" + json.dumps(stdio_tools, ensure_ascii=False, indent=1) + "\n")
    raw.write("\nhttp 面 tools/list 的 result.tools：\n" + json.dumps(http_tools, ensure_ascii=False, indent=1) + "\n")
    raw.close()

    # ---- 4) kaudit：只读审计外壳 ----
    jf = os.path.join(SRC, "报告", "样例-agent.jsonl")
    w("【kaudit】要供的账本存在 = %s（%s）" % (os.path.exists(jf), "报告/样例-agent.jsonl"))
    if os.path.exists(jf):
        addr = ("127.0.0.1", 8803)
        p = subprocess.Popen([os.path.join(BIN, "kaudit.exe"), "-listen", "127.0.0.1:8803",
                              "-journal", os.path.join("报告", "样例-agent.jsonl")],
                             cwd=SRC, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        up = wait_port(addr, True)
        rv = call("GET", "http://127.0.0.1:8803/v1/verify")
        rl = call("GET", "http://127.0.0.1:8803/v1/tools")
        cpost = dist("POST", "http://127.0.0.1:8803/v1/verify", payload={}, n=5)
        cpost0 = dist("POST", "http://127.0.0.1:8803/v1/verify", n=5, raw=b"")
        killed(p)
        wait_port(addr, False)
        txt = body(rv).decode("utf-8", "replace")
        state = ""
        try:
            state = json.loads(txt).get("state", "")
        except Exception:
            pass
        w("【kaudit】起件=%s ｜ GET /v1/verify → %s（state=%s）｜ GET /v1/tools → %s"
          % ("监听就绪" if up else "没起来", summ(rv), state or "读不出", summ(rl)))
        w("【kaudit 只读性】POST /v1/verify 带 2 字节体 ×5 = %s ｜ 空体 ×5 = %s ｜ 两行里有没有任何 2xx：%s"
          % (cpost, cpost0,
             "有" if any(isinstance(k, int) and 200 <= k < 300 for k in list(cpost) + list(cpost0)) else "没有"))
        w("【这一条在量什么】若空体那行稳定 405、带体那行偶发传输层断，则断连发生在客户端这一侧"
          "（服务端已回 405 并关连接时客户端还在发体）——「一律 405」这句就应当读成「响应恒为 405，"
          "但带体的请求不一定每次都让客户端读到那个响应」。若空体那行也不稳 405，则与体无关，这条留给作者判。")

    # ---- 5) kcheck 已在 04 里由交付件自己跑过；kresearch 明写不跑的理由 ----
    w("【kcheck】不在这里重跑 —— 交付件自跑闸门的原读数在 凭据/04-kcheck-exe.txt")
    w("【kresearch】只验编译（02 里 OK），**不验运行**。两条硬理由："
      "① 它把端点写死成外网地址（cmd/kresearch/main.go 那句 const base），跑一发就是替你把请求打到别人的机器上；"
      "② 它默认把账写到 报告/样例-真接口两发.jsonl —— 那是仓库里的凭据，覆盖了就没了。"
      "要跑它得你点名端点口令（只走环境变量）并在 TEMP 拷贝里跑；本轮两样都没有，所以不跑。")

    # ---- 6) 端口收尾自检：8802/8803 必须空，8797 必须还在（挂载中，不许动）----
    ns = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for port, want in (("8802", False), ("8803", False), ("8797", True)):
        listening = any((":%s " % port) in l and "LISTENING" in l for l in ns.splitlines())
        w("【端口】%s 监听中 = %s（应为 %s）" % (port, listening, want))

    out = "\n".join(rep) + "\n"
    with io.open(os.path.join(OUT, "18-逐件smoke.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    sys.stdout.write(out)


main()
