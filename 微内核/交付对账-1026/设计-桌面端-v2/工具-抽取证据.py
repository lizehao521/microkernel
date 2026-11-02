# -*- coding: utf-8 -*-
"""把三类本地证据抽成桌面端可消费的证据包。只读源文件；输出 UTF-8 JSON。
用法：python 工具-抽取证据.py
退出码：0 全部断言通过；1 有断言失败（打印哪一条）。
"""
import base64
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
RAW = BASE / "证据" / "raw"
EVID = BASE / "证据"
PG_RAW = RAW / "pgagent-真跑-解析.json"
AGENTD_SRC = ROOT / "PDF-1022" / "真端点-1023" / "读数" / "agentd-真端点.events.jsonl"
KERNEL_SRC = ROOT / "微内核" / "微内核" / "报告" / "样例-agent.jsonl"

BASIS_LABEL = {0: "unset", 1: "measured", 2: "relayed", 3: "estimated", 4: "model_says", 5: "absent"}

fails = []


def check(ok, label, detail=""):
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {label}" + (f" | {detail}" if detail else "")
    print(line.encode("ascii", "backslashreplace").decode("ascii"))
    if not ok:
        fails.append(label)
    return ok


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    return sha256_bytes(Path(p).read_bytes())


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(name, obj):
    p = EVID / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    raw = p.read_bytes()
    return {"file": name, "bytes": len(raw), "sha256": sha256_bytes(raw)}


