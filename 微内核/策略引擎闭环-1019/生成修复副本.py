#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成策略引擎的修复副本（原技能零改动）

每处替换必须命中恰好 1 次；任一处不命中即退出 3，不出副本。
"""
from __future__ import annotations

import difflib
import hashlib
import shutil
import sys
from pathlib import Path

SRC_DIR = Path(r"C:/Users/Admin/.qoder-cn/skills/loudong-wajue-jinhua-yinqing")
OUT_DIR = Path(__file__).resolve().parent / "修复副本"
ENGINE = "evolution_enhancer.py"
DEPS = ("meta_gene.py", "vuln_hunter_kernel.py")

PATCHES = [
    (
        "P1 内核接线：拆开三件 import，缺 mutate 不再拖垮另两件",
        '''try:
    from vuln_hunter_kernel import judge_response, scamper_mutate, mutate
except Exception:  # 允许独立运行（无 kernel）时降级
    judge_response = None
    scamper_mutate = None
    mutate = None''',
        '''try:
    # kernel 没有 mutate 这个名字；三件一起 import 会让整条链路静默降级
    from vuln_hunter_kernel import judge_response, scamper_mutate
except Exception:  # 允许独立运行（无 kernel）时降级
    judge_response = None
    scamper_mutate = None
mutate = None  # 引擎自身不使用；保留名字只为不破坏外部导入
KERNEL_LINK = {
    "judge_response": judge_response is not None,
    "scamper_mutate": scamper_mutate is not None,
}''',
    ),
    (
        "P2 选择池：把恒等的 context_switch 排除在可选策略之外",
        '''_STRATEGY_IDS = [s["id"] for s in COGNITIVE_STRATEGIES]
_TRANSFORM_IDS = [s["id"] for s in COGNITIVE_STRATEGIES if s["kind"] == "transform"]''',
        '''_STRATEGY_IDS = [s["id"] for s in COGNITIVE_STRATEGIES]
_TRANSFORM_IDS = [s["id"] for s in COGNITIVE_STRATEGIES if s["kind"] == "transform"]
# context_switch 声明为 transform 却没有实现分支（_apply_transform 落到 return p）。
# 它不进选择池：否则「策略生效但没变化」会同时污染用量与成功归因。
_IDENTITY_IDS = ["context_switch"]
_SELECTABLE_IDS = [s for s in _TRANSFORM_IDS if s not in _IDENTITY_IDS]''',
    ),
    (
        "P3 先验只对可选策略加权",
        '''            return dict(self.meta_gene.cognitive_bias(self.vuln_type, _TRANSFORM_IDS))''',
        '''            return dict(self.meta_gene.cognitive_bias(self.vuln_type, _SELECTABLE_IDS))''',
    ),
    (
        "P4 策略选择只从可选池里挑",
        '''        ids = [s for s in _TRANSFORM_IDS if s != exclude]''',
        '''        ids = [s for s in _SELECTABLE_IDS if s != exclude]''',
    ),
    (
        "P5 用量不在产出前记账",
        '''        strat = strategy or self._choose_strategy()
        self.strategy_usage[strat] = self.strategy_usage.get(strat, 0) + 1''',
        '''        strat = strategy or self._choose_strategy()''',
    ),
    (
        "P6 只有 payload 真变了才记用量/血统/strategy_used",
        '''        child = Individual(
            payload=new_payload,
            generation=self.generation + 1,
            lineage=ind.lineage[-3:] + [strat],
            strategy_used=strat,
        )
        return child''',
        '''        applied = new_payload != ind.payload
        if applied:
            self.strategy_usage[strat] = self.strategy_usage.get(strat, 0) + 1
        child = Individual(
            payload=new_payload,
            generation=self.generation + 1,
            lineage=(ind.lineage[-3:] + [strat]) if applied else list(ind.lineage),
            strategy_used=strat if applied else None,
        )
        return child''',
    ),
    (
        "P7 血统不再直接加适应度",
        '''        # 元基因血统加成：携带已知有效策略线 → 轻微加权
        if ind.lineage:
            fit = min(1.0, fit + 0.04 * len(set(ind.lineage)))''',
        '''        # 血统不参与适应度：同 payload 只因血统多而加分，会让进化自己给自己发奖。
        # 血统仍留在 Individual.lineage 里供展示，但不参与评分。''',
    ),
    (
        "P8 反馈只归因最后真正生效的那一条策略",
        '''            strategies = set(ind.lineage + ([ind.strategy_used] if ind.strategy_used else []))
            strategies.discard("seed")''',
        '''            # 只记最后真正生效的那一条；lineage 是沿革，不是这一发的归因。
            strategies = {ind.strategy_used} if ind.strategy_used else set()''',
    ),
    (
        "P9 run_evolution 暴露显式种子",
        '''def run_evolution(
    seeds: List[str],
    vuln_type: str,
    generations: int = 5,
    population_size: int = 24,
    response_fn: Optional[Callable] = None,
) -> Tuple[EvolutionEnhancer, List[Individual]]:
    """一行启动进化，返回 (enhancer, 最优种群)"""
    eh = EvolutionEnhancer(population_size=population_size)''',
        '''def run_evolution(
    seeds: List[str],
    vuln_type: str,
    generations: int = 5,
    population_size: int = 24,
    response_fn: Optional[Callable] = None,
    seed: Optional[int] = None,
) -> Tuple[EvolutionEnhancer, List[Individual]]:
    """一行启动进化，返回 (enhancer, 最优种群)"""
    eh = EvolutionEnhancer(population_size=population_size, seed=seed)''',
    ),
    (
        "P10 EvolutionArena 尊重 0 这个合法种子",
        '''        self._rng = random.Random(rng_seed or int(time.time() * 1000) % (2**31))''',
        '''        self._rng = random.Random(
            rng_seed if rng_seed is not None else int(time.time() * 1000) % (2**31)
        )''',
    ),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    out: list[str] = []

    def say(s: str = "") -> None:
        print(s)
        out.append(s)

    original = (SRC_DIR / ENGINE).read_text(encoding="utf-8")
    fixed = original
    say("=" * 72)
    say("生成修复副本（原技能只读）")
    say("=" * 72)
    say(f"源 = {SRC_DIR / ENGINE}")
    say(f"源 sha256 = {hashlib.sha256(original.encode('utf-8')).hexdigest()}")
    say(f"补丁 {len(PATCHES)} 处")

    for label, old, new in PATCHES:
        n = fixed.count(old)
        say(f"  [{ 'OK' if n == 1 else 'BAD'}] {label} ｜ 命中 {n}")
        if n != 1:
            say("尺子坏：替换目标不唯一，未出副本")
            return 3
        fixed = fixed.replace(old, new, 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / ENGINE).write_text(fixed, encoding="utf-8")
    for dep in DEPS:
        shutil.copy2(SRC_DIR / dep, OUT_DIR / dep)
    say(f"修复副本 = {OUT_DIR}")
    say(f"副本 sha256 = {hashlib.sha256(fixed.encode('utf-8')).hexdigest()}")
    say(f"副本字节 = {len(fixed.encode('utf-8'))} ｜ 原字节 = {len(original.encode('utf-8'))}")

    diff = list(difflib.unified_diff(
        original.splitlines(), fixed.splitlines(),
        fromfile=f"原/{ENGINE}", tofile=f"修复/{ENGINE}", lineterm="",
    ))
    (OUT_DIR.parent / "修复补丁.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
    say(f"统一 diff 行数 = {len(diff)} ｜ 已写 修复补丁.diff")

    (Path(__file__).resolve().parent / "修复补丁-读数.txt").write_text(
        "\n".join(out) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
