#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""26 策略引擎 · 基础能力闭环探针

只读被测目录；除 TEMP 元基因库与本目录读数外不写任何文件。
判据全部机械可数，末行自印「能闭环 / 未闭环」，退出码 0=能闭环 / 2=未闭环 / 3=尺子坏。
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_SKILL = Path(r"C:/Users/Admin/.qoder-cn/skills/loudong-wajue-jinhua-yinqing")
SEEDS = [
    "1' OR '1'='1' -- ",
    "1 UNION SELECT 1,version() -- ",
    "1' AND SLEEP(5) -- ",
]
PAYLOADS = [
    ("sqli", "1' OR '1'='1' -- "),
    ("xss", "<script>alert(1)</script>"),
    ("ssrf", "https://example.com/a?b=1"),
    ("plain", "hello world"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=str(DEFAULT_SKILL))
    args = ap.parse_args()
    skill = Path(args.skill_dir).resolve()
    engine_path = skill / "evolution_enhancer.py"

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    buf: list[str] = []

    def say(s: str = "") -> None:
        print(s)
        buf.append(s)

    if not engine_path.exists():
        say(f"尺子坏：找不到 {engine_path}")
        return 3

    sys.path.insert(0, str(skill))
    import evolution_enhancer as eng

    src = engine_path.read_text(encoding="utf-8")
    say("=" * 72)
    say("26 策略引擎 · 基础能力闭环探针")
    say("=" * 72)
    say(f"被测目录 = {skill}")
    say(f"引擎 sha256 = {hashlib.sha256(engine_path.read_bytes()).hexdigest()}")
    say(f"python = {sys.version.split()[0]}")

    checks: dict[str, bool] = {}
    rerun_errors: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = ok
        if detail:
            say(f"  [{'GREEN' if ok else 'RED'}] {name} ｜ {detail}")
        else:
            say(f"  [{'GREEN' if ok else 'RED'}] {name}")

    # ---- 一、目录与实现 ----
    say("\n-- 一、目录与实现 --")
    catalog = eng.COGNITIVE_STRATEGIES
    transforms = [s["id"] for s in catalog if s["kind"] == "transform"]
    metas = [s["id"] for s in catalog if s["kind"] == "meta"]
    branches = re.findall(r'if strat == "([^"]+)"', src)
    branch_set = set(branches)
    identity = sorted(set(transforms) - branch_set)
    say(f"目录声明 {len(catalog)} ｜ transform {len(transforms)} ｜ meta {len(metas)} "
        f"｜ 分支 {len(set(branches))}（匹配 {len(branches)} 次）")
    say(f"恒等（声明 transform 但无分支）= {len(identity)}：{identity}")
    accounted = len(branch_set) + len(metas) + len(identity)
    say(f"三态加总 {len(branch_set)} + {len(metas)} + {len(identity)} = {accounted}（目录 {len(catalog)}）")
    check("catalog_accounting", accounted == len(catalog), f"{accounted}/{len(catalog)}")

    selectable = list(getattr(eng, "_SELECTABLE_IDS", eng._TRANSFORM_IDS))
    say(f"选择池 = {len(selectable)} 条 ｜ context_switch 在池内 = {'context_switch' in selectable}")
    check("identity_not_selectable", "context_switch" not in selectable,
          f"选择池 {len(selectable)} 条")

    # ---- 二、引擎 → 内核接线 ----
    say("\n-- 二、引擎 → 内核接线 --")
    try:
        import vuln_hunter_kernel as vk
        present = [n for n in ("judge_response", "scamper_mutate", "mutate") if hasattr(vk, n)]
        missing = [n for n in ("judge_response", "scamper_mutate", "mutate") if not hasattr(vk, n)]
    except Exception as exc:  # noqa: BLE001
        present, missing = [], ["<kernel 导入失败>"]
        say(f"vuln_hunter_kernel 导入失败：{exc}")
    say(f"kernel 模块三件在场 {len(present)}：{present} ｜ 缺 {missing}")
    say(f"引擎侧 judge_response={eng.judge_response is not None} ｜ "
        f"scamper_mutate={eng.scamper_mutate is not None}")
    for i, line in enumerate(src.splitlines(), 1):
        if "from vuln_hunter_kernel import" in line:
            say(f"根因行 engine:{i}: {line.strip()}")
            break
    check("kernel_link", eng.judge_response is not None and eng.scamper_mutate is not None,
          "真评分与真变异都可走 kernel" if eng.judge_response is not None else "整条链路静默降级为 None")

    try:
        verdict = eng.judge_response(PAYLOADS[0][1], "sqli") if eng.judge_response else None
    except Exception as exc:  # noqa: BLE001
        verdict = None
        say(f"judge_response 实调用异常：{exc}")
    say(f"judge_response 实调用 = {verdict}")
    check("kernel_judge_callable",
          isinstance(verdict, dict) and "confidence" in verdict,
          "返回带 confidence 的判定" if isinstance(verdict, dict) else "不可调用")

    # CLI 自持：安全路径解释器下，脚本目录不在 sys.path，同目录兄弟模块必须显式补
    cli_env = dict(os.environ)
    cli_env["HERMES_HOME"] = tempfile.mkdtemp(prefix="celue26-cli-")
    cli_env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, str(engine_path)],
            env=cli_env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        cli_out = proc.stdout or ""
        attached = "接入元基因库" in cli_out and "未接入元基因库" not in cli_out
        weight_line = next((l for l in cli_out.splitlines() if "L4 先验权重=" in l), "")
        nonzero_weights = weight_line.count("':") > 3 and "{}" not in weight_line
        say(f"CLI demo rc={proc.returncode} ｜ 接入元基因库={attached} ｜ 第二轮回读权重={nonzero_weights}")
        if not attached:
            tail = cli_out.strip().splitlines()
            say(f"CLI 末行 = {tail[-1] if tail else '<空>'}")
        check("cli_attaches_meta_gene",
              proc.returncode == 0 and attached and nonzero_weights,
              "两轮进化读写 L4 走通" if attached else "CLI 仍开环")
    except Exception as exc:  # noqa: BLE001
        say(f"CLI 检查异常：{exc}")
        check("cli_attaches_meta_gene", False, "CLI 未跑通")

    # ---- 三、逐策略运行时：变没变 ----
    say("\n-- 三、逐策略运行时（4 组样例 / 每条） --")
    rows = []
    for i, sid in enumerate(transforms):
        changed = 0
        for j, (vt, p) in enumerate(PAYLOADS):
            eh = eng.EvolutionEnhancer(seed=1000 + i * 10 + j)
            out = eh._apply_transform(p, vt, sid)
            if out != p:
                changed += 1
        rows.append((sid, changed, sid in branch_set))
    for sid, changed, has_branch in rows:
        mark = "" if changed else "  <-- 四组样例一个都没变"
        say(f"  {sid:<16} 变了 {changed}/{len(PAYLOADS)} ｜ 有分支={'是' if has_branch else '否'}{mark}")
    cs = next((c for s, c, _ in rows if s == "context_switch"), None)
    check("identity_is_runtime_noop", cs == 0, f"context_switch 变了 {cs}/{len(PAYLOADS)}")

    eh_probe = eng.EvolutionEnhancer(seed=7)
    ind_probe = eng.Individual(payload=PAYLOADS[0][1])
    _saved_scamper = eng.scamper_mutate
    eng.scamper_mutate = None  # 隔离内置 transform，保证「恒等」这一发不被 kernel 精炼改写
    try:
        before = eh_probe.strategy_usage.get("context_switch", 0)
        child = eh_probe.mutate(ind_probe, "sqli", strategy="context_switch")
        after = eh_probe.strategy_usage.get("context_switch", 0)
    finally:
        eng.scamper_mutate = _saved_scamper
    say(f"显式 mutate(context_switch)：payload 变了={child.payload != ind_probe.payload} ｜ "
        f"用量 {before}->{after} ｜ strategy_used={child.strategy_used}")
    check("noop_not_credited", child.payload != ind_probe.payload or after == before,
          f"用量 {before}->{after}")

    # ---- 四、复现性 ----
    say("\n-- 四、复现性 --")

    def run(seed: int):
        eh = eng.EvolutionEnhancer(population_size=8, seed=seed)
        pop = eh.evolve(SEEDS, "sqli", generations=3)
        snap = [(i.payload, i.fitness, tuple(i.lineage), i.strategy_used) for i in pop]
        return snap, eh.history

    a1, h1 = run(123)
    a2, h2 = run(123)
    b1, _ = run(124)
    check("deterministic_with_seed", a1 == a2 and h1 == h2, "同种子 123 两次逐项相同")
    check("seed_changes_result", a1 != b1, "种子 123 vs 124 结果不同")
    sig = inspect.signature(eng.run_evolution)
    check("run_evolution_accepts_seed", "seed" in sig.parameters,
          f"参数={list(sig.parameters)}")
    ar1 = eng.EvolutionArena(rng_seed=0)
    s1 = [ar1._rng.random() for _ in range(3)]
    time.sleep(0.02)
    ar2 = eng.EvolutionArena(rng_seed=0)
    s2 = [ar2._rng.random() for _ in range(3)]
    say(f"EvolutionArena(rng_seed=0) 两次首样本 = {s1[0]:.9f} / {s2[0]:.9f}")
    check("arena_seed_zero_honored", s1 == s2, "0 是合法种子，不许被 falsy 丢掉")

    # ---- 五、反馈闭环：写回 → 落盘 → 读回 → 偏置 ----
    say("\n-- 五、反馈闭环 --")
    from meta_gene import MetaGeneLibrary

    tmp = Path(tempfile.mkdtemp(prefix="celue26-"))
    say(f"元基因库 TEMP = {tmp}")
    mgl = MetaGeneLibrary(data_dir=str(tmp)).load()
    eh1 = eng.EvolutionEnhancer(population_size=14, seed=42, meta_gene=mgl, vuln_type="sqli")
    eh1.evolve(SEEDS, "sqli", generations=4)
    genes = mgl.cognitive.get("sqli", {})
    total = sum(g.total_count for g in genes.values())
    succ = sum(g.success_count for g in genes.values())
    lib_path = tmp / "meta_gene_library.json"
    say(f"第 1 轮 L4 基因 {len(genes)} 条 ｜ 记录 {total} 次 ｜ 成功 {succ} 次 ｜ "
        f"落盘={lib_path.exists()} ｜ 字节={lib_path.stat().st_size if lib_path.exists() else 0}")
    check("crystal_written", len(genes) > 0 and lib_path.exists() and lib_path.stat().st_size > 0,
          f"{len(genes)} 条")

    mgl2 = MetaGeneLibrary(data_dir=str(tmp)).load()
    g2 = mgl2.cognitive.get("sqli", {})
    sig1 = {k: (v.total_count, v.success_count) for k, v in genes.items()}
    sig2 = {k: (v.total_count, v.success_count) for k, v in g2.items()}
    check("crystal_roundtrip", sig1 == sig2, f"{len(sig1)} 条逐项相同")

    eh2 = eng.EvolutionEnhancer(seed=42, meta_gene=mgl2, vuln_type="sqli")
    weights = eh2._strategy_weights
    changed_w = sorted(k for k, w in weights.items() if abs(w - 1.0) > 1e-9)
    say(f"读回权重 {len(weights)} 条 ｜ 偏离 1.0 的 {len(changed_w)} 条：{changed_w[:8]}")
    check("prior_loaded", len(changed_w) > 0, f"{len(changed_w)} 条偏置")

    # 偏置探测器：负对照（公平）与正样本（极端 L4）
    eh_flat = eng.EvolutionEnhancer(seed=99)
    for _ in range(60):
        mgl2.record_cognitive_strategy("sqli", "s_substitute", True, 0.2)
    for _ in range(60):
        mgl2.record_cognitive_strategy("sqli", "s_eliminate", False, 0.0)
    eh_biased = eng.EvolutionEnhancer(seed=99, meta_gene=mgl2, vuln_type="sqli")

    def sample(eh, n: int = 4000) -> dict[str, int]:
        cnt = {"s_substitute": 0, "s_eliminate": 0}
        for _ in range(n):
            sid = eh._choose_strategy()
            if sid in cnt:
                cnt[sid] += 1
        return cnt

    flat = sample(eh_flat)
    biased = sample(eh_biased)
    ratio_flat = flat["s_substitute"] / max(1, flat["s_eliminate"])
    ratio_biased = biased["s_substitute"] / max(1, biased["s_eliminate"])
    say(f"负对照（无先验）4000 次：{flat} ｜ 比 {ratio_flat:.2f}")
    say(f"正样本（2.0 vs 0.5）4000 次：{biased} ｜ 比 {ratio_biased:.2f}")
    check("bias_detector_distinguishes",
          0.8 <= ratio_flat <= 1.25 and ratio_biased > 2.5,
          f"负对照 {ratio_flat:.2f} ｜ 正样本 {ratio_biased:.2f}")

    # ---- 六、归因 ----
    say("\n-- 六、归因（适应度与成功记账） --")
    eh_fit = eng.EvolutionEnhancer(seed=5)
    i0 = eng.Individual(payload="X")
    i1 = eng.Individual(payload="X", lineage=["s_adapt", "s_combine"])
    f0 = eh_fit.evaluate(i0, "sqli")
    f1 = eh_fit.evaluate(i1, "sqli")
    say(f"同 payload ｜ 无血统 {f0} ｜ 两段血统 {f1} ｜ 差 {round(f1 - f0, 3)}")
    check("fitness_independent_of_lineage", abs(f1 - f0) < 1e-9, f"差 {round(f1 - f0, 3)}")

    tmp2 = tempfile.mkdtemp(prefix="celue26-attr-")
    mgl3 = MetaGeneLibrary(data_dir=tmp2).load()
    eh3 = eng.EvolutionEnhancer(seed=6, meta_gene=mgl3, vuln_type="sqli")
    ind = eng.Individual(
        payload=PAYLOADS[0][1], fitness=0.9,
        lineage=["s_adapt", "s_combine"], strategy_used="s_adapt",
    )
    eh3.population = [ind]
    eh3.feedback_bridge(0.0)
    credited = sorted(mgl3.cognitive.get("sqli", {}))
    say(f"一个个体（lineage=s_adapt,s_combine；strategy_used=s_adapt）写回策略 = {credited}")
    check("credit_only_last_applied", credited == ["s_adapt"], f"写回 {credited}")

    # ---- 七、闭环判定 ----
    say("\n" + "=" * 72)
    links = [
        ("L0 CLI 自持（脚本目录可导入兄弟模块）", checks["cli_attaches_meta_gene"]),
        ("L1 目录→实现（无恒等混入选择）",
         checks["catalog_accounting"] and checks["identity_is_runtime_noop"]
         and checks["identity_not_selectable"] and checks["noop_not_credited"]),
        ("L2 引擎→内核（真评分/真变异可用）", checks["kernel_link"]),
        ("L3a 进化→结晶（写回+落盘+读回）",
         checks["crystal_written"] and checks["crystal_roundtrip"]),
        ("L3b 归因（无血统自奖/无多记）",
         checks["fitness_independent_of_lineage"] and checks["credit_only_last_applied"]),
        ("L4 结晶→再进化（读回+偏置可测）",
         checks["prior_loaded"] and checks["bias_detector_distinguishes"]),
        ("L5 复现（显式种子/0 被尊重）",
         checks["deterministic_with_seed"] and checks["seed_changes_result"]
         and checks["run_evolution_accepts_seed"] and checks["arena_seed_zero_honored"]),
    ]
    green = sum(1 for _, ok in links if ok)
    say(f"闭环环节 {len(links)} 条 ｜ 绿 {green} ｜ 红 {len(links) - green}")
    for name, ok in links:
        say(f"  [{'GREEN' if ok else 'RED'}] {name}")
    closed = green == len(links)
    say(f"闭环判定 = {'能闭环' if closed else '未闭环'}")
    say("范围：离线/合成样例；真实目标投递 = NOT_RUN（无授权靶场，不跑）")
    say("=" * 72)

    out = Path(__file__).resolve().parent / f"探针-{skill.name}.txt"
    out.write_text("\n".join(buf) + "\n", encoding="utf-8")
    print(f"[自印] 读数已写到 {out}")
    return 0 if closed else 2


if __name__ == "__main__":
    sys.exit(main())