def preview(text, n=200):
    s = " ".join(str(text).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    # 0) 原始件拷进证据包，保证证据包自包含；原路径同时留档
    copies = []
    for src, name in [(AGENTD_SRC, "agentd-真端点.events.jsonl"), (KERNEL_SRC, "样例-agent.jsonl")]:
        dst = RAW / name
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        copies.append({"name": name, "src": str(src), "bytes": dst.stat().st_size, "sha256": sha256_file(dst)})
        check(sha256_file(dst) == sha256_file(src), f"raw copy == source: {name}", sha256_file(dst)[:16])

    # 1) pgagent 13 步真跑
    pg = read_json(PG_RAW)
    events = pg["events"]
    result = [e for e in events if e["event"] == "result"][0]["data"]
    steps = result["trace"]
    gateway = result["gateway"]
    check(len(steps) == 13, "pgagent: 13 steps", f"n={len(steps)}")
    check([s["step"] for s in steps] == list(range(1, 14)), "pgagent: step numbers 1..13", "")
    check(all(s["ran"] for s in steps), "pgagent: every step ran", "")
    check(result.get("trace_sane") is True, "pgagent: trace_sane true", result.get("trace_sane_why", ""))
    check(result.get("chain_sane") is True, "pgagent: chain_sane true", result.get("chain_why", ""))
    check(result.get("code_executed") is False, "pgagent: code_executed false", "")
    check(gateway.get("fake") is True and gateway.get("loopback") is True, "pgagent: gateway is local fake", gateway.get("base_url", ""))
    check(gateway.get("usage_in") == 0 and gateway.get("usage_out") == 0, "pgagent: zero model usage", "")
    step10 = [s for s in steps if s["name"] == "kernel.tally"][0]["out"]
    step11 = [s for s in steps if s["name"] == "kernel.verify"][0]["out"]
    step6 = [s for s in steps if s["name"] == "kernel.record_call"][0]["out"]
    check("49 条" in step6, "pgagent: record_call says 49 rows", step6[:60])
    check("共 49 条" in step11 and "49 条比对过原像" in step11, "pgagent: verify says chain 49", step11[:60])

    pg_pack = {
        "source": {
            "kind": "local-measured-run",
            "file": "证据/raw/pgagent-真跑-解析.json",
            "raw_sse_file": "证据/raw/pgagent-真跑.json",
            "raw_sse_bytes": (RAW / "pgagent-真跑.json").stat().st_size,
            "sha256": sha256_file(PG_RAW),
            "session": result["session"],
            "turn": result["turn"],
            "exe_sha256": "32c1751316a898c62089abdb51f328b579318a158671b11cb21ccd88518d32c8",
            "endpoint": gateway.get("base_url"),
            "data_dir": "系统 TEMP（跑完已清理，未进仓库）",
        },
        "question": result["question"],
        "steps": steps,
        "counts": {"steps": len(steps), "steps_ran": sum(1 for s in steps if s["ran"]), "findings": len(result.get("findings", []))},
        "sanity": {
            "trace_sane": result.get("trace_sane"),
            "trace_sane_why": result.get("trace_sane_why"),
            "chain_sane": result.get("chain_sane"),
            "chain_why": result.get("chain_why"),
        },
        "execution": {
            "code_executed": result.get("code_executed"),
            "gateway_fake": gateway.get("fake"),
            "gateway_loopback": gateway.get("loopback"),
            "real_model_calls": 0 if gateway.get("fake") else None,
            "model_label": gateway.get("model"),
        },
        "ledger": {
            "record_call": step6,
            "tally": step10,
            "verify": step11,
            "kpi_ledger_decided": result.get("kpi_ledger_decided"),
            "kpi_why": result.get("kpi_why"),
        },
        "gateway": gateway,
        "provenance_mix": result.get("provenance_mix"),
        "mix_identity_ok": result.get("mix_identity_ok"),
        "mix_identity_why": result.get("mix_identity_why"),
        "unknowns": result.get("unknowns"),
        "stop_reason": result.get("stop_reason"),
        "stop_why": result.get("stop_why"),
        "findings": result.get("findings"),
        "budget": {
            "parts_bytes": result.get("parts_bytes"),
            "effective_ceiling": result.get("budget_effective_ceiling"),
            "over": result.get("budget_over"),
            "pre_ok": result.get("budget_pre_ok"),
        },
        "scope_notes": [
            "本发是本机真跑：exe 在 TEMP，端口 61388，数据目录在系统 TEMP。",
            "端点是 127.0.0.1 假端点（脚本回帧），真实模型调用 0 次。",
            "全程未执行交付代码；未写内核研究账 8797/8799。",
            "49 格账文件随 TEMP 数据目录清理，未保留；逐格证据见另一交付的样例账。",
        ],
    }
    pg_meta = write_json("pgagent-13步.json", pg_pack)

    # 2) agentd 真事件
    agentd_rows = [json.loads(l) for l in (RAW / "agentd-真端点.events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    runs = {}
    for r in agentd_rows:
        runs.setdefault(r["run"], []).append(r)
    accepts = [r for r in agentd_rows if r["kind"] == "turn_accepted"]
    turns_settled = [r for r in agentd_rows if r["kind"] == "turn_settled"]
    runs_settled = [r for r in agentd_rows if r["kind"] == "run_settled"]
    check(len(agentd_rows) == 14, "agentd: 14 events", f"n={len(agentd_rows)}")
    check(len(runs) == 2, "agentd: 2 runs", ",".join(sorted(runs)))
    check(len(accepts) == 2 and all(a["accept"]["resumable"] for a in accepts), "agentd: 2 resumable turn_accepted", "")
    check(len(turns_settled) == 2 and all(t["settle"]["kind"] == "completed" for t in turns_settled), "agentd: 2 completed turns", "")
    check(len(runs_settled) == 2, "agentd: 2 run_settled", "")
    check(all(r.get("evidence") == "measured" for r in agentd_rows), "agentd: all evidence=measured", "")

    run_meta = []
    for idx, (rid, rows) in enumerate(runs.items(), 1):
        kinds = [r["kind"] for r in rows]
        run_meta.append({
            "index": idx,
            "run": rid,
            "session": rows[0]["session"],
            "events": len(rows),
            "kinds": kinds,
            "accept": next((r["accept"] for r in rows if r["kind"] == "turn_accepted"), None),
            "turn_settle": next((r["settle"] for r in rows if r["kind"] == "turn_settled"), None),
            "run_settle": next(({"stop": r.get("stop"), "why": r.get("stop_why"), "progress": r.get("progress")} for r in rows if r["kind"] == "run_settled"), None),
            "first_ts": min(r["ts"] for r in rows),
            "last_ts": max(r["ts"] for r in rows),
        })
    agentd_pack = {
        "source": {
            "kind": "local-event-export",
            "file": "证据/raw/agentd-真端点.events.jsonl",
            "src_path": str(AGENTD_SRC),
            "bytes": (RAW / "agentd-真端点.events.jsonl").stat().st_size,
            "sha256": sha256_file(RAW / "agentd-真端点.events.jsonl"),
            "note": "两条 run 的导出副本（real-agentd-1 / agentd-27276），非同一次 pgagent 运行。",
        },
        "events": agentd_rows,
        "runs": run_meta,
        "counts": {
            "events": len(agentd_rows),
            "runs": len(runs),
            "turns_settled": len(turns_settled),
            "runs_settled": len(runs_settled),
            "resumable": sum(1 for a in accepts if a["accept"].get("resumable")),
        },
        "scope_notes": [
            "事件来自 agentd 事件层真实落盘文件，不是脚本编的。",
            "这是导出副本：只证明导出的 14 条自洽，不证明投送端一条没丢。",
            "seq 是「每发 turn 内」的自增序号，turn 0 与 turn 1 各自从 1 开始；文件顺序按落盘先后。",
        ],
    }
    agentd_meta = write_json("agentd-事件.json", agentd_pack)

    # 3) 内核 49 格样例账（首块）
    all_rows = [json.loads(l) for l in (RAW / "样例-agent.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    block = all_rows[:49]
    check(len(all_rows) == 294, "kernel: 294 rows total", f"n={len(all_rows)}")
    check(len(block) == 49, "kernel: first block 49 rows", f"n={len(block)}")
    kinds = [r["kind"] for r in block]
    check(len(set(kinds)) == 49, "kernel: 49 unique kinds", f"unique={len(set(kinds))}")

    payload_ok = 0
    rows_out = []
    for r in block:
        pbytes = base64.b64decode(r["payload_b64"])
        ph = sha256_bytes(pbytes)
        ok = ph == r["payload_sha256"]
        payload_ok += 1 if ok else 0
        rows_out.append({
            "seq": r["seq"],
            "kind": r["kind"],
            "claim": r["claim"],
            "basis": r["basis"],
            "basis_label": BASIS_LABEL.get(r["basis"], "unknown"),
            "payload_sha256": r["payload_sha256"],
            "payload_bytes": len(pbytes),
            "payload_preview": preview(pbytes.decode("utf-8", "replace"), 220),
            "payload_hash_ok": ok,
            "prev_hash": r["prev_hash"],
            "hash": r["hash"],
        })
    check(payload_ok == 49, "kernel: 49/49 payload hashes match", f"{payload_ok}/49")

    block_links = sum(1 for i in range(1, 49) if block[i]["prev_hash"] == block[i - 1]["hash"])
    global_links = sum(1 for i in range(1, 294) if all_rows[i]["prev_hash"] == all_rows[i - 1]["hash"])
    check(block_links == 48, "kernel: 48/48 block prev links", f"{block_links}/48")
    check(global_links == 293, "kernel: 293/293 global prev links", f"{global_links}/293")

    basis_mix = {}
    for r in block:
        basis_mix[str(r["basis"])] = basis_mix.get(str(r["basis"]), 0) + 1
    check(sum(basis_mix.values()) == 49 and all(1 <= int(k) <= 5 for k in basis_mix), "kernel: every row has basis 1..5", json.dumps(basis_mix, sort_keys=True))
    check(all(r["basis"] != 0 and r["claim"] != "" for r in block), "kernel: no unset basis / empty claim", "")

    # 六块的结构：每块 49 条、kind 集合一致
    blocks = [all_rows[i:i + 49] for i in range(0, 294, 49)]
    same_shape = all(len(b) == 49 and set(x["kind"] for x in b) == set(kinds) for b in blocks)
    check(len(blocks) == 6 and same_shape, "kernel: 6 blocks share the same 49 kinds", f"blocks={len(blocks)}")

    kernel_pack = {
        "source": {
            "kind": "sample-ledger",
            "file": "证据/raw/样例-agent.jsonl",
            "src_path": str(KERNEL_SRC),
            "bytes": (RAW / "样例-agent.jsonl").stat().st_size,
            "sha256": sha256_file(RAW / "样例-agent.jsonl"),
            "note": "内核仓库里的样例账，不是 pgagent 本发落的那本账；两者非同发。",
        },
        "block": {
            "index": 1,
            "of_blocks": 6,
            "rows": 49,
            "seq_range": [block[0]["seq"], block[-1]["seq"]],
            "session": block[0]["session"],
            "actor": block[0]["actor"],
        },
        "rows": rows_out,
        "checks": {
            "unique_kinds": len(set(kinds)),
            "payload_hash_ok": payload_ok,
            "block_links_ok": block_links,
            "block_links_total": 48,
            "global_links_ok": global_links,
            "global_links_total": 293,
            "all_rows": len(all_rows),
            "blocks": len(blocks),
            "same_shape": same_shape,
        },
        "basis_mix": {BASIS_LABEL[int(k)]: v for k, v in sorted(basis_mix.items(), key=lambda kv: int(kv[0]))},
        "scope_notes": [
            "这是样例账首块，不是 pgagent 真跑那本的 49 格。",
            "只校了链接字段与载荷哈希，未复算内核签名/哈希算法本身。",
            f"{basis_mix.get('1',0)} 条 measured、{basis_mix.get('2',0)} 条 relayed、{basis_mix.get('3',0)} 条 estimated、{basis_mix.get('4',0)} 条 model_says、{basis_mix.get('5',0)} 条 absent —— 不是全部实测。",
        ],
    }
    kernel_meta = write_json("内核-49格.json", kernel_pack)

    # 4) 交付单与声明判定
    claims_d1 = [
        {"id": "D1-C1", "text": "13 步全部走完", "verdict": "MATCH", "basis": "disk",
         "why": "13 步逐条 ran=true，步号 1..13 无缺；trace_sane=true（11 条整列自洽判据）。",
         "refs": [{"ev": "pgagent", "locator": "steps", "label": "13 步轨迹"},
                  {"ev": "pgagent", "locator": "sanity.trace_sane", "label": "trace_sane"}]},
        {"id": "D1-C2", "text": "没有执行交付代码", "verdict": "MATCH", "basis": "disk",
         "why": "result.code_executed=false；13 步里没有执行步；网关是 127.0.0.1 假端点。",
         "refs": [{"ev": "pgagent", "locator": "execution.code_executed", "label": "code_executed"},
                  {"ev": "pgagent", "locator": "gateway", "label": "假端点证据"}]},
        {"id": "D1-C3", "text": "49 格整发落账、链上自洽", "verdict": "MATCH", "basis": "disk",
         "why": "record_call 落账 49 条（输入 20 + 输出 29）；tally 49 条；verify 49 条链自洽并比对原像。",
         "refs": [{"ev": "pgagent", "locator": "ledger.record_call", "label": "record_call"},
                  {"ev": "pgagent", "locator": "ledger.verify", "label": "verify"}]},
        {"id": "D1-C4", "text": "测试通过", "verdict": "MISMATCH", "basis": "disk",
         "why": "13 步里没有测试步，result.code_executed=false；盘上没有任何测试运行记录。这句声明没有对应的动作。",
         "refs": [{"ev": "pgagent", "locator": "execution.code_executed", "label": "code_executed=false"},
                  {"ev": "pgagent", "locator": "steps", "label": "13 步名单"}]},
        {"id": "D1-C5", "text": "真实模型复核过", "verdict": "MISMATCH", "basis": "disk",
         "why": "gateway.fake=true、loopback=true、真实模型调用 0 次；model 字段自述为「假端点·演示件」。",
         "refs": [{"ev": "pgagent", "locator": "gateway", "label": "gateway.fake=true"}]},
        {"id": "D1-C6", "text": "事件断线可续", "verdict": "ABSENT", "basis": "absent",
         "why": "本发走单次 /api/turn，没有 agentd 事件落盘；事件层证据只在另一份参照账（real-agentd-1）里，不能替本发作证。",
         "refs": [{"ev": "agentd", "locator": "source.note", "label": "参照账（非同发）"}]},
    ]
    claims_d2 = [
        {"id": "D2-C1", "text": "首块 49 格齐全，kind 各不相同", "verdict": "MATCH", "basis": "disk",
         "why": "首块 49 行，49 个 kind 唯一；六块形状一致。",
         "refs": [{"ev": "kernel", "locator": "rows", "label": "49 格表"}]},
        {"id": "D2-C2", "text": "49 条载荷哈希逐条匹配", "verdict": "MATCH", "basis": "disk",
         "why": "逐条 base64 解码后重算 sha256，49/49 与账上 payload_sha256 相同。",
         "refs": [{"ev": "kernel", "locator": "checks.payload_hash_ok", "label": "49/49"}]},
        {"id": "D2-C3", "text": "块内前驱链接首尾相接", "verdict": "MATCH", "basis": "disk",
         "why": "块内 48 条 prev_hash 全部等于上一条 hash；整账 293 条链接也全部相接。",
         "refs": [{"ev": "kernel", "locator": "checks.block_links_ok", "label": "48/48"},
                  {"ev": "kernel", "locator": "checks.global_links_ok", "label": "293/293"}]},
        {"id": "D2-C4", "text": "整账 294 条 = 6 块 × 49 格", "verdict": "MATCH", "basis": "disk",
         "why": "294 行按 49 行切分恰好 6 块，六块 kind 集合一致。",
         "refs": [{"ev": "kernel", "locator": "checks.all_rows", "label": "294"}]},
        {"id": "D2-C5", "text": "每一格都带依据档，没有裸值", "verdict": "MATCH", "basis": "disk",
         "why": f"49 条 basis 均在 1..5，无 unset；分布 measured {basis_mix.get('1',0)} / relayed {basis_mix.get('2',0)} / estimated {basis_mix.get('3',0)} / model_says {basis_mix.get('4',0)} / absent {basis_mix.get('5',0)}。",
         "refs": [{"ev": "kernel", "locator": "basis_mix", "label": "依据档分布"}]},
    ]
    claims_d3 = [
        {"id": "D3-C1", "text": "两发 turn 都走到收口", "verdict": "MATCH", "basis": "disk",
         "why": "两条 turn_settled 的 settle.kind=completed，reached 4 步、not_reached 为空。",
         "refs": [{"ev": "agentd", "locator": "events", "label": "turn_settled ×2"}]},
        {"id": "D3-C2", "text": "两条 run 各自收口", "verdict": "MATCH", "basis": "disk",
         "why": "两条 run_settled：一条 stop=script（剧本走完），一条 stop=turns（轮次额度到）。",
         "refs": [{"ev": "agentd", "locator": "runs", "label": "run_settled ×2"}]},
        {"id": "D3-C3", "text": "接受后断线可续", "verdict": "MATCH", "basis": "disk",
         "why": "两条 turn_accepted 的 accept.resumable 都是 true，游标写明是日志里的身份四元组。",
         "refs": [{"ev": "agentd", "locator": "events", "label": "accept.resumable=true"}]},
        {"id": "D3-C4", "text": "身份四元组齐全，可离线重放", "verdict": "MATCH", "basis": "disk",
         "why": "14 条事件都带 v/session/run/turn/seq；kind/state/evidence 齐全；按文件序可重放。",
         "refs": [{"ev": "agentd", "locator": "events", "label": "14 条事件"}]},
        {"id": "D3-C5", "text": "这份导出一条事件都没丢", "verdict": "ABSENT", "basis": "absent",
         "why": "盘上只有导出副本，没有投送端账本或 ACK 对照；只能核到「导出的这 14 条自洽」，丢没丢核不了。",
         "refs": [{"ev": "agentd", "locator": "source.note", "label": "导出副本的边界"}]},
    ]

    def verdict_of(claims):
        if any(c["verdict"] == "MISMATCH" for c in claims):
            return "NOT-ACCEPTED-MISMATCH", ["reject"]
        if any(c["verdict"] == "ABSENT" for c in claims):
            return "NOT-ACCEPTED-UNVERIFIED", ["reject", "hold"]
        return "ACCEPTED", ["accept", "reject"]

    def counts_of(claims):
        out = {"MATCH": 0, "MISMATCH": 0, "ABSENT": 0}
        for c in claims:
            out[c["verdict"]] += 1
        return out

    deliveries = []
    d1v, d1a = verdict_of(claims_d1)
    deliveries.append({
        "id": "D-1026-01",
        "title": "pgagent 真跑 · desk-1026#1",
        "subtitle": "13 步 / 49 格 / 本机假端点",
        "agent": "编程 Agent（本地 exe）",
        "submitted_at": "2026-10-26 04:2x（本机）",
        "evidence_profile": "pgagent",
        "default_tab": "steps",
        "summary": "一份声称「测试过了、真模型复核过」的代码交付；轨迹完整，但两句关键声明与盘上事实不符。",
        "claims": claims_d1,
        "counts": counts_of(claims_d1),
        "verdict": d1v,
        "allowed": d1a,
        "tabs": ["steps", "claims", "source"],
        "notes": [
            "49 格账文件随 TEMP 数据目录清理，本发只保留了 tally/verify 读数。",
            "「事件断线可续」本发没有证据，判核不了，不是通过。",
        ],
    })
    d2v, d2a = verdict_of(claims_d2)
    deliveries.append({
        "id": "D-1026-02",
        "title": "内核样例账 · 首块 49 格",
        "subtitle": "294 条 = 6 块 × 49 格",
        "agent": "内核样例账（仓库件）",
        "submitted_at": "2026-10-13 16:29（账上时间）",
        "evidence_profile": "kernel",
        "default_tab": "cells",
        "summary": "逐格可回查的样例账首块；五条声明全部有盘上依据，但不是全部实测。",
        "claims": claims_d2,
        "counts": counts_of(claims_d2),
        "verdict": d2v,
        "allowed": d2a,
        "tabs": ["cells", "claims", "source"],
        "notes": [
            "样例账不是 pgagent 本发那本账；两类证据不混写。",
            f"依据档是混的：measured {basis_mix.get('1',0)} / relayed {basis_mix.get('2',0)} / estimated {basis_mix.get('3',0)} / model_says {basis_mix.get('4',0)} / absent {basis_mix.get('5',0)}。",
        ],
    })
    d3v, d3a = verdict_of(claims_d3)
    deliveries.append({
        "id": "D-1026-03",
        "title": "agentd 真事件 · 两条 run",
        "subtitle": "14 条事件 / 可续游标 / 导出副本",
        "agent": "agentd 事件层（本机）",
        "submitted_at": "2026-10-23 12:29–12:42（事件时间）",
        "evidence_profile": "agentd",
        "default_tab": "events",
        "summary": "两条 run 的收口与可续游标都能核；但「导出没丢事件」盘上没有对照，只能判核不了。",
        "claims": claims_d3,
        "counts": counts_of(claims_d3),
        "verdict": d3v,
        "allowed": d3a,
        "tabs": ["events", "claims", "source"],
        "notes": [
            "事件来自两条不同的 run（real-agentd-1 / agentd-27276），非同一次执行。",
            "seq 是每发 turn 内的自增序号，不是全文件序号。",
        ],
    })

    all_claims = claims_d1 + claims_d2 + claims_d3
    total_counts = {"MATCH": 0, "MISMATCH": 0, "ABSENT": 0}
    for c in all_claims:
        total_counts[c["verdict"]] += 1
    expected = {"MATCH": 12, "MISMATCH": 2, "ABSENT": 2}
    check(total_counts == expected, "delivery: claim mix 12/2/2", json.dumps(total_counts))
    check([d["verdict"] for d in deliveries] == ["NOT-ACCEPTED-MISMATCH", "ACCEPTED", "NOT-ACCEPTED-UNVERIFIED"], "delivery: three verdicts", "")
    check([len(d["claims"]) for d in deliveries] == [6, 5, 5], "delivery: claims 6/5/5", "")
    check(all(c["basis"] in ("disk", "relayed", "absent") for c in all_claims), "delivery: basis vocabulary", "")
    check(all(c["why"] for c in all_claims), "delivery: every claim has why", "")
    check(len({c["id"] for c in all_claims}) == len(all_claims), "delivery: unique claim ids", "")

    delivery_pack = {
        "generated_at": generated_at,
        "operator": "本机操作者（无账号）",
        "policy": {
            "verdicts": ["ACCEPTED", "NOT-ACCEPTED-MISMATCH", "NOT-ACCEPTED-UNVERIFIED"],
            "rule": "任一 MISMATCH ⇒ 整单退回；有 ABSENT 且无 MISMATCH ⇒ 只能退回或挂起；全 MATCH 才可收。",
            "note": "收下不改变声明真假；核不了绝不写成通过。",
        },
        "deliveries": deliveries,
        "stats": {"deliveries": len(deliveries), "claims": len(all_claims), "counts": total_counts},
    }
    delivery_meta = write_json("交付.json", delivery_pack)

    index = {
        "generated_at": generated_at,
        "files": [
            dict(pg_meta, kind="pgagent-13-step", scope="本机真跑，假端点，未执行代码"),
            dict(agentd_meta, kind="agentd-events", scope="两条 run 的真实事件导出副本"),
            dict(kernel_meta, kind="kernel-49-cells", scope="仓库样例账首块，非同发"),
            dict(delivery_meta, kind="delivery-claims", scope="三份交付单与 16 条声明判定"),
            {"file": "raw/pgagent-真跑.json", "bytes": (RAW / "pgagent-真跑.json").stat().st_size, "sha256": sha256_file(RAW / "pgagent-真跑.json"), "kind": "raw-sse", "scope": "pgagent 原始 SSE"},
            *[dict(c, kind="raw-source", scope="源文件拷贝") for c in copies],
        ],
        "not_same_run": [
            "pgagent 13 步（desk-1026#1）、agentd 14 条（real-agentd-1 / agentd-27276）、内核 49 格（样例账）三者不是同一次执行。",
            "UI 必须按交付单分别标注来源，不得把三个数混写成同一发。",
        ],
    }
    index_meta = write_json("索引.json", index)
    check(all(m["bytes"] > 0 for m in [pg_meta, agentd_meta, kernel_meta, delivery_meta, index_meta]), "index: all evidence files non-empty", "")

    print("")
    print(f"files written: pgagent={pg_meta['bytes']}B agentd={agentd_meta['bytes']}B kernel={kernel_meta['bytes']}B delivery={delivery_meta['bytes']}B index={index_meta['bytes']}B")
    print("RESULT " + ("PASS" if not fails else "FAIL"))
    if fails:
        for f in fails:
            print("  - " + f.encode("ascii", "backslashreplace").decode("ascii"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
